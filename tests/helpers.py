"""Shared test helpers for attempt POSTs with slot / word keys."""

from __future__ import annotations


def post_attempt(
    client,
    session_id: int,
    item_id: int,
    audio_bytes: bytes,
    *,
    phase: str = "read",
    queue_index: int | None = None,
    word: str = "",
    filename: str = "take.wav",
):
    data: dict[str, str] = {"item_id": str(item_id), "phase": phase}
    if phase == "read":
        if queue_index is None:
            raise ValueError("queue_index required for read phase")
        data["queue_index"] = str(queue_index)
    if phase == "replay":
        data["word"] = word
    return client.post(
        f"/api/sessions/{session_id}/attempts",
        data=data,
        files={"audio": (filename, audio_bytes, "audio/wav")},
    )
