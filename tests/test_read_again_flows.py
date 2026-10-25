"""End-to-end multi-read flows: silence retry, beginner no forced close-again, strict close.

Contract (beginner default):
- Exact transcript → correct even at low Whisper confidence (no second try).
- Near-miss close → lock & move on (no second try).
- Silence → read_again with next try count; third silence → skip.

Strict mode still offers one close second-chance.
"""

from __future__ import annotations

from pathlib import Path

from app.config import MSG_CLOSE, MSG_CLOSE_OK, MSG_CORRECT, MSG_SKIP, msg_retry
from app.db import load_settings, save_settings
from app.matching import score_attempt
from app.session import apply_attempt, start_session
from app.whisper_engine import AttemptTranscript, TranscriptWord
from tests.helpers import post_attempt

ROOT = Path(__file__).resolve().parents[1]
GAME_JS = (ROOT / "static" / "js" / "game.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "css" / "app.css").read_text(encoding="utf-8")


def _apply(conn, sid, item_id, match, *, qi, silence=False):
    return apply_attempt(
        conn,
        sid,
        item_id,
        match,
        phase="read",
        is_silence_path=silence,
        queue_index=qi,
    )


def _assert_asks_another(body: dict, *, try_number: int, tries_max: int) -> None:
    assert body["read_again"] is True
    assert body["again"] is True
    assert body["try_number"] == try_number
    assert body["tries_max"] == tries_max
    msg = body["message"].lower()
    assert "read" in msg and ("again" in msg or "one more" in msg)


def _assert_done_no_another(body: dict) -> None:
    assert body.get("read_again") is False
    assert body["again"] is False
    assert body.get("try_number") is None
    assert body.get("tries_max") is None
    msg = body["message"].lower()
    assert "one more" not in msg
    assert "read it again" not in msg
    assert "please read" not in msg


def test_beginner_exact_low_conf_first_take_done(tmp_env):
    conn = tmp_env["conn"]
    data = start_session(conn, level=1)
    item = data["items"][0]
    text = item["text"]
    resp = _apply(
        conn,
        data["session_id"],
        item["id"],
        score_attempt(text, text, [0.35], mode="beginner"),
        qi=0,
    )
    assert resp["result"] == "correct"
    assert resp["message"] == MSG_CORRECT
    _assert_done_no_another(resp)


def test_beginner_close_near_miss_no_second_try(tmp_env):
    conn = tmp_env["conn"]
    data = start_session(conn, level=1)
    item = next((i for i in data["items"] if i["text"] == "cat"), data["items"][0])
    qi = data["items"].index(item)
    first = _apply(
        conn,
        data["session_id"],
        item["id"],
        score_attempt(item["text"], "cot", [0.90], mode="beginner"),
        qi=qi,
    )
    assert first["result"] == "close"
    assert first["message"] == MSG_CLOSE_OK
    _assert_done_no_another(first)


def test_strict_exact_low_confidence_accepts_without_read_again(tmp_env):
    """Exact transcript must pass even when Whisper probs are soft."""
    conn = tmp_env["conn"]
    save_settings({**load_settings(), "mode": "strict", "auto_strict": False})
    data = start_session(conn, level=1)
    assert data["mode"] == "strict"
    item = data["items"][0]
    text = item["text"]

    first = _apply(
        conn,
        data["session_id"],
        item["id"],
        score_attempt(text, text, [0.40], mode="strict"),
        qi=0,
    )
    assert first["result"] == "correct"
    assert first["message"] == MSG_CORRECT
    _assert_done_no_another(first)


def test_strict_miss_then_correct_second_chance(tmp_env):
    conn = tmp_env["conn"]
    save_settings({**load_settings(), "mode": "strict", "auto_strict": False})
    data = start_session(conn, level=1)
    item = data["items"][0]
    qi = 0
    text = item["text"]

    first = _apply(
        conn,
        data["session_id"],
        item["id"],
        score_attempt(text, "zzzznotaword", [0.9], mode="strict"),
        qi=qi,
    )
    assert first["result"] == "missed"
    _assert_asks_another(first, try_number=2, tries_max=2)

    second = _apply(
        conn,
        data["session_id"],
        item["id"],
        score_attempt(text, text, [0.40], mode="strict"),
        qi=qi,
    )
    assert second["result"] == "correct"
    _assert_done_no_another(second)

def test_silence_retry_then_correct_clears_read_again(tmp_env):
    conn = tmp_env["conn"]
    data = start_session(conn, level=1)
    item = data["items"][0]
    text = item["text"]
    sid = data["session_id"]

    retry = _apply(
        conn,
        sid,
        item["id"],
        score_attempt(text, "", mode="beginner", force_retry=True),
        qi=0,
        silence=True,
    )
    assert retry["result"] == "retry"
    _assert_asks_another(retry, try_number=2, tries_max=3)
    assert retry["message"] == msg_retry(2, 3)

    ok = _apply(
        conn,
        sid,
        item["id"],
        score_attempt(text, text, [0.95], mode="beginner"),
        qi=0,
    )
    assert ok["result"] == "correct"
    _assert_done_no_another(ok)


def test_three_silences_skip_does_not_ask_again(tmp_env):
    conn = tmp_env["conn"]
    data = start_session(conn, level=1)
    item = data["items"][0]
    text = item["text"]
    sid = data["session_id"]

    r1 = _apply(
        conn,
        sid,
        item["id"],
        score_attempt(text, "", mode="beginner", force_retry=True),
        qi=0,
        silence=True,
    )
    _assert_asks_another(r1, try_number=2, tries_max=3)

    r2 = _apply(
        conn,
        sid,
        item["id"],
        score_attempt(text, "", mode="beginner", force_retry=True),
        qi=0,
        silence=True,
    )
    _assert_asks_another(r2, try_number=3, tries_max=3)

    skip = _apply(
        conn,
        sid,
        item["id"],
        score_attempt(text, "", mode="beginner", force_retry=True),
        qi=0,
        silence=True,
    )
    assert skip["result"] == "skipped"
    assert skip["message"] == MSG_SKIP
    _assert_done_no_another(skip)


def test_api_beginner_exact_no_second_try(
    client, whisper_double, tone_wav, assert_attempt_shape
):
    start = client.post("/api/sessions", json={"level": 1}).json()
    item = start["items"][0]
    whisper_double.set_transcript(
        AttemptTranscript(
            transcript=item["text"],
            words=[TranscriptWord(word=item["text"], probability=0.35)],
            no_speech_prob=0.05,
        )
    )
    res = post_attempt(
        client, start["session_id"], item["id"], tone_wav.read_bytes(), queue_index=0
    )
    assert res.status_code == 200
    body = res.json()
    assert_attempt_shape(body)
    assert body["result"] == "correct"
    _assert_done_no_another(body)


def test_api_beginner_close_no_second_try(
    client, whisper_double, tone_wav, assert_attempt_shape
):
    start = client.post("/api/sessions", json={"level": 1}).json()
    item = next((i for i in start["items"] if i["text"] == "cat"), None)
    if item is None:
        assert "one more" not in MSG_CLOSE_OK.lower()
        return
    qi = start["items"].index(item)
    whisper_double.set_transcript(
        AttemptTranscript(
            transcript="cot",
            words=[TranscriptWord(word="cot", probability=0.9)],
            no_speech_prob=0.05,
        )
    )
    res = post_attempt(
        client, start["session_id"], item["id"], tone_wav.read_bytes(), queue_index=qi
    )
    body = res.json()
    assert_attempt_shape(body)
    assert body["result"] == "close"
    assert body["message"] == MSG_CLOSE_OK
    _assert_done_no_another(body)


def test_ui_hides_read_again_while_recording_or_scoring():
    assert "hideReadAgainBanner" in GAME_JS
    assert 'body[data-state="recording"] .read-again' in CSS
    assert 'body[data-state="scoring"] .read-again' in CSS
    assert "needsAnotherRead" in GAME_JS
    assert "one more" not in MSG_CLOSE_OK.lower()
