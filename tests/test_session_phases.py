"""Phase gates: resume, one more miss, auto-strict step back, one poem, read-through."""

from __future__ import annotations

from app.adaptive import apply_level_and_auto_strict, build_adaptive_queue
from app.config import stage_label
from app.db import load_settings, save_settings
from app.matching import score_attempt
from app.parent import play_summary, tomorrow_note
from app.session import apply_passage, complete_session, open_session_view, start_session
from tests.helpers import post_attempt


def _miss_twice(conn, data, item, qi):
    match = score_attempt(item["text"], "zzzz", [0.95], mode="beginner")
    from app.session import apply_attempt

    first = apply_attempt(conn, data["session_id"], item["id"], match, queue_index=qi)
    second = apply_attempt(conn, data["session_id"], item["id"], match, queue_index=qi)
    return first, second


def test_open_session_resume(tmp_env):
    conn = tmp_env["conn"]
    data = start_session(conn, level=1)
    view = open_session_view(conn)
    assert view["open"] is True
    assert view["session_id"] == data["session_id"]
    assert view["index"] == 0
    assert view["items"]


def test_first_miss_stays_then_locks(tmp_env):
    conn = tmp_env["conn"]
    data = start_session(conn, level=1)
    item = data["items"][0]
    first, second = _miss_twice(conn, data, item, 0)
    assert first["read_again"] is True
    assert second["read_again"] is False


def test_auto_strict_steps_back_parent_strict_stays(tmp_env):
    settings = load_settings()
    settings.update(
        {
            "level": 1,
            "stage": 3,
            "mode": "strict",
            "mode_source": "auto",
            "auto_strict": True,
            "low_streak": 1,
            "move_up_streak": 0,
        }
    )
    _, stepped = apply_level_and_auto_strict(
        level=1, correct_count=1, planned_count=10, settings=settings
    )
    assert stepped["mode"] == "beginner"
    assert "beginner" in stepped["last_mode_change"]

    parent = dict(settings)
    parent["mode_source"] = "parent"
    parent["low_streak"] = 1
    _, kept = apply_level_and_auto_strict(
        level=1, correct_count=1, planned_count=10, settings=parent
    )
    assert kept["mode"] == "strict"
    assert kept["mode_source"] == "parent"


def test_rhyme_and_story_are_one_group(tmp_env):
    conn = tmp_env["conn"]
    poem = build_adaptive_queue(conn, level=3, length=10, stage=1)
    assert len({row["rhyme_group"] for row in poem}) == 1
    assert len(poem) >= 2
    assert all(row["kind"] == "line" for row in poem)
    story = build_adaptive_queue(conn, level=4, length=10, stage=2)
    assert len({row["story_id"] for row in story}) == 1
    assert story[0]["story_id"] != build_adaptive_queue(conn, level=4, length=10, stage=1)[0]["story_id"]
    # Each story line is a real sentence, not a bare word label.
    assert all(len(row["text"].split()) >= 4 for row in story)
    loose = [row for row in conn.execute("SELECT text FROM items WHERE level = 5")]
    assert not any(row["text"] == "The cat sat on the mat." for row in loose)
    assert not any(row["text"] == "The big dog" for row in loose)


def test_passage_omits_duration_and_parent_keeps_it(client, whisper_double, tone_wav, tmp_env):
    from app.whisper_engine import AttemptTranscript, TranscriptWord

    conn = tmp_env["conn"]
    save_settings({**load_settings(), "level": 3, "stage": 1})
    data = start_session(conn, level=3, stage=1)
    sid = data["session_id"]
    heard = " ".join(item["text"] for item in data["items"])
    whisper_double.set_transcript(
        AttemptTranscript(
            transcript=heard,
            words=[TranscriptWord(word=w, probability=0.95) for w in heard.split()],
            no_speech_prob=0.05,
        )
    )
    res = post_attempt(
        client,
        sid,
        data["items"][0]["id"],
        tone_wav.read_bytes(),
        phase="passage",
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["passage"] is True
    assert "duration_seconds" not in body
    note = tomorrow_note(conn, load_settings())
    assert note["read_through"]["words_total"] >= 1
    assert note["read_through"]["seconds"] is not None


def test_quest_names_the_set(tmp_env):
    summary = play_summary()
    assert summary["quest_label"] == stage_label(1, 1)
    settings = load_settings()
    settings["level"] = 2
    settings["stage"] = 3
    settings["stage_by_difficulty"]["2"] = 3
    save_settings(settings)
    assert "Phrases" in play_summary()["quest_label"]
    assert "Set 3" in play_summary()["quest_label"]


def test_word_picture_and_missed_word_mark():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    css = (root / "static/css/app.css").read_text(encoding="utf-8")
    js = (root / "static/js/game.js").read_text(encoding="utf-8")
    assert ".word-art.is-word" in css
    assert "is-word" in js
    assert "word-soft" in js
    assert "red" not in css.split(".word-soft", 1)[-1][:200]


def test_apply_passage_direct_has_no_duration_key(tmp_env):
    conn = tmp_env["conn"]
    data = start_session(conn, level=3, stage=1)
    text = " ".join(item["text"] for item in data["items"])
    match = score_attempt(text, text, [0.95] * len(text.split()), mode="beginner")
    payload = apply_passage(conn, data["session_id"], match, duration_seconds=4.2)
    assert "duration_seconds" not in payload
    done = complete_session(conn, data["session_id"])
    assert "mastered_words" in done
