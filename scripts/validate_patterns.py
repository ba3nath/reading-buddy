#!/usr/bin/env python3
"""Fail if any item lacks a valid pattern / sight_word."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.patterns import validate_items  # noqa: E402


def main() -> int:
    path = ROOT / "content" / "items.json"
    items = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(items, list):
        items = items.get("items", [])
    errors = validate_items(items)
    if errors:
        print(f"{len(errors)} pattern tag error(s):", file=sys.stderr)
        for err in errors[:50]:
            print(" ", err, file=sys.stderr)
        return 1
    print(f"OK: {len(items)} items fully tagged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
