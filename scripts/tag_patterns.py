#!/usr/bin/env python3
"""Tag every content item with pattern + sight_word; rewrite items.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.patterns import infer_item_pattern, validate_items  # noqa: E402


def main() -> int:
    path = ROOT / "content" / "items.json"
    items = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(items, list):
        items = items.get("items", [])
    for item in items:
        pattern, sight = infer_item_pattern(item)
        item["pattern"] = pattern
        item["sight_word"] = bool(sight)
    errors = validate_items(items)
    if errors:
        print("Validation failed:", file=sys.stderr)
        for err in errors[:20]:
            print(" ", err, file=sys.stderr)
        return 1
    path.write_text(json.dumps(items, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    from collections import Counter

    counts = Counter(i["pattern"] for i in items)
    print(f"Tagged {len(items)} items:")
    for key, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {key}: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
