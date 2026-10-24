"""Deterministic coaching helpers: skill map, planning, hints (Phases 6–7).

Pure-ish modules (StoryForge / adaptive-engine style): I/O stays in session/adaptive.
"""

from app.coach.align import align_miscue, highlight_for_attempt, pattern_spans
from app.coach.hints import build_hint, empty_hint, next_hint_level
from app.coach.map import SkillStatus, skill_map, weak_item_ids
from app.coach.plan import prefer_rows, select_review_priority

__all__ = [
    "SkillStatus",
    "align_miscue",
    "build_hint",
    "empty_hint",
    "highlight_for_attempt",
    "next_hint_level",
    "pattern_spans",
    "prefer_rows",
    "select_review_priority",
    "skill_map",
    "weak_item_ids",
]
