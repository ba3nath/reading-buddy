#!/usr/bin/env python3
"""Code + drift review gate after each learning roadmap phase (0–3)."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _failures_phase0() -> list[str]:
    fails: list[str] = []
    if not (ROOT / "docs/curriculum-audit.md").is_file():
        fails.append("Missing docs/curriculum-audit.md")
    if not (ROOT / "content/patterns.json").is_file():
        fails.append("Missing content/patterns.json")
    if not (ROOT / "scripts/backup_data.py").is_file():
        fails.append("Missing scripts/backup_data.py")
    if not (ROOT / "app/events.py").is_file():
        fails.append("Missing app/events.py")
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    if "/api/warmup" not in main:
        fails.append("Missing GET /api/warmup")
    runner = (ROOT / "runner.py").read_text(encoding="utf-8")
    if "--backup" not in runner or "--restore" not in runner:
        fails.append("runner.py missing --backup/--restore")
    record = (ROOT / "static/js/record.js").read_text(encoding="utf-8")
    if "SILENCE_GAP_MS = 1200" not in record:
        fails.append("Silence gap was not tightened for latency")
    py = ROOT / ".venv" / "bin" / "python"
    cmd = [str(py) if py.exists() else sys.executable, str(ROOT / "scripts/validate_patterns.py")]
    result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        fails.append("validate_patterns.py failed")
    return fails


def _failures_phase1() -> list[str]:
    fails: list[str] = []
    story = ROOT / "docs/story-decodability.md"
    if not story.is_file():
        fails.append("Missing docs/story-decodability.md")
    else:
        text = story.read_text(encoding="utf-8")
        if "have words beyond early patterns" in text and "**0**" not in text:
            # Allow the clean "No out-of-pattern…" success line only.
            if "No out-of-pattern content words found" not in text:
                fails.append("Story decodability audit still flags OOV lines")
    adaptive = (ROOT / "app/adaptive.py").read_text(encoding="utf-8")
    if "current_unlocked_patterns" not in adaptive:
        fails.append("Pattern unlock helper missing from adaptive.py")
    if "unlocked_patterns" not in (ROOT / "app/patterns.py").read_text(encoding="utf-8"):
        fails.append("unlocked_patterns missing from patterns.py")
    parent = (ROOT / "app/parent.py").read_text(encoding="utf-8")
    if "def pattern_heatmap" not in parent:
        fails.append("pattern_heatmap missing from parent.py")
    backup = (ROOT / "scripts/backup_data.py").read_text(encoding="utf-8")
    if "AUDIO_HUMAN" not in backup or "human/" not in backup:
        fails.append("Backup omits audio/human/ parent voice")
    return fails


def _failures_phase2() -> list[str]:
    fails: list[str] = []
    adaptive = (ROOT / "app/adaptive.py").read_text(encoding="utf-8")
    config = (ROOT / "app/config.py").read_text(encoding="utf-8")
    if "_build_scheduler_v2_queue" not in adaptive:
        fails.append("scheduler_v2 queue builder missing")
    if "LEITNER_GAPS_DAYS" not in config and "leitner" not in config.lower():
        fails.append("Leitner gaps missing from config")
    if "scheduler_shadow" not in config:
        fails.append("scheduler_shadow flag missing")
    if "box =" not in adaptive and "box =" not in (ROOT / "app/db.py").read_text(
        encoding="utf-8"
    ):
        fails.append("Leitner box column/update missing")
    return fails


def _failures_phase3() -> list[str]:
    fails: list[str] = []
    game = (ROOT / "static/js/game.js").read_text(encoding="utf-8")
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    parent_html = (ROOT / "static/parent.html").read_text(encoding="utf-8")
    if "playItemClip" not in game or "word-readalong" not in game:
        fails.append("Read-along highlight missing from game.js")
    if "wordTimings.length >= 1" not in game:
        fails.append("Single-word listen has no read-along pointer")
    if "playItemClip(entry)" not in game:
        fails.append("Replay listen skips read-along timings")
    if "/timings" not in main:
        fails.append("Audio timings endpoint missing")
    if "/api/parent/voice/" not in main:
        fails.append("Parent voice upload endpoint missing")
    if "force=True" not in main and "force=True" not in (
        ROOT / "app/audio_files.py"
    ).read_text(encoding="utf-8"):
        fails.append("Timings rebuild-on-override missing")
    if "data-voice-record" not in parent_html:
        fails.append("Parent voice UI missing")
    if "effort_stars" not in (ROOT / "app/config.py").read_text(encoding="utf-8"):
        fails.append("effort_stars setting missing")
    if "_effort_stars" not in (ROOT / "app/session.py").read_text(encoding="utf-8"):
        fails.append("effort stars helper missing from session.py")
    css = (ROOT / "static/css/app.css").read_text(encoding="utf-8")
    if "readalong-pulse" not in css:
        fails.append("Single-word listen pulse style missing")
    return fails


PHASE_CHECKS = {
    "0": _failures_phase0,
    "1": _failures_phase1,
    "2": _failures_phase2,
    "3": _failures_phase3,
}


def check(phase: str) -> list[str]:
    # Cumulative: phase N includes 0..N drift checks.
    order = ["0", "1", "2", "3"]
    if phase not in order and phase not in ("fluency", "4", "runner"):
        return [f"Unknown phase for drift-review: {phase}"]
    if phase in ("fluency", "4", "runner"):
        # Read-through / runner gates reuse the latest learning phase bar.
        targets = order
    else:
        idx = order.index(phase)
        targets = order[: idx + 1]
    fails: list[str] = []
    for p in targets:
        fails.extend(PHASE_CHECKS[p]())
    return fails


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True)
    args = parser.parse_args(argv)
    failures = check(args.phase)
    print(
        json.dumps(
            {
                "agent": "drift-review",
                "ok": not failures,
                "phase": args.phase,
                "failures": failures,
            },
            indent=2,
        )
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
