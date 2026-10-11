"""Milestone 3: level moves, ladder, mastery, reinsert, modes."""

from __future__ import annotations

import json
from datetime import date, timedelta

from app.adaptive import (
    apply_day_ladder,
    apply_level_and_auto_strict,
    build_adaptive_queue,
    move_up_score,
    under_half,
)
from app.db import load_settings, local_today, save_settings
from app.matching import score_attempt
from app.session import apply_attempt, complete_session, play_ids, start_session


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


def test_move_up_score_item_level_ratio():
    assert move_up_score(8, 10) is True
    assert move_up_score(7, 10) is False
    assert move_up_score(4, 5) is True  # 4*10 >= 8*5
    assert under_half(4, 10) is True
    assert under_half(5, 10) is False


def test_level_up_on_8_of_10(tmp_env):
    settings = load_settings()
    settings["level"] = 2
    settings["low_streak"] = 0
    settings["move_up_streak"] = 0
    save_settings(settings)
    level_after, new_s = apply_level_and_auto_strict(
        level=2, correct_count=8, planned_count=10, settings=settings
    )
    assert level_after == 3
    assert new_s["level"] == 3
    assert new_s["low_streak"] == 0
    assert new_s["move_up_streak"] == 1


def test_two_under_half_steps_down(tmp_env):
    settings = load_settings()
    settings["level"] = 3
    settings["low_streak"] = 1
    settings["move_up_streak"] = 2
    save_settings(settings)
    level_after, new_s = apply_level_and_auto_strict(
        level=3, correct_count=4, planned_count=10, settings=settings
    )
    assert level_after == 2
    assert new_s["low_streak"] == 0
    assert new_s["move_up_streak"] == 0


def test_five_of_ten_no_step_down(tmp_env):
    settings = load_settings()
    settings["level"] = 2
    settings["low_streak"] = 1
    save_settings(settings)
    level_after, new_s = apply_level_and_auto_strict(
        level=2, correct_count=5, planned_count=10, settings=settings
    )
    assert level_after == 2
    assert new_s["low_streak"] == 0
    assert new_s["move_up_streak"] == 0


def test_auto_strict_after_three_move_ups(tmp_env):
    settings = load_settings()
    settings.update(
        {
            "level": 1,
            "mode": "beginner",
            "auto_strict": True,
            "auto_strict_sessions": 3,
            "move_up_streak": 2,
        }
    )
    level_after, new_s = apply_level_and_auto_strict(
        level=1, correct_count=9, planned_count=10, settings=settings
    )
    assert level_after == 2
    assert new_s["move_up_streak"] == 3
    assert new_s["mode"] == "strict"


def test_auto_strict_off_skips(tmp_env):
    settings = load_settings()
    settings.update(
        {
            "level": 1,
            "mode": "beginner",
            "auto_strict": False,
            "move_up_streak": 2,
        }
    )
    _, new_s = apply_level_and_auto_strict(
        level=1, correct_count=9, planned_count=10, settings=settings
    )
    assert new_s["mode"] == "beginner"


def test_complete_applies_level_and_abandon_does_not(tmp_env):
    conn = tmp_env["conn"]
    settings = load_settings()
    settings["level"] = 1
    settings["session_length"] = 5
    settings["low_streak"] = 0
    save_settings(settings)
    data = start_session(conn, level=1)
    sid = data["session_id"]
    # Score all planned items correct → move up
    for qi, item in enumerate(data["items"]):
        _apply(
            conn,
            sid,
            item["id"],
            score_attempt(item["text"], item["text"], [0.95] * max(1, len(item["text"].split())), mode="beginner"),
            qi=qi,
        )
    done = complete_session(conn, sid)
    assert done["level_after"] == 2
    assert load_settings()["level"] == 2

    # Abandon does not change level
    settings = load_settings()
    settings["level"] = 4
    save_settings(settings)
    abandoned = start_session(conn, level=4)
    start_session(conn, level=4)
    assert load_settings()["level"] == 4
    row = conn.execute(
        "SELECT completed, ended_at FROM sessions WHERE id = ?",
        (abandoned["session_id"],),
    ).fetchone()
    assert row["completed"] == 0
    assert row["ended_at"] is not None


def test_same_session_miss_does_not_grow_queue(tmp_env):
    """Misses must not inflate a 5/10 session (no Word 3 of 11)."""
    conn = tmp_env["conn"]
    data = start_session(conn, level=1)
    sid = data["session_id"]
    item = data["items"][0]
    before = len(data["items"])
    assert before in (5, 10)
    assert data["planned_count"] == before
    resp = _apply(
        conn,
        sid,
        item["id"],
        score_attempt(item["text"], "zzzz", [0.95], mode="beginner"),
        qi=0,
    )
    assert resp["result"] == "missed"
    assert resp["reinsert"] is None
    play = play_ids(conn.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone())
    assert len(play) == before
    row = conn.execute(
        "SELECT planned_count FROM sessions WHERE id = ?", (sid,)
    ).fetchone()
    assert row["planned_count"] == before


def test_exhausted_level_queue_stays_unique(tmp_env):
    """Few unmastered in Words → unique 5-pack (pad with mastered, never repeat)."""
    conn = tmp_env["conn"]
    # Words difficulty spans content levels 1–3.
    words = conn.execute(
        "SELECT id FROM items WHERE level IN (1, 2, 3) ORDER BY id"
    ).fetchall()
    keep = {words[0]["id"], words[1]["id"]}
    for row in words:
        if row["id"] in keep:
            conn.execute(
                """
                INSERT INTO mastery (item_id, correct_count, days_json, miss_count,
                  review_step, next_review_on, mastered)
                VALUES (?, 0, '[]', 0, 0, NULL, 0)
                ON CONFLICT(item_id) DO UPDATE SET mastered=0, correct_count=0,
                  next_review_on=NULL
                """,
                (row["id"],),
            )
        else:
            conn.execute(
                """
                INSERT INTO mastery (item_id, correct_count, days_json, miss_count,
                  review_step, next_review_on, mastered, last_seen_on)
                VALUES (?, 3, ?, 0, 0, NULL, 1, '2020-01-01')
                ON CONFLICT(item_id) DO UPDATE SET mastered=1, correct_count=3,
                  next_review_on=NULL, last_seen_on='2020-01-01'
                """,
                (row["id"], json.dumps(["2020-01-01", "2020-01-02"])),
            )
    conn.commit()

    queue = build_adaptive_queue(conn, level=1, length=10)
    queue_ids = [row["id"] for row in queue]
    assert len(queue_ids) == len(set(queue_ids))
    assert keep <= set(queue_ids)
    # Pad with mastered to a uniform 10 — never duplicates, never 6–9.
    assert len(queue_ids) == 10
    assert len([i for i in queue_ids if i in keep]) == 2

    data = start_session(conn, level=1)
    sid = data["session_id"]
    ids = [i["id"] for i in data["items"]]
    assert len(ids) == len(set(ids))
    assert len(ids) == 10
    assert keep <= set(ids)

    for qi, item in enumerate(data["items"]):
        resp = _apply(
            conn,
            sid,
            item["id"],
            score_attempt(
                item["text"],
                item["text"],
                [0.95] * max(1, len(item["text"].split())),
                mode="beginner",
            ),
            qi=qi,
        )
        assert resp["result"] == "correct"

    row = conn.execute(
        "SELECT correct_count, planned_count FROM sessions WHERE id = ?", (sid,)
    ).fetchone()
    assert row["planned_count"] == len(ids)
    assert row["correct_count"] == len(ids)


def test_session_planned_items_are_unique(tmp_env):
    """Fresh level-1 start: a 10-word set must not contain duplicate item ids."""
    conn = tmp_env["conn"]
    level1_n = conn.execute(
        "SELECT COUNT(*) AS n FROM items WHERE level = 1"
    ).fetchone()["n"]
    assert level1_n >= 10

    queue = build_adaptive_queue(conn, level=1, length=10)
    assert len(queue) == 10
    assert len({row["id"] for row in queue}) == 10

    data = start_session(conn, level=1)
    ids = [i["id"] for i in data["items"]]
    assert len(ids) == 10
    assert len(set(ids)) == 10


def test_five_remaining_words_do_not_repeat_to_ten(tmp_env):
    """Five fresh Words + mastered padding → uniform 10 unique ids, never 5×2 repeats."""
    conn = tmp_env["conn"]
    words = conn.execute(
        "SELECT id FROM items WHERE level IN (1, 2, 3) ORDER BY id"
    ).fetchall()
    assert len(words) >= 10
    keep = {row["id"] for row in words[:5]}
    mastered_ids = {row["id"] for row in words[5:]}

    for item_id in mastered_ids:
        conn.execute(
            """
            INSERT INTO mastery (item_id, correct_count, days_json, miss_count,
              review_step, next_review_on, mastered, last_seen_on)
            VALUES (?, 3, ?, 0, 0, NULL, 1, '2020-01-01')
            ON CONFLICT(item_id) DO UPDATE SET mastered=1, correct_count=3,
              next_review_on=NULL, last_seen_on='2020-01-01'
            """,
            (item_id, json.dumps(["2020-01-01", "2020-01-02"])),
        )
    for item_id in keep:
        conn.execute(
            """
            INSERT INTO mastery (item_id, correct_count, days_json, miss_count,
              review_step, next_review_on, mastered)
            VALUES (?, 0, '[]', 0, 0, NULL, 0)
            ON CONFLICT(item_id) DO UPDATE SET mastered=0, correct_count=0
            """,
            (item_id,),
        )
    conn.commit()

    queue = build_adaptive_queue(conn, level=1, length=10)
    queue_ids = [row["id"] for row in queue]
    assert len(queue_ids) == len(set(queue_ids))
    assert keep <= set(queue_ids)
    assert len(queue_ids) == 10

    data = start_session(conn, level=1)
    ids = [i["id"] for i in data["items"]]
    assert len(ids) == 10
    assert len(set(ids)) == 10
    assert keep <= set(ids)
    row = conn.execute(
        "SELECT planned_count FROM sessions WHERE id = ?",
        (data["session_id"],),
    ).fetchone()
    assert row["planned_count"] == 10


def test_miss_keeps_planned_count_for_ratio(tmp_env):
    """A miss locks the planned slot; planned_count stays 5 or 10 for the ratio."""
    conn = tmp_env["conn"]
    data = start_session(conn, level=1)
    sid = data["session_id"]
    item = data["items"][0]
    planned_n = int(
        conn.execute(
            "SELECT planned_count FROM sessions WHERE id = ?", (sid,)
        ).fetchone()["planned_count"]
    )
    assert planned_n in (5, 10)
    miss = _apply(
        conn,
        sid,
        item["id"],
        score_attempt(item["text"], "zzzz", [0.95], mode="beginner"),
        qi=0,
    )
    assert miss["result"] == "missed"
    assert miss["reinsert"] is None
    row = conn.execute(
        "SELECT correct_count, planned_count FROM sessions WHERE id = ?", (sid,)
    ).fetchone()
    assert row["correct_count"] == 0
    assert row["planned_count"] == planned_n
    # Rest of the planned set still scores against the same N.
    for qi, it in enumerate(data["items"][1:], start=1):
        _apply(
            conn,
            sid,
            it["id"],
            score_attempt(it["text"], it["text"], [0.95], mode="beginner"),
            qi=qi,
        )
    after = conn.execute(
        "SELECT correct_count, planned_count FROM sessions WHERE id = ?", (sid,)
    ).fetchone()
    assert after["planned_count"] == planned_n
    assert after["correct_count"] == planned_n - 1


def test_day_ladder_and_mastery(tmp_env):
    conn = tmp_env["conn"]
    item_id = conn.execute("SELECT id FROM items WHERE slug='cat'").fetchone()["id"]
    apply_day_ladder(conn, item_id, "missed")
    row = conn.execute("SELECT * FROM mastery WHERE item_id=?", (item_id,)).fetchone()
    assert row["review_step"] == 1
    assert row["next_review_on"] == (date.fromisoformat(local_today()) + timedelta(days=1)).isoformat()

    apply_day_ladder(conn, item_id, "missed")
    row = conn.execute("SELECT * FROM mastery WHERE item_id=?", (item_id,)).fetchone()
    assert row["review_step"] == 3

    apply_day_ladder(conn, item_id, "missed")
    row = conn.execute("SELECT * FROM mastery WHERE item_id=?", (item_id,)).fetchone()
    assert row["review_step"] == 7

    # Mastery: 3 corrects on >= 2 days
    conn.execute(
        "UPDATE mastery SET correct_count=0, days_json='[]', mastered=0, review_step=0, next_review_on=NULL WHERE item_id=?",
        (item_id,),
    )
    conn.commit()
    # Day 1
    apply_day_ladder(conn, item_id, "correct")
    # Fake prior day
    conn.execute(
        "UPDATE mastery SET days_json=? WHERE item_id=?",
        (json.dumps(["2020-01-01"]), item_id),
    )
    conn.commit()
    apply_day_ladder(conn, item_id, "correct")
    apply_day_ladder(conn, item_id, "correct")
    row = conn.execute("SELECT * FROM mastery WHERE item_id=?", (item_id,)).fetchone()
    assert row["correct_count"] >= 3
    assert row["mastered"] == 1
    assert row["next_review_on"] is None


def test_queue_due_before_unmastered(tmp_env):
    conn = tmp_env["conn"]
    # Make a level-2 item due
    due = conn.execute(
        "SELECT id FROM items WHERE level=2 ORDER BY id LIMIT 1"
    ).fetchone()
    conn.execute(
        """
        INSERT INTO mastery (item_id, correct_count, days_json, miss_count, review_step, next_review_on, mastered)
        VALUES (?, 0, '[]', 1, 1, ?, 0)
        ON CONFLICT(item_id) DO UPDATE SET
          next_review_on=excluded.next_review_on, review_step=1, mastered=0
        """,
        (due["id"], local_today()),
    )
    conn.commit()
    queue = build_adaptive_queue(conn, level=1, length=10)
    assert queue[0]["id"] == due["id"]


def test_start_session_four_difficulty_tiers(tmp_env):
    """Difficulties 1–4 map to words / phrases / rhymes / stories content."""
    from app.config import DIFFICULTY_TIERS, content_levels_for_difficulty

    conn = tmp_env["conn"]
    expect = {
        1: {"label": "Words", "kinds": {"word"}},
        2: {"label": "Phrases", "kinds": {"phrase"}},
        3: {"label": "Rhymes", "kinds": {"line"}},
        4: {"label": "Stories", "kinds": {"sentence"}},
    }
    for difficulty, meta in expect.items():
        data = start_session(conn, level=difficulty)
        assert data["level"] == difficulty
        assert data["difficulty"] == difficulty
        assert data["difficulty_label"] == meta["label"]
        assert len(data["items"]) in (5, 10)
        assert len(data["items"]) == len({i["id"] for i in data["items"]})
        kinds = {i["kind"] for i in data["items"]}
        assert kinds <= meta["kinds"]
        content_levels = set(content_levels_for_difficulty(difficulty))
        assert content_levels == set(DIFFICULTY_TIERS[difficulty]["content_levels"])


def test_legacy_content_level_maps_into_difficulty(tmp_env):
    """Old content picks 5–7 still start a session in the matching tier."""
    conn = tmp_env["conn"]
    data = start_session(conn, level=7)
    assert data["level"] == 3
    assert data["difficulty_label"] == "Rhymes"
    assert all(i["kind"] == "line" for i in data["items"])
    data = start_session(conn, level=5)
    assert data["level"] == 4
    assert data["difficulty_label"] == "Stories"
    assert all(i["kind"] == "sentence" for i in data["items"])


def test_strict_mode_on_session(tmp_env):
    conn = tmp_env["conn"]
    settings = load_settings()
    settings["mode"] = "strict"
    save_settings(settings)
    data = start_session(conn, level=1)
    assert data["mode"] == "strict"
    item = data["items"][0]
    # Plural: Beginner would accept cats for cat; Strict misses
    match = score_attempt(item["text"], item["text"] + "s", [0.95], mode="strict")
    if item["text"] == "cat":
        assert match.result == "missed"
    resp = _apply(conn, data["session_id"], item["id"], match, qi=0)
    assert resp["result"] == match.result


def test_all_mastered_queue_fills_uniform_length(tmp_env):
    """All Words mastered → unique refresher set of 5 or 10, never empty/503."""
    conn = tmp_env["conn"]
    words = conn.execute(
        "SELECT id FROM items WHERE level IN (1, 2, 3) ORDER BY id"
    ).fetchall()
    assert len(words) >= 10
    for row in words:
        conn.execute(
            """
            INSERT INTO mastery (
              item_id, correct_count, days_json, miss_count, review_step,
              next_review_on, mastered, mastered_on, last_seen_on
            ) VALUES (?, 3, ?, 0, 0, NULL, 1, '2020-01-01', '2020-01-01')
            ON CONFLICT(item_id) DO UPDATE SET
              mastered=1, correct_count=3, next_review_on=NULL,
              last_seen_on='2020-01-01', days_json=excluded.days_json
            """,
            (row["id"], json.dumps(["2020-01-01", "2020-01-02"])),
        )
    conn.commit()

    queue = build_adaptive_queue(conn, level=1, length=10)
    assert len(queue) == 10
    assert len({row["id"] for row in queue}) == 10
    for row in queue:
        m = conn.execute(
            "SELECT mastered FROM mastery WHERE item_id = ?", (row["id"],)
        ).fetchone()
        assert int(m["mastered"]) == 1

    data = start_session(conn, level=1)
    assert len(data["items"]) == 10
    row = conn.execute(
        "SELECT planned_count FROM sessions WHERE id = ?",
        (data["session_id"],),
    ).fetchone()
    assert row["planned_count"] == 10


def test_all_mastered_ineligible_refresher_does_not_503(tmp_env):
    """C7: ineligible gated refreshers still pad to 5/10 — never 503."""
    from app.db import local_now_iso
    from app.session import SessionError

    conn = tmp_env["conn"]
    words = conn.execute(
        "SELECT id FROM items WHERE level IN (1, 2, 3) ORDER BY id"
    ).fetchall()
    for row in words:
        conn.execute(
            """
            INSERT INTO mastery (
              item_id, correct_count, days_json, miss_count, review_step,
              next_review_on, mastered, mastered_on, last_seen_on
            ) VALUES (?, 3, ?, 0, 0, NULL, 1, ?, ?)
            ON CONFLICT(item_id) DO UPDATE SET
              mastered=1, correct_count=3, next_review_on=NULL,
              last_seen_on=excluded.last_seen_on, days_json=excluded.days_json
            """,
            (
                row["id"],
                json.dumps(["2020-01-01", "2020-01-02"]),
                local_today(),
                local_today(),
            ),
        )
    # Completed session + attempts → sessions_since_item == 0 (ineligible gate).
    cur = conn.execute(
        """
        INSERT INTO sessions (
          started_at, ended_at, mode, level, planned_count, planned_item_ids,
          play_item_ids, ratio_flags, correct_count, stars, low_session,
          level_after, completed
        ) VALUES (?, ?, 'beginner', 1, 1, ?, ?, '[true]', 1, 0, 0, 1, 1)
        """,
        (
            local_now_iso(),
            local_now_iso(),
            json.dumps([words[0]["id"]]),
            json.dumps([words[0]["id"]]),
        ),
    )
    sid = int(cur.lastrowid)
    for row in words:
        conn.execute(
            """
            INSERT INTO attempts (
              session_id, item_id, heard, confidence, word_scores, result,
              counts_for_session, is_replay, queue_index, replay_word, created_at
            ) VALUES (?, ?, '', NULL, '[]', 'correct', 1, 0, 0, '', ?)
            """,
            (sid, row["id"], local_now_iso()),
        )
    conn.commit()

    from app.adaptive import sessions_since_item

    assert sessions_since_item(conn, words[0]["id"]) < 7

    queue = build_adaptive_queue(conn, level=1, length=10)
    assert len(queue) == 10
    m = conn.execute(
        "SELECT mastered FROM mastery WHERE item_id = ?", (queue[0]["id"],)
    ).fetchone()
    assert m["mastered"] == 1

    try:
        data = start_session(conn, level=1)
    except SessionError as exc:
        raise AssertionError(f"start must not 503: {exc.code} {exc.message}") from exc
    assert len(data["items"]) == 10
    assert data["level"] == 1


def test_start_session_uses_settings_level_when_omitted(tmp_env):
    """C6: omit level → settings.level (adaptive path after level_after)."""
    conn = tmp_env["conn"]
    settings = load_settings()
    settings["level"] = 3
    save_settings(settings)
    data = start_session(conn, level=None)
    assert data["level"] == 3
    assert len(data["items"]) >= 1
