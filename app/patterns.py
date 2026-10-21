"""Phonics pattern catalog, tagging helpers, and unlock rules."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app import config

PATTERNS_PATH = config.ROOT / "content" / "patterns.json"

# Short closed set of function words treated as sight for decoding audits.
FUNCTION_SIGHT = frozenset(
    "a an the to of on in at for and or is are was were with from that this my me you your i we they he she it".split()
)

DIGRAPHS = {
    "sh": "digraph-sh",
    "ch": "digraph-ch",
    "th": "digraph-th",
}
BLEND_ONSETS = (
    "bl br cl cr dr fl fr gl gr pl pr sc sk sl sm sn sp st sw tr tw "
    "scr spl spr str thr"
).split()
VOWEL_TEAMS = ("ai", "ay", "ea", "ee", "oa", "ow", "oo", "oi", "oy", "ou", "aw", "au")
R_CONTROLLED = ("ar", "er", "ir", "or", "ur")


def load_ladder() -> list[str]:
    data = json.loads(PATTERNS_PATH.read_text(encoding="utf-8"))
    return list(data["ladder"])


def load_unlock_threshold() -> float:
    data = json.loads(PATTERNS_PATH.read_text(encoding="utf-8"))
    return float(data.get("unlock_threshold", 0.8))


def valid_patterns() -> frozenset[str]:
    return frozenset(load_ladder())


def infer_word_pattern(word: str, *, source: str = "") -> tuple[str, bool]:
    """Return (pattern, sight_word) for a single alphabetic token."""
    w = re.sub(r"[^a-z]", "", (word or "").lower())
    if not w:
        return "sight", True
    if source in ("dolch", "sight", "fry") or w in FUNCTION_SIGHT:
        return "sight", True
    # digraphs
    for dig, label in DIGRAPHS.items():
        if dig in w:
            return label, False
    # r-controlled
    for rc in R_CONTROLLED:
        if rc in w:
            return "r-controlled", False
    # vowel teams
    for vt in VOWEL_TEAMS:
        if vt in w:
            return "vowel-team", False
    # silent e (CVCe)
    if len(w) >= 4 and w.endswith("e") and w[-2] not in "aeiou" and w[-3] in "aeiou":
        return "silent-e", False
    # blends
    for bl in BLEND_ONSETS:
        if w.startswith(bl) and len(w) > len(bl):
            return "blend", False
    # CVC
    if len(w) == 3 and w[0] not in "aeiou" and w[1] in "aeiou" and w[2] not in "aeiou":
        return f"cvc-{w[1]}", False
    if source == "cvc" and len(w) <= 4:
        # longer cvc-ish (e.g. sit) already handled; map leftover shorts
        for ch in w:
            if ch in "aeiou":
                return f"cvc-{ch}", False
    if source == "blend":
        return "blend", False
    if source == "phonics":
        return "blend", False
    return "sight", True


def infer_item_pattern(item: dict[str, Any]) -> tuple[str, bool]:
    """Tag a content item. Rhymes/stories get kind-level patterns."""
    kind = item.get("kind", "word")
    source = str(item.get("source") or "")
    if kind == "line" or item.get("rhyme_group"):
        return "rhyme", False
    if kind == "sentence" or item.get("story_id"):
        return "story-mixed", False
    if kind == "phrase":
        return "phrase", False
    text = str(item.get("text") or "")
    return infer_word_pattern(text, source=source)


def validate_items(items: list[dict[str, Any]]) -> list[str]:
    allowed = valid_patterns()
    errors: list[str] = []
    for item in items:
        slug = item.get("slug", "?")
        pattern = item.get("pattern")
        if pattern not in allowed:
            errors.append(f"{slug}: missing/invalid pattern {pattern!r}")
        if "sight_word" not in item:
            errors.append(f"{slug}: missing sight_word")
        elif not isinstance(item["sight_word"], bool):
            errors.append(f"{slug}: sight_word must be bool")
    return errors


def pattern_rank(pattern: str) -> int:
    ladder = load_ladder()
    try:
        return ladder.index(pattern)
    except ValueError:
        return len(ladder)


def unlocked_patterns(known_by_pattern: dict[str, float], *, threshold: float | None = None) -> list[str]:
    """Return ladder prefixes unlocked given per-pattern known ratios (0–1)."""
    thr = load_unlock_threshold() if threshold is None else threshold
    ladder = load_ladder()
    unlocked = [ladder[0]] if ladder else []
    for i in range(1, len(ladder)):
        prev = ladder[i - 1]
        # Non-phonics buckets always unlock with the previous phonics step.
        if prev in ("sight", "phrase", "rhyme", "story-mixed"):
            unlocked.append(ladder[i])
            continue
        if known_by_pattern.get(prev, 0.0) >= thr:
            unlocked.append(ladder[i])
        else:
            break
    # Sight always available once any CVC is open.
    if "sight" in ladder and unlocked and "sight" not in unlocked:
        unlocked.append("sight")
    return unlocked
