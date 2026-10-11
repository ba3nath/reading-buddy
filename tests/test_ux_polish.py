"""UX / mascot polish presence checks (no browser)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "css" / "app.css").read_text(encoding="utf-8")
JS = (ROOT / "static" / "js" / "game.js").read_text(encoding="utf-8")


def test_home_has_large_buddy_and_illustrated_tiles():
    assert 'data-home-buddy-slot' in HTML
    assert 'class="buddy-tile"' in HTML
    assert 'data-buddy-choice="cat"' in HTML
    assert 'data-buddy-choice="krishna"' in HTML
    assert 'data-buddy-choice="mouse"' in HTML
    assert 'src="/static/mascots/cat.svg"' in HTML
    assert 'src="/static/mascots/mouse.svg"' in HTML
    assert "mickey" not in HTML.lower()


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
