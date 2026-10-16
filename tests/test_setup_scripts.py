"""Setup-script self-checks (no Windows VM required)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAC = (ROOT / "scripts" / "setup_mac.sh").read_text(encoding="utf-8")
WIN = (ROOT / "scripts" / "setup_windows.ps1").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")


def test_windows_setup_checks_and_installs_espeak():
    assert "Test-Espeak" in WIN
    assert "espeak-ng" in WIN.lower()
    assert "eSpeak-NG.eSpeak-NG" in WIN
    assert "choco install espeak" in WIN
    # Must hard-fail before generate_audio when still missing.
    assert "generate_audio.py" in WIN
    espeak_pos = WIN.lower().index("test-espeak")
    gen_pos = WIN.index("generate_audio.py")
    assert espeak_pos < gen_pos
    assert "ERROR: espeak or espeak-ng is not on PATH" in WIN


def test_mac_setup_requires_espeak():
    assert "brew install espeak" in MAC
    assert "espeak-ng" in MAC
    assert "ERROR: espeak or espeak-ng is still not on PATH" in MAC


def test_readme_documents_windows_espeak():
    assert "eSpeak-NG.eSpeak-NG" in README
    assert "setup_windows.ps1" in README
    assert "espeak" in README.lower()


def test_readme_documents_runner():
    assert "./run" in README
    assert "python3 runner.py" in README
    assert "launchctl" in README
    assert "--force-audio" in README
    assert "--localhost-only" in README
    assert "--force-deps" in README
    assert "0.0.0.0" in README
    assert (ROOT / "run").is_file()


def test_readme_documents_quick_start_and_matching():
    assert "git pull" in README
    assert "Beginner" in README
    assert "Strict" in README
    assert "/parent" in README
