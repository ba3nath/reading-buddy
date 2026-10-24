#!/usr/bin/env python3
"""Print adaptive vs static hard-word review counts (Phase 6)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval.scheduler.sim import compare  # noqa: E402


def main() -> int:
    results = compare(seed=7)
    payload = {
        mode: {
            "hard_reviews": r.hard_reviews,
            "easy_reviews": r.easy_reviews,
            "hard_misses": r.hard_misses,
            "hard_share": round(r.hard_share, 3),
            "days": r.days,
        }
        for mode, r in results.items()
    }
    print(json.dumps(payload, indent=2))
    adaptive = results["adaptive"]
    static = results["static"]
    if adaptive.hard_reviews <= static.hard_reviews:
        print(
            f"FAIL: adaptive hard_reviews ({adaptive.hard_reviews}) "
            f"<= static ({static.hard_reviews})",
            file=sys.stderr,
        )
        return 1
    print(
        f"OK: adaptive hard_reviews {adaptive.hard_reviews} "
        f"> static {static.hard_reviews}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
