"""Five sets (stages) inside each difficulty tier."""

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


def test_five_stages_per_difficulty():
    assert STAGES_PER_DIFFICULTY == 5
    assert normalize_stage(0) == 1
    assert normalize_stage(9) == 5
    assert stage_label(1, 2) == "Words · Set 2/5"
    assert stage_label(3, 5) == "Rhymes · Set 5/5"


def test_stage_slice_covers_pool_without_overlap():
    n = 60  # Words pool
    seen = []
    for stage in range(1, 6):
        start, end = stage_slice_bounds(n, stage)
        assert end > start or n == 0
        seen.extend(range(start, end))
    assert seen == list(range(n))
    # Phrases/Stories (20) still get 5 non-empty slices when possible.
    sizes = []
    for stage in range(1, 6):
        a, b = stage_slice_bounds(20, stage)
        sizes.append(b - a)
    assert sum(sizes) == 20
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
    for s in (4, 5):
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
    assert data["stages_total"] == 5
    assert data["stage_label"] == "Words · Set 2/5"
    assert data["planned_count"] == 5


def test_clearing_set_five_unlocks_next_difficulty(tmp_env):
    settings = load_settings()
    settings.update(
        {
            "level": 1,
            "stage": 5,
            "stage_by_difficulty": {"1": 5, "2": 1, "3": 1, "4": 1},
            "low_streak": 0,
            "move_up_streak": 0,
        }
    )
    level_after, new_s = apply_level_and_auto_strict(
        level=1, correct_count=9, planned_count=10, settings=settings
    )
    assert level_after == 2
    assert new_s["stage"] == 1
    assert new_s["stage_by_difficulty"]["1"] == 5
    assert new_s["stage_by_difficulty"]["2"] == 1


def test_ui_exposes_five_sets_copy():
    from pathlib import Path

    html = Path("static/index.html").read_text(encoding="utf-8")
    js = Path("static/js/game.js").read_text(encoding="utf-8")
    parent = Path("static/parent.html").read_text(encoding="utf-8")
    assert "Tap a set (1–5)" in html or "Tap a set (1-5)" in html
    assert "data-stage-pick" in html
    assert html.count('data-stage-pick="') == 20  # 4 difficulties × 5 sets
    assert "stage_label" in js
    assert "markCurrentSets" in js
    assert 'name="stage"' in parent
    assert "Set 1 of 5" in parent


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
    assert body["stage_label"] == "Words · Set 3/5"
    from app.db import load_settings

    settings = load_settings()
    assert settings["level"] == 1
    assert settings["stage"] == 3
    assert settings["stage_by_difficulty"]["1"] == 3
