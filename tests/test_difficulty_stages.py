"""Eight sets (stages) inside each difficulty tier."""

from __future__ import annotations

from app.adaptive import (
    apply_level_and_auto_strict,
    build_adaptive_queue,
    items_for_stage,
    _ordered_tier_items,
)
from app.config import (
    STAGES_PER_DIFFICULTY,
    content_levels_for_difficulty,
    normalize_stage,
    stage_label,
    stage_slice_bounds,
)
from app.db import load_settings, save_settings
from app.session import start_session


def test_eight_stages_per_difficulty():
    assert STAGES_PER_DIFFICULTY == 8
    assert normalize_stage(0) == 1
    assert normalize_stage(9) == 8
    assert stage_label(1, 2) == "Words · Set 2/8"
    assert stage_label(3, 8) == "Rhymes · Set 8/8"


def test_stage_slice_covers_pool_without_overlap():
    n = 96  # Words pool after sets 6–8 content
    seen = []
    for stage in range(1, STAGES_PER_DIFFICULTY + 1):
        start, end = stage_slice_bounds(n, stage)
        assert end > start or n == 0
        seen.extend(range(start, end))
    assert seen == list(range(n))
    # Phrases/Stories (32) still get 8 non-empty slices.
    sizes = []
    for stage in range(1, STAGES_PER_DIFFICULTY + 1):
        a, b = stage_slice_bounds(32, stage)
        sizes.append(b - a)
    assert sum(sizes) == 32
    assert all(s >= 1 for s in sizes)


def test_queue_stays_inside_current_and_earlier_sets(tmp_env):
    conn = tmp_env["conn"]
    levels = content_levels_for_difficulty(1)
    tier = _ordered_tier_items(conn, levels)
    stage3 = {int(r["id"]) for r in items_for_stage(tier, 3)}
    earlier = set()
    for s in (1, 2):
        earlier |= {int(r["id"]) for r in items_for_stage(tier, s)}
    later = set()
    for s in (4, 5, 6, 7, 8):
        later |= {int(r["id"]) for r in items_for_stage(tier, s)}

    queue = build_adaptive_queue(conn, level=1, length=10, stage=3)
    ids = {int(r["id"]) for r in queue}
    # Prefer current/earlier sets; Words stage pools are large enough to avoid later.
    assert len(ids & (stage3 | earlier)) >= 1
    assert len(queue) == 10
    # Majority of the set should not be locked later-stage items.
    assert len(ids & later) <= 2


def test_start_session_reports_stage_label(tmp_env):
    conn = tmp_env["conn"]
    save_settings(
        {
            **load_settings(),
            "level": 1,
            "stage": 2,
            "stage_by_difficulty": {"1": 2, "2": 1, "3": 1, "4": 1},
            "session_length": 5,
        }
    )
    data = start_session(conn, level=1)
    assert data["stage"] == 2
    assert data["stages_total"] == 8
    assert data["stage_label"] == "Words · Set 2/8"
    assert data["planned_count"] == 5


def test_clearing_last_set_unlocks_next_difficulty(tmp_env):
    settings = load_settings()
    settings.update(
        {
            "level": 1,
            "stage": 8,
            "stage_by_difficulty": {"1": 8, "2": 1, "3": 1, "4": 1},
            "low_streak": 0,
            "move_up_streak": 0,
        }
    )
    level_after, new_s = apply_level_and_auto_strict(
        level=1, correct_count=9, planned_count=10, settings=settings
    )
    assert level_after == 2
    assert new_s["stage"] == 1
    assert new_s["stage_by_difficulty"]["1"] == 8
    assert new_s["stage_by_difficulty"]["2"] == 1


def test_ui_exposes_eight_sets_copy():
    from pathlib import Path

    html = Path("static/index.html").read_text(encoding="utf-8")
    js = Path("static/js/game.js").read_text(encoding="utf-8")
    parent = Path("static/parent.html").read_text(encoding="utf-8")
    assert "data-stage-pick" not in html
    assert parent.count("Set ") >= 8
    assert "stage_label" in js
    assert "markCurrentSets" in js
    assert 'name="stage"' in parent
    assert "Set 1 of 8" in parent
    assert "Set 8 of 8" in parent


def test_parent_can_set_stage(client, tmp_env):
    body = client.put(
        "/api/parent/settings",
        json={"level": 2, "stage": 4},
    ).json()
    assert body["level"] == 2
    assert body["stage"] == 4
    assert body["stage_by_difficulty"]["2"] == 4


def test_session_create_accepts_stage(client, tmp_env):
    res = client.post("/api/sessions", json={"level": 1, "stage": 3})
    assert res.status_code == 200
    body = res.json()
    assert body["level"] == 1
    assert body["stage"] == 3
    assert body["stage_label"] == "Words · Set 3/8"
    from app.db import load_settings

    settings = load_settings()
    assert settings["level"] == 1
    assert settings["stage"] == 3
    assert settings["stage_by_difficulty"]["1"] == 3


def test_js_allows_stages_six_through_eight():
    """Regression: leftover <=5 clamps wiped sets 6–8 after expansion."""
    from pathlib import Path

    game = Path("static/js/game.js").read_text(encoding="utf-8")
    parent = Path("static/js/parent.js").read_text(encoding="utf-8")
    assert "n <= 5" not in game
    assert "n <= 8" in game
    assert "stage <= 5" not in parent
    assert "stage <= 8" in parent
