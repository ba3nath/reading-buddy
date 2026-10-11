"""Coverage for kid-facing screen flows (static wiring + API-backed paths).

These tests pin the UI contract in ``static/index.html`` / ``game.js`` so each
on-screen flow stays wired. Backend scoring/queue behavior is covered elsewhere;
this file is about what the child sees and taps.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "static" / "js" / "game.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "css" / "app.css").read_text(encoding="utf-8")
RECORD_JS = (ROOT / "static" / "js" / "record.js").read_text(encoding="utf-8")


def _fn(name: str) -> str:
    """Return the source of ``function name`` / ``async function name`` until the next top-level fn."""
    for prefix in (f"async function {name}(", f"function {name}("):
        if prefix in JS:
            start = JS.index(prefix)
            break
    else:
        raise AssertionError(f"missing function {name}")
    rest = JS[start:]
    # Next function at column 0 (game.js uses that style).
    nxt = rest.find("\nfunction ", 1)
    nxt_async = rest.find("\nasync function ", 1)
    ends = [i for i in (nxt, nxt_async) if i != -1]
    end = min(ends) if ends else len(rest)
    return rest[:end]


# ---------------------------------------------------------------------------
# Flow matrix (screen → expected coverage)
# ---------------------------------------------------------------------------

SCREEN_FLOWS = (
    "boot",
    "home_buddy_pick",
    "home_start",
    "home_difficulty",
    "home_pause_continue",
    "listen_idle_mic",
    "recording_done",
    "result_advance",
    "read_again",
    "rhymes_sing_along",
    "session_end",
    "replay",
    "play_again",
)


def test_screen_flow_matrix_is_documented():
    """Keep an explicit checklist of kid-facing flows under test."""
    assert len(SCREEN_FLOWS) >= 12
    # Every flow name below must have a matching test_* function in this module.
    import tests.test_screen_flows as mod

    for flow in SCREEN_FLOWS:
        assert hasattr(mod, f"test_flow_{flow}"), f"missing test_flow_{flow}"


def test_flow_boot():
    """Boot shows Getting ready…; failure flips to boot-error view."""
    assert 'data-state="boot"' in HTML
    assert "Getting ready…" in HTML
    assert 'data-view="boot-error"' in HTML
    assert "data-boot-error" in HTML
    boot = _fn("boot")
    assert "setState(\"home\")" in boot or "setState('home')" in boot
    assert "boot-error" in boot
    assert "/api/health" in boot


def test_flow_home_buddy_pick():
    """Home: pick Krishna/Unicorn; choice persists via settings PUT."""
    assert 'data-buddy-choice="krishna"' in HTML
    assert 'data-buddy-choice="unicorn"' in HTML
    assert 'data-buddy-choice="cat"' not in HTML
    choose = _fn("chooseBuddy")
    assert "/api/parent/settings" in choose
    assert "buddy" in choose
    assert "loadBuddySvg" in choose
    wire = _fn("wire")
    assert "data-buddy-choice" in wire
    assert "chooseBuddy" in wire


def test_flow_home_start():
    """Primary Start uses saved difficulty (no level-pick); hides home view."""
    assert 'class="btn primary" data-start>Start</button>' in HTML
    assert 'class="btn primary" data-start data-level-pick' not in HTML
    start = _fn("startSession")
    assert 'api("/api/sessions"' in start or "api('/api/sessions'" in start
    assert "state.paused = false" in start
    assert "difficulty_label" in start
    assert "difficultyLabel" in start
    assert "showListen()" in start
    assert "syncHomeControls()" in start
    wire = _fn("wire")
    assert "data-start" in wire
    assert "startSession(level)" in wire


def test_flow_home_difficulty():
    """Pick a difficulty exposes Words / Phrases / Rhymes / Stories."""
    assert "Pick a difficulty" in HTML
    for n, label in (
        (1, "Words"),
        (2, "Phrases"),
        (3, "Rhymes"),
        (4, "Stories"),
    ):
        assert f'data-level-pick="{n}">{label}</button>' in HTML
    # Wire passes numeric pick into startSession.
    wire = _fn("wire")
    assert "dataset.levelPick" in wire
    assert "Number(raw)" in wire


def test_flow_home_pause_continue():
    """Mid-session Home·pause → Continue (or Start fresh) without a new session."""
    assert "Home · pause" in HTML
    assert "data-go-home" in HTML
    assert "data-continue" in HTML
    assert "data-pause-row" in HTML
    assert "data-pause-hint" in HTML

    sync = _fn("syncHomeControls")
    assert "Start fresh" in sync
    assert 'textContent =\n      state.paused && sessionInPlay() ? "Start fresh" : "Start"' in sync or (
        '"Start fresh"' in sync and '"Start"' in sync
    )
    assert "goHome.hidden" in sync
    assert "pauseRow.hidden" in sync

    pause = _fn("pauseToHome")
    assert "discard()" in pause
    assert "stopClip()" in pause
    assert "state.paused = true" in pause
    assert "Paused on" in pause
    assert "setState(\"home\")" in pause or "setState('home')" in pause

    cont = _fn("continueSession")
    assert "state.paused = false" in cont
    assert "difficultyLabel" in cont
    assert "showListen()" in cont
    assert "syncHomeControls()" in cont

    # Discard helper exists so half-said words are not scored on pause.
    assert "discard(" in RECORD_JS

    wire = _fn("wire")
    assert "pauseToHome()" in wire
    assert "continueSession()" in wire
    # Continue UI sits above Start so resume is the first action when paused.
    assert HTML.index("data-continue") < HTML.index(
        'class="btn primary" data-start>Start</button>'
    )


def test_flow_listen_idle_mic():
    """Listen clip → idle → Tap to read enables the mic."""
    show = _fn("showListen")
    assert "stopClip()" in show
    assert 'setState("listen")' in show
    assert "playClip(" in show
    assert "enterIdle()" in show
    assert show.index("stopClip()") < show.index("setWord(")
    assert show.count("playClip(") == 1

    idle = _fn("enterIdle")
    assert 'setState("idle")' in idle
    assert "Tap to read" in idle
    assert "setMicEnabled(true)" in idle

    assert 'data-mic' in HTML
    assert 'data-mic-mode="ready"' in HTML


def test_flow_recording_done():
    """Tap to read arms recording; second tap (Tap when done) finishes the take."""
    mic = _fn("onMicTap")
    assert 'state.id === "recording"' in mic
    assert "recorder.stop()" in mic or "state.recorder.stop()" in mic
    assert 'setState("recording")' in mic
    assert "Tap when done" in mic
    assert "I hear you" in mic
    assert "hideReadAgainBanner()" in mic
    assert "onRecordComplete" in mic

    done = _fn("onRecordComplete")
    assert 'setState("scoring")' in done
    assert "Listening…" in done
    assert "/api/sessions/" in done or "api(`/api/sessions/" in done

    assert '.mic[data-mic-mode="done"]' in CSS
    assert "var(--coral" in CSS
    assert "var(--meadow" in CSS


def test_flow_result_advance():
    """Scored takes celebrate/advance; locking results never re-play audio."""
    handle = _fn("handleAttempt")
    assert "result-correct" in handle
    assert "result-miss" in handle
    assert "result-retry" in handle
    assert "result-skip" in handle
    assert "celebrateCorrectRead" not in handle or "setTimeout(() => advance()" in handle
    assert "playClip(" not in handle
    assert "advance()" in handle

    adv = _fn("advance")
    assert "finishSession()" in adv
    assert "showListen()" in adv
    assert 'state.phase === "replay"' in adv

    assert "data-success-fx" in HTML
    assert "popSuccessFx" in JS
    assert "data-progress-dots" in HTML
    assert "setProgress" in JS


def test_flow_read_again():
    """Retry / strict-close show Read again; recording hides the banner."""
    assert "data-read-again" in HTML
    assert "setReadAgain" in JS
    assert "needsAnotherRead" in JS
    assert "Tap to read again" in JS
    handle = _fn("handleAttempt")
    assert "setReadAgain" in handle
    assert "result-retry" in handle
    assert "result-close" in handle
    assert "hideReadAgainBanner" in _fn("onMicTap")
    assert 'body[data-state="recording"] .read-again' in CSS


def test_flow_rhymes_sing_along():
    """Rhymes (difficulty 3): sing-along message; one clip per line on screen."""
    rhyme = _fn("isRhymeSingAlongItem")
    assert "state.level === 3" in rhyme
    assert 'kind === "line"' in rhyme
    msg = _fn("rhymeListenMessage")
    assert "Listen and sing along…" in msg
    assert "maybeSingAlongThen" not in JS
    show = _fn("showListen")
    assert "rhymeListenMessage" in show


def test_flow_session_end():
    """End screen shows stars, optional garden/quest, and Play again."""
    assert 'data-view="end"' in HTML
    assert "data-end-stars" in HTML
    assert "data-play-again" in HTML
    assert "data-garden-end" in HTML
    assert "data-end-hint" in HTML
    finish = _fn("finishSession")
    assert "/complete" in finish
    assert 'setState("session-end")' in finish
    assert "data.replay" in finish
    assert "data-end-stars" in finish


def test_flow_replay():
    """After complete, missed words enter replay phase then return to end."""
    show = _fn("showReplayItem")
    assert 'setState("session-replay")' in show
    assert "playClip(" in show
    assert "Tap to read" in show
    fin = _fn("finishReplay")
    assert 'setState("session-end")' in fin
    assert 'state.phase = "read"' in fin
    adv = _fn("advance")
    assert "finishReplay()" in adv


def test_flow_play_again():
    """Play again clears session + pause flag and returns home."""
    wire = _fn("wire")
    # Extract the play-again click handler body.
    assert "data-play-again" in wire
    assert "state.sessionId = null" in wire
    assert "state.paused = false" in wire
    assert 'setState("home")' in wire
    assert 'data-level"]).hidden = true' in wire or '("[data-level]").hidden = true' in wire


# ---------------------------------------------------------------------------
# API-backed paths that feed the screen
# ---------------------------------------------------------------------------


def test_api_start_feeds_difficulty_badge(tmp_env, client):
    """Session start payload is what the badge / progress UI consume."""
    res = client.post("/api/sessions", json={"level": 2})
    assert res.status_code == 200
    body = res.json()
    assert body["difficulty_label"] == "Phrases"
    assert body["level"] == 2
    assert len(body["items"]) in (5, 10)
    assert all("slug" in i and "text" in i for i in body["items"])


def test_api_complete_feeds_end_and_replay(client, whisper_double, tone_wav, tmp_env):
    """Complete payload supplies end-screen stars + optional replay list."""
    from app.db import load_settings, save_settings
    from app.whisper_engine import AttemptTranscript, TranscriptWord
    from tests.helpers import post_attempt

    save_settings({**load_settings(), "session_length": 5, "level": 1})
    start = client.post("/api/sessions", json={"level": 1}).json()
    sid = start["session_id"]
    # Miss the first word so replay is non-empty; correct the rest.
    first = start["items"][0]
    whisper_double.set_transcript(
        AttemptTranscript(
            transcript="zzzznotaword",
            words=[TranscriptWord(word="zzzznotaword", probability=0.95)],
            no_speech_prob=0.05,
        )
    )
    post_attempt(client, sid, first["id"], tone_wav.read_bytes(), queue_index=0)
    for qi, item in enumerate(start["items"][1:], start=1):
        whisper_double.set_transcript(
            AttemptTranscript(
                transcript=item["text"],
                words=[TranscriptWord(word=w, probability=0.95) for w in item["text"].split()],
                no_speech_prob=0.05,
            )
        )
        post_attempt(client, sid, item["id"], tone_wav.read_bytes(), queue_index=qi)
    done = client.post(f"/api/sessions/{sid}/complete").json()
    assert "stars" in done
    assert "replay" in done
    assert "garden" in done or "play" in done or "home" in done
    assert isinstance(done["replay"], list)


def test_home_page_serves_flow_hooks(client):
    """Live HTML includes the hooks the screen-flow tests pin."""
    res = client.get("/")
    assert res.status_code == 200
    page = res.text
    for hook in (
        "data-go-home",
        "data-continue",
        "data-start",
        "data-mic",
        "data-play-again",
        "Pick a difficulty",
        "/static/js/game.js",
    ):
        assert hook in page
