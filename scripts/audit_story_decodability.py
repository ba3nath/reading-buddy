#!/usr/bin/env python3
"""Flag story tokens outside early unlocked patterns + sight words."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.matching import tokenize  # noqa: E402
from app.patterns import FUNCTION_SIGHT, infer_word_pattern, load_ladder  # noqa: E402


def main() -> int:
    items = json.loads((ROOT / "content" / "items.json").read_text(encoding="utf-8"))
    # Early unlock set: all CVC + digraphs + sight (phase-1 starting path).
    early = set(load_ladder()[:8]) | {"sight"}
    lines: list[str] = [
        "# Story decodability audit",
        "",
        f"Allowed early patterns: {', '.join(sorted(early))}",
        "",
    ]
    issues = 0
    for item in items:
        if not item.get("story_id"):
            continue
        bad: list[str] = []
        for tok in tokenize(item["text"]):
            if tok in FUNCTION_SIGHT:
                continue
            pat, sight = infer_word_pattern(tok)
            if sight or pat in early:
                continue
            bad.append(f"{tok}({pat})")
        if bad:
            issues += 1
            lines.append(
                f"- `{item['slug']}` ({item['story_id']}): {item['text']} — OOV: {', '.join(bad)}"
            )
    if issues == 0:
        lines.append("No out-of-pattern content words found against the early ladder.")
    else:
        lines.append("")
        lines.append(f"**{issues}** line(s) have words beyond early patterns.")
    out = ROOT / "docs" / "story-decodability.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {out} ({issues} flagged lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
