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
    assert 'data-buddy-choice="cat"' not in HTML
    assert 'data-buddy-choice="krishna"' in HTML
    assert 'data-buddy-choice="unicorn"' in HTML
    assert 'src="/static/mascots/cat.svg"' not in HTML
    assert 'src="/static/mascots/krishna.svg"' in HTML
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
    assert "buddy-tile-cat" not in HTML
    assert "buddy-tile-krishna" in HTML
    assert "buddy-tile-unicorn" in HTML
    assert "--sky:" in CSS
    assert "--coral:" in CSS
    assert "blob-drift" in CSS
    assert "brand-glow" in CSS or "background-clip: text" in CSS


def test_home_lede_is_playful_without_timer_copy():
    assert "Listen close, say it loud, stack those stars!" in HTML
    assert "No timers" not in HTML
    assert "lost points" not in HTML
    assert "Read words aloud" not in HTML


def test_buddies_are_krishna_and_unicorn_only():
    assert 'BUDDIES = ["krishna", "unicorn"]' in JS
    assert '"cat"' not in JS.split("const BUDDIES")[1].split(";")[0]
    assert "buddy-tile-cat" not in CSS
    assert (ROOT / "static" / "mascots" / "cat.svg").exists() is False
    assert (ROOT / "static" / "mascots" / "krishna.svg").exists()
    assert (ROOT / "static" / "mascots" / "unicorn.svg").exists()


def test_home_brand_is_not_clipped():
    """Tall home content + justify center was shearing the Reading Buddy title."""
    assert "home-brand" in HTML
    assert "safe center" in CSS
    assert "safe-area-inset-top" in CSS
    assert "line-height: 1.2" in CSS
    assert "background-position" in CSS
    assert "filter: saturate" not in CSS
    assert "@media (max-height: 700px)" in CSS


def test_home_start_comes_before_quest_hud():
    """Start must sit above the quest block so common viewports don't miss it."""
    start_at = HTML.index('class="btn primary" data-start>Start</button>')
    quest_at = HTML.index("Today's quest")
    buddy_at = HTML.index("data-buddy-pick")
    assert buddy_at < start_at < quest_at


def test_phrase_score_clears_before_next_listen():
    """Multi-word 'N of M words' is result feedback only — hide it on the next screen."""
    assert "phrase-score" in HTML
    assert "of" in HTML and "words" in HTML
    assert "clearPhraseScore" in JS
    show = JS.split("async function showListen()")[1].split("async function ")[0]
    assert "clearPhraseScore()" in show
    assert show.index("clearPhraseScore()") < show.index("setWord(")
    # Replay path also clears so end-of-session tries don't show old phrase tallies.
    replay = JS.split("async function showReplayItem()")[1].split("async function ")[0]
    assert "clearPhraseScore()" in replay


def test_home_pause_and_continue_controls():
    """Kids can leave mid-session for Home and Continue without losing progress."""
    assert "data-go-home" in HTML
    assert "Home · pause" in HTML
    assert "data-continue" in HTML
    assert "data-pause-row" in HTML
    assert "pauseToHome" in JS
    assert "continueSession" in JS
    assert "syncHomeControls" in JS
    assert "state.paused" in JS or "paused: false" in JS
    assert "discard()" in (ROOT / "static" / "js" / "record.js").read_text(
        encoding="utf-8"
    )
    assert ".btn-home" in CSS
    assert "[data-continue]" in CSS or "data-continue" in CSS
    # Continue sits above Start fresh so paused kids see resume first.
    cont_at = HTML.index("data-continue")
    start_at = HTML.index('class="btn primary" data-start>Start</button>')
    assert cont_at < start_at


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


def test_mic_ready_and_done_are_visually_distinct():
    """Tap to read (go) vs Tap when done (stop) must not share the same color language."""
    assert 'data-mic-mode="ready"' in HTML
    assert 'dataset.micMode = done ? "done" : "ready"' in JS
    assert "Tap when done" in JS
    assert "Tap to read" in JS
    # Ready = meadow green; done/recording = coral.
    assert "--meadow" in CSS
    assert "body[data-state=\"recording\"] .mic" in CSS or "body[data-state='recording'] .mic" in CSS
    assert '.mic[data-mic-mode="done"]' in CSS
    assert "var(--meadow" in CSS
    assert "var(--coral" in CSS
    # Recording pulse must use coral, not the ready green.
    assert "mic-pulse-done" in CSS
    assert "rgba(240, 106, 69" in CSS
    ready_block = CSS.split(".mic {")[1].split("body[data-state=")[0]
    assert "var(--meadow)" in ready_block or "var(--meadow-deep)" in ready_block
    assert "var(--coral)" not in ready_block.split(".mic:disabled")[0]


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
    assert "Pick a difficulty" in HTML
    assert "data-stage-pick" in HTML
    # Primary Start has no level pick — uses saved difficulty.
    assert 'class="btn primary" data-start data-level-pick' not in HTML


def test_read_again_indicator_when_retry_needed():
    assert 'data-read-again' in HTML
    assert "setReadAgain" in JS
    assert "hideReadAgainBanner" in JS
    assert "needsAnotherRead" in JS
    assert "Tap to read again" in JS
    assert "read it again" in JS.lower() or "read again" in JS.lower()
    assert ".read-again" in CSS
    assert 'body[data-state="recording"] .read-again' in CSS


def test_level7_does_not_stack_previous_and_current_audio():
    """L6–7 must not replay the finished line before the next line's listen.

    Stacking sing-along(prev) + showListen(current) made the next screen hear
    both the previous sentence and the current one.
    """
    assert "maybeSingAlongThen" not in JS
    assert "rhymeListenMessage" in JS
    assert "Listen and sing along…" in JS
    assert "isRhymeSingAlongItem" in JS
    assert "state.level === 3" in JS
    # Locking results advance directly — only the new screen's showListen plays.
    assert "setTimeout(() => advance(), 1400)" in JS
    assert "maybeSingAlongThen(advance)" not in JS
    assert "celebrateCorrectRead" in JS
    assert "popSuccessFx" in JS
    assert "SUCCESS_FX_KINDS" in JS
    for kind in ("glitter", "rainbow", "chocolate", "applause", "stars"):
        assert kind in JS
    assert 'data-success-fx' in HTML
    assert "success-fx" in CSS
    # showListen stops any prior clip before swapping text + playing the new slug.
    show = JS.split("async function showListen()")[1].split("async function ")[0]
    assert "stopClip()" in show
    assert "playItemClip(item)" in show
    assert show.index("stopClip()") < show.index("setWord(")
    assert show.count("playItemClip(") == 1

    # After a scored take, handleAttempt must not play any clip before advancing.
    handle = JS.split("function handleAttempt(result)")[1].split("\nfunction advance(")[0]
    assert "playClip(" not in handle
    assert "advance()" in handle
    assert "Sing along…" not in handle


def test_level7_session_lines_have_unique_audio_slugs(tmp_env, client):
    """Rhymes difficulty: each line on screen maps to its own slug wav."""
    from app.session import start_session

    conn = tmp_env["conn"]
    data = start_session(conn, level=3)
    assert data["level"] == 3
    assert data["difficulty_label"] == "Rhymes"
    items = data["items"]
    assert len(items) >= 2
    assert all(i.get("kind") == "line" for i in items)
    slugs = [i["slug"] for i in items]
    assert len(slugs) == len(set(slugs))
    # Advancing must request a different clip URL than the line just left.
    assert slugs[0] != slugs[1]
    for slug in slugs[:3]:
        res = client.get(f"/api/audio/{slug}")
        assert res.status_code == 200, slug
        assert res.headers["content-type"].startswith("audio/")
