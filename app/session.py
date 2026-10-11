"""Session queue, stars, close second-take, three-retry skip, slot locks."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from app import config
from app.adaptive import (
    apply_day_ladder,
    apply_level_and_auto_strict,
    build_adaptive_queue,
    maybe_reinsert_miss,
)
from app.db import (
    credit_mastery_correct,
    ensure_mastery_row,
    get_item,
    get_session,
    item_public,
    list_items_for_level,
    load_settings,
    local_now_iso,
    save_settings,
    touch_mastery,
)
from app.matching import MatchResult, normalize_text, tokenize


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


def build_fixed_queue(conn: sqlite3.Connection, level: int, length: int) -> list[sqlite3.Row]:
    pool = list_items_for_level(conn, level)
    if not pool:
        raise SessionError("unavailable", f"No content for level {level}", 503)
    queue: list[sqlite3.Row] = []
    idx = 0
    while len(queue) < length:
        queue.append(pool[idx % len(pool)])
        idx += 1
    return queue


def start_session(conn: sqlite3.Connection, level: int | None = None) -> dict[str, Any]:
    settings = load_settings()
    target_level = int(level if level is not None else settings.get("level", 1))
    if target_level < 1 or target_level > 7:
        raise SessionError("bad_request", "level must be between 1 and 7", 400)

    length = int(settings.get("session_length", config.DEFAULT_SESSION_LENGTH))
    length = max(5, min(20, length))
    mode = str(settings.get("mode", "beginner")).lower()
    if mode not in ("beginner", "strict"):
        mode = "beginner"

    abandon_open_sessions(conn)
    try:
        queue = build_adaptive_queue(conn, target_level, length)
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

    ratio_flags = [True] * length  # every planned slot counts (incl. adaptive repeats)
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
    return {
        "session_id": session_id,
        "level": target_level,
        "mode": mode,
        "buddy": settings.get("buddy", "cat"),
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
    """True for planned queue slots (including adaptive repeats); false for reinserts.

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
    if only["result"] in ("correct", "missed"):
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

    # Silence / retry / skip path
    if is_silence_path or match.result == "retry":
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
                return {
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
                    "skipped": True,
                    "attempt_id": attempt_id,
                }
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
            return {
                "result": "retry",
                "transcript": "",
                "word_scores": [],
                "words_correct": 0,
                "words_total": words_total,
                "stars_awarded": 0,
                "stars_total": stars_total,
                "message": config.MSG_RETRY,
                "retry": True,
                "again": True,
                "skipped": False,
                "attempt_id": attempt_id,
            }

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
            return {
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
                "skipped": True,
                "attempt_id": attempt_id,
            }

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
        return {
            "result": "retry",
            "transcript": "",
            "word_scores": [],
            "words_correct": 0,
            "words_total": words_total,
            "stars_awarded": 0,
            "stars_total": stars_total,
            "message": config.MSG_RETRY,
            "retry": True,
            "again": True,
            "skipped": False,
            "attempt_id": attempt_id,
        }

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

    if is_replay:
        # Replay: one non-retry take locks and advances. No close re-ask.
        stars_awarded = words_correct
        if result == "correct":
            message = config.MSG_CORRECT
            credit_mastery_correct(conn, item_id)
        elif result == "close":
            message = config.MSG_CLOSE
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
        if result == "close" and not replacing_close:
            again = True
            stars_awarded = 0
            message = config.MSG_CLOSE
            counts_for_session = 1
        else:
            if replacing_close:
                flip_prior_lock(conn, session_id, queue_index)

            stars_awarded = words_correct
            if item["hard"] == 1 and result == "correct" and not replacing_close:
                stars_awarded += 1

            play = play_ids(session)
            flags = ratio_flags(session)
            counts_for_ratio = is_ratio_slot(session, queue_index)

            if result == "correct":
                # Ratio: every planned slot (incl. adaptive repeats); not reinserts.
                if counts_for_ratio:
                    correct_count += 1
                message = config.MSG_CORRECT
                again = False
                # Same-session correct after an earlier miss keeps +1 day review.
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
                message = config.MSG_CLOSE
                again = False
            else:
                message = config.MSG_MISS
                again = False
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
    )
    touch_mastery(conn, item_id, result)
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
        "skipped": False,
        "reinsert": reinsert_info,
        "attempt_id": attempt_id,
    }
    return payload


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
) -> int:
    cur = conn.execute(
        """
        INSERT INTO attempts (
          session_id, item_id, heard, confidence, word_scores, result,
          counts_for_session, is_replay, queue_index, replay_word, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        ),
    )
    return int(cur.lastrowid)


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
    from app.parent import bump_garden

    garden = bump_garden(new_settings)
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
    return {
        "stars": int(session["stars"]),
        "correct_count": int(session["correct_count"]),
        "planned_count": int(session["planned_count"]),
        "replay": replay,
        "level_after": level_after,
        "mode": new_settings.get("mode", session["mode"]),
        "garden": garden,
        "buddy": new_settings.get("buddy", "cat"),
    }
