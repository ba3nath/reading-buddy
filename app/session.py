"""Session queue, stars, close second-take, three-retry skip, slot locks."""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

from app import config
from app.adaptive import (
    apply_day_ladder,
    apply_level_and_auto_strict,
    build_adaptive_queue,
    maybe_reinsert_miss,
    set_progress,
    shadow_queue_ids,
)
from app.events import log_event

logger = logging.getLogger(__name__)
from app.db import (
    credit_mastery_correct,
    ensure_mastery_row,
    get_item,
    get_session,
    item_public,
    load_settings,
    local_now_iso,
    local_today,
    save_settings,
    touch_mastery,
)
from app.coach.hints import (
    HINT_HIGHLIGHT,
    HINT_LISTEN,
    build_hint,
    empty_hint,
    next_hint_level,
)
from app.matching import (
    MatchResult,
    attempt_contract,
    normalize_text,
    outcome_from_legacy_result,
    tokenize,
)


class SessionError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        self.code = code
        self.message = message
        self.status = status
        super().__init__(message)


def abandon_open_sessions(conn: sqlite3.Connection) -> None:
    now = local_now_iso()
    conn.execute(
        """
        UPDATE sessions
        SET ended_at = ?, completed = 0
        WHERE ended_at IS NULL AND completed = 0
        """,
        (now,),
    )


def start_session(
    conn: sqlite3.Connection,
    level: int | None = None,
    stage: int | None = None,
) -> dict[str, Any]:
    settings = load_settings()
    raw_level = level if level is not None else settings.get("level", 1)
    target_level = config.normalize_difficulty(raw_level)
    if int(raw_level) != target_level and int(raw_level) > config.MAX_DIFFICULTY:
        # Accept legacy content-level picks (5–7) by mapping into a tier.
        target_level = config.migrate_legacy_level_to_difficulty(raw_level)
    if target_level < 1 or target_level > config.MAX_DIFFICULTY:
        raise SessionError(
            "bad_request",
            f"level must be between 1 and {config.MAX_DIFFICULTY}",
            400,
        )

    length = config.normalize_session_length(
        settings.get("session_length", config.DEFAULT_SESSION_LENGTH)
    )
    mode = str(settings.get("mode", "beginner")).lower()
    if mode not in ("beginner", "strict"):
        mode = "beginner"
    by_diff = settings.get("stage_by_difficulty") or {}
    if stage is not None:
        chosen_stage = config.normalize_stage(stage)
    else:
        chosen_stage = config.normalize_stage(
            by_diff.get(str(target_level), settings.get("stage", 1))
        )
    # Persist which difficulty/set this Start is playing.
    if (
        config.normalize_difficulty(settings.get("level", 1)) != target_level
        or config.normalize_stage(settings.get("stage", 1)) != chosen_stage
        or config.normalize_stage(by_diff.get(str(target_level), 1)) != chosen_stage
    ):
        settings = dict(settings)
        settings["level"] = target_level
        settings["stage"] = chosen_stage
        if not isinstance(settings.get("stage_by_difficulty"), dict):
            settings["stage_by_difficulty"] = config.default_stage_by_difficulty()
        settings["stage_by_difficulty"][str(target_level)] = chosen_stage
        save_settings(settings)
    stage = chosen_stage

    abandon_open_sessions(conn)
    try:
        queue = build_adaptive_queue(conn, target_level, length, stage=stage)
    except ValueError as exc:
        # No due / unmastered / eligible refresher — do not pad with mastered.
        raise SessionError("unavailable", str(exc), 503) from exc
    if not queue:
        raise SessionError("unavailable", f"No content for level {target_level}", 503)
    # Adaptive may return a shorter queue when the level is exhausted of unmastered.
    planned_ids = [row["id"] for row in queue]
    length = len(planned_ids)
    for row in queue:
        ensure_mastery_row(conn, row["id"])

    ratio_flags = [True] * length  # every planned slot counts for the session ratio
    cur = conn.execute(
        """
        INSERT INTO sessions (
          started_at, ended_at, mode, level, planned_count, planned_item_ids,
          play_item_ids, ratio_flags, correct_count, stars, low_session,
          level_after, completed
        ) VALUES (?, NULL, ?, ?, ?, ?, ?, ?, 0, 0, 0, NULL, 0)
        """,
        (
            local_now_iso(),
            mode,
            target_level,
            length,
            json.dumps(planned_ids),
            json.dumps(planned_ids),
            json.dumps(ratio_flags),
        ),
    )
    session_id = int(cur.lastrowid)
    conn.commit()
    if bool(settings.get("scheduler_shadow", False)):
        try:
            both = shadow_queue_ids(conn, target_level, length, stage)
            log_event(
                conn,
                session_id=session_id,
                item_id=None,
                pattern="",
                sight_word=False,
                result="shadow",
                phase="schedule",
                counts_for_mastery=False,
                meta={"queues": both, "chosen": planned_ids},
            )
        except Exception:  # noqa: BLE001
            logger.warning("shadow schedule event failed", exc_info=True)
    return {
        "session_id": session_id,
        "level": target_level,
        "difficulty": target_level,
        "difficulty_label": config.difficulty_label(target_level),
        "stage": stage,
        "stages_total": config.STAGES_PER_DIFFICULTY,
        "stage_label": config.stage_label(target_level, stage),
        "mode": mode,
        "buddy": settings.get("buddy", "krishna"),
        "planned_count": length,
        "items": [item_public(row) for row in queue],
    }


def planned_ids(session: sqlite3.Row) -> list[int]:
    return list(json.loads(session["planned_item_ids"]))


def play_ids(session: sqlite3.Row) -> list[int]:
    raw = session["play_item_ids"] if "play_item_ids" in session.keys() else None
    if not raw or raw == "[]":
        return planned_ids(session)
    return list(json.loads(raw))


def set_play_ids(conn: sqlite3.Connection, session_id: int, ids: list[int]) -> None:
    conn.execute(
        "UPDATE sessions SET play_item_ids = ? WHERE id = ?",
        (json.dumps(ids), session_id),
    )


def ratio_flags(session: sqlite3.Row) -> list[bool]:
    """Per-play-slot flags: True = planned (counts for ratio), False = miss reinsert."""
    raw = session["ratio_flags"] if "ratio_flags" in session.keys() else None
    if not raw or raw == "[]":
        # Legacy: treat original planned length as ratio-eligible.
        planned = planned_ids(session)
        play = play_ids(session)
        flags = [True] * len(planned)
        if len(play) > len(planned):
            flags.extend([False] * (len(play) - len(planned)))
        return flags
    return [bool(x) for x in json.loads(raw)]


def set_play_and_ratio_flags(
    conn: sqlite3.Connection,
    session_id: int,
    ids: list[int],
    flags: list[bool],
) -> None:
    conn.execute(
        """
        UPDATE sessions
        SET play_item_ids = ?, ratio_flags = ?
        WHERE id = ?
        """,
        (json.dumps(ids), json.dumps(flags), session_id),
    )


def is_ratio_slot(session: sqlite3.Row, queue_index: int) -> bool:
    """True for planned queue slots; false for same-session miss reinserts.

    Session ratio uses locking non-retry results on ratio slots only.
    Replay never uses this path for ratio (is_replay / counts_for_session=0).
    """
    flags = ratio_flags(session)
    if queue_index < 0 or queue_index >= len(flags):
        return False
    return bool(flags[queue_index])


def word_audio_slug(conn: sqlite3.Connection, word: str, fallback_slug: str) -> str:
    """Prefer a matching kind=word item slug; else a safe slug from the word."""
    norm = normalize_text(word)
    if not norm:
        return fallback_slug
    row = conn.execute(
        """
        SELECT slug FROM items
        WHERE normalized = ? AND kind = 'word'
        ORDER BY id ASC LIMIT 1
        """,
        (norm,),
    ).fetchone()
    if row:
        return row["slug"]
    # Safe slug: letters/digits/hyphen only
    slug = "".join(ch if ch.isalnum() else "-" for ch in norm).strip("-")
    return slug or fallback_slug


def _merge_hint(payload: dict[str, Any], hint: dict[str, Any] | None) -> dict[str, Any]:
    """Attach optional coach fields (old clients ignore them)."""
    h = hint or empty_hint()
    payload["hint_level"] = int(h.get("hint_level") or 0)
    payload["coach_line"] = str(h.get("coach_line") or "")
    payload["highlight_spans"] = list(h.get("highlight_spans") or [])
    payload["play_model"] = bool(h.get("play_model"))
    # Uncertain: never show “wrong word” copy — coach_line is the message.
    if payload.get("coach_line") and payload.get("outcome") == "uncertain":
        payload["message"] = payload["coach_line"]
    return payload


def consecutive_retries(
    conn: sqlite3.Connection, session_id: int, queue_index: int
) -> int:
    rows = conn.execute(
        """
        SELECT result FROM attempts
        WHERE session_id = ? AND queue_index = ? AND is_replay = 0
        ORDER BY id DESC
        """,
        (session_id, queue_index),
    ).fetchall()
    count = 0
    for row in rows:
        if row["result"] == "retry":
            count += 1
        else:
            break
    return count


def has_provisional_miss(
    conn: sqlite3.Connection, session_id: int, queue_index: int
) -> bool:
    """True when the first miss is waiting for one more read."""
    row = conn.execute(
        """
        SELECT result, counts_for_session FROM attempts
        WHERE session_id = ? AND queue_index = ? AND is_replay = 0
          AND result = 'missed'
        ORDER BY id DESC LIMIT 1
        """,
        (session_id, queue_index),
    ).fetchone()
    return bool(row and row["counts_for_session"] == 0)


def has_provisional_close(
    conn: sqlite3.Connection, session_id: int, queue_index: int
) -> bool:
    row = conn.execute(
        """
        SELECT id, result, counts_for_session FROM attempts
        WHERE session_id = ? AND queue_index = ? AND is_replay = 0
          AND counts_for_session = 1
        ORDER BY id DESC LIMIT 1
        """,
        (session_id, queue_index),
    ).fetchone()
    return bool(row and row["result"] == "close")


def flip_prior_lock(
    conn: sqlite3.Connection, session_id: int, queue_index: int
) -> None:
    conn.execute(
        """
        UPDATE attempts
        SET counts_for_session = 0
        WHERE session_id = ? AND queue_index = ? AND counts_for_session = 1
          AND is_replay = 0
        """,
        (session_id, queue_index),
    )


def slot_already_resolved(
    conn: sqlite3.Connection, session_id: int, queue_index: int
) -> bool:
    """True when this play-queue slot is locked or skipped (no further read attempts)."""
    skipped = conn.execute(
        """
        SELECT 1 FROM attempts
        WHERE session_id = ? AND queue_index = ? AND is_replay = 0
          AND result = 'skipped'
        LIMIT 1
        """,
        (session_id, queue_index),
    ).fetchone()
    if skipped:
        return True

    scored = conn.execute(
        """
        SELECT result, counts_for_session FROM attempts
        WHERE session_id = ? AND queue_index = ? AND is_replay = 0
          AND result IN ('correct', 'close', 'missed')
        ORDER BY id ASC
        """,
        (session_id, queue_index),
    ).fetchall()
    if not scored:
        return False
    if len(scored) >= 2:
        return True
    only = scored[0]
    if only["result"] == "correct":
        return True
    if only["result"] == "missed" and only["counts_for_session"] == 0:
        return False
    if only["result"] == "missed":
        return True
    if only["result"] == "close" and only["counts_for_session"] == 1:
        return False
    return True


def missed_replay_entries(conn: sqlite3.Connection, session_id: int) -> list[dict[str, Any]]:
    """Missed words from locking read attempts (not close). One entry per word."""
    rows = conn.execute(
        """
        SELECT a.item_id, a.word_scores, i.slug, i.text
        FROM attempts a
        JOIN items i ON i.id = a.item_id
        WHERE a.session_id = ? AND a.is_replay = 0 AND a.counts_for_session = 1
          AND a.result = 'missed'
        ORDER BY a.id ASC
        """,
        (session_id,),
    ).fetchall()
    entries: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    for row in rows:
        scores = json.loads(row["word_scores"] or "[]")
        if scores:
            for ws in scores:
                if ws.get("result") != "missed":
                    continue
                word = (ws.get("word") or "").strip()
                if not word:
                    continue
                key = (int(row["item_id"]), normalize_text(word))
                if key in seen:
                    continue
                seen.add(key)
                slug = word_audio_slug(conn, word, row["slug"])
                entries.append(
                    {
                        "item_id": int(row["item_id"]),
                        "text": word,
                        "slug": slug,
                        "audio_url": f"/api/audio/{slug}",
                        "word": word,
                    }
                )
        else:
            word = row["text"]
            key = (int(row["item_id"]), normalize_text(word))
            if key in seen:
                continue
            seen.add(key)
            slug = word_audio_slug(conn, word, row["slug"])
            entries.append(
                {
                    "item_id": int(row["item_id"]),
                    "text": word,
                    "slug": slug,
                    "audio_url": f"/api/audio/{slug}",
                    "word": word,
                }
            )
    return entries


def replay_already_done(
    conn: sqlite3.Connection, session_id: int, item_id: int, word: str
) -> bool:
    """True when a non-retry replay take already locked this item+word."""
    norm = normalize_text(word)
    row = conn.execute(
        """
        SELECT replay_word FROM attempts
        WHERE session_id = ? AND item_id = ? AND is_replay = 1
          AND result IN ('correct', 'close', 'missed')
        """,
        (session_id, item_id),
    ).fetchall()
    for r in row:
        if normalize_text(r["replay_word"] or "") == norm:
            return True
    return False


def consecutive_replay_retries(
    conn: sqlite3.Connection, session_id: int, item_id: int, word: str
) -> int:
    norm = normalize_text(word)
    rows = conn.execute(
        """
        SELECT result, replay_word FROM attempts
        WHERE session_id = ? AND item_id = ? AND is_replay = 1
        ORDER BY id DESC
        """,
        (session_id, item_id),
    ).fetchall()
    count = 0
    for row in rows:
        if normalize_text(row["replay_word"] or "") != norm:
            continue
        if row["result"] == "retry":
            count += 1
        else:
            break
    return count


def validate_attempt_access(
    conn: sqlite3.Connection,
    session_id: int,
    item_id: int,
    *,
    phase: str = "read",
    queue_index: int | None = None,
    replay_word: str = "",
) -> sqlite3.Row:
    """Validate session/item for read or replay. Returns the items row."""
    session = get_session(conn, session_id)
    if session is None:
        raise SessionError("not_found", "Unknown session", 404)

    item = get_item(conn, item_id)
    if item is None:
        raise SessionError("not_found", "Unknown item", 404)

    if phase == "replay":
        if session["completed"] != 1:
            raise SessionError(
                "bad_request",
                "Replay attempts are only allowed after session complete",
                400,
            )
        word = (replay_word or "").strip()
        if not word:
            raise SessionError(
                "bad_request",
                "Replay attempts require form field 'word'",
                400,
            )
        replay_entries = missed_replay_entries(conn, session_id)
        match_entry = next(
            (
                e
                for e in replay_entries
                if e["item_id"] == item_id
                and normalize_text(e["text"]) == normalize_text(word)
            ),
            None,
        )
        if match_entry is None:
            raise SessionError(
                "not_found",
                "Word is not on this session's replay list",
                404,
            )
        if replay_already_done(conn, session_id, item_id, word):
            raise SessionError(
                "already_resolved",
                "Replay already completed for this word",
                409,
            )
        return item

    # phase=read
    if session["completed"] == 1 or session["ended_at"] is not None:
        raise SessionError("session_closed", "Session already closed", 409)

    ids = play_ids(session)
    if queue_index is None:
        raise SessionError(
            "bad_request",
            "Read attempts require form field 'queue_index'",
            400,
        )
    if queue_index < 0 or queue_index >= len(ids):
        raise SessionError("not_found", "queue_index out of play queue range", 404)
    if ids[queue_index] != item_id:
        raise SessionError(
            "not_found",
            "item_id does not match play queue at queue_index",
            404,
        )

    if slot_already_resolved(conn, session_id, queue_index):
        raise SessionError(
            "already_resolved",
            "Queue slot already scored or skipped in this session",
            409,
        )
    return item


def _effort_stars(
    words_correct: int,
    *,
    result: str,
    again: bool,
    hard_bonus: bool,
) -> int:
    """Stars for a locking try; effort_stars awards at least one on correct/close."""
    if again:
        return 0
    awarded = int(words_correct)
    settings = load_settings()
    if (
        bool(settings.get("effort_stars", True))
        and result in ("correct", "close")
        and awarded < 1
    ):
        awarded = 1
    if hard_bonus and result == "correct":
        awarded += 1
    return awarded


def apply_attempt(
    conn: sqlite3.Connection,
    session_id: int,
    item_id: int,
    match: MatchResult,
    *,
    phase: str = "read",
    is_silence_path: bool = False,
    queue_index: int | None = None,
    replay_word: str = "",
    latency_ms: int | None = None,
) -> dict[str, Any]:
    if phase not in ("read", "replay"):
        raise SessionError("bad_request", "phase must be read or replay", 400)

    item = validate_attempt_access(
        conn,
        session_id,
        item_id,
        phase=phase,
        queue_index=queue_index,
        replay_word=replay_word,
    )
    session = get_session(conn, session_id)
    assert session is not None
    is_replay = 1 if phase == "replay" else 0
    stored_replay_word = normalize_text(replay_word) if is_replay else ""

    words_total = match.words_total or len(tokenize(item["text"]))
    stars_total = int(session["stars"])
    correct_count = int(session["correct_count"])
    planned_count = int(session["planned_count"])

    # Silence / uncertain retry / skip path (legacy result stays ``retry``|``skipped``).
    if is_silence_path or match.result == "retry":
        retry_outcome = "silence" if is_silence_path else match.outcome
        retry_reason = (
            "silence_gate"
            if is_silence_path
            else (match.reason_code or "low_asr_confidence")
        )
        if retry_outcome not in ("silence", "uncertain"):
            retry_outcome = "silence" if is_silence_path else "uncertain"
        if is_replay:
            prior = consecutive_replay_retries(
                conn, session_id, item_id, replay_word
            )
            if prior + 1 >= config.MAX_RETRIES_PER_ITEM:
                attempt_id = _insert_attempt(
                    conn,
                    session_id,
                    item_id,
                    heard="",
                    confidence=None,
                    word_scores=[],
                    result="skipped",
                    counts_for_session=0,
                    is_replay=1,
                    queue_index=None,
                    replay_word=stored_replay_word,
                )
                touch_mastery(conn, item_id, "skipped")
                conn.commit()
                return _merge_hint(
                    {
                        "result": "skipped",
                        "transcript": "",
                        "word_scores": [],
                        "words_correct": 0,
                        "words_total": words_total,
                        "stars_awarded": 0,
                        "stars_total": stars_total,
                        "message": config.MSG_SKIP,
                        "retry": False,
                        "again": False,
                        "read_again": False,
                        "try_number": None,
                        "tries_max": None,
                        "skipped": True,
                        "attempt_id": attempt_id,
                        **attempt_contract(
                            outcome="skipped",
                            reason_code="max_retries",
                            assisted=False,
                            mastery_eligible=False,
                        ),
                    },
                    empty_hint(),
                )
            # prior = retries already stored; this insert is +1; next read is +2.
            next_try = prior + 2
            attempt_id = _insert_attempt(
                conn,
                session_id,
                item_id,
                heard="",
                confidence=None,
                word_scores=[],
                result="retry",
                counts_for_session=0,
                is_replay=1,
                queue_index=None,
                replay_word=stored_replay_word,
            )
            touch_mastery(conn, item_id, "retry")
            conn.commit()
            hint = build_hint(
                target=str(item["text"]),
                pattern=str(item["pattern"] or "") if "pattern" in item.keys() else "",
                level=HINT_LISTEN,
                outcome=retry_outcome,
            )
            return _merge_hint(
                {
                    "result": "retry",
                    "transcript": "",
                    "word_scores": [],
                    "words_correct": 0,
                    "words_total": words_total,
                    "stars_awarded": 0,
                    "stars_total": stars_total,
                    "message": config.msg_retry(next_try, config.MAX_RETRIES_PER_ITEM),
                    "retry": True,
                    "again": True,
                    "read_again": True,
                    "try_number": next_try,
                    "tries_max": config.MAX_RETRIES_PER_ITEM,
                    "skipped": False,
                    "attempt_id": attempt_id,
                    **attempt_contract(
                        outcome=retry_outcome,  # type: ignore[arg-type]
                        reason_code=retry_reason,
                        assisted=False,
                        mastery_eligible=False,
                    ),
                },
                hint,
            )

        assert queue_index is not None
        prior_retries = consecutive_retries(conn, session_id, queue_index)
        if prior_retries + 1 >= config.MAX_RETRIES_PER_ITEM:
            if has_provisional_close(conn, session_id, queue_index):
                flip_prior_lock(conn, session_id, queue_index)
            # Skip shrinks planned_count only for planned slots — not reinserts.
            if is_ratio_slot(session, queue_index):
                planned_count = max(0, planned_count - 1)
                conn.execute(
                    "UPDATE sessions SET planned_count = ? WHERE id = ?",
                    (planned_count, session_id),
                )
            attempt_id = _insert_attempt(
                conn,
                session_id,
                item_id,
                heard="",
                confidence=None,
                word_scores=[],
                result="skipped",
                counts_for_session=0,
                is_replay=0,
                queue_index=queue_index,
                replay_word="",
            )
            touch_mastery(conn, item_id, "skipped")
            conn.commit()
            return _merge_hint(
                {
                    "result": "skipped",
                    "transcript": "",
                    "word_scores": [],
                    "words_correct": 0,
                    "words_total": words_total,
                    "stars_awarded": 0,
                    "stars_total": stars_total,
                    "message": config.MSG_SKIP,
                    "retry": False,
                    "again": False,
                    "read_again": False,
                    "try_number": None,
                    "tries_max": None,
                    "skipped": True,
                    "attempt_id": attempt_id,
                    **attempt_contract(
                        outcome="skipped",
                        reason_code="max_retries",
                        assisted=False,
                        mastery_eligible=False,
                    ),
                },
                empty_hint(),
            )

        # prior_retries = retries already stored; this insert is +1; next read is +2.
        next_try = prior_retries + 2
        attempt_id = _insert_attempt(
            conn,
            session_id,
            item_id,
            heard="",
            confidence=None,
            word_scores=[],
            result="retry",
            counts_for_session=0,
            is_replay=0,
            queue_index=queue_index,
            replay_word="",
        )
        touch_mastery(conn, item_id, "retry")
        conn.commit()
        hint = build_hint(
            target=str(item["text"]),
            pattern=str(item["pattern"] or "") if "pattern" in item.keys() else "",
            level=HINT_LISTEN,
            outcome=retry_outcome,
        )
        return _merge_hint(
            {
                "result": "retry",
                "transcript": "",
                "word_scores": [],
                "words_correct": 0,
                "words_total": words_total,
                "stars_awarded": 0,
                "stars_total": stars_total,
                "message": config.msg_retry(next_try, config.MAX_RETRIES_PER_ITEM),
                "retry": True,
                "again": True,
                "read_again": True,
                "try_number": next_try,
                "tries_max": config.MAX_RETRIES_PER_ITEM,
                "skipped": False,
                "attempt_id": attempt_id,
                **attempt_contract(
                    outcome=retry_outcome,  # type: ignore[arg-type]
                    reason_code=retry_reason,
                    assisted=False,
                    mastery_eligible=False,
                ),
            },
            hint,
        )

    result = match.result
    word_scores = [ws.to_dict() for ws in match.word_scores]
    transcript = match.transcript
    words_correct = match.words_correct
    confidences = [ws.confidence for ws in match.word_scores if ws.confidence is not None]
    mean_conf = (sum(confidences) / len(confidences)) if confidences else None

    stars_awarded = 0
    again = False
    counts_for_session = 0 if is_replay else 1
    message = config.MSG_CORRECT

    reinsert_info: dict[str, Any] | None = None
    hint_bundle: dict[str, Any] = empty_hint()

    assisted = False
    if is_replay:
        # Replay: stars/engagement only — never independent mastery evidence.
        stars_awarded = _effort_stars(
            words_correct,
            result=result,
            again=False,
            hard_bonus=False,
        )
        if result == "correct":
            message = config.MSG_CORRECT
        elif result == "close":
            message = config.MSG_CLOSE_OK
        else:
            message = config.MSG_MISS
        again = False
        stars_total += stars_awarded
        conn.execute(
            "UPDATE sessions SET stars = ? WHERE id = ?",
            (stars_total, session_id),
        )
    else:
        assert queue_index is not None
        replacing_close = has_provisional_close(conn, session_id, queue_index)
        replacing_miss = has_provisional_miss(conn, session_id, queue_index)
        session_mode = str(session["mode"] or "beginner").lower()
        # Strict keeps a close second-chance. Beginner does not — kids were
        # forced into a second try whenever Whisper marked a near-miss.
        ask_close_again = (
            result == "close"
            and not replacing_close
            and session_mode == "strict"
        )
        ask_miss_again = (
            result == "missed"
            and not replacing_miss
            and not replacing_close
        )
        item_pattern = (
            str(item["pattern"] or "") if "pattern" in item.keys() else ""
        )
        item_text = str(item["text"])
        if ask_close_again:
            again = True
            stars_awarded = 0
            message = config.MSG_CLOSE
            counts_for_session = 1
            hint_bundle = build_hint(
                target=item_text,
                heard=transcript,
                pattern=item_pattern,
                level=next_hint_level(0, kind="close"),
                outcome="incorrect",
            )
        elif ask_miss_again:
            again = True
            stars_awarded = 0
            message = config.MSG_MISS_AGAIN
            counts_for_session = 0
            hint_bundle = build_hint(
                target=item_text,
                heard=transcript,
                pattern=item_pattern,
                level=next_hint_level(0, kind="missed"),
                outcome="incorrect",
            )
        else:
            if replacing_close:
                flip_prior_lock(conn, session_id, queue_index)

            assisted = bool(replacing_close or replacing_miss)
            hard_bonus = (
                int(item["hard"] or 0) == 1
                and result == "correct"
                and not replacing_close
                and not assisted
            )
            stars_awarded = _effort_stars(
                words_correct,
                result=result,
                again=False,
                hard_bonus=hard_bonus,
            )

            play = play_ids(session)
            flags = ratio_flags(session)
            counts_for_ratio = is_ratio_slot(session, queue_index)

            if result == "correct":
                # Ratio: every planned slot; not same-session miss reinserts.
                if counts_for_ratio:
                    correct_count += 1
                message = config.MSG_CORRECT
                again = False
                # Prompted second-chance success is assisted — not independent mastery.
                if not assisted:
                    earlier_miss = conn.execute(
                        """
                        SELECT 1 FROM attempts
                        WHERE session_id = ? AND item_id = ? AND is_replay = 0
                          AND result = 'missed' AND counts_for_session = 1
                        LIMIT 1
                        """,
                        (session_id, item_id),
                    ).fetchone()
                    credit_mastery_correct(
                        conn, item_id, keep_plus_one_day=bool(earlier_miss)
                    )
            elif result == "close":
                # Beginner first close, or strict second close — lock & move on.
                message = config.MSG_CLOSE_OK
                again = False
                # Still offer a gentle highlight for learning (no second try).
                hint_bundle = build_hint(
                    target=item_text,
                    heard=transcript,
                    pattern=item_pattern,
                    level=HINT_HIGHLIGHT,
                    outcome="incorrect",
                )
            else:
                message = config.MSG_MISS
                again = False
                prior = HINT_HIGHLIGHT if replacing_miss else 0
                hint_bundle = build_hint(
                    target=item_text,
                    heard=transcript,
                    pattern=item_pattern,
                    level=next_hint_level(prior, kind="lock"),
                    outcome="incorrect",
                )
                if counts_for_session == 1:
                    apply_day_ladder(conn, item_id, "missed")
                    new_play, new_flags, reinsert_info = maybe_reinsert_miss(
                        conn, item_id, queue_index, play, flags
                    )
                    if reinsert_info is not None:
                        set_play_and_ratio_flags(
                            conn, session_id, new_play, new_flags
                        )

            stars_total += stars_awarded
            conn.execute(
                """
                UPDATE sessions
                SET stars = ?, correct_count = ?
                WHERE id = ?
                """,
                (stars_total, correct_count, session_id),
            )

    attempt_id = _insert_attempt(
        conn,
        session_id,
        item_id,
        heard=transcript,
        confidence=mean_conf,
        word_scores=word_scores,
        result=result,
        counts_for_session=counts_for_session,
        is_replay=is_replay,
        queue_index=queue_index if not is_replay else None,
        replay_word=stored_replay_word,
        latency_ms=latency_ms,
    )
    touch_mastery(conn, item_id, result)
    outcome = match.outcome
    reason_code = match.reason_code or ""
    if not outcome:
        outcome, reason_code = outcome_from_legacy_result(
            result, reason_code=reason_code
        )
    if again:
        # Provisional second-chance — never mastery-eligible.
        mastery_eligible = False
    elif is_replay:
        mastery_eligible = False
    elif assisted:
        mastery_eligible = False
    else:
        mastery_eligible = result == "correct" and counts_for_session == 1
    try:
        log_event(
            conn,
            session_id=session_id,
            item_id=item_id,
            pattern=str(item["pattern"] or "") if "pattern" in item.keys() else "",
            sight_word=bool(int(item["sight_word"] or 0))
            if "sight_word" in item.keys()
            else False,
            result=result if not again else "retry",
            phase="replay" if is_replay else phase,
            latency_ms=latency_ms,
            counts_for_mastery=bool(mastery_eligible),
            meta={
                "again": again,
                "words_correct": words_correct,
                "outcome": outcome,
                "assisted": assisted,
                "reason_code": reason_code,
                "hint_level": int(hint_bundle.get("hint_level") or 0),
            },
        )
    except Exception:  # noqa: BLE001
        logger.warning(
            "event log failed session=%s item=%s result=%s",
            session_id,
            item_id,
            result,
            exc_info=True,
        )
    conn.commit()

    payload: dict[str, Any] = {
        "result": result,
        "transcript": transcript,
        "word_scores": word_scores,
        "words_correct": words_correct,
        "words_total": words_total,
        "stars_awarded": stars_awarded,
        "stars_total": stars_total,
        "message": message,
        "retry": False,
        "again": again,
        "read_again": bool(again),
        # Close second-chance: the upcoming read is try 2 of 2.
        "try_number": 2 if again else None,
        "tries_max": 2 if again else None,
        "skipped": False,
        "reinsert": reinsert_info,
        "attempt_id": attempt_id,
        **attempt_contract(
            outcome=outcome,  # type: ignore[arg-type]
            reason_code=reason_code,
            assisted=assisted,
            mastery_eligible=mastery_eligible,
        ),
    }
    # Hard guarantee: locked results never ask for another read.
    if not again:
        payload["read_again"] = False
        payload["try_number"] = None
        payload["tries_max"] = None
        if result == "close" and message == config.MSG_CLOSE:
            payload["message"] = config.MSG_CLOSE_OK
    return _merge_hint(payload, hint_bundle)


def _insert_attempt(
    conn: sqlite3.Connection,
    session_id: int,
    item_id: int,
    *,
    heard: str,
    confidence: float | None,
    word_scores: list[dict],
    result: str,
    counts_for_session: int,
    is_replay: int,
    queue_index: int | None,
    replay_word: str,
    latency_ms: int | None = None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO attempts (
          session_id, item_id, heard, confidence, word_scores, result,
          counts_for_session, is_replay, queue_index, replay_word, created_at,
          latency_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            item_id,
            heard if heard is not None else "",
            confidence,
            json.dumps(word_scores),
            result,
            counts_for_session,
            is_replay,
            queue_index,
            replay_word or "",
            local_now_iso(),
            latency_ms,
        ),
    )
    return int(cur.lastrowid)


def open_session_view(conn: sqlite3.Connection) -> dict[str, Any]:
    """Return the unfinished session so a refresh can offer Continue."""
    session = conn.execute(
        """
        SELECT * FROM sessions
        WHERE ended_at IS NULL AND completed = 0
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()
    if session is None:
        return {"open": False}
    ids = play_ids(session)
    items = []
    for item_id in ids:
        row = get_item(conn, int(item_id))
        if row is not None:
            items.append(item_public(row))
    index = len(ids)
    for i in range(len(ids)):
        if not slot_already_resolved(conn, int(session["id"]), i):
            index = i
            break
    settings = load_settings()
    level = int(session["level"])
    by_diff = settings.get("stage_by_difficulty") or {}
    stage = config.normalize_stage(by_diff.get(str(level), settings.get("stage", 1)))
    sid = int(session["id"])
    hint_pending = False
    if index < len(ids):
        hint_pending = has_provisional_miss(conn, sid, index) or has_provisional_close(
            conn, sid, index
        )
    return {
        "open": True,
        "session_id": sid,
        "index": index,
        "items": items,
        "stars": int(session["stars"]),
        "level": level,
        "stage": stage,
        "stage_label": config.stage_label(level, stage),
        "planned_count": int(session["planned_count"]),
        "mode": session["mode"],
        "buddy": settings.get("buddy", "krishna"),
        "hint_pending": hint_pending,
    }


def passage_target_text(conn: sqlite3.Connection, session_id: int) -> str:
    session = get_session(conn, session_id)
    if session is None:
        raise SessionError("not_found", "Unknown session", 404)
    if session["completed"] == 1 or session["ended_at"] is not None:
        raise SessionError("session_closed", "Session already closed", 409)
    parts: list[str] = []
    grouped = False
    for item_id in play_ids(session):
        row = get_item(conn, int(item_id))
        if row is None:
            continue
        if row["rhyme_group"] or ("story_id" in row.keys() and row["story_id"]):
            grouped = True
        parts.append(str(row["text"]))
    if not grouped or not parts:
        raise SessionError(
            "bad_request",
            "Read it through is only for a poem or a story",
            400,
        )
    return " ".join(parts)


def apply_passage(
    conn: sqlite3.Connection,
    session_id: int,
    match: MatchResult,
    *,
    duration_seconds: float | None,
) -> dict[str, Any]:
    """Score one fluent pass. Does not finish the session or move the set."""
    session = get_session(conn, session_id)
    if session is None:
        raise SessionError("not_found", "Unknown session", 404)
    if session["completed"] == 1 or session["ended_at"] is not None:
        raise SessionError("session_closed", "Session already closed", 409)
    passage_target_text(conn, session_id)
    item_id = play_ids(session)[0]
    stars_awarded = match.words_correct
    stars_total = int(session["stars"]) + stars_awarded
    conn.execute(
        "UPDATE sessions SET stars = ? WHERE id = ?",
        (stars_total, session_id),
    )
    attempt_id = _insert_attempt(
        conn,
        session_id,
        int(item_id),
        heard=match.transcript,
        confidence=None,
        word_scores=[ws.to_dict() for ws in match.word_scores],
        result=match.result,
        counts_for_session=0,
        is_replay=0,
        queue_index=None,
        replay_word="",
    )
    conn.execute(
        """
        UPDATE attempts
        SET passage = 1, duration_seconds = ?
        WHERE id = ?
        """,
        (duration_seconds, attempt_id),
    )
    conn.commit()
    outcome = match.outcome or outcome_from_legacy_result(match.result)[0]
    reason = match.reason_code or outcome_from_legacy_result(match.result)[1]
    return {
        "result": match.result,
        "transcript": match.transcript,
        "word_scores": [ws.to_dict() for ws in match.word_scores],
        "words_correct": match.words_correct,
        "words_total": match.words_total,
        "stars_awarded": stars_awarded,
        "stars_total": stars_total,
        "message": config.MSG_CORRECT if match.result == "correct" else config.MSG_MISS_AGAIN,
        "retry": False,
        "again": False,
        "read_again": False,
        "try_number": None,
        "tries_max": None,
        "skipped": False,
        "passage": True,
        "attempt_id": attempt_id,
        **attempt_contract(
            outcome=outcome,  # type: ignore[arg-type]
            reason_code=reason,
            assisted=False,
            mastery_eligible=False,
        ),
    }


def words_mastered_this_session(conn: sqlite3.Connection, session_id: int) -> list[str]:
    """Words that hit Leitner mastery today in this session (not legacy count=3)."""
    rows = conn.execute(
        """
        SELECT DISTINCT i.text
        FROM attempts a
        JOIN items i ON i.id = a.item_id
        JOIN mastery m ON m.item_id = a.item_id
        WHERE a.session_id = ? AND a.result = 'correct' AND a.counts_for_session = 1
          AND m.mastered = 1
          AND m.mastered_on = ?
          AND COALESCE(m.box, 0) >= ?
        ORDER BY i.id ASC
        """,
        (session_id, local_today(), config.LEITNER_MASTERED_BOX),
    ).fetchall()
    return [str(row["text"]) for row in rows]


def complete_session(conn: sqlite3.Connection, session_id: int) -> dict[str, Any]:
    session = get_session(conn, session_id)
    if session is None:
        raise SessionError("not_found", "Unknown session", 404)
    if session["completed"] == 1 or session["ended_at"] is not None:
        raise SessionError("session_closed", "Session already closed", 409)

    now = local_now_iso()
    planned_count = int(session["planned_count"])
    correct_count = int(session["correct_count"])
    low_session = 1 if correct_count * 2 < planned_count else 0
    settings = load_settings()
    level_after, new_settings = apply_level_and_auto_strict(
        level=int(session["level"]),
        correct_count=correct_count,
        planned_count=planned_count,
        settings=settings,
    )
    save_settings(new_settings)
    from app.parent import bump_garden, bump_play_stats, garden_stage_name, play_summary

    growth_before = int(new_settings.get("garden_growth", 0) or 0)
    stage_before = garden_stage_name(growth_before)
    garden = bump_garden(new_settings)
    garden["stage_before"] = stage_before
    garden["stage_changed"] = garden["stage"] != stage_before
    # Re-load after garden write so play stats see latest growth.
    after_garden = load_settings()
    play = bump_play_stats(after_garden, stars_earned=int(session["stars"]))
    conn.execute(
        """
        UPDATE sessions
        SET ended_at = ?, completed = 1, low_session = ?, level_after = ?
        WHERE id = ?
        """,
        (now, low_session, level_after, session_id),
    )
    conn.commit()
    session = get_session(conn, session_id)
    assert session is not None
    replay = missed_replay_entries(conn, session_id)
    final = load_settings()
    stage_after = config.normalize_stage(final.get("stage", 1))
    return {
        "stars": int(session["stars"]),
        "correct_count": int(session["correct_count"]),
        "planned_count": int(session["planned_count"]),
        "replay": replay,
        "level_after": level_after,
        "stage_after": stage_after,
        "stages_total": config.STAGES_PER_DIFFICULTY,
        "stage_label": config.stage_label(level_after, stage_after),
        "mode": final.get("mode", session["mode"]),
        "garden": garden,
        "buddy": final.get("buddy", "krishna"),
        "play": play,
        "home": play_summary(),
        "mastered_words": words_mastered_this_session(conn, session_id),
        "set_progress": set_progress(conn),
    }
