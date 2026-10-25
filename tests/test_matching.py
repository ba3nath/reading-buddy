"""Unit tests for normalize / align / Beginner / Strict scoring."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.matching import (
    align_tokens,
    hypothesis_from_whisper_words,
    is_beginner_edit_close,
    is_plural_pair,
    levenshtein,
    metaphone_primary,
    normalize_text,
    score_attempt,
    tokenize,
)
from app.whisper_engine import TranscriptWord

FIXTURES = Path(__file__).parent / "fixtures" / "transcripts"
CONTENT = Path(__file__).resolve().parents[1] / "content" / "items.json"


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
        "humpty-dumpty-beginner",
        "jill-hill-beginner",
        "sit-sat-beginner",
        "ship-chip-beginner",
        "story-line-function-drops",
        "story-line-content-miss",
        "story-line-function-drops-strict",
    ],
)
def test_transcript_fixtures(name):
    _run_case(name)


def test_hypothesis_from_whisper_words_strips_punctuation():
    heard, confs = hypothesis_from_whisper_words(
        [
            TranscriptWord(word=" The", probability=0.9),
            TranscriptWord(word="big", probability=0.8),
            TranscriptWord(word="dog.", probability=0.7),
        ]
    )
    assert heard == "the big dog"
    assert confs == [0.9, 0.8, 0.7]


def test_beginner_function_word_swap_still_correct():
    from app.matching import FUNCTION_WORDS, score_attempt

    assert "the" in FUNCTION_WORDS
    result = score_attempt(
        "Sit on the bed with me.",
        "sit on a bed with me",
        [0.9] * 6,
        mode="beginner",
    )
    assert result.result == "correct"


def test_strict_exact_low_confidence_is_still_correct():
    """If the transcript matches, soft Whisper probs must not ask read-again."""
    result = score_attempt(
        "Hickory dickory dock",
        "hickory dickory dock",
        [0.2, 0.2, 0.2],
        mode="strict",
    )
    assert result.result == "correct"
    single = score_attempt("cup", "cup", [0.4], mode="strict")
    assert single.result == "correct"


def test_strict_exact_phrase_missing_confidences_is_correct():
    """Exact transcript must not become close when Whisper omits probs."""
    result = score_attempt(
        "three red hats",
        "three red hats",
        None,
        mode="strict",
    )
    assert result.result == "correct"
    assert result.transcript == "three red hats"


def test_strict_exact_phrase_mid_confidence_is_correct():
    """Kid phrase readings often land ~0.4 mean — still accept exact text."""
    confs = [0.42, 0.38, 0.45]
    assert sum(confs) / len(confs) < 0.50
    result = score_attempt(
        "three red hats",
        "three red hats",
        confs,
        mode="strict",
    )
    assert result.result == "correct"


def test_three_and_digit_3_are_equivalent():
    beginner = score_attempt("three red hats", "3 red hats", [0.9] * 3, mode="beginner")
    assert beginner.result == "correct"
    strict = score_attempt("three red hats", "3 red hats", [0.9] * 3, mode="strict")
    assert strict.result == "correct"


def test_away_and_await_are_equivalent():
    """Whisper often appends a ghost /t/ on away → await (not edit-close)."""
    beginner = score_attempt(
        "rain rain go away",
        "rain rain go await",
        [0.9] * 4,
        mode="beginner",
    )
    assert beginner.result == "correct"
    strict = score_attempt(
        "rain rain go away",
        "rain rain go await",
        [0.9] * 4,
        mode="strict",
    )
    assert strict.result == "correct"


def test_path_pass_baa_bar_lane_lake_aliases():
    assert score_attempt(
        "A red bus was on the path",
        "a red bus was on the pass",
        [0.9] * 6,
        mode="strict",
    ).result == "correct"
    assert score_attempt(
        "Baa baa black sheep",
        "bar bar black sheep",
        [0.9] * 4,
        mode="beginner",
    ).result == "correct"
    assert score_attempt(
        "down the lane",
        "down the lake",
        [0.9] * 3,
        mode="strict",
    ).result == "correct"


def test_hop_help_and_big_biggie_aliases():
    assert score_attempt(
        "The dog and the fox can hop",
        "the dog and the fox can help",
        [0.9] * 6,
        mode="strict",
    ).result == "correct"
    assert score_attempt(
        "Hop to the red box",
        "hope to the red box",
        [0.9] * 5,
        mode="beginner",
    ).result == "correct"
    assert score_attempt(
        "The red pen is big",
        "the red pen is biggie",
        [0.9] * 5,
        mode="strict",
    ).result == "correct"


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


@pytest.mark.parametrize(
    "target,heard,expect_close",
    [
        # Plan short-word cases — Beginner levels must stay forgiving.
        ("cat", "cot", True),
        ("box", "dox", True),
        ("fox", "box", True),
        ("sit", "sat", True),
        ("top", "tap", True),
        ("bus", "bas", True),
        # Same onset / same sound — still close.
        ("clock", "clok", True),
        ("together", "togther", True),
        ("again", "agin", True),
        ("ship", "chip", True),
        ("swim", "swam", True),
        # Longer name / rhyme swaps that change onset + sound — miss.
        ("humpty", "dumpty", False),
        ("jill", "hill", False),
        ("jack", "pack", False),
        ("mouse", "house", False),
    ],
)
def test_is_beginner_edit_close_matrix(target, heard, expect_close):
    assert is_beginner_edit_close(target, heard) is expect_close
    result = score_attempt(target, heard, [0.95], mode="beginner").word_scores[0].result
    if expect_close:
        assert result == "close"
    else:
        assert result == "missed"


def test_beginner_level1_short_words_keep_vowel_near_misses():
    """Level-1 CVC words: one-letter vowel slips stay Beginner close."""
    items = json.loads(CONTENT.read_text(encoding="utf-8"))
    level1 = [i["text"].lower() for i in items if i["level"] == 1 and i["kind"] == "word"]
    assert len(level1) >= 10
    short = [w for w in level1 if len(w) == 3]
    assert short, "expected 3-letter level-1 words"
    # Middle-vowel swap: cVc → cXc with a different vowel when possible.
    vowels = "aeiou"
    checked = 0
    for word in short:
        if word[1] not in vowels:
            continue
        alt_vowel = "a" if word[1] != "a" else "i"
        heard = word[0] + alt_vowel + word[2]
        if heard == word:
            continue
        result = score_attempt(word, heard, [0.95], mode="beginner")
        assert result.result == "close", f"{word}/{heard} should stay close"
        checked += 1
    assert checked >= 5


def test_beginner_level3_onset_preserving_slips_stay_close():
    """Level-3 blends: keep close when the first letter stays the same."""
    items = json.loads(CONTENT.read_text(encoding="utf-8"))
    level3 = [i["text"].lower() for i in items if i["level"] == 3 and i["kind"] == "word"]
    assert "ship" in level3 or "frog" in level3
    for target, heard in (("ship", "chip"), ("frog", "fog"), ("trap", "trip"), ("flag", "flak")):
        if target not in level3:
            continue
        result = score_attempt(target, heard, [0.95], mode="beginner")
        assert result.word_scores[0].result == "close", f"{target}/{heard}"


def test_humpty_line_strict_also_misses_dumpty():
    result = score_attempt(
        "Could not put Humpty together again",
        "Could not put dumpty together again",
        [0.95] * 6,
        mode="strict",
    )
    assert result.result == "missed"
    assert result.replay_words == ["humpty"]


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


def test_low_confidence_exact_is_correct_strict():
    result = score_attempt("cat", "cat", [0.40], mode="strict")
    assert result.result == "correct"
    assert result.word_scores[0].result == "correct"


def test_strict_exact_line_uses_mean_confidence():
    """Real session: Whisper heard the line; two soft tokens must not fail it."""
    confs = [
        0.5750277042388916,  # the
        0.7884606122970581,  # big
        0.9936681389808655,  # dog
        0.863253653049469,  # ran
        0.9780876636505127,  # to
        0.9955867528915405,  # the
        0.9698108434677124,  # cat
    ]
    result = score_attempt(
        "The big dog ran to the cat.",
        "the big dog ran to the cat",
        confs,
        mode="strict",
    )
    assert result.result == "correct"
    assert result.words_correct == 7
    assert all(ws.result == "correct" for ws in result.word_scores)


def test_strict_hickory_exact_low_mean_still_correct():
    """Real session 25: exact 'hickory dickory dock' at mean ~0.55 must pass."""
    confs = [0.42491139593039406, 0.5735829919576645, 0.6374983191490173]
    result = score_attempt(
        "Hickory dickory dock",
        "hickory dickory dock",
        confs,
        mode="strict",
    )
    assert sum(confs) / len(confs) < 0.85
    assert result.result == "correct"
    assert result.words_correct == 3


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
