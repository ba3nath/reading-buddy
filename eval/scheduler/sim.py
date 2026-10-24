"""Adaptive vs static review sim (Phase 6 DoD).

Pure in-memory model: Leitner-like gaps + weak-skill prefer vs round-robin.
Proves hard (frequently missed) items are reviewed more under adaptive.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# Mirror app.config.LEITNER_GAPS_DAYS
GAPS = (0, 1, 3, 7, 14)


@dataclass
class ItemState:
    item_id: int
    pattern: str
    hard: bool = False
    box: int = 1
    next_due: int = 0  # day index
    reviews: int = 0
    misses: int = 0
    hits: int = 0


@dataclass
class SimResult:
    label: str
    hard_reviews: int
    easy_reviews: int
    hard_misses: int
    days: int
    notes: dict[str, int] = field(default_factory=dict)

    @property
    def hard_share(self) -> float:
        total = self.hard_reviews + self.easy_reviews
        return (self.hard_reviews / total) if total else 0.0


def _success_prob(item: ItemState, day: int) -> float:
    """Hard items stay weak until they've been reviewed several times."""
    if not item.hard:
        return 0.9
    # Improves slowly with successful hits
    return min(0.85, 0.35 + 0.08 * item.hits)


def _attempt(item: ItemState, day: int, rng_u: float) -> bool:
    ok = rng_u < _success_prob(item, day)
    item.reviews += 1
    if ok:
        item.hits += 1
        # one box bump per calendar day already encoded (one attempt / day here)
        item.box = min(5, item.box + 1)
        gap = GAPS[min(item.box, len(GAPS)) - 1]
        item.next_due = day + int(gap)
    else:
        item.misses += 1
        item.box = 1
        item.next_due = day  # due again immediately (gap 0)
    return ok


def _static_pick(pool: list[ItemState], day: int, cursor: int) -> tuple[ItemState, int]:
    """Round-robin across all items regardless of due / difficulty."""
    item = pool[cursor % len(pool)]
    return item, cursor + 1


def _adaptive_pick(pool: list[ItemState], day: int, weak_patterns: set[str]) -> ItemState:
    """Due first; among due prefer weak patterns; else lowest box."""
    due = [i for i in pool if i.next_due <= day]
    if due:
        weak_due = [i for i in due if i.pattern in weak_patterns]
        bucket = weak_due or due
        bucket.sort(key=lambda i: (i.box, i.next_due, i.item_id))
        return bucket[0]
    pool_sorted = sorted(pool, key=lambda i: (i.box, i.next_due, i.item_id))
    return pool_sorted[0]


def _weak_patterns(pool: list[ItemState]) -> set[str]:
    by_pat: dict[str, list[ItemState]] = {}
    for i in pool:
        by_pat.setdefault(i.pattern, []).append(i)
    weak: set[str] = set()
    for pat, items in by_pat.items():
        misses = sum(i.misses for i in items)
        hits = sum(i.hits for i in items)
        if misses > hits:
            weak.add(pat)
    return weak


def run_sim(
    *,
    days: int = 40,
    session_len: int = 5,
    seed: int = 7,
    mode: str = "adaptive",
) -> SimResult:
    """Run a deterministic LCG-backed sim (no numpy dependency)."""
    # Fixed toy curriculum: 6 easy CVC-a, 4 hard digraph (sh)
    pool = [
        ItemState(item_id=i, pattern="cvc-a", hard=False) for i in range(1, 7)
    ] + [
        ItemState(item_id=i, pattern="sh", hard=True) for i in range(7, 11)
    ]
    # Simple LCG
    state = seed & 0xFFFFFFFF

    def rand() -> float:
        nonlocal state
        state = (1664525 * state + 1013904223) & 0xFFFFFFFF
        return state / 0x100000000

    cursor = 0
    for day in range(days):
        weak = _weak_patterns(pool) if mode == "adaptive" else set()
        for _ in range(session_len):
            if mode == "adaptive":
                item = _adaptive_pick(pool, day, weak)
            else:
                item, cursor = _static_pick(pool, day, cursor)
            _attempt(item, day, rand())
            if mode == "adaptive":
                weak = _weak_patterns(pool)

    hard = [i for i in pool if i.hard]
    easy = [i for i in pool if not i.hard]
    return SimResult(
        label=mode,
        hard_reviews=sum(i.reviews for i in hard),
        easy_reviews=sum(i.reviews for i in easy),
        hard_misses=sum(i.misses for i in hard),
        days=days,
        notes={
            "hard_items": len(hard),
            "easy_items": len(easy),
            "session_len": session_len,
        },
    )


def compare(seed: int = 7) -> dict[str, SimResult]:
    return {
        "adaptive": run_sim(mode="adaptive", seed=seed),
        "static": run_sim(mode="static", seed=seed),
    }


def adaptive_beats_static_on_hard_reviews(seed: int = 7) -> bool:
    """DoD: adaptive schedules more hard-word reviews than static round-robin."""
    c = compare(seed=seed)
    return c["adaptive"].hard_reviews > c["static"].hard_reviews
