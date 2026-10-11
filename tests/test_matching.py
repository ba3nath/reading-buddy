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


def test_low_confidence_exact_is_close_beginner():
    result = score_attempt("cat", "cat", [0.40], mode="beginner")
    assert result.result == "close"
    assert result.word_scores[0].result == "close"
