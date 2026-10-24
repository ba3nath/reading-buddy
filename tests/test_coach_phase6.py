"""Phase 6: skill map, planner ordering, same-day Leitner guard."""

from __future__ import annotations

import json

from app.adaptive import apply_day_ladder
from app.coach.map import classify_counts, skill_map, weak_item_ids, weak_patterns
from app.coach.plan import prefer_ids, prefer_rows, select_review_priority
from app.db import ensure_mastery_row, local_today
from app.events import log_event


def test_classify_counts_independent_beats_misses():
    assert classify_counts(independent_ok=2, assisted_ok=0, misses=1, uncertain=0) == "independent"
    assert classify_counts(independent_ok=0, assisted_ok=1, misses=0, uncertain=0) == "needs_hint"
    assert classify_counts(independent_ok=0, assisted_ok=0, misses=1, uncertain=0) == "needs_practice"
    assert classify_counts(independent_ok=0, assisted_ok=0, misses=0, uncertain=1) == "needs_practice"
    assert classify_counts(independent_ok=0, assisted_ok=0, misses=0, uncertain=0) == "not_seen"


def test_prefer_ids_stable():
    assert prefer_ids([1, 2, 3, 4], [3, 1]) == [3, 1, 2, 4]
    assert prefer_ids([1, 2], []) == [1, 2]
    assert prefer_ids([1, 2], [9]) == [1, 2]


def test_select_review_priority_due_weak_first():
    assert select_review_priority(
        due_ids=[10, 20, 30],
        weak_ids=[20, 40],
        stage_ids=[10, 20, 40],
    ) == [20, 10, 30, 40]


def test_skill_map_from_events(tmp_env):
    conn = tmp_env["conn"]
    item = conn.execute(
        "SELECT id, pattern FROM items WHERE pattern='cvc-a' LIMIT 1"
    ).fetchone()
    log_event(
        conn,
        session_id=None,
        item_id=int(item["id"]),
        pattern=item["pattern"],
        sight_word=False,
        result="missed",
        counts_for_mastery=True,
        meta={"outcome": "missed"},
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
    sm = skill_map(conn, days=30)
    assert item["pattern"] in sm
    assert sm[item["pattern"]]["misses"] >= 1
    assert sm[item["pattern"]]["status"] in ("needs_practice", "needs_hint")
    weak = weak_patterns(conn)
    assert item["pattern"] in weak
    ids = weak_item_ids(conn, limit=10)
    assert int(item["id"]) in ids


def test_prefer_rows_orders_by_weak_ids():
    rows = [{"id": 1}, {"id": 2}, {"id": 3}]
    assert [r["id"] for r in prefer_rows(rows, [3, 1])] == [3, 1, 2]


def test_same_day_box_advances_at_most_once(tmp_env):
    conn = tmp_env["conn"]
    item_id = conn.execute("SELECT id FROM items WHERE slug='cat'").fetchone()["id"]
    ensure_mastery_row(conn, item_id)
    conn.execute(
        """
        UPDATE mastery
        SET box=1, correct_count=0, days_json='[]', mastered=0,
            review_step=0, next_review_on=NULL
        WHERE item_id=?
        """,
        (item_id,),
    )
    conn.commit()
    apply_day_ladder(conn, item_id, "correct")
    row = conn.execute("SELECT * FROM mastery WHERE item_id=?", (item_id,)).fetchone()
    assert int(row["box"]) == 2
    assert local_today() in json.loads(row["days_json"])
    apply_day_ladder(conn, item_id, "correct")
    row2 = conn.execute("SELECT * FROM mastery WHERE item_id=?", (item_id,)).fetchone()
    assert int(row2["box"]) == 2  # no second bump today
    assert int(row2["correct_count"]) == 2  # evidence still counted
