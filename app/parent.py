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
BUDDIES = ("cat", "krishna", "unicorn")


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
    by = {r["d"]: {"date": r["d"], "correct": int(r["correct"]), "scored": int(r["scored"])} for r in rows}
    out = []
    cur = start
    while cur <= today:
        key = cur.isoformat()
        out.append(by.get(key, {"date": key, "correct": 0, "scored": 0}))
        cur += timedelta(days=1)
    return {"days": out}


def mastered_lists(conn) -> dict[str, Any]:
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
    return {"mastered": mastered, "this_week": this_week}


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
    rows = conn.execute(
        """
        SELECT i.sound_tags, a.result
        FROM attempts a
        JOIN items i ON i.id = a.item_id
        WHERE a.is_replay = 0 AND a.result != 'retry'
        """
    ).fetchall()
    tallies: dict[str, dict[str, int]] = {}
    for row in rows:
        tags = json.loads(row["sound_tags"] or "[]")
        if not tags:
            continue
        for tag in tags:
            bucket = tallies.setdefault(tag, {"correct": 0, "scored": 0})
            bucket["scored"] += 1
            if row["result"] == "correct":
                bucket["correct"] += 1
    tags_out = [
        {"tag": tag, "correct": v["correct"], "scored": v["scored"]}
        for tag, v in sorted(tallies.items(), key=lambda kv: (-kv[1]["scored"], kv[0]))
    ]
    return {"tags": tags_out, "note": SOUND_NOTE}


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
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        _csv_table(
            zf,
            "items.csv",
            conn,
            "SELECT id, slug, text, kind, level, sound_tags, rhyme_group, line_index, source, pd_status, hard FROM items ORDER BY id",
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
            "SELECT id, session_id, item_id, heard, confidence, result, counts_for_session, is_replay, queue_index, replay_word, created_at FROM attempts ORDER BY id",
        )
        _csv_table(
            zf,
            "mastery.csv",
            conn,
            "SELECT item_id, correct_count, days_json, miss_count, review_step, next_review_on, mastered, mastered_on, last_result, last_seen_on FROM mastery ORDER BY item_id",
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


def apply_settings_update(payload: dict[str, Any]) -> dict[str, Any]:
    settings = load_settings()
    prev_keep = bool(settings.get("keep_audio", False))
    allowed = {
        "mode",
        "level",
        "auto_strict",
        "auto_strict_sessions",
        "session_length",
        "profile_name",
        "buddy",
        "keep_audio",
    }
    for key, value in payload.items():
        if key not in allowed:
            raise ValueError(f"Unknown settings field: {key}")
        settings[key] = value

    if settings.get("mode") not in ("beginner", "strict"):
        raise ValueError("mode must be beginner or strict")
    level = int(settings["level"])
    if level < 1 or level > 7:
        raise ValueError("level must be between 1 and 7")
    settings["level"] = level
    length = int(settings.get("session_length", config.DEFAULT_SESSION_LENGTH))
    settings["session_length"] = max(5, min(20, length))
    settings["auto_strict"] = bool(settings.get("auto_strict", True))
    settings["keep_audio"] = bool(settings.get("keep_audio", False))
    buddy = str(settings.get("buddy", "cat")).lower()
    if buddy == "mouse":
        buddy = "unicorn"  # migrate retired mouse buddy
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
        "quest_label": "Finish today's reading",
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
        "quest_label": "Finish today's reading",
        "badges": badges,
        "last_play_date": last,
    }
