"""Pure helpers for the audio clip review CLI."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "review_audio_clips",
    ROOT / "scripts" / "review_audio_clips.py",
)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def test_toks_and_hit_aliases():
    assert mod.toks("The Sun.") == ["the", "sun"]
    assert mod.hit_word("sun", ["son"])
    assert mod.hit_word("your", ["yours"])
    assert mod.hit_word("three", ["3"])
    assert not mod.hit_word("cat", ["fat", "hat"])


def test_classify_buckets():
    assert mod.classify(3) == "ok"
    assert mod.classify(2) == "ok"
    assert mod.classify(1) == "weak"
    assert mod.classify(0) == "fail"


def test_candidates_are_single_token_only():
    from app.audio_files import spoken_matches_target

    for spoken, _speed, _voice in mod.candidates("cat"):
        assert spoken_matches_target("cat", spoken), spoken
        assert " " not in spoken.strip()


def test_filler_count_ignores_target_a():
    assert mod.filler_count("a", ["a"]) == 0
    assert mod.filler_count("cat", ["the", "cat"]) == 1
