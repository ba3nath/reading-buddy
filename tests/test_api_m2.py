"""Milestone 2 API tests: audio resolver + replay scoring."""

from __future__ import annotations

from pathlib import Path

from app import config
from app.whisper_engine import AttemptTranscript, TranscriptWord


def _post_attempt(client, session_id, item_id, audio_bytes, phase="read"):
    return client.post(
        f"/api/sessions/{session_id}/attempts",
        data={"item_id": str(item_id), "phase": phase},
        files={"audio": ("take.wav", audio_bytes, "audio/wav")},
    )


def test_audio_prefers_human_over_generated(client, tmp_path, monkeypatch):
    from app import audio_files

    gen = tmp_path / "generated"
    human = tmp_path / "human"
    gen.mkdir()
    human.mkdir()
    monkeypatch.setattr(config, "AUDIO_GENERATED", gen)
    monkeypatch.setattr(config, "AUDIO_HUMAN", human)
    monkeypatch.setattr(audio_files.config, "AUDIO_GENERATED", gen)
    monkeypatch.setattr(audio_files.config, "AUDIO_HUMAN", human)

    (gen / "cat.wav").write_bytes(b"RIFF____WAVEfmt generated")
    res = client.get("/api/audio/cat")
    assert res.status_code == 200
    assert res.content == b"RIFF____WAVEfmt generated"

    (human / "cat.wav").write_bytes(b"RIFF____WAVEfmt humanxxx")
    res = client.get("/api/audio/cat")
    assert res.status_code == 200
    assert res.content == b"RIFF____WAVEfmt humanxxx"


def test_audio_404(client, tmp_path, monkeypatch, assert_error_envelope):
    from app import audio_files

    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setattr(config, "AUDIO_GENERATED", empty)
    monkeypatch.setattr(config, "AUDIO_HUMAN", empty)
    monkeypatch.setattr(audio_files.config, "AUDIO_GENERATED", empty)
    monkeypatch.setattr(audio_files.config, "AUDIO_HUMAN", empty)

    res = client.get("/api/audio/missing-slug")
    assert res.status_code == 404
    assert_error_envelope(res.json(), code="not_found")


def test_complete_replay_missed_only(client, whisper_double, tone_wav):
    start = client.post("/api/sessions", json={"level": 1}).json()
    items = start["items"]
    sid = start["session_id"]

    # First item correct
    whisper_double.set_transcript(
        AttemptTranscript(
            transcript=items[0]["text"],
            words=[TranscriptWord(word=items[0]["text"], probability=0.95)],
            no_speech_prob=0.05,
        )
    )
    assert _post_attempt(client, sid, items[0]["id"], tone_wav.read_bytes()).json()[
        "result"
    ] == "correct"

    # Second item missed
    whisper_double.set_transcript(
        AttemptTranscript(
            transcript="zzzzzz",
            words=[TranscriptWord(word="zzzzzz", probability=0.95)],
            no_speech_prob=0.05,
        )
    )
    assert _post_attempt(client, sid, items[1]["id"], tone_wav.read_bytes()).json()[
        "result"
    ] == "missed"

    # Third item close (locking close on second take) — not on replay
    whisper_double.set_transcript(
        AttemptTranscript(
            transcript=items[2]["text"],
            words=[TranscriptWord(word=items[2]["text"], probability=0.4)],
            no_speech_prob=0.05,
        )
    )
    close = _post_attempt(client, sid, items[2]["id"], tone_wav.read_bytes()).json()
    assert close["result"] == "close"
    whisper_double.set_transcript(
        AttemptTranscript(
            transcript=items[2]["text"],
            words=[TranscriptWord(word=items[2]["text"], probability=0.95)],
            no_speech_prob=0.05,
        )
    )
    _post_attempt(client, sid, items[2]["id"], tone_wav.read_bytes())

    done = client.post(f"/api/sessions/{sid}/complete").json()
    assert done["replay"]
    assert all("item_id" in r and "text" in r and "audio_url" in r for r in done["replay"])
    assert all(r["item_id"] == items[1]["id"] for r in done["replay"])
    assert items[2]["id"] not in {r["item_id"] for r in done["replay"]}


def test_replay_attempt_stars_without_ratio_change(
    client, whisper_double, tone_wav, tmp_env
):
    start = client.post("/api/sessions", json={"level": 1}).json()
    item = start["items"][0]
    sid = start["session_id"]

    whisper_double.set_transcript(
        AttemptTranscript(
            transcript="zzzzzz",
            words=[TranscriptWord(word="zzzzzz", probability=0.95)],
            no_speech_prob=0.05,
        )
    )
    _post_attempt(client, sid, item["id"], tone_wav.read_bytes())
    done = client.post(f"/api/sessions/{sid}/complete").json()
    assert done["correct_count"] == 0
    planned = done["planned_count"]
    stars_at_complete = done["stars"]
    assert done["replay"]

    whisper_double.set_transcript(
        AttemptTranscript(
            transcript=item["text"],
            words=[TranscriptWord(word=item["text"], probability=0.95)],
            no_speech_prob=0.05,
        )
    )
    res = _post_attempt(
        client, sid, item["id"], tone_wav.read_bytes(), phase="replay"
    )
    assert res.status_code == 200
    body = res.json()
    assert body["result"] == "correct"
    assert body["stars_awarded"] == 1
    assert body["stars_total"] == stars_at_complete + 1

    row = tmp_env["conn"].execute(
        "SELECT correct_count, planned_count, stars FROM sessions WHERE id = ?",
        (sid,),
    ).fetchone()
    assert row["correct_count"] == 0
    assert row["planned_count"] == planned
    assert row["stars"] == stars_at_complete + 1

    attempt = tmp_env["conn"].execute(
        """
        SELECT is_replay, counts_for_session, result FROM attempts
        WHERE session_id = ? AND item_id = ? AND is_replay = 1
        ORDER BY id DESC LIMIT 1
        """,
        (sid, item["id"]),
    ).fetchone()
    assert attempt["is_replay"] == 1
    assert attempt["result"] == "correct"
    assert attempt["counts_for_session"] == 0

    mastery = tmp_env["conn"].execute(
        "SELECT correct_count FROM mastery WHERE item_id = ?",
        (item["id"],),
    ).fetchone()
    assert mastery["correct_count"] >= 1


def test_health_includes_audio_flag(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert "audio" in body
    assert isinstance(body["audio"], bool)
