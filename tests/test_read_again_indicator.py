"""API + copy for when another read is required (silence / strict close)."""

from __future__ import annotations

from app.config import MSG_CLOSE, MSG_CLOSE_OK, msg_retry
from app.whisper_engine import AttemptTranscript, TranscriptWord
from tests.helpers import post_attempt


def test_msg_retry_includes_next_try_count():
    assert "read it again" in msg_retry(2, 3).lower()
    assert "try 2 of 3" in msg_retry(2, 3)
    assert "one more" not in MSG_CLOSE_OK.lower()
    assert "on to the next" in MSG_CLOSE_OK.lower()


def test_retry_payload_flags_read_again(client, assert_attempt_shape):
    start = client.post("/api/sessions", json={"level": 1}).json()
    item = start["items"][0]
    res = post_attempt(client, start["session_id"], item["id"], b"", queue_index=0)
    assert res.status_code == 200
    body = res.json()
    assert_attempt_shape(body, words_total=1)
    assert body["read_again"] is True
    assert body["try_number"] == 2
    assert body["tries_max"] == 3
    assert body["message"] == msg_retry(2, 3)


def test_beginner_close_does_not_ask_again(
    client, whisper_double, tone_wav, assert_attempt_shape
):
    start = client.post("/api/sessions", json={"level": 1}).json()
    item = next((i for i in start["items"] if i["text"] == "cat"), None)
    if item is None:
        assert "one more time" in MSG_CLOSE.lower()
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
        client,
        start["session_id"],
        item["id"],
        tone_wav.read_bytes(),
        queue_index=qi,
    )
    assert res.status_code == 200
    body = res.json()
    assert_attempt_shape(body)
    assert body["result"] == "close"
    assert body["again"] is False
    assert body["read_again"] is False
    msg = (body["message"] or "").lower()
    assert "one more" not in msg
    assert "i heard" in msg or body["message"] == MSG_CLOSE_OK


def test_strict_exact_low_confidence_does_not_ask_read_again(
    client, whisper_double, tone_wav, assert_attempt_shape
):
    client.put("/api/parent/settings", json={"mode": "strict", "auto_strict": False})
    start = client.post("/api/sessions", json={"level": 1}).json()
    assert start["mode"] == "strict"
    item = start["items"][0]
    qi = 0
    # Exact word + soft Whisper prob must still accept (UI shows the right word).
    whisper_double.set_transcript(
        AttemptTranscript(
            transcript=item["text"],
            words=[TranscriptWord(word=item["text"], probability=0.40)],
            no_speech_prob=0.05,
        )
    )
    res = post_attempt(
        client,
        start["session_id"],
        item["id"],
        tone_wav.read_bytes(),
        queue_index=qi,
    )
    assert res.status_code == 200
    body = res.json()
    assert_attempt_shape(body)
    assert body["result"] == "correct"
    assert body["again"] is False
    assert body["read_again"] is False
