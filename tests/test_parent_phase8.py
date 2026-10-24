"""Phase 8: independent vs assisted parent aggregates, tip, export schema."""

from __future__ import annotations

import io
import zipfile

from app.db import local_today, load_settings
from app.events import log_event
from app.parent import (
    accuracy_by_day,
    export_zip_bytes,
    mastered_lists,
    retention_after_delay,
    tomorrow_note,
)


def _item(conn, slug="cat"):
    return conn.execute("SELECT * FROM items WHERE slug=?", (slug,)).fetchone()


def test_accuracy_distinguishes_independent_vs_assisted(tmp_env):
    conn = tmp_env["conn"]
    item = _item(conn)
    log_event(
        conn,
        session_id=None,
        item_id=int(item["id"]),
        pattern=item["pattern"],
        sight_word=False,
        result="correct",
        counts_for_mastery=True,
        meta={"outcome": "correct", "assisted": False},
    )
    log_event(
        conn,
        session_id=None,
        item_id=int(item["id"]),
        pattern=item["pattern"],
        sight_word=False,
        result="correct",
        counts_for_mastery=False,
        meta={"outcome": "correct", "assisted": True},
    )
    days = accuracy_by_day(conn, days=7)["days"]
    today = next(d for d in days if d["date"] == local_today())
    assert today["independent_correct"] >= 1
    assert today["assisted_correct"] >= 1
    assert today["locking_reads"] >= 2


def test_mastered_lists_include_independent(tmp_env):
    conn = tmp_env["conn"]
    item = _item(conn)
    log_event(
        conn,
        session_id=None,
        item_id=int(item["id"]),
        pattern=item["pattern"],
        sight_word=False,
        result="correct",
        counts_for_mastery=True,
        meta={"outcome": "correct", "assisted": False},
    )
    data = mastered_lists(conn)
    assert any(w["text"] == item["text"] for w in data["independent"])


def test_retention_after_delay(tmp_env):
    conn = tmp_env["conn"]
    item = _item(conn)
    # Backdate a miss, then independent correct "today".
    conn.execute(
        """
        INSERT INTO events (
          created_at, session_id, item_id, pattern, sight_word, result, phase,
          counts_for_mastery, meta_json
        ) VALUES ('2020-01-01T12:00:00', NULL, ?, ?, 0, 'missed', 'read', 1, '{}')
        """,
        (int(item["id"]), item["pattern"]),
    )
    conn.commit()
    log_event(
        conn,
        session_id=None,
        item_id=int(item["id"]),
        pattern=item["pattern"],
        sight_word=False,
        result="correct",
        counts_for_mastery=True,
        meta={"outcome": "correct", "assisted": False},
    )
    ret = retention_after_delay(conn)
    assert ret["count"] >= 1
    assert any(r["text"] == item["text"] for r in ret["items"])


def test_tomorrow_tip_deterministic(tmp_env):
    from app.db import ensure_mastery_row

    conn = tmp_env["conn"]
    item = _item(conn)
    ensure_mastery_row(conn, int(item["id"]))
    conn.execute(
        """
        UPDATE mastery
        SET next_review_on = ?, mastered = 0, box = 1, miss_count = 1
        WHERE item_id = ?
        """,
        (local_today(), int(item["id"])),
    )
    conn.commit()
    log_event(
        conn,
        session_id=None,
        item_id=int(item["id"]),
        pattern=item["pattern"],
        sight_word=False,
        result="missed",
        counts_for_mastery=True,
        meta={"outcome": "incorrect"},
    )
    a = tomorrow_note(conn, load_settings())
    b = tomorrow_note(conn, load_settings())
    assert a == b
    assert a["due_count"] >= 1
    assert a["practice_tip"]
    assert "due" in a["practice_tip"].lower() or a["weak_patterns"]


def test_export_readme_schema_version(tmp_env):
    conn = tmp_env["conn"]
    raw = export_zip_bytes(conn)
    zf = zipfile.ZipFile(io.BytesIO(raw))
    readme = zf.read("README.txt").decode("utf-8")
    assert "schema_version: 2" in readme
    assert "assisted" in readme.lower()
    assert "events.csv" in zf.namelist()
