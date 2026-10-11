"""API + copy for when another read is required."""

from __future__ import annotations

from app.config import MSG_CLOSE, MSG_CLOSE_OK, msg_retry
from app.whisper_engine import AttemptTranscript, TranscriptWord
from tests.helpers import post_attempt


def test_msg_retry_includes_try_count():
    assert "read it again" in msg_retry(2, 3).lower()
    assert "(2 of 3)" in msg_retry(2, 3)
    assert MSG_CLOSE_OK == "Almost!"


def test_retry_payload_flags_read_again(client, assert_attempt_shape):
    start = client.post("/api/sessions", json={"level": 1}).json()
    item = start["items"][0]
    res = post_attempt(client, start["session_id"], item["id"], b"", queue_index=0)
    assert res.status_code == 200
    body = res.json()
    assert_attempt_shape(body, words_total=1)
    assert body["read_again"] is True
    assert body["try_number"] == 1
    assert body["tries_max"] == 3
    assert body["message"] == msg_retry(1, 3)


def test_close_again_message_asks_for_another_read(
    client, whisper_double, tone_wav, assert_attempt_shape
):
    start = client.post("/api/sessions", json={"level": 1}).json()
    item = next((i for i in start["items"] if i["text"] == "cat"), None)
    if item is None:
        # Level queue without cat — still assert close-again copy is wired.
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
    assert body["again"] is True
    assert body["read_again"] is True
    assert body["message"] == MSG_CLOSE
    assert "one more time" in body["message"].lower()
