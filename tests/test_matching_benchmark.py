"""Phase 5a: matching benchmark stays within FP/FN budgets."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "eval_matching_benchmark", ROOT / "scripts" / "eval_matching_benchmark.py"
)
assert SPEC and SPEC.loader
bench = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bench)


def test_matching_benchmark_within_budgets():
    summary, failures = bench.run_benchmark()
    assert summary["n_cases"] >= 20
    assert summary["confidence_calibrated"] is False
    assert failures == [], failures


def test_matching_benchmark_flags_plural_strict_as_known_fn():
    summary, _failures = bench.run_benchmark()
    plural = next(r for r in summary["rows"] if r["id"] == "cat-plural-strict")
    assert plural["false_reject"] is True
    assert plural["result"] == "missed"


def test_matching_benchmark_silence_is_retry_not_missed():
    summary, _failures = bench.run_benchmark()
    silence = [r for r in summary["rows"] if r["reading_label"] == "silence"]
    assert silence
    assert all(r["result"] == "retry" for r in silence)


def test_cli_exits_zero(capsys):
    assert bench.main([]) == 0
    out = capsys.readouterr().out
    assert "budgets: OK" in out
    assert "FP" in out or "false_accept" in out.lower() or "mistake→correct" in out
