"""Phase 0–3 learning roadmap: patterns, events, Leitner, engagement hooks."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from app import config
from app.adaptive import (
    apply_day_ladder,
    build_adaptive_queue,
    current_unlocked_patterns,
    shadow_queue_ids,
)
from app.audio_files import proportional_word_timings
from app.db import init_schema, load_settings, save_settings, upsert_items_from_json
from app.events import known_ratio_by_pattern, log_event, pattern_accuracy_by_day
from app.patterns import unlocked_patterns, validate_items
from app.session import _effort_stars

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    monkeypatch.setattr(config, "DB_PATH", db)
    monkeypatch.setattr(config, "SETTINGS_PATH", tmp_path / "settings.json")
    c = sqlite3.connect(str(db))
    c.row_factory = sqlite3.Row
    init_schema(c)
    upsert_items_from_json(c)
    yield c
    c.close()


def test_all_items_have_valid_patterns():
    items = json.loads((ROOT / "content/items.json").read_text(encoding="utf-8"))
    errors = validate_items(items)
    assert errors == []
    assert len(items) >= 200


def test_curriculum_audit_and_backup_script_exist():
    assert (ROOT / "docs/curriculum-audit.md").is_file()
    assert (ROOT / "scripts/backup_data.py").is_file()
    story = (ROOT / "docs/story-decodability.md").read_text(encoding="utf-8")
    assert "No out-of-pattern content words found" in story
    backup_src = (ROOT / "scripts/backup_data.py").read_text(encoding="utf-8")
    assert "AUDIO_HUMAN" in backup_src
    assert "human/" in backup_src


def test_unlock_requires_eighty_percent_known():
    ladder_prefix = unlocked_patterns({"cvc-a": 0.79})
    assert ladder_prefix[0] == "cvc-a"
    assert "cvc-e" not in ladder_prefix
    # Sight is woven once any CVC step is open.
    assert "sight" in ladder_prefix
    opened = unlocked_patterns({"cvc-a": 0.8})
    assert "cvc-e" in opened


def test_event_log_and_pattern_query(conn):
    item = conn.execute("SELECT id, pattern, sight_word FROM items LIMIT 1").fetchone()
    log_event(
        conn,
        session_id=None,
        item_id=int(item["id"]),
        pattern=str(item["pattern"]),
        sight_word=bool(item["sight_word"]),
        result="correct",
        latency_ms=900,
    )
    rows = pattern_accuracy_by_day(conn, days=7)
    assert any(r["pattern"] == item["pattern"] and r["correct"] >= 1 for r in rows)
    assert known_ratio_by_pattern(conn)


def test_leitner_box_promotes_and_mastery(conn):
    item_id = int(conn.execute("SELECT id FROM items WHERE kind='word' LIMIT 1").fetchone()["id"])
    apply_day_ladder(conn, item_id, "correct")
    row = conn.execute("SELECT box, mastered FROM mastery WHERE item_id=?", (item_id,)).fetchone()
    assert int(row["box"]) >= 2
    # Force two distinct days via direct days_json + more corrects.
    conn.execute(
        "UPDATE mastery SET days_json=?, box=3 WHERE item_id=?",
        (json.dumps(["2020-01-01"]), item_id),
    )
    conn.commit()
    apply_day_ladder(conn, item_id, "correct")
    row = conn.execute(
        "SELECT box, mastered, correct_count FROM mastery WHERE item_id=?", (item_id,)
    ).fetchone()
    assert int(row["box"]) >= 4
    assert int(row["mastered"]) == 1


def test_scheduler_v2_and_shadow(conn, monkeypatch):
    settings = load_settings()
    settings["scheduler_v2"] = True
    settings["scheduler_shadow"] = True
    save_settings(settings)
    queue = build_adaptive_queue(conn, 1, 5, stage=1)
    assert 1 <= len(queue) <= 5
    both = shadow_queue_ids(conn, 1, 5, 1)
    assert "scheduler_v2" in both and "legacy" in both
    assert current_unlocked_patterns(conn)


def test_effort_stars_awards_try():
    assert _effort_stars(0, result="close", again=False, hard_bonus=False) >= 1
    assert _effort_stars(0, result="missed", again=False, hard_bonus=False) == 0
    assert _effort_stars(1, result="correct", again=True, hard_bonus=False) == 0


def test_proportional_timings_cover_words():
    words = proportional_word_timings("the cat sat", 1.5)
    assert len(words) == 3
    assert words[0]["start"] < words[-1]["end"]


def test_warmup_and_timings_routes_present():
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    assert "/api/warmup" in main
    assert "/timings" in main
    assert "/api/parent/voice/" in main
    game = (ROOT / "static/js/game.js").read_text(encoding="utf-8")
    assert "playItemClip" in game
    assert "client_latency_ms" in game
    # Single-word listen must still get a read-along pointer.
    assert "wordTimings.length >= 1" in game
    assert "timings.length === 1" in game
    assert "playItemClip(entry)" in game


def test_timings_force_rebuild_after_override(tmp_path, monkeypatch):
    from app import audio_files
    from app.audio_files import load_or_build_timings

    gen = tmp_path / "generated"
    human = tmp_path / "human"
    gen.mkdir()
    human.mkdir()
    monkeypatch.setattr(config, "AUDIO_GENERATED", gen)
    monkeypatch.setattr(config, "AUDIO_HUMAN", human)
    monkeypatch.setattr(audio_files.config, "AUDIO_GENERATED", gen)
    monkeypatch.setattr(audio_files.config, "AUDIO_HUMAN", human)

    # Short generated clip → short timing window.
    import struct
    import wave

    def write_wav(path: Path, seconds: float) -> None:
        rate = 16000
        n = int(rate * seconds)
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(rate)
            wf.writeframes(struct.pack("<h", 4000) * n)

    write_wav(gen / "cat.wav", 0.4)
    first = load_or_build_timings("cat", "cat")
    assert first and first[0]["end"] <= 0.5
    cached = json.loads((gen / "cat.json").read_text(encoding="utf-8"))
    assert cached["words"][0]["end"] <= 0.5

    # Longer human override must rebuild when force=True.
    write_wav(human / "cat.wav", 1.2)
    stale = load_or_build_timings("cat", "cat")  # would keep cache without force
    assert stale[0]["end"] <= 0.5
    rebuilt = load_or_build_timings("cat", "cat", force=True)
    assert rebuilt[0]["end"] >= 1.0


def test_audio_timings_and_voice_upload_api(client, tmp_path, monkeypatch, tone_wav):
    from app import audio_files

    gen = tmp_path / "generated"
    human = tmp_path / "human"
    gen.mkdir()
    human.mkdir()
    monkeypatch.setattr(config, "AUDIO_GENERATED", gen)
    monkeypatch.setattr(config, "AUDIO_HUMAN", human)
    monkeypatch.setattr(audio_files.config, "AUDIO_GENERATED", gen)
    monkeypatch.setattr(audio_files.config, "AUDIO_HUMAN", human)

    # Seed a generated wav so timings resolve.
    (gen / "cat.wav").write_bytes(tone_wav.read_bytes())
    res = client.get("/api/audio/cat/timings")
    assert res.status_code == 200
    body = res.json()
    assert body["slug"] == "cat"
    assert body["words"] and body["words"][0]["word"].lower() == "cat"
    assert (gen / "cat.json").is_file()

    # Parent voice upload overwrites human path and rebuilds timings.
    upload = client.post(
        "/api/parent/voice/cat",
        files={"audio": ("parent.wav", tone_wav.read_bytes(), "audio/wav")},
    )
    if upload.status_code == 503:
        pytest.skip("ffmpeg unavailable in this environment")
    assert upload.status_code == 200, upload.text
    assert upload.json()["ok"] is True
    assert (human / "cat.wav").is_file()
    play = client.get("/api/audio/cat")
    assert play.status_code == 200
    assert play.content == (human / "cat.wav").read_bytes()
