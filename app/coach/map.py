"""Per-pattern / per-item skill map from attempt evidence (Phase 6)."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Literal

from app.events import ensure_events_table

SkillStatus = Literal["independent", "needs_hint", "needs_practice", "not_seen"]


def _meta(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def classify_counts(
    *,
    independent_ok: int,
    assisted_ok: int,
    misses: int,
    uncertain: int,
) -> SkillStatus:
    """Map tallies → status. Independent evidence wins over assisted."""
    if independent_ok > 0 and independent_ok >= misses:
        return "independent"
    if assisted_ok > 0 and independent_ok == 0:
        return "needs_hint"
    if misses > 0 or uncertain > 0:
        return "needs_practice"
    if independent_ok > 0:
        return "independent"
    return "not_seen"


def skill_map(conn: sqlite3.Connection, *, days: int = 30) -> dict[str, dict[str, Any]]:
    """Return ``{pattern: {status, independent_ok, assisted_ok, misses, uncertain}}``."""
    ensure_events_table(conn)
    rows = conn.execute(
        """
        SELECT pattern, result, counts_for_mastery, meta_json
        FROM events
        WHERE pattern != ''
          AND substr(created_at, 1, 10) >= date('now', ?)
        """,
        (f"-{max(0, days - 1)} days",),
    ).fetchall()
    tallies: dict[str, dict[str, int]] = {}
    for row in rows:
        pattern = str(row["pattern"] or "")
        if not pattern:
            continue
        bucket = tallies.setdefault(
            pattern,
            {"independent_ok": 0, "assisted_ok": 0, "misses": 0, "uncertain": 0},
        )
        meta = _meta(row["meta_json"] if "meta_json" in row.keys() else None)
        outcome = str(meta.get("outcome") or "")
        assisted = bool(meta.get("assisted"))
        again = bool(meta.get("again"))
        reason = str(meta.get("reason_code") or "")
        result = str(row["result"] or "")
        mastery = int(row["counts_for_mastery"] or 0) == 1

        # Prefer outcome flags: provisional second-chance is logged as result=retry
        # but meta.outcome stays incorrect — never treat that as ASR fog.
        if outcome in ("silence", "uncertain"):
            bucket["uncertain"] += 1
            continue
        if again or outcome == "incorrect":
            if result == "close" or reason == "soft_mismatch":
                bucket["assisted_ok"] += 1
            else:
                bucket["misses"] += 1
            continue
        if result == "retry":
            bucket["uncertain"] += 1
            continue
        if result == "missed":
            bucket["misses"] += 1
            continue
        if result == "correct":
            if mastery and not assisted:
                bucket["independent_ok"] += 1
            elif assisted:
                bucket["assisted_ok"] += 1
            elif mastery:
                bucket["independent_ok"] += 1
            else:
                bucket["assisted_ok"] += 1
            continue
        if result == "close":
            bucket["assisted_ok"] += 1

    out: dict[str, dict[str, Any]] = {}
    for pattern, t in tallies.items():
        status = classify_counts(**t)
        out[pattern] = {"status": status, **t}
    return out


def weak_patterns(conn: sqlite3.Connection, *, days: int = 30) -> list[str]:
    """Patterns that need practice or hints, weakest first."""
    ranking = {"needs_practice": 0, "needs_hint": 1, "not_seen": 2, "independent": 3}
    items = list(skill_map(conn, days=days).items())
    items.sort(
        key=lambda kv: (
            ranking.get(str(kv[1]["status"]), 9),
            -int(kv[1].get("misses") or 0),
            kv[0],
        )
    )
    return [
        p
        for p, info in items
        if info["status"] in ("needs_practice", "needs_hint")
    ]


def weak_item_ids(
    conn: sqlite3.Connection,
    *,
    days: int = 30,
    limit: int = 40,
) -> list[int]:
    """Item ids tagged with weak patterns (for review ordering)."""
    patterns = weak_patterns(conn, days=days)
    if not patterns:
        return []
    placeholders = ",".join("?" for _ in patterns)
    rows = conn.execute(
        f"""
        SELECT id FROM items
        WHERE pattern IN ({placeholders})
          AND COALESCE(retired, 0) = 0
        ORDER BY id ASC
        LIMIT ?
        """,
        (*patterns, limit),
    ).fetchall()
    return [int(r["id"]) for r in rows]
