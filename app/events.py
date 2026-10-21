"""Append-only learning event log for scheduling and parent insight."""

from __future__ import annotations

import sqlite3
from typing import Any

from app.db import local_now_iso


def ensure_events_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY,
          created_at TEXT NOT NULL,
          session_id INTEGER,
          item_id INTEGER,
          pattern TEXT NOT NULL DEFAULT '',
          sight_word INTEGER NOT NULL DEFAULT 0,
          result TEXT NOT NULL,
          phase TEXT NOT NULL DEFAULT 'read',
          latency_ms INTEGER,
          duration_seconds REAL,
          counts_for_mastery INTEGER NOT NULL DEFAULT 1,
          meta_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_events_day_pattern ON events (created_at, pattern)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_events_item ON events (item_id, created_at)"
    )
    conn.commit()


def log_event(
    conn: sqlite3.Connection,
    *,
    session_id: int | None,
    item_id: int | None,
    pattern: str,
    sight_word: bool,
    result: str,
    phase: str = "read",
    latency_ms: int | None = None,
    duration_seconds: float | None = None,
    counts_for_mastery: bool = True,
    meta: dict[str, Any] | None = None,
) -> int:
    import json

    ensure_events_table(conn)
    cur = conn.execute(
        """
        INSERT INTO events (
          created_at, session_id, item_id, pattern, sight_word, result, phase,
          latency_ms, duration_seconds, counts_for_mastery, meta_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            local_now_iso(),
            session_id,
            item_id,
            pattern or "",
            1 if sight_word else 0,
            result,
            phase,
            latency_ms,
            duration_seconds,
            1 if counts_for_mastery else 0,
            json.dumps(meta or {}),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def pattern_accuracy_by_day(conn: sqlite3.Connection, *, days: int = 30) -> list[dict[str, Any]]:
    ensure_events_table(conn)
    rows = conn.execute(
        """
        SELECT substr(created_at, 1, 10) AS day,
               pattern,
               SUM(CASE WHEN result = 'correct' THEN 1 ELSE 0 END) AS correct,
               SUM(CASE WHEN result NOT IN ('retry') THEN 1 ELSE 0 END) AS scored
        FROM events
        WHERE counts_for_mastery = 1
          AND pattern != ''
          AND substr(created_at, 1, 10) >= date('now', ?)
        GROUP BY day, pattern
        ORDER BY day ASC, pattern ASC
        """,
        (f"-{max(0, days - 1)} days",),
    ).fetchall()
    return [
        {
            "day": r["day"],
            "pattern": r["pattern"],
            "correct": int(r["correct"]),
            "scored": int(r["scored"]),
        }
        for r in rows
    ]


def known_ratio_by_pattern(conn: sqlite3.Connection) -> dict[str, float]:
    """Fraction of items per pattern that are mastered (or box >= 2 if present)."""
    ensure_events_table(conn)
    rows = conn.execute(
        """
        SELECT i.pattern AS pattern,
               COUNT(*) AS total,
               SUM(
                 CASE
                   WHEN COALESCE(m.box, 0) >= 2 THEN 1
                   WHEN m.mastered = 1 THEN 1
                   ELSE 0
                 END
               ) AS known
        FROM items i
        LEFT JOIN mastery m ON m.item_id = i.id
        WHERE i.pattern IS NOT NULL AND i.pattern != ''
        GROUP BY i.pattern
        """
    ).fetchall()
    out: dict[str, float] = {}
    for r in rows:
        total = int(r["total"]) or 1
        out[str(r["pattern"])] = int(r["known"] or 0) / total
    return out
