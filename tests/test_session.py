"""Session / stars tests (no mic)."""

from __future__ import annotations

import json

from app.db import load_settings, save_settings
from app.matching import score_attempt
from app.session import apply_attempt, complete_session, start_session


def test_start_session_planned_length_and_ids(tmp_env):
    conn = tmp_env["conn"]
    data = start_session(conn, level=1)
    assert data["level"] == 1
    assert data["mode"] == "beginner"
    assert len(data["items"]) == 10
    row = conn.execute(
        "SELECT planned_count, planned_item_ids FROM sessions WHERE id = ?",
        (data["session_id"],),
    ).fetchone()
    assert row["planned_count"] == 10
    ids = json.loads(row["planned_item_ids"])
    assert ids == [item["id"] for item in data["items"]]


def test_correct_word_adds_star(tmp_env):
    conn = tmp_env["conn"]
    data = start_session(conn, level=1)
    item = data["items"][0]
    match = score_attempt(item["text"], item["text"], [0.95], mode="beginner")
    resp = apply_attempt(conn, data["session_id"], item["id"], match)
    assert resp["result"] == "correct"
    assert resp["stars_awarded"] == 1
    assert resp["stars_total"] == 1
    assert resp["skipped"] is False


def test_hard_bonus_first_try(tmp_env):
    conn = tmp_env["conn"]
    data = start_session(conn, level=3)
    item = data["items"][0]
    row = conn.execute("SELECT hard FROM items WHERE id = ?", (item["id"],)).fetchone()
    assert row["hard"] == 1
    match = score_attempt(item["text"], item["text"], [0.95], mode="beginner")
    resp = apply_attempt(conn, data["session_id"], item["id"], match)
    assert resp["result"] == "correct"
    assert resp["stars_awarded"] == 2  # word + hard bonus
    assert resp["stars_total"] == 2


def test_hard_bonus_not_on_close_second_take(tmp_env):
    conn = tmp_env["conn"]
    data = start_session(conn, level=3)
    item = data["items"][0]
    text = item["text"]
    # Manufacture a close: one-letter neighbor if possible, else use cot/cat pattern
    # Use matcher close via low confidence exact
    close_match = score_attempt(text, text, [0.40], mode="beginner")
    assert close_match.result == "close"
    first = apply_attempt(conn, data["session_id"], item["id"], close_match)
    assert first["again"] is True
    assert first["stars_awarded"] == 0

    second_match = score_attempt(text, text, [0.95], mode="beginner")
    second = apply_attempt(conn, data["session_id"], item["id"], second_match)
    assert second["result"] == "correct"
    assert second["again"] is False
    assert second["stars_awarded"] == 1  # no hard bonus
    assert second["stars_total"] == 1

    locks = conn.execute(
        """
        SELECT counts_for_session, result FROM attempts
        WHERE session_id = ? AND item_id = ?
        ORDER BY id
        """,
        (data["session_id"], item["id"]),
    ).fetchall()
    assert locks[0]["counts_for_session"] == 0
    assert locks[0]["result"] == "close"
    assert locks[1]["counts_for_session"] == 1
    assert locks[1]["result"] == "correct"


def test_stars_on_missed_item_partial_words(tmp_env):
    conn = tmp_env["conn"]
    data = start_session(conn, level=1)
    item = data["items"][0]
    # Inject a multi-word target by scoring against a phrase while using any planned item_id
    # Session stars logic uses match.words_correct — use big red bus fixture scoring
    match = score_attempt("a big red bus", "a big red", [0.95, 0.94, 0.93], mode="beginner")
    assert match.result == "missed"
    assert match.words_correct == 3
    resp = apply_attempt(conn, data["session_id"], item["id"], match)
    assert resp["result"] == "missed"
    assert resp["stars_awarded"] == 3
    assert resp["stars_total"] == 3


def test_replay_words_only_missed():
    match = score_attempt(
        "Quick brown fox jumped over the box",
        "Quick down fox jump over the dox",
        [0.95, 0.91, 0.94, 0.90, 0.93, 0.96, 0.88],
        mode="beginner",
    )
    assert match.replay_words == ["brown", "jumped"]


def test_three_retries_skip_decrements_planned(tmp_env):
    conn = tmp_env["conn"]
    data = start_session(conn, level=1)
    item = data["items"][0]
    sid = data["session_id"]
    for i in range(2):
        match = score_attempt(item["text"], "", mode="beginner", force_retry=True)
        resp = apply_attempt(conn, sid, item["id"], match, is_silence_path=True)
        assert resp["result"] == "retry"
        assert resp["retry"] is True
        assert resp["again"] is True
        assert resp["skipped"] is False

    match = score_attempt(item["text"], "", mode="beginner", force_retry=True)
    skip = apply_attempt(conn, sid, item["id"], match, is_silence_path=True)
    assert skip["result"] == "skipped"
    assert skip["skipped"] is True
    assert skip["retry"] is False
    assert skip["again"] is False
    assert skip["message"] == "We'll try that one another time."
    assert skip["transcript"] == ""
    assert skip["word_scores"] == []
    assert skip["words_total"] == 1

    row = conn.execute(
        "SELECT planned_count FROM sessions WHERE id = ?", (sid,)
    ).fetchone()
    assert row["planned_count"] == 9


def test_abandon_does_not_change_level(tmp_env):
    conn = tmp_env["conn"]
    settings = load_settings()
    settings["level"] = 2
    save_settings(settings)
    data = start_session(conn, level=2)
    # Abandon by starting a new session without complete
    start_session(conn, level=2)
    abandoned = conn.execute(
        "SELECT completed, ended_at FROM sessions WHERE id = ?",
        (data["session_id"],),
    ).fetchone()
    assert abandoned["completed"] == 0
    assert abandoned["ended_at"] is not None
    assert load_settings()["level"] == 2


def test_complete_replay_empty_m1(tmp_env):
    conn = tmp_env["conn"]
    data = start_session(conn, level=1)
    item = data["items"][0]
    match = score_attempt(item["text"], item["text"], [0.95], mode="beginner")
    apply_attempt(conn, data["session_id"], item["id"], match)
    done = complete_session(conn, data["session_id"])
    assert done["replay"] == []
    assert done["stars"] >= 1
    assert "correct_count" in done
    assert "planned_count" in done


def test_stars_never_decrease(tmp_env):
    conn = tmp_env["conn"]
    data = start_session(conn, level=1)
    a, b = data["items"][0], data["items"][1]
    r1 = apply_attempt(
        conn,
        data["session_id"],
        a["id"],
        score_attempt(a["text"], a["text"], [0.95], mode="beginner"),
    )
    r2 = apply_attempt(
        conn,
        data["session_id"],
        b["id"],
        score_attempt(b["text"], "zzzz", [0.95], mode="beginner"),
    )
    assert r2["stars_total"] >= r1["stars_total"]
    assert r2["stars_awarded"] == 0
