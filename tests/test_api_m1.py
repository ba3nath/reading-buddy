"""Milestone 1 API / integration tests (Whisper double, no mic)."""

from __future__ import annotations

from pathlib import Path

from app.config import MSG_CLOSE_OK, MSG_MISS_AGAIN, MSG_SKIP, msg_retry
from app.whisper_engine import AttemptTranscript, TranscriptWord
from tests.helpers import post_attempt


def _post_attempt(client, session_id: int, item_id: int, audio_bytes: bytes, *, qi: int = 0):
    return post_attempt(client, session_id, item_id, audio_bytes, queue_index=qi)


def test_health(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["whisper"] is True
    assert body["ffmpeg"] is True
    assert body["offline"] is True
    assert "audio" in body


def test_index(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "Reading Buddy" in res.text


def test_start_session_default_length(client, assert_attempt_shape):
    res = client.post("/api/sessions")
    assert res.status_code == 200
    body = res.json()
    assert body["mode"] == "beginner"
    assert body["level"] == 1
    assert len(body["items"]) == 10
    item = body["items"][0]
    for key in ("id", "slug", "text", "kind", "rhyme_group", "line_index"):
        assert key in item


def test_start_session_level_only(client, assert_error_envelope):
    res = client.post("/api/sessions", json={"level": 3})
    assert res.status_code == 200
    assert res.json()["level"] == 3
    assert all(True for _ in res.json()["items"])

    bad = client.post("/api/sessions", json={"level": 2, "mode": "strict"})
    assert bad.status_code == 400
    assert_error_envelope(bad.json(), code="bad_request")


def test_attempt_correct(client, whisper_double, tone_wav, assert_attempt_shape):
    start = client.post("/api/sessions", json={"level": 1}).json()
    item = start["items"][0]
    whisper_double.set_transcript(
        AttemptTranscript(
            transcript=item["text"],
            words=[TranscriptWord(word=item["text"], probability=0.95)],
            no_speech_prob=0.05,
        )
    )
    res = _post_attempt(client, start["session_id"], item["id"], tone_wav.read_bytes())
    assert res.status_code == 200
    body = res.json()
    assert_attempt_shape(body)
    assert body["result"] == "correct"
    assert body["stars_awarded"] == 1
    assert body["stars_total"] == 1
    assert body["skipped"] is False


def test_attempt_close(client, whisper_double, tone_wav, assert_attempt_shape):
    start = client.post("/api/sessions", json={"level": 1}).json()
    item = next((i for i in start["items"] if i["text"] == "cat"), start["items"][0])
    qi = start["items"].index(item)
    heard = "cot" if item["text"] == "cat" else item["text"]
    conf = 0.4 if heard == item["text"] else 0.9
    whisper_double.set_transcript(
        AttemptTranscript(
            transcript=heard,
            words=[TranscriptWord(word=heard, probability=conf)],
            no_speech_prob=0.05,
        )
    )
    res = _post_attempt(
        client, start["session_id"], item["id"], tone_wav.read_bytes(), qi=qi
    )
    assert res.status_code == 200
    body = res.json()
    assert_attempt_shape(body)
    if item["text"] == "cat":
        # Beginner: near-miss locks on first take (no forced second try).
        assert body["result"] == "close"
        assert body["again"] is False
        assert body["read_again"] is False
        assert body["message"] == MSG_CLOSE_OK
        assert "one more" not in body["message"].lower()


def test_attempt_miss(client, whisper_double, tone_wav, assert_attempt_shape):
    start = client.post("/api/sessions", json={"level": 1}).json()
    item = start["items"][0]
    whisper_double.set_transcript(
        AttemptTranscript(
            transcript="zzzzzz",
            words=[TranscriptWord(word="zzzzzz", probability=0.95)],
            no_speech_prob=0.05,
        )
    )
    res = _post_attempt(client, start["session_id"], item["id"], tone_wav.read_bytes())
    assert res.status_code == 200
    body = res.json()
    assert body["result"] == "missed"
    assert body["message"] == MSG_MISS_AGAIN
    assert body["read_again"] is True
    assert body["stars_awarded"] == 0


def test_attempt_retry_empty_audio(client, tmp_env, assert_attempt_shape):
    start = client.post("/api/sessions", json={"level": 1}).json()
    item = start["items"][0]
    res = _post_attempt(client, start["session_id"], item["id"], b"")
    assert res.status_code == 200
    body = res.json()
    assert_attempt_shape(body, words_total=1)
    assert body["result"] == "retry"
    assert body["retry"] is True
    assert body["again"] is True
    assert body["read_again"] is True
    assert body["try_number"] == 2
    assert body["tries_max"] == 3
    assert body["skipped"] is False
    assert body["message"] == msg_retry(2, 3)
    assert "read it again" in body["message"].lower()
    assert body["transcript"] == ""
    assert body["word_scores"] == []
    assert body["words_correct"] == 0
    assert body["words_total"] == 1
    row = tmp_env["conn"].execute(
        """
        SELECT counts_for_session, result, queue_index FROM attempts
        WHERE session_id = ? AND item_id = ?
        """,
        (start["session_id"], item["id"]),
    ).fetchone()
    assert row["result"] == "retry"
    assert row["counts_for_session"] == 0
    assert row["queue_index"] == 0


def test_three_retries_skip(client, tmp_env, assert_attempt_shape):
    start = client.post("/api/sessions", json={"level": 1}).json()
    item = start["items"][0]
    sid = start["session_id"]
    for _ in range(2):
        res = _post_attempt(client, sid, item["id"], b"")
        assert res.json()["result"] == "retry"
    res = _post_attempt(client, sid, item["id"], b"")
    body = res.json()
    assert_attempt_shape(body, words_total=1)
    assert body["result"] == "skipped"
    assert body["skipped"] is True
    assert body["retry"] is False
    assert body["again"] is False
    assert body["message"] == MSG_SKIP
    assert body["word_scores"] == []
    assert body["words_correct"] == 0
    assert body["words_total"] == 1
    assert body["transcript"] == ""
    row = tmp_env["conn"].execute(
        "SELECT planned_count FROM sessions WHERE id = ?", (sid,)
    ).fetchone()
    assert row["planned_count"] == 9
    attempts = tmp_env["conn"].execute(
        """
        SELECT result, counts_for_session FROM attempts
        WHERE session_id = ? AND item_id = ?
        ORDER BY id
        """,
        (sid, item["id"]),
    ).fetchall()
    assert [a["result"] for a in attempts] == ["retry", "retry", "skipped"]
    assert all(a["counts_for_session"] == 0 for a in attempts)


def test_complete_m1(client, whisper_double, tone_wav):
    start = client.post("/api/sessions", json={"level": 1}).json()
    item = start["items"][0]
    whisper_double.set_transcript(
        AttemptTranscript(
            transcript=item["text"],
            words=[TranscriptWord(word=item["text"], probability=0.95)],
            no_speech_prob=0.05,
        )
    )
    _post_attempt(client, start["session_id"], item["id"], tone_wav.read_bytes())
    res = client.post(f"/api/sessions/{start['session_id']}/complete")
    assert res.status_code == 200
    body = res.json()
    assert body["replay"] == []
    assert body["stars"] >= 1
    assert "correct_count" in body
    assert "planned_count" in body


def test_phase_replay_before_complete_rejected(client, tone_wav, assert_error_envelope):
    """Replay is M2-only after complete; open sessions still reject phase=replay."""
    start = client.post("/api/sessions", json={"level": 1}).json()
    item = start["items"][0]
    res = post_attempt(
        client,
        start["session_id"],
        item["id"],
        tone_wav.read_bytes(),
        phase="replay",
        word=item["text"],
    )
    assert res.status_code == 400
    assert_error_envelope(res.json(), code="bad_request")


def test_unknown_item_404(client, tone_wav, assert_error_envelope):
    start = client.post("/api/sessions", json={"level": 1}).json()
    res = _post_attempt(client, start["session_id"], 999999, tone_wav.read_bytes())
    assert res.status_code == 404
    assert_error_envelope(res.json(), code="not_found")


def test_repost_after_correct_rejected(client, whisper_double, tone_wav, assert_error_envelope):
    start = client.post("/api/sessions", json={"level": 1}).json()
    item = start["items"][0]
    whisper_double.set_transcript(
        AttemptTranscript(
            transcript=item["text"],
            words=[TranscriptWord(word=item["text"], probability=0.95)],
            no_speech_prob=0.05,
        )
    )
    first = _post_attempt(client, start["session_id"], item["id"], tone_wav.read_bytes())
    assert first.status_code == 200
    assert first.json()["stars_total"] == 1
    second = _post_attempt(client, start["session_id"], item["id"], tone_wav.read_bytes())
    assert second.status_code == 409
    assert_error_envelope(second.json(), code="already_resolved")


def test_complete_abandoned_rejected(client, assert_error_envelope):
    first = client.post("/api/sessions", json={"level": 1}).json()
    client.post("/api/sessions", json={"level": 1})  # abandons first
    res = client.post(f"/api/sessions/{first['session_id']}/complete")
    assert res.status_code == 409
    assert_error_envelope(res.json(), code="session_closed")


def test_privacy_temp_deleted(client, whisper_double, tone_wav, tmp_env):
    start = client.post("/api/sessions", json={"level": 1}).json()
    item = start["items"][0]
    whisper_double.set_transcript(
        AttemptTranscript(
            transcript=item["text"],
            words=[TranscriptWord(word=item["text"], probability=0.95)],
            no_speech_prob=0.05,
        )
    )
    _post_attempt(client, start["session_id"], item["id"], tone_wav.read_bytes())
    tmp_files = list(Path(tmp_env["tmp"]).glob("*"))
    assert tmp_files == []
    kept = list(Path(tmp_env["data"] / "kept").glob("*"))
    assert kept == []
