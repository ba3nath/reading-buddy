"""Miscue → highlight spans (Phase 7). Pure — no I/O."""

from __future__ import annotations

from typing import Any


def _first_word(text: str) -> str:
    return (text or "").strip().lower().split()[0] if (text or "").strip() else ""


def pattern_grapheme(pattern: str) -> str | None:
    """Map curriculum pattern id → grapheme to highlight, if any."""
    p = (pattern or "").strip().lower()
    if p.startswith("digraph-") and len(p) > 8:
        return p.split("-", 1)[1]
    if p.startswith("cvc-") and len(p) == 5:
        return p[-1]  # vowel letter
    if p == "silent-e":
        return "e"
    if p in ("sh", "ch", "th", "wh"):
        return p
    return None


def find_substring_spans(text: str, needle: str, *, tag: str, cue: str) -> list[dict[str, Any]]:
    """Case-insensitive non-overlapping spans for ``needle`` inside ``text``."""
    if not text or not needle:
        return []
    lower = text.lower()
    n = needle.lower()
    out: list[dict[str, Any]] = []
    start = 0
    while True:
        i = lower.find(n, start)
        if i < 0:
            break
        out.append({"start": i, "end": i + len(n), "tag": tag, "cue": cue})
        start = i + max(1, len(n))
    return out


def pattern_spans(text: str, pattern: str) -> list[dict[str, Any]]:
    """Highlight the learning objective grapheme inside ``text``."""
    g = pattern_grapheme(pattern)
    if not g:
        return []
    cue = f"Listen for {g}" if len(g) > 1 else f"Listen for the /{g}/ sound"
    return find_substring_spans(text, g, tag="pattern", cue=cue)


def align_miscue(target: str, heard: str) -> list[dict[str, Any]]:
    """Highlight the first differing stretch (e.g. cat→cap → ending letter).

    Returns character offsets into the original ``target`` string (first word).
    """
    raw = (target or "").strip()
    if not raw:
        return []
    # Operate on first token; offsets assume target starts with that token.
    tw = _first_word(raw)
    hw = _first_word(heard)
    if not tw:
        return []
    # Leading whitespace offset if any
    prefix = len(raw) - len(raw.lstrip())
    if not hw or tw == hw:
        return []

    # Longest common prefix / suffix on the first word
    i = 0
    while i < len(tw) and i < len(hw) and tw[i] == hw[i]:
        i += 1
    j_t, j_h = len(tw), len(hw)
    while j_t > i and j_h > i and tw[j_t - 1] == hw[j_h - 1]:
        j_t -= 1
        j_h -= 1
    if i >= j_t:
        # Insertion-only on heard — nudge last letter of target
        start = prefix + max(0, len(tw) - 1)
        end = prefix + len(tw)
    else:
        start = prefix + i
        end = prefix + j_t
    if end <= start:
        return []
    chunk = raw[start:end]
    return [
        {
            "start": start,
            "end": end,
            "tag": "miscue",
            "cue": f"Check the '{chunk}' part",
        }
    ]


def highlight_for_attempt(
    *,
    target: str,
    heard: str,
    pattern: str = "",
) -> list[dict[str, Any]]:
    """Prefer miscue span; fall back to pattern grapheme."""
    spans = align_miscue(target, heard)
    if spans:
        return spans
    return pattern_spans(target, pattern)
