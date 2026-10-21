"""Regression tests for intent/code drifts fixed in the full drift pass."""

from __future__ import annotations

import json
import time
from pathlib import Path

from app import config
from app.adaptive import apply_day_ladder
from app.db import ensure_mastery_row, load_settings, local_today, save_settings
from app.session import complete_session, start_session, words_mastered_this_session
from app.matching import score_attempt
from app.session import apply_attempt


def test_words_mastered_uses_leitner_not_correct_count_three(tmp_env):
    conn = tmp_env["conn"]
    save_settings({**load_settings(), "scheduler_v2": True, "session_length": 5})
    data = start_session(conn, level=1, stage=1)
    sid = data["session_id"]
    item = data["items"][0]
    item_id = int(item["id"])
    # Leitner mastery with correct_count != 3 (the old broken filter).
    ensure_mastery_row(conn, item_id)
    conn.execute(
        """
        UPDATE mastery
        SET correct_count = 2, box = 4, mastered = 1, mastered_on = ?,
            days_json = ?
        WHERE item_id = ?
        """,
        (local_today(), json.dumps(["2020-01-01", local_today()]), item_id),
    )
    conn.commit()
    match = score_attempt(item["text"], item["text"], [0.95], mode="beginner")
    apply_attempt(conn, sid, item_id, match, queue_index=0)
    words = words_mastered_this_session(conn, sid)
    assert item["text"] in words


def test_garden_complete_reports_stage_changed(tmp_env):
    conn = tmp_env["conn"]
    save_settings({**load_settings(), "garden_growth": 0, "session_length": 5})
    data = start_session(conn, level=1, stage=1)
    sid = data["session_id"]
    for qi, item in enumerate(data["items"]):
        match = score_attempt(item["text"], item["text"], [0.95], mode="beginner")
        apply_attempt(conn, sid, item["id"], match, queue_index=qi)
    done = complete_session(conn, sid)
    assert done["garden"]["growth"] == 1
    assert done["garden"]["stage"] == "sprout"
    assert done["garden"]["stage_before"] == "seed"
    assert done["garden"]["stage_changed"] is True

    # Second complete at growth 1→2 stays "sprout" — not a new stage name.
    save_settings({**load_settings(), "garden_growth": 1})
    data2 = start_session(conn, level=1, stage=1)
    sid2 = data2["session_id"]
    for qi, item in enumerate(data2["items"]):
        match = score_attempt(item["text"], item["text"], [0.95], mode="beginner")
        apply_attempt(conn, sid2, item["id"], match, queue_index=qi)
    done2 = complete_session(conn, sid2)
    assert done2["garden"]["stage"] == "sprout"
    assert done2["garden"]["stage_before"] == "sprout"
    assert done2["garden"]["stage_changed"] is False


def test_timings_rebuild_when_human_wav_newer(tmp_path, monkeypatch):
    from app import audio_files
    from app.audio_files import load_or_build_timings
    import struct
    import wave

    gen = tmp_path / "generated"
    human = tmp_path / "human"
    gen.mkdir()
    human.mkdir()
    monkeypatch.setattr(config, "AUDIO_GENERATED", gen)
    monkeypatch.setattr(config, "AUDIO_HUMAN", human)
    monkeypatch.setattr(audio_files.config, "AUDIO_GENERATED", gen)
    monkeypatch.setattr(audio_files.config, "AUDIO_HUMAN", human)

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
    assert first[0]["end"] <= 0.5
    time.sleep(0.05)
    write_wav(human / "cat.wav", 1.2)
    rebuilt = load_or_build_timings("cat", "cat")  # no force — mtime should rebuild
    assert rebuilt[0]["end"] >= 1.0


def test_garden_end_copy_checks_stage_changed():
    js = Path("static/js/game.js").read_text(encoding="utf-8")
    assert "stage_changed" in js
    assert "Your garden grew — it never shrinks." in js


def test_leitner_gaps_match_patterns_catalog():
    data = json.loads(Path("content/patterns.json").read_text(encoding="utf-8"))
    assert tuple(data["leitner_gaps_days"][:5]) == config.LEITNER_GAPS_DAYS
