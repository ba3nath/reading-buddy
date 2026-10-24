"""Retired curriculum rows must not block audio-ready / boot."""

from __future__ import annotations

from app.db import active_item_slugs, upsert_items_from_json


def test_stale_used_items_are_retired_not_deleted(tmp_env):
    conn = tmp_env["conn"]
    row = conn.execute("SELECT id, slug FROM items LIMIT 1").fetchone()
    # Pretend this slug was removed from content but still has attempts.
    conn.execute(
        """
        INSERT INTO sessions (
          started_at, mode, level, planned_count, planned_item_ids, completed
        ) VALUES ('2020-01-01 00:00:00', 'beginner', 1, 1, ?, 0)
        """,
        (f'[{row["id"]}]',),
    )
    sid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        """
        INSERT INTO attempts (
          session_id, item_id, heard, word_scores, result,
          counts_for_session, is_replay, created_at
        ) VALUES (?, ?, '', '[]', 'correct', 1, 0, '2020-01-01 00:00:00')
        """,
        (sid, row["id"]),
    )
    conn.execute("UPDATE items SET slug = 'retired-ghost-slug' WHERE id = ?", (row["id"],))
    conn.commit()

    upsert_items_from_json(conn)
    ghost = conn.execute(
        "SELECT retired FROM items WHERE slug = 'retired-ghost-slug'"
    ).fetchone()
    assert ghost is not None
    assert int(ghost["retired"]) == 1
    assert "retired-ghost-slug" not in active_item_slugs(conn)


def test_health_ignores_retired_missing_wav(tmp_env, client, monkeypatch):
    conn = tmp_env["conn"]
    upsert_items_from_json(conn)
    conn.execute(
        """
        INSERT INTO items (
          slug, text, normalized, kind, level, sound_tags, sounds_locked,
          source, pd_status, hard, pattern, sight_word, retired
        ) VALUES (
          'no-wav-retired', 'Nope', 'nope', 'word', 1, '[]', 0,
          'test', 'n/a', 0, 'cvc-a', 0, 1
        )
        """
    )
    conn.commit()

    # Force active slugs to look ready even if fixtures have no wavs.
    monkeypatch.setattr(
        "app.main.generated_audio_ready",
        lambda slugs: "no-wav-retired" not in slugs and bool(slugs),
    )
    body = client.get("/api/health").json()
    assert body["audio"] is True
