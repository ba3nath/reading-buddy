"""Four difficulty tiers (words / phrases / rhymes / stories) and 5|10 sessions."""

from __future__ import annotations

from app.adaptive import _snap_uniform_length, build_adaptive_queue
from app.config import (
    DIFFICULTY_TIERS,
    MAX_DIFFICULTY,
    content_levels_for_difficulty,
    difficulty_label,
    migrate_legacy_level_to_difficulty,
    normalize_difficulty,
    normalize_session_length,
)
from app.db import load_settings, save_settings
from app.session import start_session


def test_difficulty_tier_map():
    assert MAX_DIFFICULTY == 4
    assert content_levels_for_difficulty(1) == (1, 2, 3)
    assert content_levels_for_difficulty(2) == (4,)
    assert content_levels_for_difficulty(3) == (6, 7)
    assert content_levels_for_difficulty(4) == (5,)
    assert difficulty_label(1) == "Words"
    assert difficulty_label(2) == "Phrases"
    assert difficulty_label(3) == "Rhymes"
    assert difficulty_label(4) == "Stories"
    assert set(DIFFICULTY_TIERS) == {1, 2, 3, 4}


def test_migrate_legacy_content_levels():
    assert migrate_legacy_level_to_difficulty(1) == 1
    assert migrate_legacy_level_to_difficulty(2) == 1
    assert migrate_legacy_level_to_difficulty(3) == 1
    assert migrate_legacy_level_to_difficulty(4) == 2
    assert migrate_legacy_level_to_difficulty(5) == 4
    assert migrate_legacy_level_to_difficulty(6) == 3
    assert migrate_legacy_level_to_difficulty(7) == 3
    assert normalize_difficulty(7) == 3
    assert normalize_difficulty(0) == 1
    assert normalize_difficulty("phrases") == 1


def test_snap_uniform_length_never_six_to_nine():
    class Row(dict):
        pass

    rows = [Row(id=i) for i in range(8)]
    snapped = _snap_uniform_length(rows, 10)
    assert len(snapped) == 5
    assert len(_snap_uniform_length(rows[:3], 10)) == 3
    assert len(_snap_uniform_length(rows + [Row(id=8), Row(id=9)], 10)) == 10
    assert len(_snap_uniform_length(rows[:5], 5)) == 5


def test_queue_length_always_five_or_ten_when_pool_allows(tmp_env):
    conn = tmp_env["conn"]
    for difficulty in (1, 2, 3, 4):
        for length in (5, 10):
            queue = build_adaptive_queue(conn, level=difficulty, length=length)
            assert len(queue) == length
            assert len({row["id"] for row in queue}) == length
            levels = {int(row["level"]) for row in queue}
            assert levels <= set(content_levels_for_difficulty(difficulty))


def test_settings_migrate_legacy_level_once(tmp_env):
    save_settings(
        {
            **load_settings(),
            "level": 6,
            "difficulty_migrated": False,
        }
    )
    settings = load_settings()
    assert settings["level"] == 3
    assert settings["difficulty_migrated"] is True
    # Second load keeps the migrated tier (does not re-map 3→words).
    again = load_settings()
    assert again["level"] == 3


def test_parent_settings_clamp_difficulty(client, tmp_env):
    body = client.put("/api/parent/settings", json={"level": 7}).json()
    assert body["level"] == 3
    body = client.put("/api/parent/settings", json={"level": 4}).json()
    assert body["level"] == 4
    parent = client.get("/parent").text
    assert "Words" in parent
    assert "Phrases" in parent
    assert "Rhymes" in parent
    assert "Stories" in parent
    assert 'max="7"' not in parent


def test_session_start_reports_difficulty_label(tmp_env):
    conn = tmp_env["conn"]
    save_settings({**load_settings(), "session_length": 5, "level": 2})
    data = start_session(conn, level=None)
    assert data["level"] == 2
    assert data["difficulty"] == 2
    assert data["difficulty_label"] == "Phrases"
    assert len(data["items"]) == 5
    assert data["planned_count"] == 5
    assert normalize_session_length(8) == 10


def test_ui_progress_uses_planned_count_not_grown_queue():
    """Progress copy must never say Word N of 11 — only 5 or 10."""
    from pathlib import Path

    js = Path("static/js/game.js").read_text(encoding="utf-8")
    assert "plannedCount" in js
    assert "planned_count" in js
    prog = js.split("function setProgress()")[1].split("\nfunction ")[0]
    assert "state.plannedCount" in prog
    assert "of 11" not in prog
    # Client refuses to grow the queue from a legacy reinsert payload.
    apply = js.split("function applyReinsert(")[1].split("\nfunction ")[0]
    assert "result.reinsert = null" in apply


def test_home_ui_exposes_four_difficulties():
    from pathlib import Path

    html = Path("static/index.html").read_text(encoding="utf-8")
    js = Path("static/js/game.js").read_text(encoding="utf-8")
    assert "Pick a difficulty" in html
    for label, n in (("Words", 1), ("Phrases", 2), ("Rhymes", 3), ("Stories", 4)):
        assert f'data-difficulty="{n}"' in html
        assert f">{label}</p>" in html
        for stage in range(1, 6):
            assert f'data-level-pick="{n}" data-stage-pick="{stage}"' in html
    assert "difficulty_label" in js
    assert "difficultyLabel" in js
