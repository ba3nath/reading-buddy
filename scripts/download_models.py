#!/usr/bin/env python3
"""Download Whisper small.en and Kokoro ONNX weights into models/ (once, online)."""

from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config  # noqa: E402

KOKORO_RELEASE = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
)
KOKORO_FILES = {
    "kokoro-v1.0.onnx": f"{KOKORO_RELEASE}/kokoro-v1.0.onnx",
    "voices-v1.0.bin": f"{KOKORO_RELEASE}/voices-v1.0.bin",
}


def download_file(url: str, dest: Path) -> None:
    """Download to a ``.partial`` file, then rename — safe to retry after interrupt."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.stat().st_size > 0:
        print(f"  already present: {dest}")
        return
    if dest.is_file() and dest.stat().st_size == 0:
        dest.unlink(missing_ok=True)
    partial = dest.with_name(dest.name + ".partial")
    try:
        if partial.exists():
            partial.unlink()
        print(f"  downloading {url} → {dest}")
        urllib.request.urlretrieve(url, partial)
        if not partial.is_file() or partial.stat().st_size <= 0:
            raise RuntimeError(f"Empty download for {url}")
        partial.replace(dest)
    except Exception:
        if partial.exists():
            try:
                partial.unlink()
            except OSError:
                pass
        raise


def download_whisper(model_id: str) -> None:
    print(f"Downloading Whisper '{model_id}' into {config.MODELS_DIR} …")
    from faster_whisper import WhisperModel

    model = WhisperModel(
        model_id,
        device=config.WHISPER_DEVICE,
        compute_type=config.WHISPER_COMPUTE_TYPE,
        download_root=str(config.MODELS_DIR),
    )
    del model


def download_kokoro() -> None:
    print(f"Downloading Kokoro ONNX into {config.KOKORO_MODEL_PATH.parent} …")
    for name, url in KOKORO_FILES.items():
        download_file(url, config.KOKORO_MODEL_PATH.parent / name)


def main() -> int:
    parser = argparse.ArgumentParser(description="Download Reading Buddy models")
    parser.add_argument("--model", default=config.WHISPER_MODEL)
    parser.add_argument("--skip-whisper", action="store_true")
    parser.add_argument("--skip-kokoro", action="store_true")
    args = parser.parse_args()

    config.MODELS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        if not args.skip_whisper:
            download_whisper(args.model)
        if not args.skip_kokoro:
            download_kokoro()
    except ImportError:
        print("Install dependencies first: pip install -r requirements.txt", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"Download failed: {exc}", file=sys.stderr)
        return 1

    print("Done. You can now run offline with HF_HUB_OFFLINE=1.")
    print("Then generate clips: python scripts/generate_audio.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
