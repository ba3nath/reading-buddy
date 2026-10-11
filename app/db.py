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


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
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
    return merged


def save_settings(settings: dict[str, Any], path: Path | None = None) -> None:
    settings_path = path or config.SETTINGS_PATH
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    with settings_path.open("w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")


def upsert_items_from_json(conn: sqlite3.Connection, items_path: Path | None = None) -> int:
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
        source = raw.get("source", "cvc")
        pd_status = raw.get("pd_status", "n/a")
        hard = 1 if raw.get("hard", level >= 3) else 0
        conn.execute(
            """
            INSERT INTO items (
              slug, text, normalized, kind, level, sound_tags, sounds_locked,
              rhyme_group, line_index, source, pd_status, hard
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
              hard=excluded.hard
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
            ),
        )
        count += 1
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


def item_public(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "slug": row["slug"],
        "text": row["text"],
        "kind": row["kind"],
        "rhyme_group": row["rhyme_group"],
        "line_index": row["line_index"],
    }
