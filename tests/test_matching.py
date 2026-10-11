"""Unit tests for normalize / align / Beginner / Strict scoring."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.matching import (
    align_tokens,
    is_plural_pair,
    levenshtein,
    metaphone_primary,
    normalize_text,
    score_attempt,
    tokenize,
)

FIXTURES = Path(__file__).parent / "fixtures" / "transcripts"


def _load(name: str) -> dict:
    with (FIXTURES / f"{name}.json").open(encoding="utf-8") as f:
        return json.load(f)


def _run_case(name: str):
    case = _load(name)
    result = score_attempt(
        case["target_text"],
        case["heard_text"],
        case.get("word_confidences"),
        mode=case["mode"],
        force_retry=bool(case.get("force_retry")),
    )
    expect = case["expect"]
    assert result.result == expect["result"]
    assert result.words_correct == expect["words_correct"]
    assert result.words_total == expect["words_total"]
    assert result.replay_words == expect["replay_words"]
    assert len(result.word_scores) == len(expect["word_scores"])
    for got, exp in zip(result.word_scores, expect["word_scores"]):
        assert got.word == exp["word"]
        assert got.heard == exp["heard"]
        assert got.result == exp["result"]
        if exp["confidence"] is None:
            assert got.confidence is None
        else:
            assert got.confidence == pytest.approx(exp["confidence"])


@pytest.mark.parametrize(
    "name",
    [
        "cat-exact",
        "cat-plural-beginner",
        "cat-plural-strict",
        "cat-cot",
        "cat-dog",
        "silence",
        "big-red-bus",
        "fox-beginner",
        "fox-strict",
    ],
)
def test_transcript_fixtures(name):
    _run_case(name)


def test_normalize_strips_punctuation():
    assert normalize_text("Don't!") == "dont"
    assert tokenize("Quick brown fox") == ["quick", "brown", "fox"]


def test_plural_pairs():
    assert is_plural_pair("cat", "cats")
    assert is_plural_pair("bus", "buses")
    assert is_plural_pair("baby", "babies")
    assert not is_plural_pair("jump", "jumped")
    assert not is_plural_pair("sun", "un")


def test_jumped_jump_not_close_beginner():
    # Levenshtein 2, metaphone JMP vs JMPT
    assert levenshtein("jumped", "jump") == 2
    assert metaphone_primary("jump") != metaphone_primary("jumped")
    result = score_attempt("jumped", "jump", [0.95], mode="beginner")
    assert result.word_scores[0].result == "missed"


def test_humpty_vs_dumpty_is_missed_beginner():
    """Saying Dumpty for Humpty must not lock as a Beginner near-miss pass."""
    assert levenshtein("humpty", "dumpty") == 1
    assert metaphone_primary("humpty") != metaphone_primary("dumpty")
    word = score_attempt("Humpty", "dumpty", [0.95], mode="beginner")
    assert word.result == "missed"
    assert word.word_scores[0].result == "missed"

    line = score_attempt(
        "Could not put Humpty together again",
        "Could not put dumpty together again",
        [0.95] * 6,
        mode="beginner",
    )
    assert line.result == "missed"
    by_word = {ws.word: ws for ws in line.word_scores}
    assert by_word["humpty"].result == "missed"
    assert by_word["humpty"].heard == "dumpty"
    assert "humpty" in line.replay_words
    assert line.words_correct == 5


def test_short_first_letter_swap_still_close_beginner():
    """Plan fixtures: cat/cot and box/dox stay Beginner close."""
    assert score_attempt("cat", "cot", [0.90], mode="beginner").result == "close"
    assert score_attempt("box", "dox", [0.88], mode="beginner").word_scores[0].result == (
        "close"
    )


def test_jill_vs_hill_is_missed_beginner():
    """Rhyme names that only share an edit must not count as close."""
    result = score_attempt("Jill", "hill", [0.95], mode="beginner")
    assert result.result == "missed"


def test_fox_alignment_keeps_later_corrects():
    pairs = align_tokens(
        tokenize("Quick brown fox jumped over the box"),
        tokenize("Quick down fox jump over the dox"),
    )
    by_target = {t: h for t, h in pairs}
    assert by_target["fox"] == "fox"
    assert by_target["over"] == "over"
    assert by_target["the"] == "the"
    assert by_target["brown"] == "down"
    assert by_target["box"] == "dox"


def test_low_confidence_exact_is_correct_beginner():
    # Whisper often scores kid short words under 0.60 — still count as correct.
    result = score_attempt("cat", "cat", [0.40], mode="beginner")
    assert result.result == "correct"
    assert result.word_scores[0].result == "correct"


def test_low_confidence_exact_still_close_strict():
    result = score_attempt("cat", "cat", [0.40], mode="strict")
    assert result.result == "close"
    assert result.word_scores[0].result == "close"


def test_strict_extras_not_exact():
    """Strict: extra hypothesis tokens make the item not exact (contracts §4)."""
    beginner = score_attempt("cat", "cat dog", [0.95, 0.95], mode="beginner")
    assert beginner.result == "correct"
    assert beginner.word_scores[0].result == "correct"

    strict = score_attempt("cat", "cat dog", [0.95, 0.95], mode="strict")
    assert strict.word_scores[0].result == "correct"
    assert strict.result == "missed"
    assert strict.words_correct == 1
    assert strict.words_total == 1
