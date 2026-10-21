#!/usr/bin/env python3
"""Reorder word/phrase items so stage slices follow the phonics ladder."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.patterns import pattern_rank  # noqa: E402


def main() -> int:
    path = ROOT / "content" / "items.json"
    items = json.loads(path.read_text(encoding="utf-8"))
    words = [i for i in items if i.get("kind") == "word"]
    phrases = [i for i in items if i.get("kind") == "phrase"]
    rest = [i for i in items if i.get("kind") not in ("word", "phrase")]

    def sort_key(item: dict) -> tuple:
        return (
            int(item.get("level", 1)),
            pattern_rank(str(item.get("pattern") or "sight")),
            str(item.get("slug") or ""),
        )

    words_sorted = sorted(words, key=sort_key)
    phrases_sorted = sorted(phrases, key=sort_key)
    # Preserve non-word/phrase order (rhymes/stories already grouped).
    out = words_sorted + phrases_sorted + rest
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Reordered {len(words_sorted)} words and {len(phrases_sorted)} phrases by pattern ladder.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
