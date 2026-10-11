"""Milestone 3 API: mode from settings, multi-word ratio, parent settings."""

from __future__ import annotations

from app.db import load_settings, save_settings
from app.whisper_engine import AttemptTranscript, TranscriptWord
from tests.helpers import post_attempt


def test_parent_settings_mode_and_level(client):
    res = client.put(
        "/api/parent/settings",
        json={"mode": "strict", "level": 4, "auto_strict": True},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["mode"] == "strict"
    assert body["level"] == 4
    got = client.get("/api/parent/settings").json()
    assert got["mode"] == "strict"
    assert got["level"] == 4


def test_session_uses_settings_mode_strict(client, whisper_double, tone_wav):
    client.put("/api/parent/settings", json={"mode": "strict", "level": 1})
    start = client.post("/api/sessions", json={"level": 1}).json()
    assert start["mode"] == "strict"
    # Find cat
    item = next((i for i in start["items"] if i["text"] == "cat"), start["items"][0])
    qi = start["items"].index(item)
    whisper_double.set_transcript(
        AttemptTranscript(
            transcript="cats",
            words=[TranscriptWord(word="cats", probability=0.95)],
            no_speech_prob=0.05,
        )
    )
    res = post_attempt(
        client,
        start["session_id"],
        item["id"],
        tone_wav.read_bytes(),
        queue_index=qi,
    )
    assert res.status_code == 200
    if item["text"] == "cat":
        assert res.json()["result"] == "missed"


def test_multiword_item_ratio_and_replay_words_only(
    client, whisper_double, tone_wav, tmp_env
):
    import json

    from app.db import normalize_text
    from app.session import set_play_ids

    conn = tmp_env["conn"]
    # Use a real level-5 sentence from content
    row = conn.execute(
        "SELECT id, slug, text FROM items WHERE kind='sentence' AND level=5 LIMIT 1"
    ).fetchone()
    assert row is not None
    client.put("/api/parent/settings", json={"mode": "beginner", "level": 5})
    start = client.post("/api/sessions", json={"level": 5}).json()
    sid = start["session_id"]
    # Force single sentence as only play item for a clear ratio
    set_play_ids(conn, sid, [row["id"]])
    conn.execute(
        "UPDATE sessions SET planned_item_ids=?, planned_count=1 WHERE id=?",
        (json.dumps([row["id"]]), sid),
    )
    conn.commit()

    # Miss last word only: say all but last token
    tokens = row["text"].replace("?", "").replace(".", "").split()
    heard = " ".join(tokens[:-1])
    whisper_double.set_transcript(
        AttemptTranscript(
            transcript=heard,
            words=[TranscriptWord(word=w, probability=0.95) for w in tokens[:-1]],
            no_speech_prob=0.05,
        )
    )
    res = post_attempt(
        client, sid, row["id"], tone_wav.read_bytes(), queue_index=0
    )
    assert res.status_code == 200
    body = res.json()
    assert body["result"] == "missed"
    assert body["words_total"] == len(tokens)
    assert body["words_correct"] == len(tokens) - 1
    # Item-level ratio: one planned item, not correct
    done = client.post(f"/api/sessions/{sid}/complete").json()
    assert done["planned_count"] == 1
    assert done["correct_count"] == 0
    assert len(done["replay"]) == 1
    assert done["replay"][0]["text"].lower() == tokens[-1].lower().rstrip(".,?!")


def test_complete_returns_level_after(client, whisper_double, tone_wav, tmp_env):
    client.put(
        "/api/parent/settings",
        json={"mode": "beginner", "level": 1, "session_length": 5},
    )
    start = client.post("/api/sessions", json={"level": 1}).json()
    sid = start["session_id"]
    for qi, item in enumerate(start["items"]):
        whisper_double.set_transcript(
            AttemptTranscript(
                transcript=item["text"],
                words=[TranscriptWord(word=item["text"], probability=0.95)],
                no_speech_prob=0.05,
            )
        )
        post_attempt(client, sid, item["id"], tone_wav.read_bytes(), queue_index=qi)
    done = client.post(f"/api/sessions/{sid}/complete").json()
    assert "level_after" in done
    assert done["level_after"] == 1
    assert done["stage_after"] == 2
    assert load_settings()["level"] == 1
    assert load_settings()["stage"] == 2


def test_difficulty_tiers_session_start(client):
    """POST level 1–4 starts that tier; legacy 5–7 map into a tier."""
    expect = {
        1: ("Words", 1),
        2: ("Phrases", 2),
        3: ("Rhymes", 3),
        4: ("Stories", 4),
        5: ("Stories", 4),
        6: ("Rhymes", 3),
        7: ("Rhymes", 3),
    }
    for raw, (label, difficulty) in expect.items():
        res = client.post("/api/sessions", json={"level": raw})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["level"] == difficulty
        assert body["difficulty_label"] == label
        assert len(body["items"]) in (5, 10)


def test_start_omits_level_uses_settings(client):
    """C6: POST /api/sessions with no body uses settings.level."""
    client.put("/api/parent/settings", json={"mode": "beginner", "level": 4})
    res = client.post("/api/sessions")
    assert res.status_code == 200
    assert res.json()["level"] == 4
    assert res.json()["difficulty_label"] == "Stories"
    assert len(res.json()["items"]) >= 1


def test_start_all_mastered_ineligible_not_503(client, tmp_env):
    """C7 API: all-mastered Words still starts a uniform 5/10 session, not 503."""
    import json

    from app.db import local_now_iso, local_today

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
              last_seen_on=excluded.last_seen_on
            """,
            (
                row["id"],
                json.dumps(["2020-01-01", "2020-01-02"]),
                local_today(),
                local_today(),
            ),
        )
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
    client.put("/api/parent/settings", json={"mode": "beginner", "level": 1})
    res = client.post("/api/sessions")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["level"] == 1
    assert len(body["items"]) == 10


def test_start_button_omits_level_pick():
    """C6 FE: primary Start has no data-level-pick (uses settings)."""
    from pathlib import Path

    html = Path("static/index.html").read_text(encoding="utf-8")
    assert 'class="btn primary" data-start>Start</button>' in html
    assert 'class="btn primary" data-start data-level-pick' not in html
    assert 'data-level-pick="2">Phrases</button>' in html
