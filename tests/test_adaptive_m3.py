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


def test_same_session_miss_reinsert(tmp_env):
    conn = tmp_env["conn"]
    data = start_session(conn, level=1)
    sid = data["session_id"]
    item = data["items"][0]
    before = len(data["items"])
    resp = _apply(
        conn,
        sid,
        item["id"],
        score_attempt(item["text"], "zzzz", [0.95], mode="beginner"),
        qi=0,
    )
    assert resp["result"] == "missed"
    assert resp["reinsert"] is not None
    assert resp["reinsert"]["item"]["id"] == item["id"]
    assert resp["reinsert"]["queue_index"] == 3  # two ahead of slot 0 → index 3
    play = play_ids(conn.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone())
    assert len(play) == before + 1
    assert play[3] == item["id"]

    # Second miss on the reinserted slot does not insert again
    re_qi = resp["reinsert"]["queue_index"]
    # Resolve slots 1 and 2 first so we can hit reinsert cleanly
    for qi in (1, 2):
        it = data["items"][qi]
        _apply(
            conn,
            sid,
            it["id"],
            score_attempt(it["text"], it["text"], [0.95], mode="beginner"),
            qi=qi,
        )
    second = _apply(
        conn,
        sid,
        item["id"],
        score_attempt(item["text"], "zzzz", [0.95], mode="beginner"),
        qi=re_qi,
    )
    assert second["result"] == "missed"
    assert second["reinsert"] is None
    play2 = play_ids(conn.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone())
    assert len(play2) == len(play)


def test_planned_repeats_all_count_for_ratio(tmp_env):
    """B2: adaptive repeat-fill slots count; all-correct → full correct_count."""
    conn = tmp_env["conn"]
    # Master all but two level-1 items so the queue repeats those two.
    level1 = conn.execute(
        "SELECT id FROM items WHERE level = 1 ORDER BY id"
    ).fetchall()
    keep = {level1[0]["id"], level1[1]["id"]}
    for row in level1:
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

    data = start_session(conn, level=1)
    sid = data["session_id"]
    assert len(data["items"]) == 10
    ids = [i["id"] for i in data["items"]]
    assert set(ids) <= keep
    assert len(set(ids)) == 2  # only the two unmastered, repeated

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
    assert row["planned_count"] == 10
    assert row["correct_count"] == 10  # every planned slot, not unique item_id
    done = complete_session(conn, sid)
    assert done["level_after"] >= data["level"]  # 10/10 moves up (unless already 7)


def test_reinsert_correct_does_not_increase_correct_count(tmp_env):
    """B1: same-session reinsert correct must not change the session ratio."""
    conn = tmp_env["conn"]
    data = start_session(conn, level=1)
    sid = data["session_id"]
    item = data["items"][0]
    planned = conn.execute(
        "SELECT planned_count, correct_count FROM sessions WHERE id = ?", (sid,)
    ).fetchone()
    assert planned["correct_count"] == 0
    planned_n = int(planned["planned_count"])

    miss = _apply(
        conn,
        sid,
        item["id"],
        score_attempt(item["text"], "zzzz", [0.95], mode="beginner"),
        qi=0,
    )
    assert miss["result"] == "missed"
    assert miss["reinsert"] is not None
    re_qi = miss["reinsert"]["queue_index"]

    row = conn.execute(
        "SELECT correct_count, planned_count FROM sessions WHERE id = ?", (sid,)
    ).fetchone()
    assert row["correct_count"] == 0
    assert row["planned_count"] == planned_n

    # Resolve intervening planned slots with corrects (no further reinserts).
    for qi in range(1, re_qi):
        it = data["items"][qi]
        _apply(
            conn,
            sid,
            it["id"],
            score_attempt(it["text"], it["text"], [0.95], mode="beginner"),
            qi=qi,
        )

    before = conn.execute(
        "SELECT correct_count, planned_count, stars FROM sessions WHERE id = ?",
        (sid,),
    ).fetchone()
    assert before["correct_count"] == re_qi - 1  # planned corrects only
    assert before["planned_count"] == planned_n

    again = _apply(
        conn,
        sid,
        item["id"],
        score_attempt(item["text"], item["text"], [0.95], mode="beginner"),
        qi=re_qi,
    )
    assert again["result"] == "correct"
    assert again["stars_awarded"] >= 1  # stars / mastery still credit
    assert again["stars_total"] == before["stars"] + again["stars_awarded"]

    after = conn.execute(
        "SELECT correct_count, planned_count FROM sessions WHERE id = ?", (sid,)
    ).fetchone()
    assert after["correct_count"] == before["correct_count"]  # reinsert did not bump
    assert after["planned_count"] == planned_n


def test_reinsert_skip_does_not_shrink_planned_count(tmp_env):
    """B1: three-retry skip on a reinsert slot must not distort the ratio."""
    conn = tmp_env["conn"]
    data = start_session(conn, level=1)
    sid = data["session_id"]
    item = data["items"][0]
    planned_n = int(
        conn.execute(
            "SELECT planned_count FROM sessions WHERE id = ?", (sid,)
        ).fetchone()["planned_count"]
    )
    miss = _apply(
        conn,
        sid,
        item["id"],
        score_attempt(item["text"], "zzzz", [0.95], mode="beginner"),
        qi=0,
    )
    re_qi = miss["reinsert"]["queue_index"]
    for qi in range(1, re_qi):
        it = data["items"][qi]
        _apply(
            conn,
            sid,
            it["id"],
            score_attempt(it["text"], it["text"], [0.95], mode="beginner"),
            qi=qi,
        )
    for _ in range(3):
        resp = _apply(
            conn,
            sid,
            item["id"],
            score_attempt(item["text"], "", mode="beginner", force_retry=True),
            qi=re_qi,
            silence=True,
        )
    assert resp["result"] == "skipped"
    row = conn.execute(
        "SELECT planned_count, correct_count FROM sessions WHERE id = ?", (sid,)
    ).fetchone()
    assert row["planned_count"] == planned_n
    assert row["correct_count"] == re_qi - 1  # only intervening planned corrects


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


def test_start_session_levels_4_to_7(tmp_env):
    conn = tmp_env["conn"]
    for level in (4, 5, 6, 7):
        data = start_session(conn, level=level)
        assert data["level"] == level
        assert len(data["items"]) == 10
        kinds = {i["kind"] for i in data["items"]}
        if level == 4:
            assert "phrase" in kinds
        if level == 5:
            assert "sentence" in kinds
        if level >= 6:
            assert "line" in kinds


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


def test_all_mastered_queue_at_most_one_refresher(tmp_env):
    """C1: 10/10 mastered must not return a full session of mastered items."""
    conn = tmp_env["conn"]
    level1 = conn.execute(
        "SELECT id FROM items WHERE level = 1 ORDER BY id"
    ).fetchall()
    assert len(level1) >= 10
    for row in level1:
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
    mastered_flags = []
    for row in queue:
        m = conn.execute(
            "SELECT mastered FROM mastery WHERE item_id = ?", (row["id"],)
        ).fetchone()
        mastered_flags.append(int(m["mastered"]) if m else 0)
    assert len(queue) <= 1
    assert sum(mastered_flags) <= 1
    assert all(f == 1 for f in mastered_flags)

    # Session start must also stay short — not pad via fixed-queue fallback.
    data = start_session(conn, level=1)
    assert len(data["items"]) <= 1
    row = conn.execute(
        "SELECT planned_count FROM sessions WHERE id = ?",
        (data["session_id"],),
    ).fetchone()
    assert row["planned_count"] == len(data["items"])
    assert row["planned_count"] <= 1
