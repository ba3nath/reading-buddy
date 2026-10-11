"""Session / stars tests (no mic)."""

from __future__ import annotations

import json

from app.db import load_settings, save_settings
from app.matching import score_attempt
from app.session import (
    SessionError,
    apply_attempt,
    complete_session,
    play_ids,
    ratio_flags,
    set_play_and_ratio_flags,
    set_play_ids,
    start_session,
)


def _apply(conn, sid, item_id, match, *, qi, phase="read", word="", silence=False):
    return apply_attempt(
        conn,
        sid,
        item_id,
        match,
        phase=phase,
        is_silence_path=silence,
        queue_index=qi if phase == "read" else None,
        replay_word=word,
    )


def test_start_session_planned_length_and_ids(tmp_env):
    conn = tmp_env["conn"]
    data = start_session(conn, level=1)
    assert data["level"] == 1
    assert data["mode"] == "beginner"
    assert len(data["items"]) == 10
    row = conn.execute(
        "SELECT planned_count, planned_item_ids, play_item_ids FROM sessions WHERE id = ?",
        (data["session_id"],),
    ).fetchone()
    assert row["planned_count"] == 10
    ids = json.loads(row["planned_item_ids"])
    assert ids == [item["id"] for item in data["items"]]
    assert json.loads(row["play_item_ids"]) == ids


def test_correct_word_adds_star(tmp_env):
    conn = tmp_env["conn"]
    data = start_session(conn, level=1)
    item = data["items"][0]
    match = score_attempt(item["text"], item["text"], [0.95], mode="beginner")
    resp = _apply(conn, data["session_id"], item["id"], match, qi=0)
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
    resp = _apply(conn, data["session_id"], item["id"], match, qi=0)
    assert resp["result"] == "correct"
    assert resp["stars_awarded"] == 2  # word + hard bonus
    assert resp["stars_total"] == 2


def test_hard_bonus_not_on_close_second_take(tmp_env):
    conn = tmp_env["conn"]
    data = start_session(conn, level=3)
    item = data["items"][0]
    text = item["text"]
    close_match = score_attempt(text, text, [0.40], mode="beginner")
    assert close_match.result == "close"
    first = _apply(conn, data["session_id"], item["id"], close_match, qi=0)
    assert first["again"] is True
    assert first["stars_awarded"] == 0

    second_match = score_attempt(text, text, [0.95], mode="beginner")
    second = _apply(conn, data["session_id"], item["id"], second_match, qi=0)
    assert second["result"] == "correct"
    assert second["again"] is False
    assert second["stars_awarded"] == 1  # no hard bonus
    assert second["stars_total"] == 1

    locks = conn.execute(
        """
        SELECT counts_for_session, result, queue_index FROM attempts
        WHERE session_id = ? AND item_id = ?
        ORDER BY id
        """,
        (data["session_id"], item["id"]),
    ).fetchall()
    assert locks[0]["counts_for_session"] == 0
    assert locks[0]["result"] == "close"
    assert locks[0]["queue_index"] == 0
    assert locks[1]["counts_for_session"] == 1
    assert locks[1]["result"] == "correct"


def test_stars_on_missed_item_partial_words(tmp_env):
    conn = tmp_env["conn"]
    data = start_session(conn, level=1)
    item = data["items"][0]
    match = score_attempt("a big red bus", "a big red", [0.95, 0.94, 0.93], mode="beginner")
    assert match.result == "missed"
    assert match.words_correct == 3
    resp = _apply(conn, data["session_id"], item["id"], match, qi=0)
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
    for _ in range(2):
        match = score_attempt(item["text"], "", mode="beginner", force_retry=True)
        resp = _apply(conn, sid, item["id"], match, qi=0, silence=True)
        assert resp["result"] == "retry"
        assert resp["retry"] is True
        assert resp["again"] is True
        assert resp["skipped"] is False

    match = score_attempt(item["text"], "", mode="beginner", force_retry=True)
    skip = _apply(conn, sid, item["id"], match, qi=0, silence=True)
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

    attempt_rows = conn.execute(
        """
        SELECT result, counts_for_session, queue_index FROM attempts
        WHERE session_id = ? AND item_id = ?
        ORDER BY id
        """,
        (sid, item["id"]),
    ).fetchall()
    assert [r["result"] for r in attempt_rows] == ["retry", "retry", "skipped"]
    assert all(r["counts_for_session"] == 0 for r in attempt_rows)
    assert all(r["queue_index"] == 0 for r in attempt_rows)


def test_retry_counts_for_session_zero(tmp_env):
    conn = tmp_env["conn"]
    data = start_session(conn, level=1)
    item = data["items"][0]
    _apply(
        conn,
        data["session_id"],
        item["id"],
        score_attempt(item["text"], "", mode="beginner", force_retry=True),
        qi=0,
        silence=True,
    )
    row = conn.execute(
        """
        SELECT counts_for_session, result FROM attempts
        WHERE session_id = ? AND item_id = ?
        """,
        (data["session_id"], item["id"]),
    ).fetchone()
    assert row["result"] == "retry"
    assert row["counts_for_session"] == 0


def test_reject_repost_after_lock(tmp_env):
    conn = tmp_env["conn"]
    data = start_session(conn, level=1)
    item = data["items"][0]
    first = _apply(
        conn,
        data["session_id"],
        item["id"],
        score_attempt(item["text"], item["text"], [0.95], mode="beginner"),
        qi=0,
    )
    assert first["stars_total"] == 1
    try:
        _apply(
            conn,
            data["session_id"],
            item["id"],
            score_attempt(item["text"], item["text"], [0.95], mode="beginner"),
            qi=0,
        )
        raise AssertionError("expected SessionError on re-POST")
    except SessionError as exc:
        assert exc.status == 409
        assert exc.code == "already_resolved"
    session = conn.execute(
        "SELECT stars, correct_count FROM sessions WHERE id = ?",
        (data["session_id"],),
    ).fetchone()
    assert session["stars"] == 1
    assert session["correct_count"] == 1
    locks = conn.execute(
        """
        SELECT COUNT(*) AS n FROM attempts
        WHERE session_id = ? AND queue_index = 0 AND counts_for_session = 1
        """,
        (data["session_id"],),
    ).fetchone()
    assert locks["n"] == 1


def test_same_item_reinsert_slot_not_blocked(tmp_env):
    """R1: locking queue_index 0 must not block a later slot with the same item_id."""
    conn = tmp_env["conn"]
    data = start_session(conn, level=1)
    item = data["items"][0]
    sid = data["session_id"]
    _apply(
        conn,
        sid,
        item["id"],
        score_attempt(item["text"], "zzzz", [0.95], mode="beginner"),
        qi=0,
    )
    # Simulate same-session reinsert at end of play queue (ratio flag false)
    session = conn.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
    ids = play_ids(session)
    flags = ratio_flags(session)
    ids.append(item["id"])
    flags.append(False)
    set_play_and_ratio_flags(conn, sid, ids, flags)
    conn.commit()
    re_qi = len(ids) - 1
    before = conn.execute(
        "SELECT correct_count FROM sessions WHERE id = ?", (sid,)
    ).fetchone()["correct_count"]
    second = _apply(
        conn,
        sid,
        item["id"],
        score_attempt(item["text"], item["text"], [0.95], mode="beginner"),
        qi=re_qi,
    )
    assert second["result"] == "correct"
    assert second["stars_awarded"] == 1
    after = conn.execute(
        "SELECT correct_count FROM sessions WHERE id = ?", (sid,)
    ).fetchone()["correct_count"]
    assert after == before  # reinsert does not count for ratio


def test_abandon_does_not_change_level(tmp_env):
    conn = tmp_env["conn"]
    settings = load_settings()
    settings["level"] = 2
    save_settings(settings)
    data = start_session(conn, level=2)
    start_session(conn, level=2)
    abandoned = conn.execute(
        "SELECT completed, ended_at FROM sessions WHERE id = ?",
        (data["session_id"],),
    ).fetchone()
    assert abandoned["completed"] == 0
    assert abandoned["ended_at"] is not None
    assert load_settings()["level"] == 2


def test_complete_rejects_abandoned(tmp_env):
    conn = tmp_env["conn"]
    data = start_session(conn, level=1)
    start_session(conn, level=1)  # abandons prior
    try:
        complete_session(conn, data["session_id"])
        raise AssertionError("expected SessionError")
    except SessionError as exc:
        assert exc.status == 409
        assert exc.code == "session_closed"


def test_complete_replay_empty_when_no_misses(tmp_env):
    conn = tmp_env["conn"]
    data = start_session(conn, level=1)
    item = data["items"][0]
    match = score_attempt(item["text"], item["text"], [0.95], mode="beginner")
    _apply(conn, data["session_id"], item["id"], match, qi=0)
    done = complete_session(conn, data["session_id"])
    assert done["replay"] == []
    assert done["stars"] >= 1
    assert "correct_count" in done
    assert "planned_count" in done


def test_replay_close_locks_without_again(tmp_env):
    """C1 regression: replay close must not offer again=true then 409 the second take."""
    conn = tmp_env["conn"]
    data = start_session(conn, level=1)
    item = next((i for i in data["items"] if i["text"] == "cat"), data["items"][0])
    sid = data["session_id"]
    _apply(
        conn,
        sid,
        item["id"],
        score_attempt(item["text"], "zzzz", [0.95], mode="beginner"),
        qi=data["items"].index(item),
    )
    done = complete_session(conn, sid)
    assert done["replay"]
    word = done["replay"][0]["text"]
    planned = done["planned_count"]
    correct = done["correct_count"]

    close = _apply(
        conn,
        sid,
        item["id"],
        score_attempt(word, word, [0.40], mode="beginner"),
        qi=None,
        phase="replay",
        word=word,
    )
    assert close["result"] == "close"
    assert close["again"] is False
    assert close["retry"] is False
    assert close["skipped"] is False
    assert close["message"] == "Nice try — on to the next!"
    assert close.get("read_again") is False

    session = conn.execute(
        "SELECT correct_count, planned_count FROM sessions WHERE id = ?",
        (sid,),
    ).fetchone()
    assert session["correct_count"] == correct
    assert session["planned_count"] == planned

    try:
        _apply(
            conn,
            sid,
            item["id"],
            score_attempt(word, word, [0.95], mode="beginner"),
            qi=None,
            phase="replay",
            word=word,
        )
        raise AssertionError("second replay after locked close should 409")
    except SessionError as exc:
        assert exc.status == 409
        assert exc.code == "already_resolved"


def test_replay_awards_stars_without_changing_ratio(tmp_env):
    conn = tmp_env["conn"]
    data = start_session(conn, level=1)
    item = data["items"][0]
    sid = data["session_id"]
    _apply(
        conn,
        sid,
        item["id"],
        score_attempt(item["text"], "zzzz", [0.95], mode="beginner"),
        qi=0,
    )
    done = complete_session(conn, sid)
    assert done["correct_count"] == 0
    planned = done["planned_count"]
    stars_before = done["stars"]
    assert len(done["replay"]) == 1
    assert done["replay"][0]["item_id"] == item["id"]
    word = done["replay"][0]["text"]

    replay = _apply(
        conn,
        sid,
        item["id"],
        score_attempt(word, word, [0.95], mode="beginner"),
        qi=None,
        phase="replay",
        word=word,
    )
    assert replay["result"] == "correct"
    assert replay["stars_awarded"] == 1
    assert replay["stars_total"] == stars_before + 1

    session = conn.execute(
        "SELECT correct_count, planned_count, stars FROM sessions WHERE id = ?",
        (sid,),
    ).fetchone()
    assert session["correct_count"] == 0
    assert session["planned_count"] == planned
    assert session["stars"] == stars_before + 1

    row = conn.execute(
        """
        SELECT is_replay, counts_for_session, replay_word FROM attempts
        WHERE session_id = ? AND is_replay = 1
        """,
        (sid,),
    ).fetchone()
    assert row["is_replay"] == 1
    assert row["counts_for_session"] == 0
    assert row["replay_word"] == word

    mastery = conn.execute(
        "SELECT correct_count FROM mastery WHERE item_id = ?",
        (item["id"],),
    ).fetchone()
    assert mastery["correct_count"] >= 1


def test_word_level_replay_multi_word_item(tmp_env):
    """R2: score/audio target the missed word, not the full phrase."""
    from app.db import normalize_text
    from app.session import missed_replay_entries

    conn = tmp_env["conn"]
    # Inject a phrase item and use it as the sole play slot
    conn.execute(
        """
        INSERT INTO items (
          slug, text, normalized, kind, level, sound_tags, sounds_locked,
          rhyme_group, line_index, source, pd_status, hard
        ) VALUES (?, ?, ?, 'phrase', 1, '[]', 0, NULL, NULL, 'test', 'n/a', 0)
        """,
        (
            "a-big-red-bus",
            "a big red bus",
            normalize_text("a big red bus"),
        ),
    )
    conn.commit()
    phrase = conn.execute(
        "SELECT * FROM items WHERE slug = 'a-big-red-bus'"
    ).fetchone()
    # Ensure word-level slug for bus exists (level-1 bus)
    bus = conn.execute("SELECT slug FROM items WHERE text = 'bus'").fetchone()
    assert bus is not None

    data = start_session(conn, level=1)
    sid = data["session_id"]
    set_play_ids(conn, sid, [phrase["id"]])
    conn.execute(
        "UPDATE sessions SET planned_item_ids = ?, planned_count = 1 WHERE id = ?",
        (json.dumps([phrase["id"]]), sid),
    )
    conn.commit()

    match = score_attempt(
        "a big red bus", "a big red", [0.95, 0.94, 0.93], mode="beginner"
    )
    assert match.result == "missed"
    assert "bus" in match.replay_words
    _apply(conn, sid, phrase["id"], match, qi=0)
    done = complete_session(conn, sid)
    assert len(done["replay"]) == 1
    entry = done["replay"][0]
    assert entry["text"] == "bus"
    assert entry["word"] == "bus"
    assert entry["audio_url"] == f"/api/audio/{bus['slug']}"
    assert entry["item_id"] == phrase["id"]

    # Score only the word "bus" on replay
    replay = _apply(
        conn,
        sid,
        phrase["id"],
        score_attempt("bus", "bus", [0.95], mode="beginner"),
        qi=None,
        phase="replay",
        word="bus",
    )
    assert replay["result"] == "correct"
    assert replay["words_total"] == 1

    # Second missed word on same item would get its own replay key
    entries = missed_replay_entries(conn, sid)
    # locking attempt already done; entries still list missed words from read
    assert any(e["text"] == "bus" for e in entries)


def test_multi_word_replay_keys_independent(tmp_env):
    """R1+R2: two missed words on one item each get their own replay lock."""
    from app.db import normalize_text

    conn = tmp_env["conn"]
    conn.execute(
        """
        INSERT INTO items (
          slug, text, normalized, kind, level, sound_tags, sounds_locked,
          rhyme_group, line_index, source, pd_status, hard
        ) VALUES (?, ?, ?, 'sentence', 1, '[]', 0, NULL, NULL, 'test', 'n/a', 0)
        """,
        (
            "fox-line",
            "Quick brown fox jumped over the box",
            normalize_text("Quick brown fox jumped over the box"),
        ),
    )
    conn.commit()
    item = conn.execute("SELECT * FROM items WHERE slug = 'fox-line'").fetchone()
    data = start_session(conn, level=1)
    sid = data["session_id"]
    set_play_ids(conn, sid, [item["id"]])
    conn.execute(
        "UPDATE sessions SET planned_item_ids = ?, planned_count = 1 WHERE id = ?",
        (json.dumps([item["id"]]), sid),
    )
    conn.commit()

    match = score_attempt(
        "Quick brown fox jumped over the box",
        "Quick down fox jump over the dox",
        [0.95, 0.91, 0.94, 0.90, 0.93, 0.96, 0.88],
        mode="beginner",
    )
    assert match.replay_words == ["brown", "jumped"]
    _apply(conn, sid, item["id"], match, qi=0)
    done = complete_session(conn, sid)
    texts = [e["text"] for e in done["replay"]]
    assert texts == ["brown", "jumped"]

    first = _apply(
        conn,
        sid,
        item["id"],
        score_attempt("brown", "brown", [0.95], mode="beginner"),
        qi=None,
        phase="replay",
        word="brown",
    )
    assert first["result"] == "correct"

    # Second word still open
    second = _apply(
        conn,
        sid,
        item["id"],
        score_attempt("jumped", "jumped", [0.95], mode="beginner"),
        qi=None,
        phase="replay",
        word="jumped",
    )
    assert second["result"] == "correct"

    try:
        _apply(
            conn,
            sid,
            item["id"],
            score_attempt("brown", "brown", [0.95], mode="beginner"),
            qi=None,
            phase="replay",
            word="brown",
        )
        raise AssertionError("brown replay should already be resolved")
    except SessionError as exc:
        assert exc.code == "already_resolved"
        assert exc.status == 409


def test_409_codes_distinct_session_closed_vs_already_resolved(tmp_env):
    """R3: closed session vs lock conflict use different error codes."""
    conn = tmp_env["conn"]
    data = start_session(conn, level=1)
    item = data["items"][0]
    sid = data["session_id"]
    _apply(
        conn,
        sid,
        item["id"],
        score_attempt(item["text"], item["text"], [0.95], mode="beginner"),
        qi=0,
    )
    try:
        _apply(
            conn,
            sid,
            item["id"],
            score_attempt(item["text"], item["text"], [0.95], mode="beginner"),
            qi=0,
        )
        raise AssertionError("expected already_resolved")
    except SessionError as exc:
        assert exc.status == 409
        assert exc.code == "already_resolved"

    complete_session(conn, sid)
    try:
        _apply(
            conn,
            sid,
            data["items"][1]["id"],
            score_attempt(
                data["items"][1]["text"],
                data["items"][1]["text"],
                [0.95],
                mode="beginner",
            ),
            qi=1,
        )
        raise AssertionError("expected session_closed")
    except SessionError as exc:
        assert exc.status == 409
        assert exc.code == "session_closed"


def test_stars_never_decrease(tmp_env):
    conn = tmp_env["conn"]
    data = start_session(conn, level=1)
    a, b = data["items"][0], data["items"][1]
    r1 = _apply(
        conn,
        data["session_id"],
        a["id"],
        score_attempt(a["text"], a["text"], [0.95], mode="beginner"),
        qi=0,
    )
    r2 = _apply(
        conn,
        data["session_id"],
        b["id"],
        score_attempt(b["text"], "zzzz", [0.95], mode="beginner"),
        qi=1,
    )
    assert r2["stars_total"] >= r1["stars_total"]
    assert r2["stars_awarded"] == 0
