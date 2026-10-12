"""SQLite schema, settings, and CRUD helpers."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from app import config
from app.matching import normalize_text


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY,
  slug TEXT NOT NULL UNIQUE,
  text TEXT NOT NULL,
  normalized TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('word', 'phrase', 'sentence', 'line')),
  level INTEGER NOT NULL CHECK (level BETWEEN 1 AND 7),
  sound_tags TEXT NOT NULL DEFAULT '[]',
  sounds_locked INTEGER NOT NULL DEFAULT 0 CHECK (sounds_locked IN (0, 1)),
  rhyme_group TEXT,
  line_index INTEGER,
  source TEXT NOT NULL,
  pd_status TEXT NOT NULL,
  hard INTEGER NOT NULL DEFAULT 0 CHECK (hard IN (0, 1))
);
CREATE INDEX IF NOT EXISTS idx_items_level_kind ON items (level, kind);

CREATE TABLE IF NOT EXISTS sessions (
  id INTEGER PRIMARY KEY,
  started_at TEXT NOT NULL,
  ended_at TEXT,
  mode TEXT NOT NULL CHECK (mode IN ('beginner', 'strict')),
  level INTEGER NOT NULL,
  planned_count INTEGER NOT NULL,
  planned_item_ids TEXT NOT NULL,
  play_item_ids TEXT NOT NULL DEFAULT '[]',
  ratio_flags TEXT NOT NULL DEFAULT '[]',
  correct_count INTEGER NOT NULL DEFAULT 0,
  stars INTEGER NOT NULL DEFAULT 0,
  low_session INTEGER NOT NULL DEFAULT 0 CHECK (low_session IN (0, 1)),
  level_after INTEGER,
  completed INTEGER NOT NULL DEFAULT 0 CHECK (completed IN (0, 1))
);

CREATE TABLE IF NOT EXISTS attempts (
  id INTEGER PRIMARY KEY,
  session_id INTEGER NOT NULL REFERENCES sessions(id),
  item_id INTEGER NOT NULL REFERENCES items(id),
  heard TEXT NOT NULL,
  confidence REAL,
  word_scores TEXT NOT NULL,
  result TEXT NOT NULL CHECK (result IN ('correct', 'close', 'missed', 'retry', 'skipped')),
  counts_for_session INTEGER NOT NULL CHECK (counts_for_session IN (0, 1)),
  is_replay INTEGER NOT NULL DEFAULT 0 CHECK (is_replay IN (0, 1)),
  queue_index INTEGER,
  replay_word TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_attempts_session ON attempts (session_id);
CREATE INDEX IF NOT EXISTS idx_attempts_item_created ON attempts (item_id, created_at);

CREATE TABLE IF NOT EXISTS mastery (
  item_id INTEGER PRIMARY KEY REFERENCES items(id),
  correct_count INTEGER NOT NULL DEFAULT 0,
  days_json TEXT NOT NULL DEFAULT '[]',
  miss_count INTEGER NOT NULL DEFAULT 0,
  review_step INTEGER NOT NULL DEFAULT 0,
  next_review_on TEXT,
  mastered INTEGER NOT NULL DEFAULT 0 CHECK (mastered IN (0, 1)),
  mastered_on TEXT,
  last_result TEXT,
  last_seen_on TEXT
);
CREATE INDEX IF NOT EXISTS idx_mastery_next_review ON mastery (next_review_on);
"""


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    # Additive migrations for DBs created before pre-M3 / M3 columns.
    _ensure_column(conn, "sessions", "play_item_ids", "TEXT NOT NULL DEFAULT '[]'")
    _ensure_column(conn, "sessions", "ratio_flags", "TEXT NOT NULL DEFAULT '[]'")
    _ensure_column(conn, "attempts", "queue_index", "INTEGER")
    _ensure_column(conn, "attempts", "replay_word", "TEXT NOT NULL DEFAULT ''")
    # Indexes that depend on migrated columns (must run after _ensure_column).
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_attempts_queue ON attempts (session_id, queue_index)"
    )
    _ensure_column(conn, "items", "story_id", "TEXT")
    _ensure_column(conn, "attempts", "passage", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "attempts", "duration_seconds", "REAL")
    # Backfill play_item_ids from planned when empty.
    conn.execute(
        """
        UPDATE sessions
        SET play_item_ids = planned_item_ids
        WHERE play_item_ids IS NULL OR play_item_ids = '' OR play_item_ids = '[]'
        """
    )
    # Backfill ratio_flags: one true per planned slot (parallel to play when equal).
    rows = conn.execute(
        "SELECT id, planned_item_ids, play_item_ids, ratio_flags FROM sessions"
    ).fetchall()
    for row in rows:
        flags_raw = row["ratio_flags"]
        if flags_raw and flags_raw not in ("", "[]"):
            continue
        planned = json.loads(row["planned_item_ids"] or "[]")
        play = json.loads(row["play_item_ids"] or "[]") or planned
        # Mark first len(planned) play slots as ratio-eligible when play started as planned.
        flags = [True] * len(planned)
        if len(play) > len(planned):
            flags.extend([False] * (len(play) - len(planned)))
        conn.execute(
            "UPDATE sessions SET ratio_flags = ? WHERE id = ?",
            (json.dumps(flags), row["id"]),
        )
    conn.commit()


def load_settings(path: Path | None = None) -> dict[str, Any]:
    settings_path = path or config.SETTINGS_PATH
    if not settings_path.exists():
        save_settings(dict(config.DEFAULT_SETTINGS), settings_path)
        return dict(config.DEFAULT_SETTINGS)
    with settings_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    merged = dict(config.DEFAULT_SETTINGS)
    merged.update(data)
    dirty = False
    # Migrate retired buddies (persist so old settings stay valid).
    buddy = str(merged.get("buddy", "")).lower()
    if buddy == "mouse":
        merged["buddy"] = "unicorn"
        dirty = True
    elif buddy == "cat":
        merged["buddy"] = "krishna"
        dirty = True
    # Session length is only 5 or 10.
    length = config.normalize_session_length(
        merged.get("session_length", config.DEFAULT_SESSION_LENGTH)
    )
    if int(merged.get("session_length", 0) or 0) != length:
        merged["session_length"] = length
        dirty = True
    # Content levels 1–7 → difficulty tiers 1–4 (once).
    if not merged.get("difficulty_migrated"):
        merged["level"] = config.migrate_legacy_level_to_difficulty(
            merged.get("level", 1)
        )
        merged["difficulty_migrated"] = True
        dirty = True
    else:
        difficulty = config.normalize_difficulty(merged.get("level", 1))
        if int(merged.get("level", 0) or 0) != difficulty:
            merged["level"] = difficulty
            dirty = True
    # Per-difficulty sets (stages) 1–8.
    by_diff = merged.get("stage_by_difficulty")
    if not isinstance(by_diff, dict):
        by_diff = config.default_stage_by_difficulty()
        dirty = True
    else:
        fixed = config.default_stage_by_difficulty()
        for key, val in by_diff.items():
            if str(key) in fixed:
                fixed[str(key)] = config.normalize_stage(val)
        by_diff = fixed
        if by_diff != merged.get("stage_by_difficulty"):
            dirty = True
    merged["stage_by_difficulty"] = by_diff
    difficulty = config.normalize_difficulty(merged.get("level", 1))
    stage = config.normalize_stage(
        by_diff.get(str(difficulty), merged.get("stage", 1))
    )
    if int(merged.get("stage", 0) or 0) != stage:
        merged["stage"] = stage
        dirty = True
    if dirty:
        save_settings(merged, settings_path)
    return merged


def save_settings(settings: dict[str, Any], path: Path | None = None) -> None:
    settings_path = path or config.SETTINGS_PATH
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    with settings_path.open("w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")


def upsert_items_from_json(conn: sqlite3.Connection, items_path: Path | None = None) -> int:
    _ensure_column(conn, "items", "story_id", "TEXT")
    path = items_path or config.CONTENT_ITEMS
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    items = payload if isinstance(payload, list) else payload.get("items", [])
    count = 0
    for raw in items:
        slug = raw["slug"]
        text = raw["text"]
        normalized = raw.get("normalized") or normalize_text(text)
        kind = raw.get("kind", "word")
        level = int(raw["level"])
        sound_tags = json.dumps(raw.get("sound_tags", []))
        sounds_locked = 1 if raw.get("sounds_locked") else 0
        rhyme_group = raw.get("rhyme_group")
        line_index = raw.get("line_index")
        story_id = raw.get("story_id")
        source = raw.get("source", "cvc")
        pd_status = raw.get("pd_status", "n/a")
        hard = 1 if raw.get("hard", level >= 3) else 0
        conn.execute(
            """
            INSERT INTO items (
              slug, text, normalized, kind, level, sound_tags, sounds_locked,
              rhyme_group, line_index, source, pd_status, hard, story_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
              text=excluded.text,
              normalized=excluded.normalized,
              kind=excluded.kind,
              level=excluded.level,
              sound_tags=excluded.sound_tags,
              sounds_locked=excluded.sounds_locked,
              rhyme_group=excluded.rhyme_group,
              line_index=excluded.line_index,
              source=excluded.source,
              pd_status=excluded.pd_status,
              hard=excluded.hard,
              story_id=excluded.story_id
            """,
            (
                slug,
                text,
                normalized,
                kind,
                level,
                sound_tags,
                sounds_locked,
                rhyme_group,
                line_index,
                source,
                pd_status,
                hard,
                story_id,
            ),
        )
        count += 1
    keep = [raw["slug"] for raw in items]
    placeholders = ",".join("?" * len(keep)) if keep else "''"
    stale = conn.execute(
        f"SELECT id, slug FROM items WHERE slug NOT IN ({placeholders})",
        keep,
    ).fetchall()
    for row in stale:
        used = conn.execute(
            "SELECT 1 FROM attempts WHERE item_id = ? LIMIT 1",
            (row["id"],),
        ).fetchone()
        if used:
            continue
        conn.execute("DELETE FROM mastery WHERE item_id = ?", (row["id"],))
        conn.execute("DELETE FROM items WHERE id = ?", (row["id"],))
    conn.commit()
    return count


def local_now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def local_today() -> str:
    return datetime.now().date().isoformat()


def get_item(conn: sqlite3.Connection, item_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()


def get_session(conn: sqlite3.Connection, session_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()


def list_items_for_level(conn: sqlite3.Connection, level: int) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM items WHERE level = ? ORDER BY id ASC",
            (level,),
        ).fetchall()
    )


def ensure_mastery_row(conn: sqlite3.Connection, item_id: int) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO mastery (item_id, correct_count, days_json, miss_count, review_step, mastered)
        VALUES (?, 0, '[]', 0, 0, 0)
        """,
        (item_id,),
    )


def touch_mastery(conn: sqlite3.Connection, item_id: int, result: str) -> None:
    ensure_mastery_row(conn, item_id)
    conn.execute(
        """
        UPDATE mastery
        SET last_result = ?, last_seen_on = ?
        WHERE item_id = ?
        """,
        (result, local_today(), item_id),
    )


def credit_mastery_correct(
    conn: sqlite3.Connection, item_id: int, *, keep_plus_one_day: bool = False
) -> None:
    """Increment mastery / ladder for a locking or replay correct (M3)."""
    from app.adaptive import apply_day_ladder

    apply_day_ladder(
        conn, item_id, "correct", keep_plus_one_day=keep_plus_one_day
    )


def item_public(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "slug": row["slug"],
        "text": row["text"],
        "kind": row["kind"],
        "rhyme_group": row["rhyme_group"],
        "line_index": row["line_index"],
        "story_id": row["story_id"] if "story_id" in row.keys() else None,
    }
