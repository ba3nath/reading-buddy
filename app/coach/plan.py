"""Deterministic next-activity ordering helpers (Phase 6)."""

from __future__ import annotations

from typing import Any, Sequence


def prefer_ids(ordered: Sequence[int], prefer: Sequence[int]) -> list[int]:
    """Stable reorder: ``prefer`` members first (in prefer order), then the rest."""
    present = {int(x) for x in ordered}
    seen: set[int] = set()
    out: list[int] = []
    for item_id in prefer:
        iid = int(item_id)
        if iid in present and iid not in seen:
            out.append(iid)
            seen.add(iid)
    for item_id in ordered:
        iid = int(item_id)
        if iid not in seen:
            out.append(iid)
            seen.add(iid)
    return out


def prefer_rows(rows: Sequence[Any], prefer_ids_list: Sequence[int]) -> list[Any]:
    """Reorder sqlite rows / mappings with an ``id`` field using ``prefer_ids``."""
    if not rows or not prefer_ids_list:
        return list(rows)
    by_id = {int(r["id"]): r for r in rows}
    order = prefer_ids([int(r["id"]) for r in rows], prefer_ids_list)
    return [by_id[i] for i in order if i in by_id]


def select_review_priority(
    *,
    due_ids: Sequence[int],
    weak_ids: Sequence[int],
    stage_ids: Sequence[int],
) -> list[int]:
    """Due ∩ weak first, then other due, then weak-in-stage (no duplicates)."""
    due = [int(x) for x in due_ids]
    weak = [int(x) for x in weak_ids]
    stage = {int(x) for x in stage_ids}
    due_set = set(due)
    out: list[int] = []
    seen: set[int] = set()
    for iid in weak:
        if iid in due_set and iid not in seen:
            out.append(iid)
            seen.add(iid)
    for iid in due:
        if iid not in seen:
            out.append(iid)
            seen.add(iid)
    for iid in weak:
        if iid in stage and iid not in seen:
            out.append(iid)
            seen.add(iid)
    return out
