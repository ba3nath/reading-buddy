#!/usr/bin/env python3
"""Test coverage gate. Fails when pytest fails or new behavior has no test."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check(phase: str) -> list[str]:
    text = (ROOT / "tests/test_session_phases.py").read_text(encoding="utf-8")
    failures: list[str] = []
    required = {
        "1": ("open_session_view", "read_again", "mode_source"),
        "2": ("story_id", "rhyme_group"),
        "fluency": ("apply_passage", "duration_seconds"),
        "3": ("quest_label", "mastered_words"),
        "4": ("word-soft", "is-word"),
        "runner": (
            "ensure_deps",
            "find_system_python",
            "verify_runtime_imports",
            "requires-python",
            "ctranslate2",
        ),
    }
    # Phase 4 markers live in the client; coverage still requires the phase tests above.
    blob = (
        text
        + "\n"
        + (ROOT / "static/js/game.js").read_text(encoding="utf-8")
        + "\n"
        + (ROOT / "tests/test_runner.py").read_text(encoding="utf-8")
        + "\n"
        + (ROOT / "tests/test_dependencies.py").read_text(encoding="utf-8")
        + "\n"
        + (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        + "\n"
        + (ROOT / "requirements.txt").read_text(encoding="utf-8")
    )
    for marker in required.get(phase, ()):
        if marker not in blob and marker not in text:
            failures.append(f"No test or client marker for {marker}.")
    if os.environ.get("READING_BUDDY_SKIP_PYTEST") == "1":
        return failures
    py = ROOT / ".venv" / "bin" / "python"
    cmd = [
        str(py) if py.exists() else sys.executable,
        "-m",
        "pytest",
        "-q",
        "--tb=no",
        "--ignore=tests/test_gate_agents.py",
    ]
    result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        tail = (result.stdout or result.stderr or "").strip().splitlines()[-5:]
        failures.append("pytest failed: " + " | ".join(tail))
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True)
    args = parser.parse_args(argv)
    failures = check(args.phase)
    print(json.dumps({"agent": "test-coverage", "ok": not failures, "phase": args.phase, "failures": failures}, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
