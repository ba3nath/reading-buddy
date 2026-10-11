#!/usr/bin/env python3
"""Generate Kokoro wavs for every content item (Milestone 2).

Reads the voice list from the installed kokoro-onnx voices bin.
Uses config.KOKORO_VOICE_ID (must be present in that list).
Writes audio/generated/{slug}.wav after ffmpeg mono trim + loudnorm.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config  # noqa: E402
from app.audio_files import postprocess_generated_wav  # noqa: E402


def load_items() -> list[dict]:
    with config.CONTENT_ITEMS.open(encoding="utf-8") as f:
        payload = json.load(f)
    return payload if isinstance(payload, list) else payload.get("items", [])


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Reading Buddy item audio")
    parser.add_argument("--voice", default=None, help="Override config.KOKORO_VOICE_ID")
    parser.add_argument("--slug", default=None, help="Generate only this slug")
    parser.add_argument("--list-voices", action="store_true")
    args = parser.parse_args()

    if not config.KOKORO_MODEL_PATH.exists() or not config.KOKORO_VOICES_PATH.exists():
        print(
            "Kokoro model files missing. Run: python scripts/download_models.py",
            file=sys.stderr,
        )
        return 1

    try:
        from kokoro_onnx import Kokoro
        import soundfile as sf
    except ImportError:
        print("Install deps: pip install -r requirements.txt", file=sys.stderr)
        return 1

    kokoro = Kokoro(str(config.KOKORO_MODEL_PATH), str(config.KOKORO_VOICES_PATH))
    voices = list(kokoro.get_voices())
    if args.list_voices:
        for v in sorted(voices):
            print(v)
        return 0

    voice = args.voice or config.KOKORO_VOICE_ID
    if voice not in voices:
        print(
            f"Voice '{voice}' not in install voice list. "
            f"British options: {[v for v in voices if v.startswith(('bf_', 'bm_'))]}",
            file=sys.stderr,
        )
        return 1

    items = load_items()
    if args.slug:
        items = [i for i in items if i["slug"] == args.slug]
        if not items:
            print(f"Unknown slug {args.slug}", file=sys.stderr)
            return 1

    config.AUDIO_GENERATED.mkdir(parents=True, exist_ok=True)
    print(f"Generating {len(items)} clips with voice={voice} lang={config.KOKORO_LANG}")

    with tempfile.TemporaryDirectory(prefix="rb-kokoro-") as tmp:
        tmp_dir = Path(tmp)
        for item in items:
            slug = item["slug"]
            text = item["text"]
            raw = tmp_dir / f"{slug}.raw.wav"
            dest = config.AUDIO_GENERATED / f"{slug}.wav"
            samples, sr = kokoro.create(
                text,
                voice=voice,
                speed=1.0,
                lang=config.KOKORO_LANG,
            )
            sf.write(str(raw), samples, sr)
            postprocess_generated_wav(raw, dest)
            print(f"  wrote {dest.relative_to(ROOT)}")

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
