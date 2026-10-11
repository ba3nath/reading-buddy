#!/usr/bin/env python3
"""Generate Kokoro wavs for every content item (Milestone 2/3).

Reads the voice list from the installed kokoro-onnx voices bin.
Uses config.KOKORO_VOICE_ID (must be present in that list).
Writes audio/generated/{slug}.wav after ffmpeg mono trim + loudnorm.

Also writes per-word clips for multi-word items when no kind=word item
already owns that normalized word (needed for word-level replay).
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
from app.audio_files import postprocess_generated_wav, tts_render  # noqa: E402
from app.matching import normalize_text  # noqa: E402


def load_items() -> list[dict]:
    with config.CONTENT_ITEMS.open(encoding="utf-8") as f:
        payload = json.load(f)
    return payload if isinstance(payload, list) else payload.get("items", [])


def word_jobs(items: list[dict]) -> list[tuple[str, str]]:
    """(slug, text) for item clips plus orphan word tokens."""
    jobs: list[tuple[str, str]] = []
    owned_words: set[str] = set()
    for item in items:
        if item.get("kind") == "word":
            owned_words.add(normalize_text(item["text"]))
        jobs.append((item["slug"], item["text"]))

    seen_extra: set[str] = set()
    for item in items:
        if item.get("kind") == "word":
            continue
        for tok in normalize_text(item["text"]).split():
            if tok in owned_words or tok in seen_extra:
                continue
            seen_extra.add(tok)
            slug = "".join(ch if ch.isalnum() else "-" for ch in tok).strip("-")
            if slug:
                jobs.append((slug, tok))
    return jobs


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Reading Buddy item audio")
    parser.add_argument("--voice", default=None, help="Override config.KOKORO_VOICE_ID")
    parser.add_argument("--slug", default=None, help="Generate only this slug")
    parser.add_argument("--list-voices", action="store_true")
    parser.add_argument("--force", action="store_true", help="Overwrite existing wavs")
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
    jobs = word_jobs(items)
    if args.slug:
        jobs = [j for j in jobs if j[0] == args.slug]
        if not jobs:
            print(f"Unknown slug {args.slug}", file=sys.stderr)
            return 1

    config.AUDIO_GENERATED.mkdir(parents=True, exist_ok=True)
    todo = [
        (slug, text)
        for slug, text in jobs
        if args.force or not (config.AUDIO_GENERATED / f"{slug}.wav").exists()
    ]
    print(
        f"Generating {len(todo)} clips "
        f"(skipping {len(jobs) - len(todo)} existing) "
        f"voice={voice} lang={config.KOKORO_LANG}"
    )

    with tempfile.TemporaryDirectory(prefix="rb-kokoro-") as tmp:
        tmp_dir = Path(tmp)
        for slug, text in todo:
            raw = tmp_dir / f"{slug}.raw.wav"
            dest = config.AUDIO_GENERATED / f"{slug}.wav"
            spoken, speed = tts_render(text)
            samples, sr = kokoro.create(
                spoken,
                voice=voice,
                speed=speed,
                lang=config.KOKORO_LANG,
            )
            sf.write(str(raw), samples, sr)
            postprocess_generated_wav(raw, dest)
            print(f"  wrote {dest.relative_to(ROOT)}  ({spoken!r} @ {speed})")

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
