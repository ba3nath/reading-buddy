"""Phase 5b: explicit outcomes; silence ≠ uncertain; replay ≠ mastery."""

from __future__ import annotations

from app.db import ensure_mastery_row
from app.matching import score_attempt
from app.session import apply_attempt, start_session
from tests.helpers import post_attempt


def test_score_attempt_silence_vs_uncertain():
    silence = score_attempt("cat", "", mode="beginner")
    assert silence.result == "retry"
    assert silence.outcome == "silence"
    assert silence.reason_code == "empty_transcript"

    forced = score_attempt("cat", "x", mode="beginner", force_retry=True)
    assert forced.outcome == "silence"
    assert forced.reason_code == "forced_retry"

    uncertain = score_attempt("ship", "zzz", [0.05], mode="beginner")
    assert uncertain.result == "retry"
    assert uncertain.outcome == "uncertain"
    assert uncertain.reason_code == "low_asr_confidence"


def test_score_attempt_miss_maps_to_incorrect_outcome():
    miss = score_attempt("cat", "dog", [0.95], mode="beginner")
    assert miss.result == "missed"
    assert miss.outcome == "incorrect"


def test_api_empty_audio_is_silence_outcome(client, assert_attempt_shape):
    start = client.post("/api/sessions", json={"level": 1}).json()
    item = start["items"][0]
    res = post_attempt(client, start["session_id"], item["id"], b"", queue_index=0)
    body = res.json()
    assert_attempt_shape(body, words_total=1)
    assert body["result"] == "retry"
    assert body["outcome"] == "silence"
    assert body["mastery_eligible"] is False


def test_apply_uncertain_match_exposes_uncertain_outcome(tmp_env):
    conn = tmp_env["conn"]
    data = start_session(conn, level=1)
    sid = data["session_id"]
    item = data["items"][0]
    match = score_attempt(item["text"], "zzz", [0.05], mode="beginner")
    assert match.outcome == "uncertain"
    body = apply_attempt(conn, sid, int(item["id"]), match, queue_index=0)
    assert body["result"] == "retry"
    assert body["outcome"] == "uncertain"
    assert body["reason_code"] == "low_asr_confidence"
    assert body["mastery_eligible"] is False


def test_replay_correct_does_not_credit_mastery(tmp_env):
    from app.session import complete_session

    conn = tmp_env["conn"]
    data = start_session(conn, level=1)
    sid = data["session_id"]
    item = data["items"][0]
    item_id = int(item["id"])
    ensure_mastery_row(conn, item_id)
    conn.execute(
        """
        UPDATE mastery
        SET correct_count = 0, box = 1, mastered = 0, mastered_on = NULL,
            days_json = '[]'
        WHERE item_id = ?
        """,
        (item_id,),
    )
    conn.commit()

    # Lock every planned slot (miss → second miss) so the session can complete.
    for qi, it in enumerate(data["items"]):
        miss = score_attempt(it["text"], "zzzzzz", [0.95], mode="beginner")
        first = apply_attempt(conn, sid, int(it["id"]), miss, queue_index=qi)
        if first.get("again"):
            apply_attempt(conn, sid, int(it["id"]), miss, queue_index=qi)

    complete_session(conn, sid)

    before = conn.execute(
        "SELECT correct_count, box, mastered FROM mastery WHERE item_id = ?",
        (item_id,),
    ).fetchone()

    ok = score_attempt(item["text"], item["text"], [0.95], mode="beginner")
    word = item["text"].split()[0]
    replay = apply_attempt(
        conn,
        sid,
        item_id,
        ok,
        phase="replay",
        replay_word=word,
    )
    assert replay["result"] == "correct"
    assert replay["outcome"] == "correct"
    assert replay["mastery_eligible"] is False
    assert replay["assisted"] is False

    after = conn.execute(
        "SELECT correct_count, box, mastered FROM mastery WHERE item_id = ?",
        (item_id,),
    ).fetchone()
    assert after["correct_count"] == before["correct_count"]
    assert after["box"] == before["box"]
    assert int(after["mastered"] or 0) == int(before["mastered"] or 0)


def test_independent_correct_is_mastery_eligible(client, whisper_double, tone_wav):
    from app.whisper_engine import AttemptTranscript, TranscriptWord

    start = client.post("/api/sessions", json={"level": 1}).json()
    item = start["items"][0]
    text = item["text"]
    whisper_double.set_transcript(
        AttemptTranscript(
            transcript=text,
            words=[
                TranscriptWord(word=w, probability=0.95) for w in text.split()
            ],
            no_speech_prob=0.05,
        )
    )
    res = post_attempt(
        client, start["session_id"], item["id"], tone_wav.read_bytes(), queue_index=0
    )
    body = res.json()
    assert body["result"] == "correct"
    assert body["outcome"] == "correct"
    assert body["assisted"] is False
    assert body["mastery_eligible"] is True
