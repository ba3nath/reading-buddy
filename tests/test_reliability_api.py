"""Phase 4a: controlled API failures and temp audio cleanup."""

from __future__ import annotations

from pathlib import Path

from tests.helpers import post_attempt


def test_nonexistent_session_attempt_404(client, tone_wav, assert_error_envelope):
    res = post_attempt(client, 999_999, 1, tone_wav.read_bytes(), queue_index=0)
    assert res.status_code == 404
    assert_error_envelope(res.json(), code="not_found")


def test_nonexistent_session_complete_404(client, assert_error_envelope):
    res = client.post("/api/sessions/999999/complete")
    assert res.status_code == 404
    assert_error_envelope(res.json(), code="not_found")


def test_invalid_session_payload_400(client, assert_error_envelope):
    res = client.post("/api/sessions", json={"level": "not-a-level"})
    assert res.status_code == 400
    assert_error_envelope(res.json(), code="bad_request")


def test_empty_audio_cleans_tmp(client, tmp_env, assert_attempt_shape):
    start = client.post("/api/sessions", json={"level": 1}).json()
    item = start["items"][0]
    res = post_attempt(client, start["session_id"], item["id"], b"", queue_index=0)
    assert res.status_code == 200
    body = res.json()
    assert_attempt_shape(body, words_total=1)
    assert body["result"] == "retry"
    assert list(Path(tmp_env["tmp"]).glob("*")) == []


def test_transcription_exception_returns_503_and_cleans_tmp(
    client, tmp_env, tone_wav, whisper_double, monkeypatch, assert_error_envelope
):
    start = client.post("/api/sessions", json={"level": 1}).json()
    item = start["items"][0]

    def boom(*_a, **_k):  # noqa: ANN001
        raise RuntimeError("whisper down")

    monkeypatch.setattr(whisper_double, "transcribe", boom)
    res = post_attempt(
        client, start["session_id"], item["id"], tone_wav.read_bytes(), queue_index=0
    )
    assert res.status_code == 503
    assert_error_envelope(res.json(), code="unavailable")
    msg = res.json()["error"]["message"].lower()
    assert "whisper" in msg
    assert list(Path(tmp_env["tmp"]).glob("*")) == []


def test_interrupted_closed_session_rejects_attempt(
    client, tone_wav, assert_error_envelope
):
    start = client.post("/api/sessions", json={"level": 1}).json()
    sid = start["session_id"]
    # Open a second session — first is abandoned/closed.
    client.post("/api/sessions", json={"level": 1})
    item = start["items"][0]
    res = post_attempt(client, sid, item["id"], tone_wav.read_bytes(), queue_index=0)
    assert res.status_code == 409
    assert_error_envelope(res.json(), code="session_closed")
