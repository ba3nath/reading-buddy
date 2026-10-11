#!/usr/bin/env python3
"""Download Whisper small.en into models/ (run once while online)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Download Reading Buddy models")
    parser.add_argument(
        "--model",
        default=config.WHISPER_MODEL,
        help="Whisper model id (default: small.en)",
    )
    args = parser.parse_args()

    config.MODELS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Downloading Whisper '{args.model}' into {config.MODELS_DIR} …")
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("Install dependencies first: pip install -r requirements.txt", file=sys.stderr)
        return 1

    # Load once to trigger download into download_root
    model = WhisperModel(
        args.model,
        device=config.WHISPER_DEVICE,
        compute_type=config.WHISPER_COMPUTE_TYPE,
        download_root=str(config.MODELS_DIR),
    )
    del model
    print("Done. You can now run offline with HF_HUB_OFFLINE=1.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
