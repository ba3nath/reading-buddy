"""Phase 6 DoD: adaptive reviews hard words more than static."""

from __future__ import annotations

from eval.scheduler.sim import (
    adaptive_beats_static_on_hard_reviews,
    compare,
    run_sim,
)


def test_adaptive_beats_static_hard_reviews():
    assert adaptive_beats_static_on_hard_reviews(seed=7)
    c = compare(seed=7)
    assert c["adaptive"].hard_reviews > c["static"].hard_reviews


def test_sim_deterministic():
    a = run_sim(mode="adaptive", seed=7)
    b = run_sim(mode="adaptive", seed=7)
    assert a.hard_reviews == b.hard_reviews
    assert a.easy_reviews == b.easy_reviews
