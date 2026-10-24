"""Parent heatmaps must not treat assisted corrects as independent success."""

from __future__ import annotations

from app.events import log_event
from app.parent import pattern_heatmap


def test_pattern_heatmap_ignores_assisted_correct(tmp_env):
    conn = tmp_env["conn"]
    item = conn.execute(
        "SELECT id, pattern, text FROM items WHERE pattern='cvc-a' LIMIT 1"
    ).fetchone()
    # Independent miss
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
    # Assisted correct should not inflate correct%
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
    heat = pattern_heatmap(conn)
    row = next(p for p in heat["patterns"] if p["pattern"] == item["pattern"])
    assert row["scored"] >= 2
    assert row["correct"] == 0
