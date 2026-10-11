"""Quest / streak / badge play stats (kindness-first gamification)."""

from __future__ import annotations

from pathlib import Path

from app.db import load_settings
from app.matching import score_attempt
from app.parent import bump_play_stats, compute_badges, play_summary
from app.session import apply_attempt, complete_session, start_session

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "static" / "js" / "game.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "css" / "app.css").read_text(encoding="utf-8")


def _apply(conn, sid, item_id, match, *, qi=0):
    return apply_attempt(
        conn, sid, item_id, match, phase="read", queue_index=qi
    )


def test_play_summary_quest_incomplete_by_default(tmp_env):
    summary = play_summary()
    assert summary["quest_complete"] is False
    assert summary["lifetime_stars"] == 0
    assert summary["day_streak"] == 0
    assert summary["quest_label"]


def test_bump_play_stats_starts_streak_and_badges(tmp_env):
    settings = load_settings()
    play = bump_play_stats(settings, stars_earned=3)
    assert play["lifetime_stars"] == 3
    assert play["day_streak"] == 1
    assert play["quest_complete"] is True
    assert any(b["id"] == "first_star" for b in play["new_badges"])
    again = bump_play_stats(load_settings(), stars_earned=2)
    assert again["lifetime_stars"] == 5
    assert again["day_streak"] == 1  # same day — no double count


def test_complete_session_returns_play_payload(tmp_env):
    conn = tmp_env["conn"]
    data = start_session(conn, level=1)
    item = data["items"][0]
    _apply(
        conn,
        data["session_id"],
        item["id"],
        score_attempt(item["text"], item["text"], [0.95], mode="beginner"),
        qi=0,
    )
    done = complete_session(conn, data["session_id"])
    assert "play" in done
    assert done["play"]["quest_complete"] is True
    assert done["play"]["lifetime_stars"] >= 1
    assert done["play"]["day_streak"] >= 1
    assert "home" in done


def test_settings_includes_play_block(client):
    res = client.get("/api/parent/settings")
    assert res.status_code == 200
    body = res.json()
    assert "play" in body
    assert "quest_label" in body["play"]
    assert "badges" in body["play"]


def test_ui_has_quest_combo_and_badges():
    assert "data-play-hud" in HTML
    assert "data-quest" in HTML
    assert "data-combo" in HTML
    assert "Sunny streak" in JS
    assert "renderPlayHud" in JS
    assert "popStarFloat" in JS
    assert ".play-hud" in CSS
    assert ".combo" in CSS


def test_badge_predicates():
    badges = compute_badges(
        {
            "lifetime_stars": 10,
            "garden_growth": 3,
            "day_streak": 3,
        }
    )
    ids = {b["id"] for b in badges}
    assert "first_star" in ids
    assert "star_10" in ids
    assert "garden_flower" in ids
    assert "streak_3" in ids
