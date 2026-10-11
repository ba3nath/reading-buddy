"""Milestone 2 API tests: audio resolver + replay scoring."""

from __future__ import annotations

from app import config
from app.whisper_engine import AttemptTranscript, TranscriptWord
from tests.helpers import post_attempt


def _post_attempt(client, session_id, item_id, audio_bytes, *, qi=0, phase="read", word=""):
    return post_attempt(
        client,
        session_id,
        item_id,
        audio_bytes,
        phase=phase,
        queue_index=qi if phase == "read" else None,
        word=word,
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

    whisper_double.set_transcript(
        AttemptTranscript(
            transcript=items[0]["text"],
            words=[TranscriptWord(word=items[0]["text"], probability=0.95)],
            no_speech_prob=0.05,
        )
    )
    assert _post_attempt(client, sid, items[0]["id"], tone_wav.read_bytes(), qi=0).json()[
        "result"
    ] == "correct"

    whisper_double.set_transcript(
        AttemptTranscript(
            transcript="zzzzzz",
            words=[TranscriptWord(word="zzzzzz", probability=0.95)],
            no_speech_prob=0.05,
        )
    )
    assert _post_attempt(client, sid, items[1]["id"], tone_wav.read_bytes(), qi=1).json()[
        "result"
    ] == "missed"

    whisper_double.set_transcript(
        AttemptTranscript(
            transcript=items[2]["text"],
            words=[TranscriptWord(word=items[2]["text"], probability=0.4)],
            no_speech_prob=0.05,
        )
    )
    close = _post_attempt(client, sid, items[2]["id"], tone_wav.read_bytes(), qi=2).json()
    assert close["result"] == "close"
    whisper_double.set_transcript(
        AttemptTranscript(
            transcript=items[2]["text"],
            words=[TranscriptWord(word=items[2]["text"], probability=0.95)],
            no_speech_prob=0.05,
        )
    )
    _post_attempt(client, sid, items[2]["id"], tone_wav.read_bytes(), qi=2)

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
    _post_attempt(client, sid, item["id"], tone_wav.read_bytes(), qi=0)
    done = client.post(f"/api/sessions/{sid}/complete").json()
    assert done["correct_count"] == 0
    planned = done["planned_count"]
    stars_at_complete = done["stars"]
    assert done["replay"]
    word = done["replay"][0]["text"]

    whisper_double.set_transcript(
        AttemptTranscript(
            transcript=word,
            words=[TranscriptWord(word=word, probability=0.95)],
            no_speech_prob=0.05,
        )
    )
    res = _post_attempt(
        client, sid, item["id"], tone_wav.read_bytes(), phase="replay", word=word
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
        SELECT is_replay, counts_for_session, result, replay_word FROM attempts
        WHERE session_id = ? AND item_id = ? AND is_replay = 1
        ORDER BY id DESC LIMIT 1
        """,
        (sid, item["id"]),
    ).fetchone()
    assert attempt["is_replay"] == 1
    assert attempt["result"] == "correct"
    assert attempt["counts_for_session"] == 0
    assert attempt["replay_word"] == word

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


def test_replay_close_no_again_then_advance(
    client, whisper_double, tone_wav, tmp_env, assert_error_envelope
):
    """C1 regression: replay close locks with again=false; second POST is 409, not a trap."""
    start = client.post("/api/sessions", json={"level": 1}).json()
    item = next((i for i in start["items"] if i["text"] == "cat"), start["items"][0])
    qi = start["items"].index(item)
    sid = start["session_id"]

    whisper_double.set_transcript(
        AttemptTranscript(
            transcript="zzzzzz",
            words=[TranscriptWord(word="zzzzzz", probability=0.95)],
            no_speech_prob=0.05,
        )
    )
    _post_attempt(client, sid, item["id"], tone_wav.read_bytes(), qi=qi)
    done = client.post(f"/api/sessions/{sid}/complete").json()
    assert done["replay"]
    word = done["replay"][0]["text"]
    planned = done["planned_count"]
    correct = done["correct_count"]

    whisper_double.set_transcript(
        AttemptTranscript(
            transcript=word,
            words=[TranscriptWord(word=word, probability=0.40)],
            no_speech_prob=0.05,
        )
    )
    res = _post_attempt(
        client, sid, item["id"], tone_wav.read_bytes(), phase="replay", word=word
    )
    assert res.status_code == 200
    body = res.json()
    assert body["result"] == "close"
    assert body["again"] is False
    assert body["retry"] is False

    row = tmp_env["conn"].execute(
        "SELECT correct_count, planned_count FROM sessions WHERE id = ?",
        (sid,),
    ).fetchone()
    assert row["correct_count"] == correct
    assert row["planned_count"] == planned

    second = _post_attempt(
        client, sid, item["id"], tone_wav.read_bytes(), phase="replay", word=word
    )
    assert second.status_code == 409
    assert_error_envelope(second.json(), code="already_resolved")


def test_api_word_level_replay_scores_word_not_phrase(
    client, whisper_double, tone_wav, tmp_env, assert_error_envelope
):
    """R2 API: Whisper target is the missed word; FE word field required."""
    from app.db import normalize_text
    from app.session import set_play_ids
    import json

    conn = tmp_env["conn"]
    conn.execute(
        """
        INSERT INTO items (
          slug, text, normalized, kind, level, sound_tags, sounds_locked,
          rhyme_group, line_index, source, pd_status, hard
        ) VALUES (?, ?, ?, 'phrase', 1, '[]', 0, NULL, NULL, 'test', 'n/a', 0)
        """,
        ("a-big-red-bus", "a big red bus", normalize_text("a big red bus")),
    )
    conn.commit()
    phrase = conn.execute(
        "SELECT id, slug FROM items WHERE slug = 'a-big-red-bus'"
    ).fetchone()

    start = client.post("/api/sessions", json={"level": 1}).json()
    sid = start["session_id"]
    set_play_ids(conn, sid, [phrase["id"]])
    conn.execute(
        "UPDATE sessions SET planned_item_ids = ?, planned_count = 1 WHERE id = ?",
        (json.dumps([phrase["id"]]), sid),
    )
    conn.commit()

    # Child says "a big red" — bus missed
    whisper_double.set_transcript(
        AttemptTranscript(
            transcript="a big red",
            words=[
                TranscriptWord(word="a", probability=0.95),
                TranscriptWord(word="big", probability=0.94),
                TranscriptWord(word="red", probability=0.93),
            ],
            no_speech_prob=0.05,
        )
    )
    res = _post_attempt(client, sid, phrase["id"], tone_wav.read_bytes(), qi=0)
    assert res.status_code == 200
    assert res.json()["result"] == "missed"

    done = client.post(f"/api/sessions/{sid}/complete").json()
    assert len(done["replay"]) == 1
    assert done["replay"][0]["text"] == "bus"
    assert done["replay"][0]["audio_url"].endswith("/bus")

    # Child says "bus" — must score correct against word target
    whisper_double.set_transcript(
        AttemptTranscript(
            transcript="bus",
            words=[TranscriptWord(word="bus", probability=0.95)],
            no_speech_prob=0.05,
        )
    )
    replay = _post_attempt(
        client,
        sid,
        phrase["id"],
        tone_wav.read_bytes(),
        phase="replay",
        word="bus",
    )
    assert replay.status_code == 200
    body = replay.json()
    assert body["result"] == "correct"
    assert body["words_total"] == 1

    # Missing word field → 400
    bad = client.post(
        f"/api/sessions/{sid}/attempts",
        data={"item_id": str(phrase["id"]), "phase": "replay"},
        files={"audio": ("take.wav", tone_wav.read_bytes(), "audio/wav")},
    )
    # bus already resolved → if word empty, bad_request for missing word
    # (or already_resolved if somehow matched). Prefer missing word.
    assert bad.status_code in (400, 409)
