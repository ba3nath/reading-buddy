"""UX / mascot polish presence checks (no browser)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "css" / "app.css").read_text(encoding="utf-8")
JS = (ROOT / "static" / "js" / "game.js").read_text(encoding="utf-8")


def test_home_has_large_buddy_and_illustrated_tiles():
    assert 'data-home-buddy-slot' in HTML
    assert "buddy-tile" in HTML
    assert 'data-buddy-choice="cat"' in HTML
    assert 'data-buddy-choice="krishna"' in HTML
    assert 'data-buddy-choice="unicorn"' in HTML
    assert 'src="/static/mascots/cat.svg"' in HTML
    assert 'src="/static/mascots/unicorn.svg"' in HTML
    assert "mickey" not in HTML.lower()


def test_home_greeting_does_not_sit_in_fixed_square():
    """Greeting must not share the mascot's fixed square height (was overlapping tiles)."""
    assert "data-home-greeting" in HTML
    assert "home-buddy-wave" in CSS
    # Container grows with text; only the slot is the square mascot frame.
    assert "height: auto" in CSS
    assert ".home-buddy-slot" in CSS or ".home-buddy .buddy-slot" in CSS
    assert "text-wrap: balance" in CSS or "line-height" in CSS


def test_home_landing_is_colorful():
    assert 'class="home-sky"' in HTML or "home-sky" in HTML
    assert "home-blob-sun" in HTML
    assert "buddy-tile-cat" in HTML
    assert "buddy-tile-krishna" in HTML
    assert "buddy-tile-unicorn" in HTML
    assert "--sky:" in CSS
    assert "--coral:" in CSS
    assert "blob-drift" in CSS
    assert "brand-glow" in CSS or "background-clip: text" in CSS


def test_home_brand_is_not_clipped():
    """Tall home content + justify center was shearing the Reading Buddy title."""
    assert "home-brand" in HTML
    assert "safe center" in CSS
    assert "safe-area-inset-top" in CSS
    assert "line-height: 1.2" in CSS
    assert "background-position" in CSS
    assert "filter: saturate" not in CSS
    assert "@media (max-height: 700px)" in CSS


def test_home_has_gamify_quest_hud():
    assert "data-play-hud" in HTML
    assert "Today's quest" in HTML
    assert "data-streak" in HTML
    assert "data-badges" in HTML


def test_mic_hear_you_feedback_no_timer():
    assert "mic-particles" in HTML
    assert "I hear you" in JS
    assert "countdown" not in CSS.lower()
    assert "time's up" not in JS.lower()
    assert "buzzer" not in JS.lower()


def test_celebration_and_encourage_motion():
    assert "star-burst" in HTML or "data-star-burst" in HTML
    assert "popStarBurst" in JS
    assert "buddy-encourage" in CSS
    assert "greeting-bob" in CSS
    assert "result-correct" in JS
    assert 'gardenStageName' in JS or "garden grew" in JS.lower() or "New garden" in JS


def test_start_primary_and_more_levels():
    assert 'class="btn primary" data-start>Start</button>' in HTML
    assert "more-levels" in HTML
    assert 'data-level-pick="2"' in HTML
    assert 'data-level-pick="1"' not in HTML


def test_read_again_indicator_when_retry_needed():
    assert 'data-read-again' in HTML
    assert "setReadAgain" in JS
    assert "hideReadAgainBanner" in JS
    assert "needsAnotherRead" in JS
    assert "Tap to read again" in JS
    assert "read it again" in JS.lower() or "read again" in JS.lower()
    assert ".read-again" in CSS
    assert 'body[data-state="recording"] .read-again' in CSS
