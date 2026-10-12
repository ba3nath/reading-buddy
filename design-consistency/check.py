#!/usr/bin/env python3
"""Design consistency gate. Exit 1 when this phase's UI drifts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check(phase: str) -> list[str]:
    html = (ROOT / "static/index.html").read_text(encoding="utf-8")
    js = (ROOT / "static/js/game.js").read_text(encoding="utf-8")
    css = (ROOT / "static/css/app.css").read_text(encoding="utf-8")
    failures: list[str] = []
    if "data-stage-pick" in html or "Pick a difficulty" in html:
        failures.append("Child home still has a set picker.")
    if 'class="btn primary" data-start>Start</button>' not in html:
        failures.append("Primary Start button is missing.")
    lowered = js.lower()
    if "words per minute" in lowered or "words-per-minute" in lowered:
        failures.append("Child script mentions words per minute.")
    soft = css.split(".word-soft", 1)[-1][:400] if ".word-soft" in css else ""
    if "red" in soft or "#f00" in soft:
        failures.append("Missed-word style uses a red fail treatment.")
    if phase in {"4", "phase4"}:
        if ".word-art.is-word" not in css:
            failures.append("Single-word picture is not enlarged.")
        if ".word-soft" not in css:
            failures.append("Missed words in a phrase have no soft mark.")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True)
    args = parser.parse_args(argv)
    failures = check(args.phase)
    print(json.dumps({"agent": "design-consistency", "ok": not failures, "phase": args.phase, "failures": failures}, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
