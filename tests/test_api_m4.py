"""Milestone 4 API: parent page, settings, keep_audio, export, garden."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from app.db import load_settings, save_settings
from app.parent import SOUND_NOTE, garden_stage_name
from app.whisper_engine import AttemptTranscript, TranscriptWord
from tests.helpers import post_attempt


def test_parent_page_no_pin(client):
    res = client.get("/parent")
    assert res.status_code == 200
    assert "Parent" in res.text
    assert "no pin" in res.text.lower()
    assert "enter pin" not in res.text.lower()
    assert "password" not in res.text.lower()


def test_parent_json_routes(client):
    for path in (
        "/api/parent/accuracy",
        "/api/parent/mastered",
        "/api/parent/tricky",
        "/api/parent/sounds",
        "/api/parent/kept",
        "/api/parent/settings",
    ):
        res = client.get(path)
        assert res.status_code == 200, path
        assert "error" not in res.json() or path.endswith("settings")


def test_sounds_note(client):
    body = client.get("/api/parent/sounds").json()
    assert body["note"].startswith(SOUND_NOTE)
    assert "independent" in body["note"].lower()
    assert "tags" in body


def test_settings_round_trip(client):
    payload = {
        "mode": "strict",
        "level": 4,
        "session_length": 10,
        "keep_audio": False,
        "profile_name": "Asha",
        "buddy": "krishna",
        "auto_strict": False,
    }
    res = client.put("/api/parent/settings", json=payload)
    assert res.status_code == 200
    body = res.json()
    assert body["mode"] == "strict"
    assert body["level"] == 4
    assert body["session_length"] == 10
    assert body["keep_audio"] is False
    assert body["profile_name"] == "Asha"
    assert body["buddy"] == "krishna"
    assert body["auto_strict"] is False

    got = client.get("/api/parent/settings").json()
    assert got["buddy"] == "krishna"
    assert got["profile_name"] == "Asha"


def test_session_length_only_5_or_10(client, tmp_env):
    """Uniform session sizes: only 5 or 10; other values snap to the nearer."""
    from app.config import normalize_session_length

    assert normalize_session_length(5) == 5
    assert normalize_session_length(10) == 10
    assert normalize_session_length(12) == 10
    assert normalize_session_length(6) == 5
    assert normalize_session_length(7) == 5
    assert normalize_session_length(8) == 10

    assert client.put("/api/parent/settings", json={"session_length": 5}).json()[
        "session_length"
    ] == 5
    assert client.put("/api/parent/settings", json={"session_length": 12}).json()[
        "session_length"
    ] == 10
    save_settings({**load_settings(), "session_length": 15})
    assert load_settings()["session_length"] == 10

    parent = client.get("/parent").text
    assert 'value="5"' in parent
    assert 'value="10"' in parent
    assert 'max="20"' not in parent


def test_empty_profile_still_saves_session_and_export(client, whisper_double, tone_wav, tmp_env):
    """Progress persists with no profile name — sessions, attempts, mastery, export."""
    save_settings({**load_settings(), "profile_name": "", "session_length": 5})
    assert load_settings()["profile_name"] == ""

    start = client.post("/api/sessions", json={"level": 1}).json()
    sid = start["session_id"]
    assert len(start["items"]) == 5
    item = start["items"][0]
    whisper_double.set_transcript(
        AttemptTranscript(
            transcript=item["text"],
            words=[TranscriptWord(word=item["text"], probability=0.95)],
            no_speech_prob=0.05,
        )
    )
    post_attempt(client, sid, item["id"], tone_wav.read_bytes(), queue_index=0)
    # Finish remaining slots quickly so complete works.
    for qi, it in enumerate(start["items"][1:], start=1):
        whisper_double.set_transcript(
            AttemptTranscript(
                transcript=it["text"],
                words=[TranscriptWord(word=it["text"], probability=0.95)],
                no_speech_prob=0.05,
            )
        )
        post_attempt(client, sid, it["id"], tone_wav.read_bytes(), queue_index=qi)

    done = client.post(f"/api/sessions/{sid}/complete", json={}).json()
    assert done["planned_count"] == 5
    assert done["stars"] >= 1
    assert load_settings()["lifetime_stars"] >= 1
    assert load_settings()["profile_name"] == ""

    export = client.get("/api/parent/export")
    assert export.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(export.content))
    names = set(zf.namelist())
    assert "sessions.csv" in names
    assert "attempts.csv" in names
    assert "mastery.csv" in names
    assert "settings.csv" in names
    settings_csv = zf.read("settings.csv").decode("utf-8")
    assert "profile_name" in settings_csv
    sessions_csv = zf.read("sessions.csv").decode("utf-8")
    assert str(sid) in sessions_csv


def test_buddy_validation(client, assert_error_envelope):
    bad = client.put("/api/parent/settings", json={"buddy": "mickey"})
    assert bad.status_code == 400
    assert_error_envelope(bad.json(), code="bad_request")


def test_mouse_buddy_migrates_to_unicorn(client, tmp_env):
    """Saved buddy=mouse is rewritten to unicorn on load and via settings PUT."""
    save_settings({**load_settings(), "buddy": "mouse"})
    assert load_settings()["buddy"] == "unicorn"
    migrated = client.put("/api/parent/settings", json={"buddy": "mouse"})
    assert migrated.status_code == 200
    assert migrated.json()["buddy"] == "unicorn"


def test_cat_buddy_migrates_to_krishna(client, tmp_env):
    """Retired cat persona rewrites to Krishna on load and via settings PUT."""
    save_settings({**load_settings(), "buddy": "cat"})
    assert load_settings()["buddy"] == "krishna"
    migrated = client.put("/api/parent/settings", json={"buddy": "cat"})
    assert migrated.status_code == 200
    assert migrated.json()["buddy"] == "krishna"
    parent = client.get("/parent").text
    assert 'value="krishna"' in parent
    assert 'value="unicorn"' in parent
    assert 'value="cat"' not in parent


def test_keep_audio_false_leaves_no_kept(client, whisper_double, tone_wav, tmp_env):
    client.put("/api/parent/settings", json={"keep_audio": False})
    start = client.post("/api/sessions", json={"level": 1}).json()
    item = start["items"][0]
    whisper_double.set_transcript(
        AttemptTranscript(
            transcript=item["text"],
            words=[TranscriptWord(word=item["text"], probability=0.95)],
            no_speech_prob=0.05,
        )
    )
    res = post_attempt(
        client, start["session_id"], item["id"], tone_wav.read_bytes(), queue_index=0
    )
    assert res.status_code == 200
    assert list(Path(tmp_env["tmp"]).glob("*")) == []
    assert list(Path(tmp_env["data"] / "kept").glob("*")) == []


def test_keep_audio_true_stores_and_plays(client, whisper_double, tone_wav, tmp_env):
    client.put("/api/parent/settings", json={"keep_audio": True})
    start = client.post("/api/sessions", json={"level": 1}).json()
    item = start["items"][0]
    whisper_double.set_transcript(
        AttemptTranscript(
            transcript=item["text"],
            words=[TranscriptWord(word=item["text"], probability=0.95)],
            no_speech_prob=0.05,
        )
    )
    res = post_attempt(
        client, start["session_id"], item["id"], tone_wav.read_bytes(), queue_index=0
    )
    assert res.status_code == 200
    body = res.json()
    assert "attempt_id" in body
    kept = Path(tmp_env["data"] / "kept") / f"{body['attempt_id']}.wav"
    assert kept.is_file()
    assert list(Path(tmp_env["tmp"]).glob("*")) == []

    play = client.get(f"/api/parent/kept/{body['attempt_id']}")
    assert play.status_code == 200
    assert play.headers["content-type"].startswith("audio/")

    listing = client.get("/api/parent/kept").json()
    assert any(c["attempt_id"] == body["attempt_id"] for c in listing["clips"])


def test_keep_audio_off_deletes_kept(client, whisper_double, tone_wav, tmp_env):
    client.put("/api/parent/settings", json={"keep_audio": True})
    start = client.post("/api/sessions", json={"level": 1}).json()
    item = start["items"][0]
    whisper_double.set_transcript(
        AttemptTranscript(
            transcript=item["text"],
            words=[TranscriptWord(word=item["text"], probability=0.95)],
            no_speech_prob=0.05,
        )
    )
    body = post_attempt(
        client, start["session_id"], item["id"], tone_wav.read_bytes(), queue_index=0
    ).json()
    kept = Path(tmp_env["data"] / "kept") / f"{body['attempt_id']}.wav"
    assert kept.is_file()

    off = client.put("/api/parent/settings", json={"keep_audio": False})
    assert off.status_code == 200
    assert off.json()["keep_audio"] is False
    assert list(Path(tmp_env["data"] / "kept").glob("*")) == []


def test_export_zip_four_csvs(client):
    res = client.get("/api/parent/export")
    assert res.status_code == 200
    assert res.headers["content-type"] in (
        "application/zip",
        "application/x-zip-compressed",
    )
    zf = zipfile.ZipFile(io.BytesIO(res.content))
    names = set(zf.namelist())
    assert {
        "items.csv",
        "sessions.csv",
        "attempts.csv",
        "mastery.csv",
        "events.csv",
        "settings.csv",
        "README.txt",
    } <= names
    items_header = zf.read("items.csv").decode("utf-8").splitlines()[0]
    assert "pattern" in items_header and "sight_word" in items_header
    mastery_header = zf.read("mastery.csv").decode("utf-8").splitlines()[0]
    assert "box" in mastery_header
    attempts_header = zf.read("attempts.csv").decode("utf-8").splitlines()[0]
    assert "latency_ms" in attempts_header
    for name in names:
        if name.endswith(".csv"):
            text = zf.read(name).decode("utf-8")
            assert "," in text or text.strip()


def test_garden_grows_on_complete(client, whisper_double, tone_wav):
    before = load_settings().get("garden_growth", 0)
    start = client.post("/api/sessions", json={"level": 1}).json()
    item = start["items"][0]
    whisper_double.set_transcript(
        AttemptTranscript(
            transcript=item["text"],
            words=[TranscriptWord(word=item["text"], probability=0.95)],
            no_speech_prob=0.05,
        )
    )
    post_attempt(
        client, start["session_id"], item["id"], tone_wav.read_bytes(), queue_index=0
    )
    done = client.post(f"/api/sessions/{start['session_id']}/complete")
    assert done.status_code == 200
    body = done.json()
    assert "garden" in body
    assert body["garden"]["growth"] == before + 1
    assert body["garden"]["stage"] == garden_stage_name(before + 1)
    assert load_settings()["garden_growth"] == before + 1

    # Second complete rejected — growth must not decrease or double-bump.
    again = client.post(f"/api/sessions/{start['session_id']}/complete")
    assert again.status_code == 409
    assert load_settings()["garden_growth"] == before + 1


def test_session_includes_buddy(client):
    client.put("/api/parent/settings", json={"buddy": "unicorn"})
    start = client.post("/api/sessions", json={"level": 1}).json()
    assert start["buddy"] == "unicorn"


def test_accuracy_and_mastered_shapes(client, whisper_double, tone_wav, tmp_env):
    client.put("/api/parent/settings", json={"mode": "beginner", "level": 1})
    start = client.post("/api/sessions", json={"level": 1}).json()
    item = start["items"][0]
    whisper_double.set_transcript(
        AttemptTranscript(
            transcript=item["text"],
            words=[TranscriptWord(word=item["text"], probability=0.95)],
            no_speech_prob=0.05,
        )
    )
    post_attempt(
        client, start["session_id"], item["id"], tone_wav.read_bytes(), queue_index=0
    )

    acc = client.get("/api/parent/accuracy").json()
    assert "days" in acc
    assert all({"date", "correct", "scored"} <= set(d.keys()) for d in acc["days"])

    mastered = client.get("/api/parent/mastered").json()
    assert "mastered" in mastered and "this_week" in mastered

    tricky = client.get("/api/parent/tricky").json()
    assert "items" in tricky


def test_mascot_svgs_served(client):
    import xml.etree.ElementTree as ET

    for name in ("krishna", "unicorn", "garden"):
        res = client.get(f"/static/mascots/{name}.svg")
        assert res.status_code == 200, name
        # <img src="…svg"> uses a strict XML parser — control chars break the tile.
        raw = res.content
        assert not any(b < 32 and b not in (9, 10, 13) for b in raw), name
        ET.fromstring(raw)
    assert client.get("/static/mascots/cat.svg").status_code == 404
    unicorn = client.get("/static/mascots/unicorn.svg").text.lower()
    assert "mickey" not in unicorn
    assert "buddy-root" in unicorn
    assert "horn" in unicorn
    assert "muzzle" in unicorn  # horse snout, not a round blob
    assert "mane" in unicorn
    assert "colorful" in unicorn or "horse" in unicorn
    # rainbow mane / colorful coat (not plain cream-only)
    assert "#ff8f6b" in unicorn or "#ffb0c8" in unicorn
    assert "#7ec8e8" in unicorn
    assert "#ff0000" not in unicorn
    assert "fill=\"red\"" not in unicorn
    assert "\x14" not in unicorn  # no invalid XML control chars
    krishna = client.get("/static/mascots/krishna.svg").text.lower()
    assert "flute" in krishna
    assert "feather" in krishna
