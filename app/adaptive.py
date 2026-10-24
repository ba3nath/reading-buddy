"""Adaptive queue, level moves, day ladder, mastery, auto-strict (M3)."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from typing import Any

from app import config
from app.db import ensure_mastery_row, local_today, load_settings
from app.events import known_ratio_by_pattern
from app.patterns import unlocked_patterns


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

    if under_half(correct_count, planned_count) and int(settings.get("low_streak", 0)) == 0:
        # low_streak was just reset after the second rough session.
        if (
            settings.get("mode") == "strict"
            and settings.get("mode_source") == "auto"
            and not move_up_score(correct_count, planned_count)
        ):
            settings["mode"] = "beginner"
            settings["last_mode_change"] = (
                "Moved back to beginner after a rough stretch."
            )
    if settings.get("auto_strict", True):
        streak_need = int(
            settings.get("auto_strict_sessions", config.AUTO_STRICT_SESSIONS)
        )
        if move_up_streak >= streak_need and settings.get("mode") != "strict":
            settings["mode"] = "strict"
            settings["mode_source"] = "auto"
            settings["last_mode_change"] = (
                "Moved to strict after strong sessions."
            )
        elif move_up_streak >= streak_need and settings.get("mode_source") == "auto":
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
        SELECT review_step, next_review_on, mastered, correct_count, days_json, box
        FROM mastery WHERE item_id = ?
        """,
        (item_id,),
    ).fetchone()
    today = _today()
    today_s = local_today()

    # Leitner box (1–5); gaps from config.LEITNER_GAPS_DAYS.
    try:
        box = int(row["box"] or 1)
    except (KeyError, IndexError, TypeError):
        box = 1
    box = max(1, min(5, box))

    if result == "missed":
        # Gentle demotion: step box back silently (even if previously mastered).
        new_box = 1 if row["mastered"] == 1 else max(1, box - 1)
        gap = config.LEITNER_GAPS_DAYS[min(new_box, len(config.LEITNER_GAPS_DAYS)) - 1]
        # Box 1 is "due now"; schedule for today so the queue picks it up.
        next_on = today + timedelta(days=int(gap))
        step = 1 if gap <= 1 else (3 if gap <= 3 else 7)
        conn.execute(
            """
            UPDATE mastery
            SET box = ?, review_step = ?, next_review_on = ?,
                miss_count = miss_count + 1, mastered = 0,
                last_result = 'missed', last_seen_on = ?
            WHERE item_id = ?
            """,
            (new_box, step, next_on.isoformat(), today_s, item_id),
        )
        return

    # correct — at most one Leitner box advance per calendar day (Phase 6).
    days = json.loads(row["days_json"] or "[]")
    already_today = today_s in days
    if not already_today:
        days.append(today_s)
    correct_count = int(row["correct_count"]) + 1
    new_box = box if already_today else min(5, box + 1)
    distinct_days = len(set(days))
    # Mastered = box >= 4 with passes on separate days (Phase 2).
    mastered = (
        1
        if new_box >= config.LEITNER_MASTERED_BOX and distinct_days >= 2
        else 0
    )
    # Legacy fallback: still allow classic 3-correct/2-day if box somehow stalls.
    if not mastered and correct_count >= 3 and distinct_days >= 2 and new_box >= 3:
        mastered = 1

    if mastered or (row["mastered"] == 1 and new_box >= config.LEITNER_MASTERED_BOX):
        conn.execute(
            """
            UPDATE mastery
            SET correct_count = ?, days_json = ?, review_step = 0,
                next_review_on = NULL, mastered = 1, box = ?,
                mastered_on = COALESCE(mastered_on, ?),
                last_result = 'correct', last_seen_on = ?
            WHERE item_id = ?
            """,
            (correct_count, json.dumps(days), max(new_box, config.LEITNER_MASTERED_BOX), today_s, today_s, item_id),
        )
        return

    gap = config.LEITNER_GAPS_DAYS[min(new_box, len(config.LEITNER_GAPS_DAYS)) - 1]
    if keep_plus_one_day:
        gap = 1
        new_box = max(1, min(new_box, 2))
    next_on = today + timedelta(days=int(gap)) if gap else today
    step = 1 if gap <= 1 else (3 if gap <= 3 else 7)

    conn.execute(
        """
        UPDATE mastery
        SET correct_count = ?, days_json = ?, review_step = ?,
            next_review_on = ?, box = ?, last_result = 'correct', last_seen_on = ?
        WHERE item_id = ?
        """,
        (
            correct_count,
            json.dumps(days),
            step,
            next_on.isoformat(),
            new_box,
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
          AND COALESCE(retired, 0) = 0
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
              AND COALESCE(i.retired, 0) = 0
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
        WHERE i.level IN ({ph}) AND COALESCE(i.retired, 0) = 0
        ORDER BY i.level ASC, i.id ASC
        """,
        content_levels,
    ).fetchall()


def _one_group_queue(
    conn: sqlite3.Connection, stage: int, *, column: str
) -> list[sqlite3.Row]:
    """One rhyme or one story for this set. Never mix the next group in."""
    if column not in ("rhyme_group", "story_id"):
        raise ValueError(column)
    names = [
        row[0]
        for row in conn.execute(
            f"""
            SELECT {column}
            FROM items
            WHERE {column} IS NOT NULL AND {column} != ''
              AND COALESCE(retired, 0) = 0
            GROUP BY {column}
            ORDER BY MIN(level) ASC, MIN(id) ASC
            """
        ).fetchall()
    ]
    if not names:
        return []
    idx = min(config.normalize_stage(stage), len(names)) - 1
    chosen = names[idx]
    return conn.execute(
        f"""
        SELECT * FROM items
        WHERE {column} = ? AND COALESCE(retired, 0) = 0
        ORDER BY line_index ASC, id ASC
        """,
        (chosen,),
    ).fetchall()


def set_item_ids(conn: sqlite3.Connection, difficulty: int, stage: int) -> set[int]:
    """Item ids that belong to one set, with no review padding."""
    difficulty = config.normalize_difficulty(difficulty)
    stage = config.normalize_stage(stage)
    if difficulty == 3:
        rows = _one_group_queue(conn, stage, column="rhyme_group")
    elif difficulty == 4:
        rows = _one_group_queue(conn, stage, column="story_id")
    else:
        levels = config.content_levels_for_difficulty(difficulty)
        rows = items_for_stage(_ordered_tier_items(conn, levels), stage)
    return {int(row["id"]) for row in rows}


def set_progress(conn: sqlite3.Connection) -> dict[str, dict[str, str]]:
    """done, partial, or new for every difficulty and set.

    A set is done when a finished session has scored every item in it.
    Started items that are not all finished are partial. The rest are new.
    """
    catalog: dict[int, dict[int, set[int]]] = {}
    for difficulty in range(1, config.MAX_DIFFICULTY + 1):
        catalog[difficulty] = {
            stage: set_item_ids(conn, difficulty, stage)
            for stage in range(1, config.STAGES_PER_DIFFICULTY + 1)
        }
    covered: dict[tuple[int, int], set[int]] = {
        (difficulty, stage): set()
        for difficulty, stages in catalog.items()
        for stage in stages
    }
    started: set[tuple[int, int]] = set()
    locked: dict[int, set[int]] = {}
    for row in conn.execute(
        """
        SELECT session_id, item_id FROM attempts
        WHERE counts_for_session = 1
          AND result IN ('correct', 'close', 'missed', 'skipped')
        """
    ):
        locked.setdefault(int(row["session_id"]), set()).add(int(row["item_id"]))

    for session in conn.execute(
        "SELECT id, level, planned_item_ids, completed FROM sessions"
    ):
        difficulty = config.normalize_difficulty(session["level"])
        stages = catalog.get(difficulty) or {}
        try:
            planned = {int(item_id) for item_id in json.loads(session["planned_item_ids"] or "[]")}
        except (TypeError, ValueError):
            planned = set()
        evidence = planned if int(session["completed"] or 0) == 1 else locked.get(int(session["id"]), set())
        if not evidence:
            continue
        best_stage = 0
        best_overlap: set[int] = set()
        for stage, ids in stages.items():
            overlap = ids & evidence
            if len(overlap) > len(best_overlap):
                best_stage = stage
                best_overlap = overlap
        if not best_stage:
            continue
        key = (difficulty, best_stage)
        if int(session["completed"] or 0) == 1:
            covered[key] |= stages[best_stage] & planned
        elif best_overlap:
            started.add(key)

    progress: dict[str, dict[str, str]] = {}
    for difficulty, stages in catalog.items():
        bucket: dict[str, str] = {}
        for stage, ids in stages.items():
            key = (difficulty, stage)
            if ids and ids <= covered[key]:
                bucket[str(stage)] = "done"
            elif key in started or (covered[key] & ids):
                bucket[str(stage)] = "partial"
            else:
                bucket[str(stage)] = "new"
        progress[str(difficulty)] = bucket
    return progress


def items_for_stage(
    rows: list[sqlite3.Row], stage: int
) -> list[sqlite3.Row]:
    """Split a difficulty pool into STAGES_PER_DIFFICULTY ordered sets."""
    if not rows:
        return []
    start, end = config.stage_slice_bounds(len(rows), stage)
    return rows[start:end]


def current_unlocked_patterns(conn: sqlite3.Connection) -> list[str]:
    """Derive unlocked ladder prefixes; honour persisted settings override."""
    settings = load_settings()
    persisted = settings.get("unlocked_patterns")
    if isinstance(persisted, list) and persisted:
        return [str(p) for p in persisted]
    ratios = known_ratio_by_pattern(conn)
    return unlocked_patterns(ratios)


def _pattern_allowed(row: sqlite3.Row, open_patterns: set[str]) -> bool:
    try:
        pat = str(row["pattern"] or "")
    except (KeyError, IndexError, TypeError):
        return True
    if not pat or not open_patterns:
        return True
    if pat in open_patterns:
        return True
    # Sight words always practise once any phonics step is open.
    try:
        if int(row["sight_word"] or 0) == 1 and "sight" in open_patterns:
            return True
    except (KeyError, IndexError, TypeError):
        pass
    return False


def _build_legacy_queue(
    conn: sqlite3.Connection,
    difficulty: int,
    length: int,
    stage: int,
) -> list[sqlite3.Row]:
    """Pre–scheduler_v2 mix: due → unmastered → mastered padding."""
    if difficulty == 3:
        poem = _one_group_queue(conn, stage, column="rhyme_group")
        if poem:
            return poem
    if difficulty == 4:
        story = _one_group_queue(conn, stage, column="story_id")
        if story:
            return story
    content_levels = config.content_levels_for_difficulty(difficulty)
    ph = _placeholders(len(content_levels))
    today = local_today()
    tier_rows = _ordered_tier_items(conn, content_levels)
    stage_rows = items_for_stage(tier_rows, stage)
    stage_ids = {int(r["id"]) for r in stage_rows}
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
          AND COALESCE(i.retired, 0) = 0
          AND m.mastered = 0
          AND m.next_review_on IS NOT NULL
          AND m.next_review_on <= ?
        ORDER BY m.next_review_on ASC, i.id ASC
        """,
        (*content_levels, today),
    ).fetchall()
    _take(due, id_filter=stage_ids)
    _take(due, id_filter=earlier_ids)

    if difficulty == 3:
        fill = _rhyme_grouped(conn, content_levels)
    else:
        fill = conn.execute(
            f"""
            SELECT i.*
            FROM items i
            LEFT JOIN mastery m ON m.item_id = i.id
            WHERE i.level IN ({ph})
              AND COALESCE(i.retired, 0) = 0
              AND COALESCE(m.mastered, 0) = 0
            ORDER BY COALESCE(m.correct_count, 0) ASC, i.level ASC, i.id ASC
            """,
            content_levels,
        ).fetchall()
    tier_ids = {int(r["id"]) for r in tier_rows}
    _take(fill, skip_correct_today=True, id_filter=stage_ids)
    _take(fill, skip_correct_today=True, id_filter=earlier_ids)
    if len(queue) < length:
        _take(fill, skip_correct_today=False, id_filter=stage_ids)
    if len(queue) < length:
        _take(fill, skip_correct_today=False, id_filter=earlier_ids)
    if len(queue) < length:
        _take(fill, skip_correct_today=False, id_filter=tier_ids)

    if len(queue) < length:
        mastered = conn.execute(
            f"""
            SELECT i.*, m.last_seen_on
            FROM items i
            JOIN mastery m ON m.item_id = i.id
            WHERE m.mastered = 1 AND i.level IN ({ph})
              AND COALESCE(i.retired, 0) = 0
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

    if not queue:
        for candidate in stage_rows or tier_rows:
            queue.append(candidate)
            break

    if not queue:
        raise ValueError(f"No content for difficulty {difficulty}")
    return _snap_uniform_length(queue, length)


def _build_scheduler_v2_queue(
    conn: sqlite3.Connection,
    difficulty: int,
    length: int,
    stage: int,
) -> list[sqlite3.Row]:
    """Easy opener → due → this set's items → earlier review → easy closer.

    Rhymes and stories stay one group per set (unchanged).

    Choosing a set always unlocks that set's patterns (so Set 3 is not stuck
    replaying Set 1's ``cat``). Mastery-based unlock still gates *earlier*
    review padding from patterns the child has not opened yet.
    """
    if difficulty == 3:
        poem = _one_group_queue(conn, stage, column="rhyme_group")
        if poem:
            return poem
    if difficulty == 4:
        story = _one_group_queue(conn, stage, column="story_id")
        if story:
            return story

    content_levels = config.content_levels_for_difficulty(difficulty)
    ph = _placeholders(len(content_levels))
    today = local_today()
    tier_rows = _ordered_tier_items(conn, content_levels)
    stage_rows = items_for_stage(tier_rows, stage)
    stage_ids = {int(r["id"]) for r in stage_rows}
    earlier_ids: set[int] = set()
    for s in range(1, stage):
        earlier_ids.update(int(r["id"]) for r in items_for_stage(tier_rows, s))

    # Set pick opens this set's patterns; mastery unlock gates cross-set review.
    stage_patterns = {
        str(r["pattern"] or "")
        for r in stage_rows
        if "pattern" in r.keys() and r["pattern"]
    }
    mastery_unlocked = set(current_unlocked_patterns(conn))
    review_patterns = mastery_unlocked | stage_patterns

    queue: list[sqlite3.Row] = []
    seen: set[int] = set()

    # Leave one slot for an easy closer when the session is longer than 2.
    fill_cap = max(0, length - 1) if length > 2 else length

    def _take(
        rows: list[sqlite3.Row],
        *,
        id_filter: set[int] | None = None,
        require_pattern: bool = False,
        pattern_set: set[str] | None = None,
        limit: int | None = None,
        stop_at: int | None = None,
    ) -> None:
        allowed = pattern_set if pattern_set is not None else review_patterns
        cap = length if stop_at is None else stop_at
        added = 0
        for row in rows:
            if len(queue) >= cap:
                return
            if limit is not None and added >= limit:
                return
            rid = int(row["id"])
            if rid in seen:
                continue
            if id_filter is not None and rid not in id_filter:
                continue
            if require_pattern and not _pattern_allowed(row, allowed):
                continue
            queue.append(row)
            seen.add(rid)
            added += 1

    easy = conn.execute(
        f"""
        SELECT i.*
        FROM items i
        LEFT JOIN mastery m ON m.item_id = i.id
        WHERE i.level IN ({ph}) AND COALESCE(i.retired, 0) = 0
        ORDER BY COALESCE(m.mastered, 0) DESC,
                 COALESCE(m.box, 1) DESC,
                 COALESCE(m.correct_count, 0) DESC,
                 i.id ASC
        """,
        content_levels,
    ).fetchall()
    # Opener: easiest word *in this set* (never pull cat from Set 1 into Set 5).
    _take(easy, id_filter=stage_ids, require_pattern=False, limit=1)
    if not queue and stage_rows:
        queue.append(stage_rows[0])
        seen.add(int(stage_rows[0]["id"]))

    due = conn.execute(
        f"""
        SELECT i.*
        FROM items i
        JOIN mastery m ON m.item_id = i.id
        WHERE i.level IN ({ph})
          AND COALESCE(i.retired, 0) = 0
          AND m.mastered = 0
          AND m.next_review_on IS NOT NULL
          AND m.next_review_on <= ?
        ORDER BY COALESCE(m.box, 1) ASC, m.next_review_on ASC, i.id ASC
        """,
        (*content_levels, today),
    ).fetchall()
    # Bias review toward weak phonics skills (Phase 6 map) without leaving the set.
    from app.coach.map import weak_item_ids
    from app.coach.plan import prefer_rows

    try:
        weak_ids = weak_item_ids(conn)
        due = prefer_rows(due, weak_ids)
    except Exception:  # noqa: BLE001 — queue must still build if map fails
        weak_ids = []
    # This set first (due + curriculum order), then earlier review — never let
    # Set 1 due-reviews crowd out the set the child just picked.
    _take(due, id_filter=stage_ids, require_pattern=False, stop_at=fill_cap)
    _take(stage_rows, require_pattern=False, stop_at=fill_cap)
    _take(
        due,
        id_filter=earlier_ids,
        require_pattern=True,
        pattern_set=mastery_unlocked,
        stop_at=fill_cap,
    )
    earlier_rows = [r for r in tier_rows if int(r["id"]) in earlier_ids]
    if weak_ids:
        earlier_rows = prefer_rows(earlier_rows, weak_ids)
    _take(
        earlier_rows,
        require_pattern=True,
        pattern_set=mastery_unlocked,
        stop_at=fill_cap,
    )
    # Prefer current + earlier. Later sets only as last resort so 5|10 length
    # still works when a set is thin (e.g. phrases = 4/stage) — and only after
    # every item in this set is already queued.
    allowed_ids = stage_ids | earlier_ids
    if len(queue) < fill_cap:
        _take(tier_rows, id_filter=allowed_ids, require_pattern=False, stop_at=fill_cap)
    later_ids = {
        int(r["id"]) for r in tier_rows if int(r["id"]) not in allowed_ids
    }
    stage_fully_included = not stage_ids or stage_ids.issubset(seen)
    if len(queue) < fill_cap and stage_fully_included and later_ids:
        _take(tier_rows, id_filter=later_ids, require_pattern=False, stop_at=fill_cap)

    # Closer: easy item from this set when possible.
    if len(queue) < length:
        _take(easy, id_filter=stage_ids, require_pattern=False, limit=1)
    if len(queue) < length:
        _take(
            easy,
            id_filter=earlier_ids,
            require_pattern=True,
            pattern_set=mastery_unlocked,
            limit=1,
        )
    if len(queue) < length:
        _take(easy, id_filter=allowed_ids, require_pattern=False)
    if len(queue) < length and stage_fully_included and later_ids:
        _take(easy, id_filter=later_ids, require_pattern=False, limit=1)

    if not queue:
        for candidate in stage_rows or tier_rows:
            queue.append(candidate)
            break

    if not queue:
        raise ValueError(f"No content for difficulty {difficulty}")
    return _snap_uniform_length(queue, length)


def build_adaptive_queue(
    conn: sqlite3.Connection,
    level: int,
    length: int,
    stage: int | None = None,
) -> list[sqlite3.Row]:
    """Build a unique queue for one set (stage) inside a difficulty tier.

    Always uses the Leitner / set-scoped scheduler (``scheduler_v2``). The
    legacy queue remains only for shadow comparison via ``shadow_queue_ids``.
    Rhymes/stories stay one-group sessions.
    """
    difficulty = config.normalize_difficulty(level)
    length = config.normalize_session_length(length)
    stage = config.normalize_stage(stage if stage is not None else 1)
    # Force set-scoped mix — legacy path drifts from "Set N practises Set N".
    return _build_scheduler_v2_queue(conn, difficulty, length, stage)


def shadow_queue_ids(
    conn: sqlite3.Connection,
    level: int,
    length: int,
    stage: int,
) -> dict[str, list[int]]:
    """Build both schedulers for shadow comparison (Phase 2)."""
    difficulty = config.normalize_difficulty(level)
    length = config.normalize_session_length(length)
    stage = config.normalize_stage(stage)
    v2 = [int(r["id"]) for r in _build_scheduler_v2_queue(conn, difficulty, length, stage)]
    legacy = [int(r["id"]) for r in _build_legacy_queue(conn, difficulty, length, stage)]
    return {"scheduler_v2": v2, "legacy": legacy}


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
