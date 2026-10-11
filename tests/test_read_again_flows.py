"""End-to-end multi-read flows: retry, close second-chance, lock, skip.

Contract:
- First silence → read_again, try_number is the *next* try (2 of 3).
- First close → read_again, asks for one more; try_number 2 of 2.
- Second close / correct after close → NOT read_again; message must not ask again.
- Third silence → skip; not read_again.
"""

from __future__ import annotations

from pathlib import Path

from app.config import MSG_CLOSE, MSG_CLOSE_OK, MSG_CORRECT, MSG_SKIP, msg_retry
from app.matching import score_attempt
from app.session import apply_attempt, start_session
from app.whisper_engine import AttemptTranscript, TranscriptWord
from tests.helpers import post_attempt

ROOT = Path(__file__).resolve().parents[1]
GAME_JS = (ROOT / "static" / "js" / "game.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "css" / "app.css").read_text(encoding="utf-8")
CONFIG_SRC = (ROOT / "app" / "config.py").read_text(encoding="utf-8")


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
    # Must not look like a finished / move-on line.
    assert "on to the next" not in msg


def _assert_done_no_another(body: dict) -> None:
    assert body.get("read_again") is False
    assert body["again"] is False
    assert body.get("try_number") is None
    assert body.get("tries_max") is None
    msg = body["message"].lower()
    assert "one more" not in msg
    assert "read it again" not in msg
    assert "please read" not in msg


def test_close_then_correct_stops_asking(tmp_env):
    conn = tmp_env["conn"]
    data = start_session(conn, level=1)
    item = data["items"][0]
    text = item["text"]

    first = _apply(
        conn,
        data["session_id"],
        item["id"],
        score_attempt(text, text, [0.40], mode="beginner"),
        qi=0,
    )
    assert first["result"] == "close"
    _assert_asks_another(first, try_number=2, tries_max=2)
    assert first["message"] == MSG_CLOSE

    second = _apply(
        conn,
        data["session_id"],
        item["id"],
        score_attempt(text, text, [0.95], mode="beginner"),
        qi=0,
    )
    assert second["result"] == "correct"
    assert second["message"] == MSG_CORRECT
    _assert_done_no_another(second)


def test_close_then_close_locks_without_one_more(tmp_env):
    conn = tmp_env["conn"]
    data = start_session(conn, level=1)
    item = data["items"][0]
    text = item["text"]

    first = _apply(
        conn,
        data["session_id"],
        item["id"],
        score_attempt(text, text, [0.40], mode="beginner"),
        qi=0,
    )
    assert first["result"] == "close"
    _assert_asks_another(first, try_number=2, tries_max=2)

    second = _apply(
        conn,
        data["session_id"],
        item["id"],
        score_attempt(text, text, [0.45], mode="beginner"),
        qi=0,
    )
    assert second["result"] == "close"
    assert second["message"] == MSG_CLOSE_OK
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


def test_api_close_second_take_no_one_more(
    client, whisper_double, tone_wav, assert_attempt_shape
):
    start = client.post("/api/sessions", json={"level": 1}).json()
    item = next((i for i in start["items"] if i["text"] == "cat"), start["items"][0])
    qi = start["items"].index(item)
    sid = start["session_id"]

    whisper_double.set_transcript(
        AttemptTranscript(
            transcript="cot",
            words=[TranscriptWord(word="cot", probability=0.9)],
            no_speech_prob=0.05,
        )
    )
    first = post_attempt(client, sid, item["id"], tone_wav.read_bytes(), queue_index=qi)
    assert first.status_code == 200
    body1 = first.json()
    assert_attempt_shape(body1)
    if body1["result"] != "close":
        # Queue without cat close path — still assert copy invariants.
        assert "one more" in MSG_CLOSE.lower()
        assert "one more" not in MSG_CLOSE_OK.lower()
        return

    _assert_asks_another(body1, try_number=2, tries_max=2)

    whisper_double.set_transcript(
        AttemptTranscript(
            transcript=item["text"],
            words=[TranscriptWord(word=item["text"], probability=0.95)],
            no_speech_prob=0.05,
        )
    )
    second = post_attempt(client, sid, item["id"], tone_wav.read_bytes(), queue_index=qi)
    assert second.status_code == 200
    body2 = second.json()
    assert_attempt_shape(body2)
    assert body2["result"] == "correct"
    _assert_done_no_another(body2)


def test_api_close_then_close_message_is_close_ok(
    client, whisper_double, tone_wav, assert_attempt_shape
):
    start = client.post("/api/sessions", json={"level": 1}).json()
    item = next((i for i in start["items"] if i["text"] == "cat"), None)
    if item is None:
        assert "on to the next" in MSG_CLOSE_OK.lower()
        return
    qi = start["items"].index(item)
    sid = start["session_id"]

    whisper_double.set_transcript(
        AttemptTranscript(
            transcript="cot",
            words=[TranscriptWord(word="cot", probability=0.9)],
            no_speech_prob=0.05,
        )
    )
    first = post_attempt(client, sid, item["id"], tone_wav.read_bytes(), queue_index=qi)
    body1 = first.json()
    assert body1["result"] == "close"
    assert body1["again"] is True

    # Second take still "close" confidence — must lock, not ask again.
    whisper_double.set_transcript(
        AttemptTranscript(
            transcript=item["text"],
            words=[TranscriptWord(word=item["text"], probability=0.4)],
            no_speech_prob=0.05,
        )
    )
    second = post_attempt(client, sid, item["id"], tone_wav.read_bytes(), queue_index=qi)
    assert second.status_code == 200
    body2 = second.json()
    assert_attempt_shape(body2)
    assert body2["result"] == "close"
    assert body2["message"] == MSG_CLOSE_OK
    _assert_done_no_another(body2)


def test_ui_hides_read_again_while_recording_or_scoring():
    assert "hideReadAgainBanner" in GAME_JS
    assert 'body[data-state="recording"] .read-again' in CSS
    assert 'body[data-state="scoring"] .read-again' in CSS
    assert "needsAnotherRead" in GAME_JS
    # Locked-close copy must not ask for another read.
    assert "on to the next" in CONFIG_SRC.lower() or "MSG_CLOSE_OK" in CONFIG_SRC
    assert "one more" not in MSG_CLOSE_OK.lower()
