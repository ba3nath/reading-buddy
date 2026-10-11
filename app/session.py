"""Session queue, stars, close second-take, three-retry skip (M1)."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from app import config
from app.db import (
    credit_mastery_correct,
    ensure_mastery_row,
    get_item,
    get_session,
    item_public,
    list_items_for_level,
    load_settings,
    local_now_iso,
    touch_mastery,
)
from app.matching import MatchResult, tokenize


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
    # M1 content is levels 1–3
    if target_level > 3:
        raise SessionError("bad_request", "Milestone 1 supports levels 1–3 only", 400)

    length = int(settings.get("session_length", config.DEFAULT_SESSION_LENGTH))
    length = max(5, min(20, length))
    mode = "beginner"  # M1 product path

    abandon_open_sessions(conn)
    queue = build_fixed_queue(conn, target_level, length)
    planned_ids = [row["id"] for row in queue]
    for row in queue:
        ensure_mastery_row(conn, row["id"])

    cur = conn.execute(
        """
        INSERT INTO sessions (
          started_at, ended_at, mode, level, planned_count, planned_item_ids,
          correct_count, stars, low_session, level_after, completed
        ) VALUES (?, NULL, ?, ?, ?, ?, 0, 0, 0, NULL, 0)
        """,
        (
            local_now_iso(),
            mode,
            target_level,
            length,
            json.dumps(planned_ids),
        ),
    )
    session_id = int(cur.lastrowid)
    conn.commit()
    return {
        "session_id": session_id,
        "level": target_level,
        "mode": mode,
        "items": [item_public(row) for row in queue],
    }


def planned_ids(session: sqlite3.Row) -> list[int]:
    return list(json.loads(session["planned_item_ids"]))


def consecutive_retries(conn: sqlite3.Connection, session_id: int, item_id: int) -> int:
    rows = conn.execute(
        """
        SELECT result FROM attempts
        WHERE session_id = ? AND item_id = ? AND is_replay = 0
        ORDER BY id DESC
        """,
        (session_id, item_id),
    ).fetchall()
    count = 0
    for row in rows:
        if row["result"] == "retry":
            count += 1
        else:
            break
    return count


def has_provisional_close(conn: sqlite3.Connection, session_id: int, item_id: int) -> bool:
    row = conn.execute(
        """
        SELECT id, result, counts_for_session FROM attempts
        WHERE session_id = ? AND item_id = ? AND is_replay = 0 AND counts_for_session = 1
        ORDER BY id DESC LIMIT 1
        """,
        (session_id, item_id),
    ).fetchone()
    return bool(row and row["result"] == "close")


def flip_prior_lock(conn: sqlite3.Connection, session_id: int, item_id: int) -> None:
    conn.execute(
        """
        UPDATE attempts
        SET counts_for_session = 0
        WHERE session_id = ? AND item_id = ? AND counts_for_session = 1 AND is_replay = 0
        """,
        (session_id, item_id),
    )


def item_already_resolved(conn: sqlite3.Connection, session_id: int, item_id: int) -> bool:
    """True when this planned item is locked or skipped (no further read attempts)."""
    skipped = conn.execute(
        """
        SELECT 1 FROM attempts
        WHERE session_id = ? AND item_id = ? AND is_replay = 0 AND result = 'skipped'
        LIMIT 1
        """,
        (session_id, item_id),
    ).fetchone()
    if skipped:
        return True

    scored = conn.execute(
        """
        SELECT result, counts_for_session FROM attempts
        WHERE session_id = ? AND item_id = ? AND is_replay = 0
          AND result IN ('correct', 'close', 'missed')
        ORDER BY id ASC
        """,
        (session_id, item_id),
    ).fetchall()
    if not scored:
        return False
    # Second take already happened (close then replace).
    if len(scored) >= 2:
        return True
    only = scored[0]
    if only["result"] in ("correct", "missed"):
        return True
    # Single provisional close still awaiting one immediate re-record.
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
                word = ws.get("word") or ""
                key = (int(row["item_id"]), word)
                if key in seen:
                    continue
                seen.add(key)
                # Single-word items: slug matches; multi-word later may differ.
                slug = row["slug"] if len(scores) == 1 else row["slug"]
                entries.append(
                    {
                        "item_id": int(row["item_id"]),
                        "text": word or row["text"],
                        "audio_url": f"/api/audio/{slug}",
                    }
                )
        else:
            key = (int(row["item_id"]), row["text"])
            if key in seen:
                continue
            seen.add(key)
            entries.append(
                {
                    "item_id": int(row["item_id"]),
                    "text": row["text"],
                    "audio_url": f"/api/audio/{row['slug']}",
                }
            )
    return entries


def replay_already_done(conn: sqlite3.Connection, session_id: int, item_id: int) -> bool:
    """True when a non-retry replay take already locked this item."""
    row = conn.execute(
        """
        SELECT 1 FROM attempts
        WHERE session_id = ? AND item_id = ? AND is_replay = 1
          AND result IN ('correct', 'close', 'missed')
        LIMIT 1
        """,
        (session_id, item_id),
    ).fetchone()
    return bool(row)


def consecutive_replay_retries(
    conn: sqlite3.Connection, session_id: int, item_id: int
) -> int:
    rows = conn.execute(
        """
        SELECT result FROM attempts
        WHERE session_id = ? AND item_id = ? AND is_replay = 1
        ORDER BY id DESC
        """,
        (session_id, item_id),
    ).fetchall()
    count = 0
    for row in rows:
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
        replay_ids = {e["item_id"] for e in missed_replay_entries(conn, session_id)}
        if item_id not in replay_ids:
            raise SessionError(
                "not_found",
                "Item is not on this session's replay list",
                404,
            )
        if replay_already_done(conn, session_id, item_id):
            raise SessionError(
                "bad_request",
                "Replay already completed for this item",
                409,
            )
        return item

    # phase=read
    if session["completed"] == 1 or session["ended_at"] is not None:
        raise SessionError("session_closed", "Session already closed", 409)

    ids = planned_ids(session)
    if item_id not in ids:
        raise SessionError("not_found", "Item not in this session queue", 404)

    if item_already_resolved(conn, session_id, item_id):
        raise SessionError(
            "bad_request",
            "Item already scored or skipped in this session",
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
) -> dict[str, Any]:
    if phase not in ("read", "replay"):
        raise SessionError("bad_request", "phase must be read or replay", 400)

    item = validate_attempt_access(conn, session_id, item_id, phase=phase)
    session = get_session(conn, session_id)
    assert session is not None
    is_replay = 1 if phase == "replay" else 0

    words_total = match.words_total or len(tokenize(item["text"]))
    stars_total = int(session["stars"])
    correct_count = int(session["correct_count"])
    planned_count = int(session["planned_count"])

    # Silence / retry / skip path
    if is_silence_path or match.result == "retry":
        if is_replay:
            # Replay silence: retry kindly; do not skip or touch planned_count.
            prior = consecutive_replay_retries(conn, session_id, item_id)
            if prior + 1 >= config.MAX_RETRIES_PER_ITEM:
                _insert_attempt(
                    conn,
                    session_id,
                    item_id,
                    heard="",
                    confidence=None,
                    word_scores=[],
                    result="skipped",
                    counts_for_session=0,
                    is_replay=1,
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
                }
            _insert_attempt(
                conn,
                session_id,
                item_id,
                heard="",
                confidence=None,
                word_scores=[],
                result="retry",
                counts_for_session=0,
                is_replay=1,
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
            }

        prior_retries = consecutive_retries(conn, session_id, item_id)
        if prior_retries + 1 >= config.MAX_RETRIES_PER_ITEM:
            if has_provisional_close(conn, session_id, item_id):
                flip_prior_lock(conn, session_id, item_id)
            planned_count = max(0, planned_count - 1)
            conn.execute(
                "UPDATE sessions SET planned_count = ? WHERE id = ?",
                (planned_count, session_id),
            )
            _insert_attempt(
                conn,
                session_id,
                item_id,
                heard="",
                confidence=None,
                word_scores=[],
                result="skipped",
                counts_for_session=0,
                is_replay=0,
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
            }

        _insert_attempt(
            conn,
            session_id,
            item_id,
            heard="",
            confidence=None,
            word_scores=[],
            result="retry",
            counts_for_session=0,
            is_replay=0,
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

    if is_replay:
        # Replay: stars + mastery; never change correct_count / planned_count.
        if result == "close" and not _replay_has_close(conn, session_id, item_id):
            again = True
            stars_awarded = 0
            message = config.MSG_CLOSE
            counts_for_session = 0
        else:
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
        # Close second-take detection (read phase)
        replacing_close = has_provisional_close(conn, session_id, item_id)
        if result == "close" and not replacing_close:
            again = True
            stars_awarded = 0
            message = config.MSG_CLOSE
            counts_for_session = 1
        else:
            if replacing_close:
                flip_prior_lock(conn, session_id, item_id)

            stars_awarded = words_correct
            if item["hard"] == 1 and result == "correct" and not replacing_close:
                stars_awarded += 1

            if result == "correct":
                correct_count += 1
                message = config.MSG_CORRECT
                again = False
                credit_mastery_correct(conn, item_id)
            elif result == "close":
                message = config.MSG_CLOSE
                again = False
            else:
                message = config.MSG_MISS
                again = False

            stars_total += stars_awarded
            conn.execute(
                """
                UPDATE sessions
                SET stars = ?, correct_count = ?
                WHERE id = ?
                """,
                (stars_total, correct_count, session_id),
            )

    _insert_attempt(
        conn,
        session_id,
        item_id,
        heard=transcript,
        confidence=mean_conf,
        word_scores=word_scores,
        result=result,
        counts_for_session=counts_for_session,
        is_replay=is_replay,
    )
    touch_mastery(conn, item_id, result)
    conn.commit()

    return {
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
    }


def _replay_has_close(conn: sqlite3.Connection, session_id: int, item_id: int) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM attempts
        WHERE session_id = ? AND item_id = ? AND is_replay = 1 AND result = 'close'
        LIMIT 1
        """,
        (session_id, item_id),
    ).fetchone()
    return bool(row)


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
) -> int:
    cur = conn.execute(
        """
        INSERT INTO attempts (
          session_id, item_id, heard, confidence, word_scores, result,
          counts_for_session, is_replay, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            local_now_iso(),
        ),
    )
    return int(cur.lastrowid)


def complete_session(conn: sqlite3.Connection, session_id: int) -> dict[str, Any]:
    session = get_session(conn, session_id)
    if session is None:
        raise SessionError("not_found", "Unknown session", 404)
    # Abandoned (ended_at set, completed=0) and already-completed both reject.
    if session["completed"] == 1 or session["ended_at"] is not None:
        raise SessionError("session_closed", "Session already closed", 409)

    now = local_now_iso()
    planned_count = int(session["planned_count"])
    correct_count = int(session["correct_count"])
    low_session = 1 if correct_count * 2 < planned_count else 0
    # M1/M2: no level move
    conn.execute(
        """
        UPDATE sessions
        SET ended_at = ?, completed = 1, low_session = ?, level_after = ?
        WHERE id = ?
        """,
        (now, low_session, session["level"], session_id),
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
    }

