#!/usr/bin/env bash
# Reading Buddy one-time setup for macOS (online), then offline play.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> Reading Buddy setup (macOS)"
echo "    Project root: $ROOT"

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 not found. Install Python 3.11+ (e.g. brew install python@3.12)." >&2
  exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg is missing. Installing with Homebrew…"
  if ! command -v brew >/dev/null 2>&1; then
    echo "ERROR: Homebrew not found. Install from https://brew.sh then re-run." >&2
    echo "  Or: brew install ffmpeg" >&2
    exit 1
  fi
  brew install ffmpeg
fi

if ! ffmpeg -version >/dev/null 2>&1; then
  echo "ERROR: ffmpeg -version failed. Install ffmpeg and ensure it is on PATH." >&2
  exit 1
fi

if ! command -v espeak >/dev/null 2>&1 && ! command -v espeak-ng >/dev/null 2>&1; then
  echo "espeak not found; installing espeak for Kokoro phonemizer…"
  brew install espeak || true
fi

echo "==> Creating virtualenv"
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt

echo "==> Downloading models (Whisper + Kokoro) — needs network once"
python scripts/download_models.py

if [[ ! -d audio/generated ]] || [[ -z "$(ls -A audio/generated 2>/dev/null || true)" ]]; then
  echo "==> Generating voice clips"
  python scripts/generate_audio.py
fi

echo ""
echo "Setup complete."
echo ""
echo "Offline second run (network can be off):"
echo "  cd \"$ROOT\""
echo "  source .venv/bin/activate"
echo "  export HF_HUB_OFFLINE=1"
echo "  python -m uvicorn app.main:app --host 127.0.0.1 --port 8765"
echo ""
echo "Open http://127.0.0.1:8765 in Chrome or Edge."
echo "Parent page: http://127.0.0.1:8765/parent"
