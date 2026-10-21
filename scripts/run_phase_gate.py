#!/usr/bin/env python3
"""Run the four phase gate agents. Exit 1 if any agent fails."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = (
    "design-consistency",
    "ux-consistency",
    "test-coverage",
    "code-review",
    "drift-review",
)


def main(argv: list[str] | None = None) -> int:
    phase = (argv or sys.argv[1:])[0] if (argv or sys.argv[1:]) else "1"
    failed = False
    for name in AGENTS:
        check = ROOT / name / "check.py"
        result = subprocess.run([sys.executable, str(check), "--phase", phase])
        failed = failed or result.returncode != 0
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
