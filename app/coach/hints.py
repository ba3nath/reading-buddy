"""Graduated hint ladder (Phase 7). Pure — no I/O."""

from __future__ import annotations

from typing import Any, Literal

from app.coach.align import highlight_for_attempt, pattern_grapheme, pattern_spans

HintLevel = Literal[0, 1, 2, 3, 4]

# 0 none · 1 listen again · 2 highlight pattern/miscue · 3 sound cue · 4 model word
HINT_NONE = 0
HINT_LISTEN = 1
HINT_HIGHLIGHT = 2
HINT_SOUND = 3
HINT_MODEL = 4


def next_hint_level(prior: int, *, kind: str) -> HintLevel:
    """Advance the ladder for the next coach offer.

    ``kind``: silence | uncertain | close | missed | lock
    """
    prior = max(0, min(4, int(prior or 0)))
    if kind in ("silence", "uncertain"):
        return HINT_LISTEN if prior < HINT_LISTEN else HINT_LISTEN  # type: ignore[return-value]
    if kind == "close":
        return HINT_HIGHLIGHT if prior < HINT_HIGHLIGHT else HINT_SOUND  # type: ignore[return-value]
    if kind == "missed":
        if prior < HINT_HIGHLIGHT:
            return HINT_HIGHLIGHT
        if prior < HINT_SOUND:
            return HINT_SOUND
        return HINT_MODEL
    if kind == "lock":
        return HINT_MODEL if prior < HINT_MODEL else HINT_MODEL  # type: ignore[return-value]
    return HINT_NONE


def _short_heard(heard: str, *, max_chars: int = 40) -> str:
    h = " ".join((heard or "").strip().split())
    if not h:
        return ""
    if len(h) > max_chars:
        return h[: max_chars - 1].rstrip() + "…"
    return h


def reading_feedback(
    target: str, heard: str = "", *, invite_again: bool = True
) -> str:
    """One clear line: what we heard vs the target (empty if nothing useful)."""
    word = (target or "").strip() or "that word"
    said = _short_heard(heard)
    if not said:
        return ""
    # Same words (case/punct) — no contrast line needed.
    if said.lower().rstrip(".!?") == word.lower().rstrip(".!?"):
        return ""
    if invite_again:
        return f'I heard "{said}" — try "{word}".'
    return f'I heard "{said}". The word is "{word}".'


def coach_line_for(
    level: int,
    *,
    target: str,
    heard: str = "",
    pattern: str = "",
    outcome: str = "",
    invite_again: bool = True,
) -> str:
    """Child-facing copy. Never frames ASR uncertainty as a reading failure."""
    word = (target or "").strip() or "that word"
    g = pattern_grapheme(pattern)
    contrast = reading_feedback(target, heard, invite_again=invite_again)
    if outcome in ("silence", "uncertain") or level <= HINT_LISTEN:
        if outcome == "uncertain":
            return "I wasn't sure I heard you — tap to try once more."
        return "Let's listen again, then you read it."
    if level == HINT_HIGHLIGHT:
        if contrast:
            if g and len(g) > 1:
                return f"{contrast} Look at the {g}."
            if g:
                return f"{contrast} Listen for /{g}/."
            return contrast
        if g and len(g) > 1:
            return f"Look at the {g} in {word}."
        if g:
            return f"Look at the /{g}/ sound in {word}."
        return f"Look carefully at {word}."
    if level == HINT_SOUND:
        if contrast:
            if g and len(g) > 1:
                return f"{contrast} The letters {g} say /{g}/."
            if g:
                return f"{contrast} Listen for /{g}/."
            return contrast
        if g and len(g) > 1:
            return f"The letters {g} say /{g}/. Now you try."
        if g:
            return f"Listen for /{g}/, then read {word}."
        return f"Say the first sound, then read {word}."
    # MODEL
    if contrast:
        return f"{contrast} Listen: {word}."
    if invite_again:
        return f"I'll say it — {word}. Now you read it."
    return f"I'll say it — {word}."


def build_hint(
    *,
    target: str,
    heard: str = "",
    pattern: str = "",
    level: int,
    outcome: str = "",
    invite_again: bool = True,
) -> dict[str, Any]:
    """Return coach fields for an attempt response (optional for old clients)."""
    level_i = max(0, min(4, int(level or 0)))
    spans: list[dict[str, Any]] = []
    if level_i >= HINT_HIGHLIGHT:
        spans = highlight_for_attempt(target=target, heard=heard, pattern=pattern)
        if not spans and pattern:
            spans = pattern_spans(target, pattern)
    line = coach_line_for(
        level_i,
        target=target,
        heard=heard,
        pattern=pattern,
        outcome=outcome,
        invite_again=invite_again,
    )
    return {
        "hint_level": level_i,
        "coach_line": line,
        "highlight_spans": spans,
        "play_model": level_i >= HINT_MODEL,
    }


def empty_hint() -> dict[str, Any]:
    return {
        "hint_level": 0,
        "coach_line": "",
        "highlight_spans": [],
        "play_model": False,
    }
