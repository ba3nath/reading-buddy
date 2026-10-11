"""Adaptive queue, level moves, day ladder, mastery, auto-strict (M3)."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from typing import Any

from app import config
from app.db import get_item, item_public, local_today, ensure_mastery_row


def move_up_score(correct_count: int, planned_count: int) -> bool:
    """Item-level 8/10 default: correct_count * 10 >= 8 * N."""
    n = max(0, int(planned_count))
    if n == 0:
        return False
    return int(correct_count) * 10 >= 8 * n


def under_half(correct_count: int, planned_count: int) -> bool:
    n = max(0, int(planned_count))
    if n == 0:
        return False
    return int(correct_count) * 2 < n


def apply_level_and_auto_strict(
    *,
    level: int,
    correct_count: int,
    planned_count: int,
    settings: dict[str, Any],
) -> tuple[int, dict[str, Any]]:
    """Return (level_after, updated_settings) for a completed session.

    ``level`` is a difficulty tier 1–4 (words / phrases / rhymes / stories).
    """
    settings = dict(settings)
    level = config.normalize_difficulty(level)
    low_streak = int(settings.get("low_streak", 0))
    move_up_streak = int(settings.get("move_up_streak", 0))
    level_after = level

    if move_up_score(correct_count, planned_count):
        level_after = min(config.MAX_DIFFICULTY, level + 1)
        low_streak = 0
        move_up_streak += 1
    elif under_half(correct_count, planned_count):
        low_streak += 1
        move_up_streak = 0
        if low_streak >= 2:
            level_after = max(1, level - 1)
            low_streak = 0
    else:
        low_streak = 0
        move_up_streak = 0

    settings["low_streak"] = low_streak
    settings["move_up_streak"] = move_up_streak
    settings["level"] = level_after
    settings["difficulty_migrated"] = True

    if settings.get("auto_strict", True):
        streak_need = int(
            settings.get("auto_strict_sessions", config.AUTO_STRICT_SESSIONS)
        )
        if move_up_streak >= streak_need:
            settings["mode"] = "strict"

    return level_after, settings


def _today() -> date:
    return date.fromisoformat(local_today())


def apply_day_ladder(
    conn: sqlite3.Connection,
    item_id: int,
    result: str,
    *,
    keep_plus_one_day: bool = False,
) -> None:
    """Update mastery + review ladder for a locking miss/correct or replay correct.

    Close does not call this. Mastery: correct_count >= 3 and >= 2 distinct days.
    """
    if result not in ("missed", "correct"):
        return
    ensure_mastery_row(conn, item_id)
    row = conn.execute(
        """
        SELECT review_step, next_review_on, mastered, correct_count, days_json
        FROM mastery WHERE item_id = ?
        """,
        (item_id,),
    ).fetchone()
    today = _today()
    today_s = local_today()

    if result == "missed":
        if row["mastered"] == 1:
            conn.execute(
                """
                UPDATE mastery
                SET miss_count = miss_count + 1, last_result = 'missed',
                    last_seen_on = ?
                WHERE item_id = ?
                """,
                (today_s, item_id),
            )
            return
        step = int(row["review_step"] or 0)
        if step == 0:
            next_on = today + timedelta(days=1)
            step = 1
        elif step == 1:
            next_on = today + timedelta(days=3)
            step = 3
        else:
            next_on = today + timedelta(days=7)
            step = 7
        conn.execute(
            """
            UPDATE mastery
            SET review_step = ?, next_review_on = ?, miss_count = miss_count + 1,
                last_result = 'missed', last_seen_on = ?
            WHERE item_id = ?
            """,
            (step, next_on.isoformat(), today_s, item_id),
        )
        return

    # correct
    days = json.loads(row["days_json"] or "[]")
    if today_s not in days:
        days.append(today_s)
    correct_count = int(row["correct_count"]) + 1
    mastered = 1 if correct_count >= 3 and len(set(days)) >= 2 else 0

    if mastered or row["mastered"] == 1:
        conn.execute(
            """
            UPDATE mastery
            SET correct_count = ?, days_json = ?, review_step = 0,
                next_review_on = NULL, mastered = 1,
                mastered_on = COALESCE(mastered_on, ?),
                last_result = 'correct', last_seen_on = ?
            WHERE item_id = ?
            """,
            (correct_count, json.dumps(days), today_s, today_s, item_id),
        )
        return

    step = int(row["review_step"] or 0)
    on_ladder = row["next_review_on"] is not None or step > 0

    if keep_plus_one_day:
        next_on = today + timedelta(days=1)
        step = 1
    elif on_ladder:
        if step <= 1:
            next_on = today + timedelta(days=3)
            step = 3
        else:
            next_on = today + timedelta(days=7)
            step = 7
    else:
        next_on = None
        step = 0

    conn.execute(
        """
        UPDATE mastery
        SET correct_count = ?, days_json = ?, review_step = ?,
            next_review_on = ?, last_result = 'correct', last_seen_on = ?
        WHERE item_id = ?
        """,
        (
            correct_count,
            json.dumps(days),
            step,
            next_on.isoformat() if next_on else None,
            today_s,
            item_id,
        ),
    )


def had_correct_today(conn: sqlite3.Connection, item_id: int) -> bool:
    today_s = local_today()
    row = conn.execute(
        """
        SELECT 1 FROM attempts
        WHERE item_id = ? AND result = 'correct'
          AND (counts_for_session = 1 OR is_replay = 1)
          AND substr(created_at, 1, 10) = ?
        LIMIT 1
        """,
        (item_id, today_s),
    ).fetchone()
    return bool(row)


def sessions_since_item(conn: sqlite3.Connection, item_id: int) -> int:
    last = conn.execute(
        """
        SELECT MAX(s.id) AS sid
        FROM attempts a
        JOIN sessions s ON s.id = a.session_id
        WHERE a.item_id = ? AND s.completed = 1
        """,
        (item_id,),
    ).fetchone()["sid"]
    current = conn.execute(
        "SELECT COALESCE(MAX(id), 0) AS sid FROM sessions WHERE completed = 1"
    ).fetchone()["sid"]
    if last is None:
        return 10**9
    return max(0, int(current) - int(last))


def _placeholders(n: int) -> str:
    return ",".join("?" * n)


def _rhyme_grouped(conn: sqlite3.Connection, content_levels: tuple[int, ...]) -> list[sqlite3.Row]:
    """Prefer whole rhyme groups in line_index order across rhyme content levels."""
    ph = _placeholders(len(content_levels))
    groups = conn.execute(
        f"""
        SELECT rhyme_group, MIN(line_index) AS mi
        FROM items
        WHERE level IN ({ph}) AND rhyme_group IS NOT NULL
        GROUP BY rhyme_group
        ORDER BY mi ASC, rhyme_group ASC
        """,
        content_levels,
    ).fetchall()
    rows: list[sqlite3.Row] = []
    for g in groups:
        lines = conn.execute(
            f"""
            SELECT i.*
            FROM items i
            LEFT JOIN mastery m ON m.item_id = i.id
            WHERE i.level IN ({ph}) AND i.rhyme_group = ?
              AND COALESCE(m.mastered, 0) = 0
            ORDER BY i.level ASC, i.line_index ASC, i.id ASC
            """,
            (*content_levels, g["rhyme_group"]),
        ).fetchall()
        rows.extend(lines)
    return rows


def _snap_uniform_length(queue: list[sqlite3.Row], target: int) -> list[sqlite3.Row]:
    """Return exactly 5 or 10 items when possible (never 6–9)."""
    target = config.normalize_session_length(target)
    n = len(queue)
    if n >= target:
        return queue[:target]
    if target == 10 and n >= 5:
        return queue[:5]
    return queue


def build_adaptive_queue(
    conn: sqlite3.Connection, level: int, length: int
) -> list[sqlite3.Row]:
    """Build a unique queue for a difficulty tier (1–4).

    Fills from all content levels in the tier: due → fresh unmastered →
    practiced-today unmastered → mastered, then snaps to 5 or 10.
    """
    difficulty = config.normalize_difficulty(level)
    length = config.normalize_session_length(length)
    content_levels = config.content_levels_for_difficulty(difficulty)
    ph = _placeholders(len(content_levels))
    today = local_today()
    queue: list[sqlite3.Row] = []
    seen: set[int] = set()

    def _take(rows: list[sqlite3.Row], *, skip_correct_today: bool = False) -> None:
        for row in rows:
            if len(queue) >= length:
                return
            if row["id"] in seen:
                continue
            if skip_correct_today and had_correct_today(conn, row["id"]):
                continue
            queue.append(row)
            seen.add(row["id"])

    due = conn.execute(
        f"""
        SELECT i.*
        FROM items i
        JOIN mastery m ON m.item_id = i.id
        WHERE i.level IN ({ph})
          AND m.mastered = 0
          AND m.next_review_on IS NOT NULL
          AND m.next_review_on <= ?
        ORDER BY m.next_review_on ASC, i.id ASC
        """,
        (*content_levels, today),
    ).fetchall()
    _take(due)

    if difficulty == 3:  # rhymes
        fill = _rhyme_grouped(conn, content_levels)
    else:
        fill = conn.execute(
            f"""
            SELECT i.*
            FROM items i
            LEFT JOIN mastery m ON m.item_id = i.id
            WHERE i.level IN ({ph})
              AND COALESCE(m.mastered, 0) = 0
            ORDER BY COALESCE(m.correct_count, 0) ASC, i.level ASC, i.id ASC
            """,
            content_levels,
        ).fetchall()
    _take(fill, skip_correct_today=True)
    # Prefer a full 5/10 set: allow same-day unmastered before mastered padding.
    if len(queue) < length:
        _take(fill, skip_correct_today=False)

    if len(queue) < length:
        mastered = conn.execute(
            f"""
            SELECT i.*, m.last_seen_on
            FROM items i
            JOIN mastery m ON m.item_id = i.id
            WHERE m.mastered = 1 AND i.level IN ({ph})
            ORDER BY CASE WHEN m.last_seen_on IS NULL THEN 0 ELSE 1 END,
                     m.last_seen_on ASC, i.id ASC
            """,
            content_levels,
        ).fetchall()
        for row in mastered:
            if len(queue) >= length:
                break
            if row["id"] in seen:
                continue
            # Prefer gated refreshers first; then any mastered to hit 5/10.
            if sessions_since_item(conn, row["id"]) >= config.MASTERED_EVERY_N_SESSIONS:
                queue.append(row)
                seen.add(row["id"])
        for row in mastered:
            if len(queue) >= length:
                break
            if row["id"] in seen:
                continue
            queue.append(row)
            seen.add(row["id"])

    # C7: never return an empty queue when any item exists in the tier.
    if not queue:
        fallback = conn.execute(
            f"""
            SELECT i.*
            FROM items i
            LEFT JOIN mastery m ON m.item_id = i.id
            WHERE i.level IN ({ph})
            ORDER BY CASE WHEN m.last_seen_on IS NULL THEN 0 ELSE 1 END,
                     m.last_seen_on ASC, i.id ASC
            LIMIT 1
            """,
            content_levels,
        ).fetchone()
        if fallback is not None:
            queue.append(fallback)

    if not queue:
        raise ValueError(f"No content for difficulty {difficulty}")
    return _snap_uniform_length(queue, length)


def maybe_reinsert_miss(
    conn: sqlite3.Connection,
    item_id: int,
    queue_index: int,
    play: list[int],
    flags: list[bool],
) -> tuple[list[int], list[bool], dict[str, Any] | None]:
    """Insert miss once, two items ahead. Reinsert slots do not count for ratio.

    Only planned (ratio) slots trigger a reinsert. A miss on an already-inserted
    reinsert does not insert again. At most one reinsert per item_id per session.
    """
    if queue_index < 0 or queue_index >= len(play) or queue_index >= len(flags):
        return play, flags, None
    if play[queue_index] != item_id:
        return play, flags, None
    # Miss on a reinsert slot — do not insert again.
    if not flags[queue_index]:
        return play, flags, None
    # Already reinserted this item once this session.
    for i, is_ratio in enumerate(flags):
        if not is_ratio and play[i] == item_id:
            return play, flags, None
    insert_at = min(queue_index + 3, len(play))
    new_play = list(play)
    new_flags = list(flags)
    new_play.insert(insert_at, item_id)
    new_flags.insert(insert_at, False)  # reinsert: does not count for ratio
    row = get_item(conn, item_id)
    if row is None:
        return play, flags, None
    return new_play, new_flags, {
        "item": item_public(row),
        "queue_index": insert_at,
    }
