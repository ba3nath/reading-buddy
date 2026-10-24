#!/usr/bin/env python3
"""Phase 5a: matching FP/FN report against labeled reading intent.

Does not change matcher behavior — freezes and guards a baseline.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.matching import score_attempt  # noqa: E402

CASES_PATH = ROOT / "eval" / "matching" / "cases.json"
BUDGETS_PATH = ROOT / "eval" / "matching" / "baseline_budgets.json"


def load_cases(path: Path = CASES_PATH) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_budgets(path: Path = BUDGETS_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def run_case(case: dict[str, Any]) -> dict[str, Any]:
    match = score_attempt(
        case["target_text"],
        case.get("heard_text", ""),
        case.get("word_confidences"),
        mode=case["mode"],
        force_retry=bool(case.get("force_retry")),
    )
    result = match.result
    label = case["reading_label"]
    baseline = case.get("baseline_result")
    false_accept = label == "reading_mistake" and result == "correct"
    false_reject = label == "reading_ok" and result == "missed"
    silence_ok = label == "silence" and result == "retry"
    uncertain_ok = label == "asr_uncertain" and result == "retry"
    baseline_ok = baseline is None or baseline == result
    return {
        "id": case["id"],
        "mode": case["mode"],
        "bucket": case.get("bucket", ""),
        "reading_label": label,
        "result": result,
        "baseline_result": baseline,
        "baseline_ok": baseline_ok,
        "false_accept": false_accept,
        "false_reject": false_reject,
        "silence_ok": silence_ok if label == "silence" else None,
        "uncertain_ok": uncertain_ok if label == "asr_uncertain" else None,
        "notes": case.get("notes", ""),
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def rate(num: int, den: int) -> float:
        return (num / den) if den else 0.0

    by_mode: dict[str, Any] = {}
    for mode in sorted({r["mode"] for r in rows}):
        subset = [r for r in rows if r["mode"] == mode]
        ok_n = sum(1 for r in subset if r["reading_label"] == "reading_ok")
        miss_n = sum(1 for r in subset if r["reading_label"] == "reading_mistake")
        fa = sum(1 for r in subset if r["false_accept"])
        fr = sum(1 for r in subset if r["false_reject"])
        by_mode[mode] = {
            "n": len(subset),
            "reading_ok": ok_n,
            "reading_mistake": miss_n,
            "false_accept": fa,
            "false_reject": fr,
            "false_accept_rate": rate(fa, miss_n),
            "false_reject_rate": rate(fr, ok_n),
            "close": sum(1 for r in subset if r["result"] == "close"),
            "retry": sum(1 for r in subset if r["result"] == "retry"),
        }

    ok_n = sum(1 for r in rows if r["reading_label"] == "reading_ok")
    miss_n = sum(1 for r in rows if r["reading_label"] == "reading_mistake")
    fa = sum(1 for r in rows if r["false_accept"])
    fr = sum(1 for r in rows if r["false_reject"])
    drift = sum(1 for r in rows if not r["baseline_ok"])
    silence_fail = sum(
        1 for r in rows if r["silence_ok"] is False
    )
    uncertain_fail = sum(
        1 for r in rows if r["uncertain_ok"] is False
    )
    by_bucket: dict[str, int] = defaultdict(int)
    for r in rows:
        if r["false_accept"] or r["false_reject"] or not r["baseline_ok"]:
            by_bucket[r["bucket"] or "unknown"] += 1

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_cases": len(rows),
        "confidence_calibrated": False,
        "overall": {
            "reading_ok": ok_n,
            "reading_mistake": miss_n,
            "false_accept": fa,
            "false_reject": fr,
            "false_accept_rate": rate(fa, miss_n),
            "false_reject_rate": rate(fr, ok_n),
            "baseline_drift": drift,
            "silence_misfires": silence_fail,
            "uncertain_misfires": uncertain_fail,
        },
        "by_mode": by_mode,
        "issue_buckets": dict(by_bucket),
        "rows": rows,
    }


def check_budgets(summary: dict[str, Any], budgets: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    overall = summary["overall"]
    o = budgets["overall"]
    if overall["false_accept_rate"] > o["max_false_accept_rate"] + 1e-12:
        failures.append(
            f"overall false_accept_rate {overall['false_accept_rate']:.3f} "
            f"> {o['max_false_accept_rate']}"
        )
    if overall["false_reject_rate"] > o["max_false_reject_rate"] + 1e-12:
        failures.append(
            f"overall false_reject_rate {overall['false_reject_rate']:.3f} "
            f"> {o['max_false_reject_rate']}"
        )
    if overall["baseline_drift"] > o["max_baseline_drift"]:
        failures.append(
            f"baseline_drift {overall['baseline_drift']} > {o['max_baseline_drift']}"
        )
    for mode, caps in budgets.get("by_mode", {}).items():
        block = summary["by_mode"].get(mode)
        if not block:
            continue
        if block["false_accept_rate"] > caps["max_false_accept_rate"] + 1e-12:
            failures.append(
                f"{mode} false_accept_rate {block['false_accept_rate']:.3f} "
                f"> {caps['max_false_accept_rate']}"
            )
        if block["false_reject_rate"] > caps["max_false_reject_rate"] + 1e-12:
            failures.append(
                f"{mode} false_reject_rate {block['false_reject_rate']:.3f} "
                f"> {caps['max_false_reject_rate']}"
            )
    if overall["silence_misfires"]:
        failures.append(f"silence_misfires={overall['silence_misfires']}")
    if overall["uncertain_misfires"]:
        failures.append(f"uncertain_misfires={overall['uncertain_misfires']}")
    return failures


def format_report(summary: dict[str, Any], failures: list[str]) -> str:
    o = summary["overall"]
    lines = [
        "Matching benchmark (Phase 5a)",
        f"cases={summary['n_cases']}  calibrated={summary['confidence_calibrated']}",
        (
            f"FP (mistake→correct): {o['false_accept']}/{o['reading_mistake']} "
            f"= {o['false_accept_rate']:.3f}"
        ),
        (
            f"FN (ok→missed): {o['false_reject']}/{o['reading_ok']} "
            f"= {o['false_reject_rate']:.3f}"
        ),
        f"baseline_drift={o['baseline_drift']}",
    ]
    for mode, block in summary["by_mode"].items():
        lines.append(
            f"  {mode}: FP={block['false_accept_rate']:.3f} "
            f"FN={block['false_reject_rate']:.3f} "
            f"close={block['close']} retry={block['retry']}"
        )
    bad = [
        r
        for r in summary["rows"]
        if r["false_accept"] or r["false_reject"] or not r["baseline_ok"]
    ]
    if bad:
        lines.append("flagged cases:")
        for r in bad:
            flags = []
            if r["false_accept"]:
                flags.append("FP")
            if r["false_reject"]:
                flags.append("FN")
            if not r["baseline_ok"]:
                flags.append(
                    f"drift(expected={r['baseline_result']}, got={r['result']})"
                )
            lines.append(f"  - {r['id']}: {', '.join(flags)}")
    if failures:
        lines.append("BUDGET FAILURES:")
        lines.extend(f"  ! {f}" for f in failures)
    else:
        lines.append("budgets: OK")
    return "\n".join(lines)


def run_benchmark(
    *,
    cases_path: Path = CASES_PATH,
    budgets_path: Path = BUDGETS_PATH,
) -> tuple[dict[str, Any], list[str]]:
    cases = load_cases(cases_path)
    budgets = load_budgets(budgets_path)
    rows = [run_case(c) for c in cases]
    summary = summarize(rows)
    failures = check_budgets(summary, budgets)
    return summary, failures


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Evaluate matching FP/FN vs labeled cases")
    p.add_argument(
        "--json",
        type=Path,
        default=None,
        help="Write full JSON report to this path",
    )
    p.add_argument("--cases", type=Path, default=CASES_PATH)
    p.add_argument("--budgets", type=Path, default=BUDGETS_PATH)
    args = p.parse_args(argv)
    summary, failures = run_benchmark(cases_path=args.cases, budgets_path=args.budgets)
    print(format_report(summary, failures))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        payload = {**summary, "budget_failures": failures}
        args.json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {args.json}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
