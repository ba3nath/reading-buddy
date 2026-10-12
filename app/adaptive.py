"""Adaptive queue, level moves, day ladder, mastery, auto-strict (M3)."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from typing import Any

from app import config
from app.db import ensure_mastery_row, local_today


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

    ``level`` is a difficulty tier 1–4. Strong sessions advance the set
    (stage) within that difficulty; clearing the last set unlocks the next tier.
    """
    settings = dict(settings)
    level = config.normalize_difficulty(level)
    low_streak = int(settings.get("low_streak", 0))
    move_up_streak = int(settings.get("move_up_streak", 0))
    by_diff = settings.get("stage_by_difficulty")
    if not isinstance(by_diff, dict):
        by_diff = config.default_stage_by_difficulty()
    else:
        by_diff = {
            **config.default_stage_by_difficulty(),
            **{str(k): config.normalize_stage(v) for k, v in by_diff.items()},
        }
    # Keep settings.stage in sync when this session is on the saved difficulty.
    if config.normalize_difficulty(settings.get("level", level)) == level:
        by_diff[str(level)] = config.normalize_stage(
            settings.get("stage", by_diff.get(str(level), 1))
        )
    stage = config.normalize_stage(by_diff.get(str(level), 1))
    level_after = level
    stage_after = stage

    if move_up_score(correct_count, planned_count):
        low_streak = 0
        move_up_streak += 1
        if stage < config.STAGES_PER_DIFFICULTY:
            stage_after = stage + 1
            level_after = level
        else:
            level_after = min(config.MAX_DIFFICULTY, level + 1)
            stage_after = 1 if level_after != level else config.STAGES_PER_DIFFICULTY
    elif under_half(correct_count, planned_count):
        low_streak += 1
        move_up_streak = 0
        if low_streak >= 2:
            low_streak = 0
            if stage > 1:
                stage_after = stage - 1
                level_after = level
            else:
                level_after = max(1, level - 1)
                stage_after = (
                    config.STAGES_PER_DIFFICULTY if level_after < level else 1
                )
    else:
        low_streak = 0
        move_up_streak = 0

    if level_after == level:
        by_diff[str(level)] = stage_after
    else:
        if level_after > level:
            by_diff[str(level)] = config.STAGES_PER_DIFFICULTY
        else:
            by_diff[str(level)] = 1
        by_diff[str(level_after)] = stage_after
    settings["low_streak"] = low_streak
    settings["move_up_streak"] = move_up_streak
    settings["level"] = level_after
    settings["stage"] = stage_after
    settings["stage_by_difficulty"] = by_diff
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


def _ordered_tier_items(
    conn: sqlite3.Connection, content_levels: tuple[int, ...]
) -> list[sqlite3.Row]:
    ph = _placeholders(len(content_levels))
    return conn.execute(
        f"""
        SELECT i.*
        FROM items i
        WHERE i.level IN ({ph})
        ORDER BY i.level ASC, i.id ASC
        """,
        content_levels,
    ).fetchall()


def items_for_stage(
    rows: list[sqlite3.Row], stage: int
) -> list[sqlite3.Row]:
    """Split a difficulty pool into STAGES_PER_DIFFICULTY ordered sets."""
    if not rows:
        return []
    start, end = config.stage_slice_bounds(len(rows), stage)
    chunk = rows[start:end]
    return chunk or list(rows)


def build_adaptive_queue(
    conn: sqlite3.Connection,
    level: int,
    length: int,
    stage: int | None = None,
) -> list[sqlite3.Row]:
    """Build a unique queue for one set (stage) inside a difficulty tier.

    Prefers the current set's items, then earlier sets for review padding,
    never later (locked) sets. Snaps to 5 or 10.
    """
    difficulty = config.normalize_difficulty(level)
    length = config.normalize_session_length(length)
    stage = config.normalize_stage(
        stage if stage is not None else 1
    )
    content_levels = config.content_levels_for_difficulty(difficulty)
    ph = _placeholders(len(content_levels))
    today = local_today()
    tier_rows = _ordered_tier_items(conn, content_levels)
    stage_rows = items_for_stage(tier_rows, stage)
    stage_ids = {int(r["id"]) for r in stage_rows}
    # Earlier sets only — unlock later sets by advancing stage.
    earlier_ids: set[int] = set()
    for s in range(1, stage):
        earlier_ids.update(int(r["id"]) for r in items_for_stage(tier_rows, s))
    allowed_ids = stage_ids | earlier_ids
    queue: list[sqlite3.Row] = []
    seen: set[int] = set()

    def _take(
        rows: list[sqlite3.Row],
        *,
        skip_correct_today: bool = False,
        id_filter: set[int] | None = None,
    ) -> None:
        for row in rows:
            if len(queue) >= length:
                return
            rid = int(row["id"])
            if rid in seen:
                continue
            if id_filter is not None and rid not in id_filter:
                continue
            if skip_correct_today and had_correct_today(conn, rid):
                continue
            queue.append(row)
            seen.add(rid)

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
    _take(due, id_filter=stage_ids)
    _take(due, id_filter=earlier_ids)

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
    tier_ids = {int(r["id"]) for r in tier_rows}
    _take(fill, skip_correct_today=True, id_filter=stage_ids)
    _take(fill, skip_correct_today=True, id_filter=earlier_ids)
    # Prefer a full 5/10 set: allow same-day unmastered before mastered padding.
    if len(queue) < length:
        _take(fill, skip_correct_today=False, id_filter=stage_ids)
    if len(queue) < length:
        _take(fill, skip_correct_today=False, id_filter=earlier_ids)
    # Small sets (e.g. Phrases slices of 4) may need the rest of the tier to hit 5|10.
    if len(queue) < length:
        _take(fill, skip_correct_today=False, id_filter=tier_ids)

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
        for id_filter in (stage_ids, earlier_ids, allowed_ids, tier_ids):
            for row in mastered:
                if len(queue) >= length:
                    break
                rid = int(row["id"])
                if rid in seen or rid not in id_filter:
                    continue
                if sessions_since_item(conn, rid) >= config.MASTERED_EVERY_N_SESSIONS:
                    queue.append(row)
                    seen.add(rid)
            for row in mastered:
                if len(queue) >= length:
                    break
                rid = int(row["id"])
                if rid in seen or rid not in id_filter:
                    continue
                queue.append(row)
                seen.add(rid)

    # C7: never return an empty queue when any item exists in the tier.
    if not queue:
        for candidate in stage_rows or tier_rows:
            queue.append(candidate)
            break

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
    """Same-session miss reinsert is disabled — sessions stay exactly 5 or 10.

    Growing the play queue (e.g. 10 → 11) made the kid UI show ``Word 3 of 11``.
    Missed words still surface in end-of-session replay; ratio/mastery still score
    the original planned slot.
    """
    _ = (conn, item_id, queue_index)
    return play, flags, None
