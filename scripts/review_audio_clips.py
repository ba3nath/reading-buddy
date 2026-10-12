#!/usr/bin/env python3
"""Whisper review + single-token A/B retune for Reading Buddy listen clips.

Encodes learnings from the batch audio clarity work:

- Feed Whisper a float32 ndarray (PyAV path is unreliable for these wavs).
- Never add carrier words — spoken text must be only the on-screen token
  (optional trailing . ! ?). Clarity levers: punctuation, speed, voice.
- Score 3 Whisper passes: hits>=2 OK, hits==1 weak, hits==0 fail.
- A/B across bf_emma / bf_alice / bf_isabella / bm_lewis × punct/speed.
- Prefer more hits, then fewer filler tokens, then bf_emma.
- Homophone aliases for audit hits only (sun/son, your/yours, …).

Subcommands:
  audit          Classify word clips OK / weak / fail
  ab-tune        A/B retune fail+weak (or --words)
  apply-winners  Merge winners JSON into app/audio_files.py overrides
  regen          Force-regenerate wavs for given slugs / winners file
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config  # noqa: E402
from app.audio_files import (  # noqa: E402
    postprocess_generated_wav,
    resolve_audio_slug,
    spoken_matches_target,
    tts_render,
    tts_voice,
)
from app.whisper_engine import engine  # noqa: E402

VOICES = ("bf_emma", "bf_alice", "bf_isabella", "bm_lewis")
DEFAULT_VOICE = config.KOKORO_VOICE_ID

# Whisper often respells these; kids still hear the right word.
ALIASES: dict[str, set[str]] = {
    "sun": {"sun", "son"},
    "your": {"your", "yours"},
    "chair": {"chair", "chairs"},
    "were": {"were", "where"},
    "truck": {"truck", "track"},
    "three": {"three", "3"},
}

WORD_OVERRIDE_RE = re.compile(
    r"(_TTS_WORD_OVERRIDES: dict\[str, tuple\[str, float\]\] = \{)(.*?)(\n\})",
    re.S,
)
VOICE_OVERRIDE_RE = re.compile(
    r"(_TTS_VOICE_OVERRIDES: dict\[str, tuple\[str, str\]\] = \{)(.*?)(\n\})",
    re.S,
)


def ensure_whisper() -> None:
    if not engine.ready and not engine.load():
        raise SystemExit(f"Whisper failed to load: {engine.load_error}")


def load_word_list() -> list[str]:
    payload = json.loads(config.CONTENT_ITEMS.read_text(encoding="utf-8"))
    items = payload if isinstance(payload, list) else payload.get("items", [])
    return sorted(
        {
            (it.get("text") or "").strip().lower()
            for it in items
            if it.get("kind") == "word" and (it.get("text") or "").strip()
        }
    )


def load_wav_f32(path: Path) -> np.ndarray:
    """Load mono wav as float32 @ 16 kHz for faster-whisper (bypass PyAV)."""
    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        frames = w.readframes(w.getnframes())
        a = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    if sr != 16000:
        a = np.interp(
            np.linspace(0, 1, int(len(a) * 16000 / sr), False),
            np.linspace(0, 1, len(a), False),
            a,
        ).astype(np.float32)
    return a


def heard(path: Path) -> str:
    segs, _ = engine._model.transcribe(
        load_wav_f32(path),
        language="en",
        beam_size=config.WHISPER_BEAM_SIZE,
        temperature=0.0,
        condition_on_previous_text=False,
        word_timestamps=True,
        vad_filter=False,
        initial_prompt=None,
    )
    parts: list[str] = []
    for seg in segs:
        for w in getattr(seg, "words", None) or []:
            t = (w.word or "").strip()
            if t:
                parts.append(t)
        if not parts and seg.text:
            parts.append(seg.text.strip())
    return " ".join(parts).strip()


def toks(s: str) -> list[str]:
    return "".join(c if c.isalnum() or c.isspace() else " " for c in s.lower()).split()


def hit_word(word: str, tokens: list[str]) -> bool:
    return bool(set(tokens) & ALIASES.get(word, {word}))


def filler_count(word: str, tokens: list[str]) -> int:
    fillers = {"the", "a", "an", "and"} - {word}
    return sum(1 for t in tokens if t in fillers)


def candidates(word: str) -> list[tuple[str, float, str]]:
    spoken_speeds = [
        (f"{word}.", 0.78),
        (f"{word}.", 0.82),
        (f"{word}.", 0.88),
        (f"{word}.", 0.94),
        (f"{word}!", 0.95),
        (f"{word}!", 1.0),
        (word, 0.88),
        (word, 0.94),
        (word, 1.0),
        (f"{word}?", 0.92),
    ]
    out: list[tuple[str, float, str]] = []
    for voice in VOICES:
        for spoken, speed in spoken_speeds:
            if spoken_matches_target(word, spoken):
                out.append((spoken, speed, voice))
    return out


def classify(hits: int) -> str:
    if hits >= 2:
        return "ok"
    if hits == 1:
        return "weak"
    return "fail"


def cmd_audit(args: argparse.Namespace) -> int:
    ensure_whisper()
    words = args.words or load_word_list()
    passes = args.passes
    fail: list[dict] = []
    weak: list[dict] = []
    ok: list[dict] = []

    print(f"auditing {len(words)} word clips ({passes} passes)", flush=True)
    for word in words:
        path = resolve_audio_slug(word)
        spoken, speed = tts_render(word)
        voice = tts_voice(word)
        single = spoken_matches_target(word, spoken)
        if path is None or not path.is_file():
            rec = {
                "word": word,
                "hits": 0,
                "samples": ["MISSING"],
                "spoken": spoken,
                "speed": speed,
                "voice": list(voice),
                "single": single,
                "filler": False,
                "label": "fail",
            }
            fail.append(rec)
            print(f"FAIL {word}: MISSING", flush=True)
            continue

        samples: list[str] = []
        hits = 0
        filler = False
        for _ in range(passes):
            u = heard(path)
            samples.append(u)
            t = toks(u)
            if hit_word(word, t):
                hits += 1
            if filler_count(word, t):
                filler = True
        label = classify(hits)
        rec = {
            "word": word,
            "hits": hits,
            "samples": samples,
            "spoken": spoken,
            "speed": speed,
            "voice": list(voice),
            "single": single,
            "filler": filler,
            "label": label,
        }
        {"ok": ok, "weak": weak, "fail": fail}[label].append(rec)
        print(
            f"{label.upper():4} {word:8} hits={hits}/{passes} "
            f"spoken={spoken!r}@{speed} voice={voice} samples={samples}",
            flush=True,
        )

    out = {
        "ok": ok,
        "weak": weak,
        "fail": fail,
        "ok_count": len(ok),
        "weak_count": len(weak),
        "fail_count": len(fail),
        "total": len(words),
        "passes": passes,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(
        f"\nSUMMARY OK {len(ok)} / WEAK {len(weak)} / FAIL {len(fail)} "
        f"of {len(words)} → {args.out}",
        flush=True,
    )
    return 0


def cmd_ab_tune(args: argparse.Namespace) -> int:
    ensure_whisper()
    try:
        from kokoro_onnx import Kokoro
        import soundfile as sf
    except ImportError as exc:
        raise SystemExit(f"kokoro deps missing: {exc}") from exc

    if not config.KOKORO_MODEL_PATH.exists() or not config.KOKORO_VOICES_PATH.exists():
        raise SystemExit("Kokoro models missing. Run scripts/download_models.py")

    if args.words:
        targets = sorted(set(args.words))
    elif args.audit:
        audit = json.loads(args.audit.read_text(encoding="utf-8"))
        targets = sorted(
            {
                r["word"]
                for bucket in ("fail", "weak")
                for r in audit.get(bucket, [])
                if isinstance(r, dict) and r.get("word")
            }
        )
    else:
        raise SystemExit("Provide --audit JSON or --words")

    if not targets:
        print("No targets to retune.", flush=True)
        args.out.write_text("{}\n", encoding="utf-8")
        return 0

    kokoro = Kokoro(str(config.KOKORO_MODEL_PATH), str(config.KOKORO_VOICES_PATH))
    print(f"retuning {len(targets)} words: {targets}", flush=True)
    winners: dict[str, dict] = {}

    with tempfile.TemporaryDirectory(prefix="rb-ab-") as tmp:
        tmp_path = Path(tmp)
        for word in targets:
            best: dict | None = None
            print(f"\n=== {word} ===", flush=True)
            for spoken, speed, voice in candidates(word):
                samples, sr = kokoro.create(
                    spoken, voice=voice, speed=speed, lang=config.KOKORO_LANG
                )
                raw = tmp_path / "r.wav"
                out_wav = tmp_path / "o.wav"
                sf.write(str(raw), samples, sr)
                postprocess_generated_wav(raw, out_wav)

                hits = 0
                filler_hits = 0
                samples_h: list[str] = []
                for _ in range(args.passes):
                    u = heard(out_wav)
                    samples_h.append(u)
                    t = toks(u)
                    if hit_word(word, t):
                        hits += 1
                    filler_hits += filler_count(word, t)

                score = (
                    hits * 10
                    - filler_hits * 2
                    + (1 if voice == "bf_emma" else 0)
                )
                if hits >= 2:
                    print(
                        f"  {spoken!r:10} {speed} {voice:12} "
                        f"hits={hits}/{args.passes} filler={filler_hits} {samples_h}",
                        flush=True,
                    )
                rec = {
                    "score": score,
                    "hits": hits,
                    "filler": filler_hits,
                    "spoken": spoken,
                    "speed": speed,
                    "voice": voice,
                    "samples": samples_h,
                }
                if best is None or rec["score"] > best["score"]:
                    best = rec
                    if hits == args.passes and filler_hits == 0:
                        print(
                            f"  early perfect {spoken!r} {speed} {voice}",
                            flush=True,
                        )
                        break
            assert best is not None
            winners[word] = best
            print(
                f"  >> WIN {best['spoken']!r} {best['speed']} {best['voice']} "
                f"hits={best['hits']}/{args.passes} filler={best['filler']}",
                flush=True,
            )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(winners, indent=2) + "\n", encoding="utf-8")
    good = sum(1 for b in winners.values() if b["hits"] >= 2)
    print(
        f"\nSUMMARY winners with >=2/{args.passes}: {good}/{len(winners)} → {args.out}",
        flush=True,
    )
    return 0


def _parse_word_overrides(body: str) -> dict[str, tuple[str, float]]:
    cur: dict[str, tuple[str, float]] = {}
    for line in body.splitlines():
        line = line.strip().rstrip(",")
        if not line or line.startswith("#"):
            continue
        m = re.match(r'"(\w+)":\s*\((.+)\)\s*$', line)
        if not m:
            continue
        spoken, speed = eval(f"({m.group(2)})")  # noqa: S307 — local authored file
        cur[m.group(1)] = (str(spoken), float(speed))
    return cur


def _parse_voice_overrides(body: str) -> dict[str, tuple[str, str]]:
    cur: dict[str, tuple[str, str]] = {}
    for line in body.splitlines():
        line = line.strip().rstrip(",")
        if not line or line.startswith("#"):
            continue
        m = re.match(r'"(\w+)":\s*\((.+)\)\s*$', line)
        if not m:
            continue
        voice, lang = eval(f"({m.group(2)})")  # noqa: S307
        cur[m.group(1)] = (str(voice), str(lang))
    return cur


def _format_word_overrides(cur: dict[str, tuple[str, float]]) -> str:
    lines = ['_TTS_WORD_OVERRIDES: dict[str, tuple[str, float]] = {']
    for word in sorted(cur):
        spoken, speed = cur[word]
        lines.append(f'    "{word}": ({spoken!r}, {speed}),')
    lines.append("}")
    return "\n".join(lines)


def _format_voice_overrides(cur: dict[str, tuple[str, str]]) -> str:
    lines = ['_TTS_VOICE_OVERRIDES: dict[str, tuple[str, str]] = {']
    for word in sorted(cur):
        voice, lang = cur[word]
        lines.append(f'    "{word}": ({voice!r}, {lang!r}),')
    lines.append(
        "    # Default bf_isabella when absent (batch Whisper winners)."
    )
    lines.append("}")
    return "\n".join(lines)


def cmd_apply_winners(args: argparse.Namespace) -> int:
    winners = json.loads(args.winners.read_text(encoding="utf-8"))
    if not isinstance(winners, dict) or not winners:
        raise SystemExit("winners JSON empty or invalid")

    audio_path = ROOT / "app" / "audio_files.py"
    src = audio_path.read_text(encoding="utf-8")
    wm = WORD_OVERRIDE_RE.search(src)
    vm = VOICE_OVERRIDE_RE.search(src)
    if not wm or not vm:
        raise SystemExit("Could not find override dicts in app/audio_files.py")

    words = _parse_word_overrides(wm.group(2))
    voices = _parse_voice_overrides(vm.group(2))

    applied: list[str] = []
    for word, rec in winners.items():
        spoken = rec["spoken"]
        speed = float(rec["speed"])
        voice = rec["voice"]
        if not spoken_matches_target(word, spoken):
            raise SystemExit(
                f"Refusing carrier for {word!r}: spoken={spoken!r}"
            )
        words[word] = (spoken, speed)
        if voice == DEFAULT_VOICE:
            voices.pop(word, None)
        else:
            voices[word] = (voice, "en-gb")
        applied.append(word)

    new_src = WORD_OVERRIDE_RE.sub(
        _format_word_overrides(words), src, count=1
    )
    new_src = VOICE_OVERRIDE_RE.sub(
        _format_voice_overrides(voices), new_src, count=1
    )

    # Safety: every override still single-token
    for w, (s, _) in words.items():
        if not spoken_matches_target(w, s):
            raise SystemExit(f"Carrier slipped in for {w!r}: {s!r}")

    result = {
        "applied": sorted(applied),
        "word_override_count": len(words),
        "voice_override_count": len(voices),
        "dry_run": bool(args.dry_run),
        "path": str(audio_path),
    }
    if args.dry_run:
        result["preview_words"] = {
            w: {"spoken": words[w][0], "speed": words[w][1]}
            for w in sorted(applied)
        }
        result["preview_voices"] = {
            w: list(voices[w]) for w in sorted(applied) if w in voices
        }
        print(json.dumps(result, indent=2))
        print("dry-run: no files written", flush=True)
        return 0

    audio_path.write_text(new_src, encoding="utf-8")
    print(json.dumps(result, indent=2))
    print(f"wrote {audio_path}", flush=True)
    return 0


def cmd_regen(args: argparse.Namespace) -> int:
    if args.winners:
        winners = json.loads(args.winners.read_text(encoding="utf-8"))
        slugs = sorted(winners.keys())
    elif args.words:
        slugs = sorted(set(args.words))
    else:
        raise SystemExit("Provide --winners or --words")

    fails: list[str] = []
    for slug in slugs:
        cmd = [
            sys.executable,
            str(ROOT / "scripts" / "generate_audio.py"),
            "--force",
            "--slug",
            slug,
        ]
        print(f"regen {slug}...", flush=True)
        r = subprocess.run(cmd, cwd=str(ROOT))
        if r.returncode != 0:
            fails.append(slug)
    print(json.dumps({"regenerated": slugs, "fails": fails}, indent=2))
    return 1 if fails else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("audit", help="Whisper-classify word clips")
    a.add_argument("--words", nargs="*", default=None)
    a.add_argument("--passes", type=int, default=3)
    a.add_argument(
        "--out",
        type=Path,
        default=Path("/tmp/audio_audit.json"),
    )
    a.set_defaults(func=cmd_audit)

    ab = sub.add_parser("ab-tune", help="A/B retune weak/fail words")
    ab.add_argument("--audit", type=Path, default=None)
    ab.add_argument("--words", nargs="*", default=None)
    ab.add_argument("--passes", type=int, default=3)
    ab.add_argument(
        "--out",
        type=Path,
        default=Path("/tmp/audio_winners.json"),
    )
    ab.set_defaults(func=cmd_ab_tune)

    ap = sub.add_parser(
        "apply-winners", help="Merge winners into audio_files.py overrides"
    )
    ap.add_argument("--winners", type=Path, required=True)
    ap.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Preview only (default)",
    )
    ap.add_argument(
        "--write",
        action="store_true",
        help="Actually write app/audio_files.py",
    )
    ap.set_defaults(func=cmd_apply_winners)

    rg = sub.add_parser("regen", help="Force-regenerate wavs for slugs")
    rg.add_argument("--winners", type=Path, default=None)
    rg.add_argument("--words", nargs="*", default=None)
    rg.set_defaults(func=cmd_regen)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "apply-winners":
        args.dry_run = not args.write
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
