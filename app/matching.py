"""Normalize, align, and score transcripts (Beginner / Strict)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

from metaphone import doublemetaphone

from app import config

WordResult = Literal["correct", "close", "missed"]
ItemResult = Literal["correct", "close", "missed", "retry"]
Mode = Literal["beginner", "strict"]

_NORMALIZE_RE = re.compile(r"[^a-z0-9\s]+")

# Tiny words Whisper often drops on longer lines. Beginner forgives these;
# content words still decide the item.
FUNCTION_WORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "to",
        "of",
        "on",
        "in",
        "at",
        "for",
        "and",
        "or",
        "is",
        "are",
        "was",
        "were",
        "with",
        "from",
        "that",
        "this",
    }
)


@dataclass
class WordScore:
    word: str
    heard: str
    confidence: float | None
    result: WordResult

    def to_dict(self) -> dict:
        return {
            "word": self.word,
            "heard": self.heard,
            "confidence": self.confidence,
            "result": self.result,
        }


@dataclass
class MatchResult:
    result: ItemResult
    word_scores: list[WordScore]
    words_correct: int
    words_total: int
    transcript: str
    replay_words: list[str]


def normalize_text(text: str) -> str:
    # Drop punctuation (don't → dont); keep letters, digits, whitespace.
    lowered = (text or "").lower()
    cleaned = _NORMALIZE_RE.sub("", lowered)
    return " ".join(cleaned.split())


def tokenize(text: str) -> list[str]:
    normalized = normalize_text(text)
    if not normalized:
        return []
    return normalized.split()


def hypothesis_from_whisper_words(
    words: list,
) -> tuple[str, list[float | None]]:
    """Normalize each ASR word so confidences stay aligned with hyp tokens.

    Whisper often attaches punctuation (\"dog.\") or leading spaces; stripping
    per token keeps probability count in sync with tokenize(heard_text).
    """
    tokens: list[str] = []
    confidences: list[float | None] = []
    for w in words or []:
        raw = getattr(w, "word", None)
        if raw is None and isinstance(w, dict):
            raw = w.get("word", "")
        prob = getattr(w, "probability", None)
        if prob is None and isinstance(w, dict):
            prob = w.get("probability")
        for part in tokenize(str(raw or "")):
            tokens.append(part)
            confidences.append(float(prob) if prob is not None else None)
    return " ".join(tokens), confidences


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i]
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            curr.append(min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost))
        prev = curr
    return prev[-1]


def is_plural_pair(a: str, b: str) -> bool:
    if a == b:
        return True
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if longer == shorter + "s":
        return True
    if longer == shorter + "es":
        return True
    if shorter.endswith("y") and longer == shorter[:-1] + "ies":
        return True
    return False


def metaphone_primary(word: str) -> str:
    primary, _ = doublemetaphone(word)
    return primary or ""


def is_beginner_edit_close(target: str, heard: str) -> bool:
    """True when a one-edit difference should count as Beginner close.

    Plan cases like cat/cot and box/dox stay close. Longer tokens that change
    the leading letter and sound different (humpty/dumpty) are not close —
    that was accepting the wrong nursery-rhyme name as a pass.
    """
    if not target or not heard:
        return False
    dist = levenshtein(target, heard)
    if dist == 0:
        return True
    if dist > 1:
        return False
    if metaphone_primary(target) == metaphone_primary(heard):
        return True
    if target[0] == heard[0]:
        return True
    # Short CVC-style tokens: first-letter swaps stay near (box/dox, fox/box).
    if len(target) <= 3 and len(heard) <= 3:
        return True
    return False


def is_beginner_near_match(target: str, heard: str) -> bool:
    if not target or not heard:
        return False
    if is_plural_pair(target, heard):
        return True
    dist = levenshtein(target, heard)
    if is_beginner_edit_close(target, heard):
        return True
    if metaphone_primary(target) == metaphone_primary(heard) and dist <= 2:
        return True
    return False


def align_tokens(target: list[str], hypothesis: list[str]) -> list[tuple[str, str]]:
    """Align target tokens to hypothesis; return (target, heard) pairs.

    Substitutions attach to the target they replace. Insertions in the
    hypothesis do not create target rows. Deletions yield heard=\"\".
    """
    matcher = SequenceMatcher(a=target, b=hypothesis, autojunk=False)
    pairs: list[tuple[str, str]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for t, h in zip(target[i1:i2], hypothesis[j1:j2]):
                pairs.append((t, h))
        elif tag == "replace":
            t_span = target[i1:i2]
            h_span = hypothesis[j1:j2]
            for idx, t in enumerate(t_span):
                heard = h_span[idx] if idx < len(h_span) else ""
                pairs.append((t, heard))
        elif tag == "delete":
            for t in target[i1:i2]:
                pairs.append((t, ""))
        elif tag == "insert":
            # Extra hypothesis words are ignored for Beginner misses.
            continue
    return pairs


def is_function_word(word: str) -> bool:
    return (word or "") in FUNCTION_WORDS


def score_word(
    target: str,
    heard: str,
    confidence: float | None,
    mode: Mode,
) -> WordResult:
    conf = confidence if confidence is not None else 0.0

    if mode == "strict":
        if heard == target and conf >= config.STRICT_CORRECT_MIN_PROB:
            return "correct"
        if heard == target and conf < config.STRICT_CORRECT_MIN_PROB:
            return "close"
        return "missed"

    # Beginner — trust an exact (or plural) transcript over Whisper
    # confidence. Kid short words often land at 0.3–0.55 and used to force
    # a pointless "close" second try.
    # Longer story/rhyme lines: forgive dropped/swapped function words so a
    # good reading is not a full miss when Whisper omits "the"/"to"/"a".
    if is_function_word(target):
        if (
            not heard
            or is_function_word(heard)
            or is_beginner_near_match(target, heard)
        ):
            return "correct"
    if not heard:
        return "missed"
    if is_plural_pair(target, heard):
        return "correct"
    dist = levenshtein(target, heard)
    if dist == 0:
        return "correct"
    if is_beginner_edit_close(target, heard):
        return "close"
    if metaphone_primary(target) == metaphone_primary(heard) and dist <= 2:
        return "close"
    return "missed"


def rollup_item(word_results: list[WordResult]) -> ItemResult:
    if not word_results:
        return "missed"
    if all(r == "correct" for r in word_results):
        return "correct"
    if any(r == "missed" for r in word_results):
        return "missed"
    return "close"


def score_attempt(
    target_text: str,
    heard_text: str,
    word_confidences: list[float | None] | None = None,
    mode: Mode = "beginner",
    *,
    force_retry: bool = False,
) -> MatchResult:
    target_tokens = tokenize(target_text)
    words_total = len(target_tokens)

    if force_retry:
        return MatchResult(
            result="retry",
            word_scores=[],
            words_correct=0,
            words_total=words_total,
            transcript="",
            replay_words=[],
        )

    hyp_tokens = tokenize(heard_text)
    transcript = " ".join(hyp_tokens)

    if not hyp_tokens:
        return MatchResult(
            result="retry",
            word_scores=[],
            words_correct=0,
            words_total=words_total,
            transcript="",
            replay_words=[],
        )

    confs = list(word_confidences or [])
    while len(confs) < len(hyp_tokens):
        confs.append(None)
    confs = confs[: len(hyp_tokens)]

    # Empty / low-confidence gate (plan step 6)
    all_low = all((c is None or c < config.LOW_TOKEN_PROB) for c in confs)
    if all_low:
        near = any(
            is_beginner_near_match(t, h)
            for t in target_tokens
            for h in hyp_tokens
        )
        if not near:
            return MatchResult(
                result="retry",
                word_scores=[],
                words_correct=0,
                words_total=words_total,
                transcript="",
                replay_words=[],
            )

    pairs = align_tokens(target_tokens, hyp_tokens)

    # Map hypothesis token -> confidence by first occurrence index
    hyp_conf_by_index = {i: confs[i] for i in range(len(hyp_tokens))}

    word_scores: list[WordScore] = []
    # Walk hyp tokens in order to assign confidences to aligned heard tokens
    hyp_cursor = 0
    for target, heard in pairs:
        confidence: float | None = None
        if heard:
            # Find next matching hyp token from cursor
            while hyp_cursor < len(hyp_tokens) and hyp_tokens[hyp_cursor] != heard:
                hyp_cursor += 1
            if hyp_cursor < len(hyp_tokens):
                confidence = hyp_conf_by_index.get(hyp_cursor)
                hyp_cursor += 1
        result = score_word(target, heard, confidence, mode)
        word_scores.append(
            WordScore(word=target, heard=heard if heard else "", confidence=confidence, result=result)
        )

    # Strict: extras / missing / reorder make the item not exact.
    exact_seq = target_tokens == hyp_tokens
    if mode == "strict" and exact_seq:
        # Exact full-line match: use mean confidence so one soft "the"/"big"
        # under 0.85 does not force a pointless second try on a clear reading.
        # Multi-word nursery lines get a lower bar — Whisper under-confidences
        # hickory/dickory even when the words are right.
        present = [
            float(ws.confidence)
            for ws in word_scores
            if ws.confidence is not None
        ]
        mean_conf = (sum(present) / len(present)) if present else 0.0
        threshold = (
            config.STRICT_MULTIWORD_EXACT_MIN_MEAN
            if words_total >= 2
            else config.STRICT_CORRECT_MIN_PROB
        )
        verdict: WordResult = "correct" if mean_conf >= threshold else "close"
        word_scores = [
            WordScore(ws.word, ws.heard, ws.confidence, verdict)
            for ws in word_scores
        ]
    elif mode == "strict" and not exact_seq:
        # Re-score: any non-exact token is missed unless exact+low-conf → close
        revised: list[WordScore] = []
        for ws in word_scores:
            if ws.heard == ws.word:
                conf = ws.confidence if ws.confidence is not None else 0.0
                if conf >= config.STRICT_CORRECT_MIN_PROB:
                    revised.append(
                        WordScore(ws.word, ws.heard, ws.confidence, "correct")
                    )
                else:
                    revised.append(
                        WordScore(ws.word, ws.heard, ws.confidence, "close")
                    )
            else:
                revised.append(WordScore(ws.word, ws.heard, ws.confidence, "missed"))
        word_scores = revised

    words_correct = sum(1 for ws in word_scores if ws.result == "correct")
    item_result = rollup_item([ws.result for ws in word_scores])
    # Extras-only (e.g. "cat" / "cat dog"): targets may all look correct, but
    # Strict still requires an exact token sequence.
    if mode == "strict" and not exact_seq and item_result == "correct":
        item_result = "missed"
    replay_words = [ws.word for ws in word_scores if ws.result == "missed"]

    return MatchResult(
        result=item_result,
        word_scores=word_scores,
        words_correct=words_correct,
        words_total=words_total,
        transcript=transcript,
        replay_words=replay_words,
    )
