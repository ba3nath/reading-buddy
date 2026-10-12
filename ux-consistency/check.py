#!/usr/bin/env python3
"""UX consistency gate for one phase of the child and parent flows."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check(phase: str) -> list[str]:
    html = (ROOT / "static/index.html").read_text(encoding="utf-8")
    js = (ROOT / "static/js/game.js").read_text(encoding="utf-8")
    parent = (ROOT / "static/parent.html").read_text(encoding="utf-8")
    failures: list[str] = []
    if "data-stage-pick" in html:
        failures.append("Child home grew a set picker.")
    if 'I heard "' not in js:
        failures.append('Child never shows "I heard".')
    if "sessionStorage" not in js or "/api/sessions/open" not in js:
        failures.append("Refresh cannot resume an open session.")
    if "data-try-again" not in html:
        failures.append("End screen has no Try these again button.")
    if "setTimeout(() => startReplay()" in js:
        failures.append("Replay still starts by itself.")
    if "profile_name" not in js:
        failures.append("Profile name is not used in the greeting.")
    if "data-hear-again" not in html:
        failures.append("Hear again is missing.")
    later = phase in {"2", "fluency", "3", "4"}
    if later:
        items = (ROOT / "content/items.json").read_text(encoding="utf-8")
        adaptive = (ROOT / "app/adaptive.py").read_text(encoding="utf-8")
        if "story_id" not in items or "_one_group_queue" not in adaptive:
            failures.append("A rhyme or story session can still mix groups.")
        if "The cat sat on the mat." in items:
            failures.append("Loose story sentences are still in the content.")
    if phase in {"fluency", "3", "4"}:
        if "startReadThrough" not in js:
            failures.append("Read it through is missing.")
        if "duration_seconds" in js:
            failures.append("The child script reads the read-through duration.")
        if "data-tomorrow-through" not in parent:
            failures.append("Parent page cannot show the read-through.")
    if phase in {"3", "4"}:
        if "mastered_words" not in js or "data-tomorrow-stay" not in parent:
            failures.append("The set name or mastered words are not shown.")
    if phase == "4":
        if "is-word" not in js or "word-soft" not in js:
            failures.append("Word cards and missed phrase words are not marked.")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True)
    args = parser.parse_args(argv)
    failures = check(args.phase)
    print(json.dumps({"agent": "ux-consistency", "ok": not failures, "phase": args.phase, "failures": failures}, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
