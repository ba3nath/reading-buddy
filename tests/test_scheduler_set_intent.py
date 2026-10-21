"""Intent vs code: set pick must drive the session, not a global easy opener.

Product intent (Phases 1–2):
- Eight sets slice the Words/Phrases pool; choosing Set N practises Set N.
- scheduler_v2 mix: easy opener → due → this set → earlier review → closer.
- Mastery / pattern unlock may add *earlier* review, but must not replace the set.
- Rhymes/stories stay one poem/story group per set.

Regression this file guards: every set opened with ``cat`` because the opener
was the global lowest-id "easy" item and Set 1 due-reviews filled the queue.
"""

from __future__ import annotations

from datetime import date, timedelta

from app import config
from app.adaptive import (
    _build_scheduler_v2_queue,
    build_adaptive_queue,
    items_for_stage,
    _ordered_tier_items,
)
from app.db import ensure_mastery_row, load_settings, local_today, save_settings
from app.session import start_session


def _enable_v2() -> None:
    settings = load_settings()
    settings["scheduler_v2"] = True
    save_settings(settings)


def _tier_and_stage_ids(conn, difficulty: int = 1):
    levels = config.content_levels_for_difficulty(difficulty)
    tier = _ordered_tier_items(conn, levels)
    by_stage = {
        stage: {int(r["id"]) for r in items_for_stage(tier, stage)}
        for stage in range(1, config.STAGES_PER_DIFFICULTY + 1)
    }
    return tier, by_stage


def _mark_due(conn, item_id: int, *, days_ago: int = 0) -> None:
    ensure_mastery_row(conn, item_id)
    due = (date.fromisoformat(local_today()) - timedelta(days=days_ago)).isoformat()
    conn.execute(
        """
        UPDATE mastery
        SET mastered = 0, box = 1, next_review_on = ?, correct_count = 0
        WHERE item_id = ?
        """,
        (due, item_id),
    )
    conn.commit()


def _mark_easy(conn, item_id: int) -> None:
    """Make an item look like the global easiest (mastered, high box)."""
    ensure_mastery_row(conn, item_id)
    conn.execute(
        """
        UPDATE mastery
        SET mastered = 1, box = 5, correct_count = 9,
            next_review_on = NULL, days_json = ?
        WHERE item_id = ?
        """,
        ('["2020-01-01","2020-01-02"]', item_id),
    )
    conn.commit()


def test_each_words_set_opens_with_an_item_from_that_set(tmp_env):
    conn = tmp_env["conn"]
    _enable_v2()
    _, by_stage = _tier_and_stage_ids(conn)
    openers: list[str] = []
    for stage in range(1, config.STAGES_PER_DIFFICULTY + 1):
        queue = build_adaptive_queue(conn, 1, 5, stage=stage)
        assert len(queue) == 5
        opener = queue[0]
        openers.append(str(opener["slug"]))
        assert int(opener["id"]) in by_stage[stage], (
            f"Set {stage} opened with {opener['slug']!r} "
            f"which is not in that set"
        )
    # The bug: every opener was "cat". Distinct sets must not all share one opener.
    assert openers.count("cat") <= 1, openers
    assert len(set(openers)) >= 6, openers


def test_words_queue_majority_is_current_set_even_on_fresh_profile(tmp_env):
    conn = tmp_env["conn"]
    _enable_v2()
    _, by_stage = _tier_and_stage_ids(conn)
    for stage in (2, 4, 6, 8):
        queue = build_adaptive_queue(conn, 1, 5, stage=stage)
        ids = [int(r["id"]) for r in queue]
        in_stage = sum(1 for i in ids if i in by_stage[stage])
        assert in_stage >= 4, (
            f"Set {stage}: only {in_stage}/5 from the set — "
            f"{[r['slug'] for r in queue]}"
        )


def test_mastered_cat_does_not_hijack_later_set_opener(tmp_env):
    conn = tmp_env["conn"]
    _enable_v2()
    cat = conn.execute("SELECT id FROM items WHERE slug='cat'").fetchone()
    assert cat is not None
    _mark_easy(conn, int(cat["id"]))

    _, by_stage = _tier_and_stage_ids(conn)
    for stage in (3, 5, 7):
        queue = _build_scheduler_v2_queue(conn, 1, 5, stage)
        assert queue[0]["slug"] != "cat"
        assert int(queue[0]["id"]) in by_stage[stage]


def test_earlier_due_reviews_cannot_crowd_out_chosen_set(tmp_env):
    """Set 1 due items must not fill a Set 6 session before Set 6 words."""
    conn = tmp_env["conn"]
    _enable_v2()
    tier, by_stage = _tier_and_stage_ids(conn)
    # Make every Set 1 word due today — the old bug filled later sets with these.
    for item_id in by_stage[1]:
        _mark_due(conn, item_id)

    queue = build_adaptive_queue(conn, 1, 5, stage=6)
    ids = {int(r["id"]) for r in queue}
    in_six = ids & by_stage[6]
    from_one = ids & by_stage[1]
    assert len(in_six) >= 4, [r["slug"] for r in queue]
    # At most the closer slot may pull earlier review when fill_cap leaves room.
    assert len(from_one) <= 1, [r["slug"] for r in queue]
    assert int(queue[0]["id"]) in by_stage[6]


def test_start_session_stage_matches_planned_items(tmp_env):
    conn = tmp_env["conn"]
    _enable_v2()
    _, by_stage = _tier_and_stage_ids(conn)
    data = start_session(conn, level=1, stage=4)
    assert data["stage"] == 4
    assert data["planned_count"] == len(data["items"])
    planned = {int(i["id"]) for i in data["items"]}
    assert planned <= (by_stage[4] | by_stage[3] | by_stage[2] | by_stage[1])
    assert len(planned & by_stage[4]) >= 4
    assert data["items"][0]["id"] in by_stage[4]


def test_phrases_sets_also_stay_on_chosen_stage(tmp_env):
    conn = tmp_env["conn"]
    _enable_v2()
    levels = config.content_levels_for_difficulty(2)
    tier = _ordered_tier_items(conn, levels)
    if len(tier) < 8:
        return
    stage = 3
    stage_ids = {int(r["id"]) for r in items_for_stage(tier, stage)}
    queue = build_adaptive_queue(conn, 2, 5, stage=stage)
    assert int(queue[0]["id"]) in stage_ids
    assert sum(1 for r in queue if int(r["id"]) in stage_ids) >= 3


def test_rhyme_and_story_sets_ignore_word_opener_logic(tmp_env):
    conn = tmp_env["conn"]
    _enable_v2()
    poem = build_adaptive_queue(conn, 3, 10, stage=1)
    groups = {r["rhyme_group"] for r in poem}
    assert len(groups) == 1
    assert all(r["slug"] != "cat" or r["kind"] == "line" for r in poem)

    story = build_adaptive_queue(conn, 4, 10, stage=2)
    sids = {r["story_id"] for r in story}
    assert len(sids) == 1
    other = build_adaptive_queue(conn, 4, 10, stage=1)
    assert story[0]["story_id"] != other[0]["story_id"]


def test_scheduler_v2_flag_off_still_uses_set_scoped_queue(tmp_env):
    """Legacy path is retired — even with the flag off, Set N stays Set N."""
    conn = tmp_env["conn"]
    settings = load_settings()
    settings["scheduler_v2"] = False
    save_settings(settings)
    _, by_stage = _tier_and_stage_ids(conn)
    queue = build_adaptive_queue(conn, 1, 5, stage=2)
    assert int(queue[0]["id"]) in by_stage[2]
    assert sum(1 for r in queue if int(r["id"]) in by_stage[2]) >= 4


def test_queue_never_pulls_later_sets_when_current_set_is_large_enough(tmp_env):
    """Words sets (~13 items) must not pad from later sets for a length-10 queue."""
    conn = tmp_env["conn"]
    _enable_v2()
    _, by_stage = _tier_and_stage_ids(conn)
    later = set()
    for s in (4, 5, 6, 7, 8):
        later |= by_stage[s]
    queue = build_adaptive_queue(conn, 1, 10, stage=3)
    ids = {int(r["id"]) for r in queue}
    assert not (ids & later), [r["slug"] for r in queue if int(r["id"]) in later]


def test_thin_phrase_set_may_pad_later_only_after_full_set(tmp_env):
    """Phrases have 4/stage — length 5 needs one later item after the whole set."""
    conn = tmp_env["conn"]
    _enable_v2()
    _, by_stage = _tier_and_stage_ids(conn, difficulty=2)
    stage = 1
    queue = build_adaptive_queue(conn, 2, 5, stage=stage)
    assert len(queue) == 5
    stage_ids = by_stage[stage]
    assert stage_ids.issubset({int(r["id"]) for r in queue})
    assert int(queue[0]["id"]) in stage_ids
    later = set()
    for s in range(2, config.STAGES_PER_DIFFICULTY + 1):
        later |= by_stage[s]
    assert len({int(r["id"]) for r in queue} & later) == 1


def test_api_session_stage_items_belong_to_set(client, tmp_env):
    _enable_v2()
    conn = tmp_env["conn"]
    _, by_stage = _tier_and_stage_ids(conn)
    res = client.post("/api/sessions", json={"level": 1, "stage": 5})
    assert res.status_code == 200
    body = res.json()
    assert body["stage"] == 5
    opener_id = int(body["items"][0]["id"])
    assert opener_id in by_stage[5]
    in_stage = sum(1 for it in body["items"] if int(it["id"]) in by_stage[5])
    assert in_stage >= 4
