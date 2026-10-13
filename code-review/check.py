#!/usr/bin/env python3
"""Code review gate for kindness, scope, and the read-through duration rule."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check(phase: str) -> list[str]:
    adaptive = (ROOT / "app/adaptive.py").read_text(encoding="utf-8")
    config = (ROOT / "app/config.py").read_text(encoding="utf-8")
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    html = (ROOT / "static/index.html").read_text(encoding="utf-8")
    clip = (ROOT / "audio-clip-review/bot/instructions.md").read_text(encoding="utf-8")
    failures: list[str] = []
    if "mode_source" not in adaptive:
        failures.append("Auto strict cannot tell a parent choice from an automatic one.")
    if 'settings["mode"] = "beginner"' not in adaptive:
        failures.append("Auto strict never steps back to beginner.")
    if "MSG_MISS_AGAIN" not in config:
        failures.append("A first miss has no kind second-read line.")
    if "data-stage-pick" not in html:
        failures.append("The child cannot choose a difficulty and set.")
    if phase in {"fluency", "3", "4"} and 'payload.pop("duration_seconds"' not in main:
        failures.append("Read-through duration can leak to the child response.")
    if "No carriers" not in clip:
        failures.append("audio-clip-review instructions were changed.")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True)
    args = parser.parse_args(argv)
    failures = check(args.phase)
    print(json.dumps({"agent": "code-review", "ok": not failures, "phase": args.phase, "failures": failures}, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
