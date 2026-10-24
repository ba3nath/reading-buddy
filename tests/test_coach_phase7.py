"""Phase 7: miscue align, hint ladder, assisted mastery, session recovery."""

from __future__ import annotations

from app.coach.align import align_miscue, highlight_for_attempt, pattern_spans
from app.coach.hints import HINT_HIGHLIGHT, HINT_LISTEN, build_hint, next_hint_level
from app.db import load_settings, save_settings
from app.matching import score_attempt
from app.session import (
    SessionError,
    apply_attempt,
    open_session_view,
    start_session,
    validate_attempt_access,
)


def test_align_cat_to_cap_highlights_ending():
    spans = align_miscue("cat", "cap")
    assert spans
    assert spans[0]["start"] == 2
    assert spans[0]["end"] == 3
    assert "t" in spans[0]["cue"] or spans[0]["tag"] == "miscue"


def test_pattern_spans_digraph_sh():
    spans = pattern_spans("ship", "digraph-sh")
    assert spans == [{"start": 0, "end": 2, "tag": "pattern", "cue": spans[0]["cue"]}]
    assert "sh" in spans[0]["cue"]


def test_highlight_prefers_miscue_over_pattern():
    spans = highlight_for_attempt(target="ship", heard="sip", pattern="digraph-sh")
    assert spans and spans[0]["tag"] == "miscue"


def test_hint_ladder_levels():
    assert next_hint_level(0, kind="uncertain") == HINT_LISTEN
    assert next_hint_level(0, kind="missed") == HINT_HIGHLIGHT
    assert next_hint_level(HINT_HIGHLIGHT, kind="lock") == 4
    hint = build_hint(target="ship", heard="sip", pattern="digraph-sh", level=2)
    assert hint["hint_level"] == 2
    assert hint["highlight_spans"]
    assert "ship" in hint["coach_line"].lower() or "sh" in hint["coach_line"].lower()


def test_uncertain_copy_never_says_wrong(tmp_env):
    conn = tmp_env["conn"]
    data = start_session(conn, level=1)
    item = data["items"][0]
    match = score_attempt(item["text"], "", [0.1], mode="beginner", force_retry=True)
    resp = apply_attempt(
        conn,
        data["session_id"],
        item["id"],
        match,
        phase="read",
        queue_index=0,
        is_silence_path=False,
    )
    assert resp["result"] == "retry"
    assert resp["outcome"] in ("silence", "uncertain")
    msg = (resp["message"] or "").lower()
    assert "wrong" not in msg
    assert "can't read" not in msg and "cannot read" not in msg
    assert resp["hint_level"] >= 1
    assert resp["mastery_eligible"] is False


def test_miss_second_chance_then_correct_is_assisted(tmp_env):
    conn = tmp_env["conn"]
    data = start_session(conn, level=1)
    item = next((i for i in data["items"] if i["text"] == "cat"), data["items"][0])
    qi = data["items"].index(item)
    first = apply_attempt(
        conn,
        data["session_id"],
        item["id"],
        score_attempt(item["text"], "dog", [0.95], mode="beginner"),
        phase="read",
        queue_index=qi,
    )
    assert first["again"] is True
    assert first["hint_level"] >= HINT_HIGHLIGHT
    assert first["highlight_spans"]
    assert first["mastery_eligible"] is False

    second = apply_attempt(
        conn,
        data["session_id"],
        item["id"],
        score_attempt(item["text"], item["text"], [0.95], mode="beginner"),
        phase="read",
        queue_index=qi,
    )
    assert second["result"] == "correct"
    assert second["assisted"] is True
    assert second["mastery_eligible"] is False


def test_strict_close_again_includes_coach_fields(tmp_env):
    conn = tmp_env["conn"]
    save_settings({**load_settings(), "mode": "strict", "auto_strict": False})
    data = start_session(conn, level=1)
    item = data["items"][0]
    text = item["text"]
    # Strict close = exact transcript, low confidence.
    first = apply_attempt(
        conn,
        data["session_id"],
        item["id"],
        score_attempt(text, text, [0.40], mode="strict"),
        phase="read",
        queue_index=0,
    )
    assert first["result"] == "close"
    assert first["again"] is True
    assert first["hint_level"] >= HINT_HIGHLIGHT
    assert "coach_line" in first


def test_open_session_resume_blocks_duplicate_resolved_slot(tmp_env):
    conn = tmp_env["conn"]
    data = start_session(conn, level=1)
    sid = data["session_id"]
    item = data["items"][0]
    apply_attempt(
        conn,
        sid,
        item["id"],
        score_attempt(item["text"], item["text"], [0.95], mode="beginner"),
        phase="read",
        queue_index=0,
    )
    view = open_session_view(conn)
    assert view["open"] is True
    assert view["session_id"] == sid
    assert view["index"] == 1
    assert view.get("hint_pending") is False
    try:
        validate_attempt_access(conn, sid, item["id"], phase="read", queue_index=0)
        raised = False
    except SessionError as exc:
        raised = True
        assert exc.status in (409, 400)
    assert raised
