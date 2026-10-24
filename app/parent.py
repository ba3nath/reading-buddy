"""Parent page aggregations, CSV export, keep-audio helpers (M4)."""

from __future__ import annotations

import csv
import io
import json
import shutil
import zipfile
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

from app import config
from app.db import load_settings, local_today, save_settings


SOUND_NOTE = "Version 1 reflects reading accuracy, not pronunciation."
BUDDIES = ("krishna", "unicorn")


def clear_kept_audio() -> int:
    """Delete all files under data/kept/. Returns count removed."""
    kept = config.KEPT_DIR
    if not kept.exists():
        return 0
    n = 0
    for path in kept.iterdir():
        if path.is_file():
            path.unlink(missing_ok=True)
            n += 1
    return n


def keep_attempt_wav(attempt_id: int, wav_path: Path) -> Path | None:
    if not wav_path.exists():
        return None
    config.KEPT_DIR.mkdir(parents=True, exist_ok=True)
    dest = config.KEPT_DIR / f"{attempt_id}.wav"
    shutil.copy2(wav_path, dest)
    return dest


def accuracy_by_day(conn, *, days: int = 30) -> dict[str, Any]:
    """Daily accuracy. ``correct``/``scored`` stay attempt-based (compat).

    Phase 8 adds ``independent_correct`` / ``assisted_correct`` from events
    (mastery-eligible vs assisted), so stars never stand in for reading proof.
    """
    from app.events import ensure_events_table

    ensure_events_table(conn)
    today = date.fromisoformat(local_today())
    start = today - timedelta(days=days - 1)
    rows = conn.execute(
        """
        SELECT substr(created_at, 1, 10) AS d,
               SUM(CASE WHEN result = 'correct' THEN 1 ELSE 0 END) AS correct,
               SUM(CASE WHEN result != 'retry' THEN 1 ELSE 0 END) AS scored
        FROM attempts
        WHERE is_replay = 0
          AND substr(created_at, 1, 10) >= ?
        GROUP BY d
        ORDER BY d ASC
        """,
        (start.isoformat(),),
    ).fetchall()
    ev = conn.execute(
        """
        SELECT substr(created_at, 1, 10) AS d,
               SUM(
                 CASE WHEN result = 'correct' AND counts_for_mastery = 1
                 THEN 1 ELSE 0 END
               ) AS independent_correct,
               SUM(
                 CASE WHEN result = 'correct' AND counts_for_mastery = 0
                 THEN 1 ELSE 0 END
               ) AS assisted_correct,
               SUM(
                 CASE WHEN result IN ('correct', 'close', 'missed')
                 THEN 1 ELSE 0 END
               ) AS locking_reads
        FROM events
        WHERE substr(created_at, 1, 10) >= ?
          AND phase != 'replay'
        GROUP BY d
        """,
        (start.isoformat(),),
    ).fetchall()
    by = {
        r["d"]: {
            "date": r["d"],
            "correct": int(r["correct"]),
            "scored": int(r["scored"]),
            "independent_correct": 0,
            "assisted_correct": 0,
            "locking_reads": 0,
        }
        for r in rows
    }
    for r in ev:
        bucket = by.setdefault(
            r["d"],
            {
                "date": r["d"],
                "correct": 0,
                "scored": 0,
                "independent_correct": 0,
                "assisted_correct": 0,
                "locking_reads": 0,
            },
        )
        bucket["independent_correct"] = int(r["independent_correct"] or 0)
        bucket["assisted_correct"] = int(r["assisted_correct"] or 0)
        bucket["locking_reads"] = int(r["locking_reads"] or 0)
    out = []
    cur = start
    while cur <= today:
        key = cur.isoformat()
        out.append(
            by.get(
                key,
                {
                    "date": key,
                    "correct": 0,
                    "scored": 0,
                    "independent_correct": 0,
                    "assisted_correct": 0,
                    "locking_reads": 0,
                },
            )
        )
        cur += timedelta(days=1)
    return {"days": out, "note": "Lead metric: independent_correct / locking_reads (not stars)."}


def mastered_lists(conn) -> dict[str, Any]:
    from app.events import ensure_events_table

    ensure_events_table(conn)
    today = date.fromisoformat(local_today())
    week_start = (today - timedelta(days=today.weekday())).isoformat()
    all_rows = conn.execute(
        """
        SELECT i.id, i.slug, i.text, i.level, m.mastered_on
        FROM mastery m
        JOIN items i ON i.id = m.item_id
        WHERE m.mastered = 1
        ORDER BY m.mastered_on DESC, i.id ASC
        """
    ).fetchall()
    mastered = [
        {
            "id": r["id"],
            "slug": r["slug"],
            "text": r["text"],
            "level": r["level"],
            "mastered_on": r["mastered_on"],
        }
        for r in all_rows
    ]
    this_week = [m for m in mastered if m["mastered_on"] and m["mastered_on"] >= week_start]
    # Independent evidence (Phase 5–7): mastery-eligible corrects, not stars.
    ind_rows = conn.execute(
        """
        SELECT i.id, i.slug, i.text, i.pattern,
               COUNT(*) AS independent_oks,
               MAX(substr(e.created_at, 1, 10)) AS last_independent_on
        FROM events e
        JOIN items i ON i.id = e.item_id
        WHERE e.counts_for_mastery = 1 AND e.result = 'correct'
          AND e.phase != 'replay'
        GROUP BY i.id
        ORDER BY independent_oks DESC, i.id ASC
        LIMIT 60
        """
    ).fetchall()
    independent = [
        {
            "id": r["id"],
            "slug": r["slug"],
            "text": r["text"],
            "pattern": r["pattern"],
            "independent_oks": int(r["independent_oks"]),
            "last_independent_on": r["last_independent_on"],
        }
        for r in ind_rows
    ]
    return {
        "mastered": mastered,
        "this_week": this_week,
        "independent": independent,
    }


def retention_after_delay(conn) -> dict[str, Any]:
    """Words missed then later read independently on a different calendar day."""
    from app.events import ensure_events_table

    ensure_events_table(conn)
    rows = conn.execute(
        """
        SELECT i.id, i.slug, i.text, i.pattern,
               miss.d AS missed_on,
               ok.d AS retained_on
        FROM items i
        JOIN (
          SELECT item_id, MIN(substr(created_at, 1, 10)) AS d
          FROM events
          WHERE result = 'missed' AND phase != 'replay'
          GROUP BY item_id
        ) miss ON miss.item_id = i.id
        JOIN (
          SELECT item_id, MIN(substr(created_at, 1, 10)) AS d
          FROM events
          WHERE result = 'correct' AND counts_for_mastery = 1
            AND phase != 'replay'
          GROUP BY item_id
        ) ok ON ok.item_id = i.id
        WHERE ok.d > miss.d
        ORDER BY ok.d DESC, i.id ASC
        LIMIT 40
        """
    ).fetchall()
    return {
        "items": [
            {
                "id": r["id"],
                "slug": r["slug"],
                "text": r["text"],
                "pattern": r["pattern"],
                "missed_on": r["missed_on"],
                "retained_on": r["retained_on"],
            }
            for r in rows
        ],
        "count": len(rows),
        "note": "Independent success on a later day after a miss (retention signal).",
    }


def tricky_words(conn) -> dict[str, Any]:
    today = date.fromisoformat(local_today())
    since = (today - timedelta(days=14)).isoformat()
    rows = conn.execute(
        """
        SELECT i.id, i.slug, i.text, i.level,
               SUM(CASE WHEN a.result = 'missed'
                         AND substr(a.created_at, 1, 10) >= ?
                    THEN 1 ELSE 0 END) AS recent_misses,
               SUM(CASE WHEN a.result = 'missed' THEN 1 ELSE 0 END) AS all_misses
        FROM items i
        JOIN attempts a ON a.item_id = i.id
        WHERE a.is_replay = 0
        GROUP BY i.id
        HAVING all_misses > 0
        ORDER BY recent_misses DESC, all_misses DESC, i.id ASC
        LIMIT 40
        """,
        (since,),
    ).fetchall()
    return {
        "items": [
            {
                "id": r["id"],
                "slug": r["slug"],
                "text": r["text"],
                "level": r["level"],
                "recent_misses": int(r["recent_misses"]),
                "all_misses": int(r["all_misses"]),
            }
            for r in rows
        ]
    }


def sound_heatmap(conn) -> dict[str, Any]:
    """Sound accuracy from events — independent corrects only (not assisted)."""
    from app.events import ensure_events_table

    ensure_events_table(conn)
    rows = conn.execute(
        """
        SELECT i.sound_tags, e.result, e.counts_for_mastery
        FROM events e
        JOIN items i ON i.id = e.item_id
        WHERE e.phase != 'replay'
          AND e.result IN ('correct', 'close', 'missed')
        """
    ).fetchall()
    tallies: dict[str, dict[str, int]] = {}
    for row in rows:
        tags = json.loads(row["sound_tags"] or "[]")
        if not tags:
            continue
        independent = (
            row["result"] == "correct" and int(row["counts_for_mastery"] or 0) == 1
        )
        for tag in tags:
            bucket = tallies.setdefault(tag, {"correct": 0, "scored": 0})
            bucket["scored"] += 1
            if independent:
                bucket["correct"] += 1
    tags_out = [
        {"tag": tag, "correct": v["correct"], "scored": v["scored"]}
        for tag, v in sorted(tallies.items(), key=lambda kv: (-kv[1]["scored"], kv[0]))
    ]
    return {
        "tags": tags_out,
        "note": SOUND_NOTE + " Correct% uses independent reads only.",
    }


def pattern_heatmap(conn) -> dict[str, Any]:
    """Accuracy by grapheme pattern — independent corrects only (not assisted)."""
    from app.events import ensure_events_table, known_ratio_by_pattern

    ensure_events_table(conn)
    rows = conn.execute(
        """
        SELECT i.pattern AS pattern, e.result, e.counts_for_mastery
        FROM events e
        JOIN items i ON i.id = e.item_id
        WHERE e.phase != 'replay'
          AND e.result IN ('correct', 'close', 'missed')
          AND i.pattern IS NOT NULL AND i.pattern != ''
        """
    ).fetchall()
    tallies: dict[str, dict[str, int]] = {}
    for row in rows:
        pat = str(row["pattern"])
        bucket = tallies.setdefault(pat, {"correct": 0, "scored": 0})
        bucket["scored"] += 1
        if row["result"] == "correct" and int(row["counts_for_mastery"] or 0) == 1:
            bucket["correct"] += 1
    known = known_ratio_by_pattern(conn)
    patterns = [
        {
            "pattern": pat,
            "correct": v["correct"],
            "scored": v["scored"],
            "known_ratio": round(known.get(pat, 0.0), 3),
        }
        for pat, v in sorted(
            tallies.items(), key=lambda kv: (-kv[1]["scored"], kv[0])
        )
    ]
    return {
        "patterns": patterns,
        "note": (
            "Pattern is the phonics curriculum key. Correct% is independent only; "
            "practise the lowest known_ratio next."
        ),
    }


def list_kept_clips(conn) -> dict[str, Any]:
    clips = []
    if not config.KEPT_DIR.exists():
        return {"clips": clips}
    for path in sorted(config.KEPT_DIR.glob("*.wav"), reverse=True):
        try:
            attempt_id = int(path.stem)
        except ValueError:
            continue
        row = conn.execute(
            """
            SELECT a.id, a.created_at, a.result, i.text, i.slug
            FROM attempts a
            JOIN items i ON i.id = a.item_id
            WHERE a.id = ?
            """,
            (attempt_id,),
        ).fetchone()
        if row is None:
            continue
        clips.append(
            {
                "attempt_id": attempt_id,
                "text": row["text"],
                "slug": row["slug"],
                "result": row["result"],
                "created_at": row["created_at"],
                "audio_url": f"/api/parent/kept/{attempt_id}",
            }
        )
    return {"clips": clips}


def export_zip_bytes(conn) -> bytes:
    """Analytics CSV zip (not a full restore — use ./run --backup for that)."""
    from app.events import ensure_events_table

    ensure_events_table(conn)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        _csv_table(
            zf,
            "items.csv",
            conn,
            """
            SELECT id, slug, text, kind, level, pattern, sight_word, sound_tags,
                   rhyme_group, line_index, story_id, source, pd_status, hard
            FROM items ORDER BY id
            """,
        )
        _csv_table(
            zf,
            "sessions.csv",
            conn,
            "SELECT id, started_at, ended_at, mode, level, planned_count, correct_count, stars, low_session, level_after, completed FROM sessions ORDER BY id",
        )
        _csv_table(
            zf,
            "attempts.csv",
            conn,
            """
            SELECT id, session_id, item_id, heard, confidence, result,
                   counts_for_session, is_replay, queue_index, replay_word,
                   latency_ms, duration_seconds, passage, created_at
            FROM attempts ORDER BY id
            """,
        )
        _csv_table(
            zf,
            "mastery.csv",
            conn,
            """
            SELECT item_id, correct_count, days_json, miss_count, review_step,
                   next_review_on, box, mastered, mastered_on, last_result, last_seen_on
            FROM mastery ORDER BY item_id
            """,
        )
        _csv_table(
            zf,
            "events.csv",
            conn,
            """
            SELECT id, created_at, session_id, item_id, pattern, sight_word, result,
                   phase, latency_ms, duration_seconds, counts_for_mastery, meta_json
            FROM events ORDER BY id
            """,
        )
        # Settings snapshot (profile optional — still export so progress is backed up).
        settings = load_settings()
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["key", "value"])
        for key in sorted(settings.keys()):
            writer.writerow([key, json.dumps(settings[key])])
        zf.writestr("settings.csv", out.getvalue())
        zf.writestr(
            "README.txt",
            (
                "Reading Buddy CSV export (analytics).\n"
                "schema_version: 2\n"
                "\n"
                "events.meta_json may include outcome, assisted, hint_level,\n"
                "reason_code (Phase 5–7). counts_for_mastery=1 means independent\n"
                "evidence; assisted corrects stay 0.\n"
                "\n"
                "For a restorable backup of progress + parent voice, use:\n"
                "  ./run --backup\n"
            ),
        )
    return buf.getvalue()


def _csv_table(zf: zipfile.ZipFile, name: str, conn, sql: str) -> None:
    cur = conn.execute(sql)
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(cols)
    for row in rows:
        writer.writerow([row[c] for c in cols])
    zf.writestr(name, out.getvalue())


def last_read_through(conn) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT duration_seconds, word_scores
        FROM attempts
        WHERE passage = 1
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        return None
    scores = json.loads(row["word_scores"] or "[]")
    correct = sum(1 for ws in scores if ws.get("result") == "correct")
    total = len(scores)
    seconds = row["duration_seconds"]
    return {
        "seconds": None if seconds is None else round(float(seconds), 1),
        "words_correct": correct,
        "words_total": total,
    }


def tomorrow_note(conn, settings: dict[str, Any]) -> dict[str, Any]:
    """Parent-only next step. Pace is not shown to the child.

    Deterministic: due reviews + weakest patterns (Phase 6 map) + recent misses.
    """
    from app.coach.map import weak_patterns

    rows = conn.execute(
        """
        SELECT correct_count, planned_count
        FROM sessions
        WHERE completed = 1
        ORDER BY id DESC
        LIMIT 2
        """
    ).fetchall()
    under = False
    if rows:
        last = rows[0]
        planned = int(last["planned_count"] or 0)
        under = planned > 0 and int(last["correct_count"]) * 2 < planned
    level = config.normalize_difficulty(settings.get("level", 1))
    stage = config.normalize_stage(settings.get("stage", 1))
    label = config.stage_label(level, stage)
    tricky = [item["text"] for item in tricky_words(conn)["items"][:3]]
    today = local_today()
    due_n = int(
        conn.execute(
            """
            SELECT COUNT(*) AS n FROM mastery
            WHERE mastered = 0
              AND next_review_on IS NOT NULL
              AND next_review_on <= ?
            """,
            (today,),
        ).fetchone()["n"]
    )
    weak = weak_patterns(conn, days=30)[:3]
    if under:
        stay = f"Stay on {label}."
    else:
        stay = f"Keep going on {label}."
    tip_parts = []
    if due_n:
        tip_parts.append(f"{due_n} word{'s' if due_n != 1 else ''} due for review")
    if weak:
        tip_parts.append("focus on " + ", ".join(weak))
    practice_tip = "; ".join(tip_parts) + "." if tip_parts else "A short set on " + label + " is enough."
    return {
        "stay": stay,
        "tricky": tricky,
        "due_count": due_n,
        "weak_patterns": weak,
        "practice_tip": practice_tip,
        "mode_change": str(settings.get("last_mode_change") or ""),
        "read_through": last_read_through(conn),
    }


def apply_settings_update(payload: dict[str, Any]) -> dict[str, Any]:
    settings = load_settings()
    prev_keep = bool(settings.get("keep_audio", False))
    prev_mode = str(settings.get("mode") or "beginner")
    allowed = {
        "mode",
        "level",
        "stage",
        "auto_strict",
        "auto_strict_sessions",
        "session_length",
        "profile_name",
        "buddy",
        "keep_audio",
        "effort_stars",
        "scheduler_shadow",
    }
    for key, value in payload.items():
        if key not in allowed:
            raise ValueError(f"Unknown settings field: {key}")
        settings[key] = value

    if settings.get("mode") not in ("beginner", "strict"):
        raise ValueError("mode must be beginner or strict")
    if str(settings.get("mode")) != prev_mode:
        settings["mode_source"] = "parent"
        settings["last_mode_change"] = ""
    level = config.normalize_difficulty(settings.get("level", 1))
    settings["level"] = level
    settings["difficulty_migrated"] = True
    by_diff = settings.get("stage_by_difficulty")
    if not isinstance(by_diff, dict):
        by_diff = config.default_stage_by_difficulty()
    else:
        by_diff = {
            **config.default_stage_by_difficulty(),
            **{str(k): config.normalize_stage(v) for k, v in by_diff.items()},
        }
    if "stage" in payload:
        stage = config.normalize_stage(payload.get("stage"))
    else:
        stage = config.normalize_stage(by_diff.get(str(level), 1))
    by_diff[str(level)] = stage
    settings["stage"] = stage
    settings["stage_by_difficulty"] = by_diff
    settings["session_length"] = config.normalize_session_length(
        settings.get("session_length", config.DEFAULT_SESSION_LENGTH)
    )
    settings["auto_strict"] = bool(settings.get("auto_strict", True))
    settings["keep_audio"] = bool(settings.get("keep_audio", False))
    settings["effort_stars"] = bool(settings.get("effort_stars", True))
    settings["scheduler_shadow"] = bool(settings.get("scheduler_shadow", False))
    # scheduler_v2 is always on in build_adaptive_queue; keep flag true for clarity.
    settings["scheduler_v2"] = True
    # Empty unlocked_patterns = derive from mastery; reject stale non-list values.
    if not isinstance(settings.get("unlocked_patterns"), list):
        settings["unlocked_patterns"] = []
    buddy = str(settings.get("buddy", "krishna")).lower()
    if buddy == "mouse":
        buddy = "unicorn"  # migrate retired mouse buddy
    if buddy == "cat":
        buddy = "krishna"  # migrate retired cat buddy
    if buddy not in BUDDIES:
        raise ValueError(f"buddy must be one of {', '.join(BUDDIES)}")
    settings["buddy"] = buddy
    settings["profile_name"] = str(settings.get("profile_name") or "")

    if prev_keep and not settings["keep_audio"]:
        clear_kept_audio()

    save_settings(settings)
    return settings


def bump_garden(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Increment garden growth on completed session; never decreases."""
    settings = dict(settings or load_settings())
    growth = int(settings.get("garden_growth", 0)) + 1
    settings["garden_growth"] = growth
    save_settings(settings)
    return {
        "growth": growth,
        "stage": garden_stage_name(growth),
    }


def garden_stage_name(growth: int) -> str:
    if growth <= 0:
        return "seed"
    if growth <= 2:
        return "sprout"
    if growth <= 5:
        return "flower"
    if growth <= 9:
        return "creature"
    return "sticker"


# id → (label, predicate over settings-like dict)
BADGE_DEFS: list[tuple[str, str, Callable[[dict[str, Any]], bool]]] = [
    ("first_star", "First star", lambda s: int(s.get("lifetime_stars", 0)) >= 1),
    ("garden_seed", "Garden planted", lambda s: int(s.get("garden_growth", 0)) >= 1),
    ("streak_3", "3-day streak", lambda s: int(s.get("day_streak", 0)) >= 3),
    ("star_10", "10 stars", lambda s: int(s.get("lifetime_stars", 0)) >= 10),
    ("garden_flower", "Flower garden", lambda s: int(s.get("garden_growth", 0)) >= 3),
    ("streak_7", "Week of reading", lambda s: int(s.get("day_streak", 0)) >= 7),
    ("star_50", "Star collector", lambda s: int(s.get("lifetime_stars", 0)) >= 50),
    ("garden_sticker", "Garden sticker", lambda s: int(s.get("garden_growth", 0)) >= 10),
]


def compute_badges(settings: dict[str, Any]) -> list[dict[str, str]]:
    earned: list[dict[str, str]] = []
    for badge_id, label, pred in BADGE_DEFS:
        try:
            if pred(settings):
                earned.append({"id": badge_id, "label": label})
        except Exception:  # noqa: BLE001
            continue
    return earned


def bump_play_stats(
    settings: dict[str, Any],
    *,
    stars_earned: int,
) -> dict[str, Any]:
    """Update lifetime stars, day streak, badges after a completed session."""
    settings = dict(settings)
    today = local_today()
    last = str(settings.get("last_play_date") or "")
    streak = int(settings.get("day_streak", 0) or 0)

    if last == today:
        # Already played today — keep streak; still add stars.
        pass
    elif last:
        try:
            prev = date.fromisoformat(last)
            today_d = date.fromisoformat(today)
            if (today_d - prev).days == 1:
                streak += 1
            elif (today_d - prev).days > 1:
                streak = 1  # quiet reset — no scolding
            # same day already handled
        except ValueError:
            streak = 1
    else:
        streak = 1

    prev_badges = set(settings.get("badges_earned") or [])
    settings["lifetime_stars"] = int(settings.get("lifetime_stars", 0) or 0) + max(
        0, int(stars_earned)
    )
    settings["day_streak"] = max(1, streak)
    settings["last_play_date"] = today

    all_badges = compute_badges(settings)
    badge_ids = [b["id"] for b in all_badges]
    settings["badges_earned"] = badge_ids
    new_badges = [b for b in all_badges if b["id"] not in prev_badges]

    save_settings(settings)
    return {
        "lifetime_stars": int(settings["lifetime_stars"]),
        "day_streak": int(settings["day_streak"]),
        "quest_complete": True,
        "quest_label": config.stage_label(
            config.normalize_difficulty(settings.get("level", 1)),
            config.normalize_stage(settings.get("stage", 1)),
        ),
        "badges": all_badges,
        "new_badges": new_badges,
        "last_play_date": today,
    }


def play_summary(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Home-screen quest / streak / badge snapshot."""
    settings = dict(settings or load_settings())
    today = local_today()
    last = str(settings.get("last_play_date") or "")
    quest_complete = last == today
    level = config.normalize_difficulty(settings.get("level", 1))
    stage = config.normalize_stage(settings.get("stage", 1))
    badges = compute_badges(settings)
    # Persist derived badge ids if settings lag behind (e.g. after upgrade).
    earned_ids = [b["id"] for b in badges]
    if set(earned_ids) != set(settings.get("badges_earned") or []):
        settings["badges_earned"] = earned_ids
        save_settings(settings)
    return {
        "lifetime_stars": int(settings.get("lifetime_stars", 0) or 0),
        "day_streak": int(settings.get("day_streak", 0) or 0),
        "quest_complete": quest_complete,
        "quest_label": config.stage_label(level, stage),
        "badges": badges,
        "last_play_date": last,
    }
