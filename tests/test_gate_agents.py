"""The four phase gates pass without editing the audio-clip agent."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = (
    "design-consistency",
    "ux-consistency",
    "test-coverage",
    "code-review",
)
PHASES = ("1", "2", "fluency", "3", "4")


def test_gate_agents_pass_every_phase():
    env = os.environ.copy()
    # Nested pytest is the coverage agent's own job when run from the shell.
    env["READING_BUDDY_SKIP_PYTEST"] = "1"
    for phase in PHASES:
        for name in AGENTS:
            result = subprocess.run(
                [sys.executable, str(ROOT / name / "check.py"), "--phase", phase],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0, f"{name} phase {phase}\n{result.stdout}\n{result.stderr}"


def test_audio_clip_review_untouched_shape():
    instructions = (ROOT / "audio-clip-review/bot/instructions.md").read_text(encoding="utf-8")
    assert "No carriers" in instructions
    assert not (ROOT / "audio-clip-review/check.py").exists()
