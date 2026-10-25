"""ffmpeg decode, RMS/duration gates, temp cleanup."""

from __future__ import annotations

import array
import math
import os
import shutil
import subprocess
import wave
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from app import config

# LaunchAgent / minimal PATH often omits Homebrew. Prefer PATH, then known installs.
_FFMPEG_CANDIDATES = (
    "/opt/homebrew/bin/ffmpeg",
    "/usr/local/bin/ffmpeg",
    "/usr/bin/ffmpeg",
)


@lru_cache(maxsize=1)
def resolve_ffmpeg() -> str | None:
    """Absolute path to ffmpeg, or None if not found."""
    which = shutil.which("ffmpeg")
    if which:
        return which
    for candidate in _FFMPEG_CANDIDATES:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def _pcm_rms(frames: bytes, sampwidth: int) -> float:
    """RMS of little-endian PCM (stdlib ``audioop`` was removed in 3.13)."""
    if not frames or sampwidth <= 0:
        return 0.0
    if sampwidth == 1:
        # 8-bit PCM is unsigned.
        samples = array.array("B")
        samples.frombytes(frames)
        if not samples:
            return 0.0
        mean = sum((s - 128) ** 2 for s in samples) / len(samples)
        return math.sqrt(mean)
    typecode = {2: "h", 4: "i"}.get(sampwidth)
    if typecode is None:
        return 0.0
    samples = array.array(typecode)
    samples.frombytes(frames)
    if not samples:
        return 0.0
    mean = sum(int(s) * int(s) for s in samples) / len(samples)
    return math.sqrt(mean)


class AudioError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def ffmpeg_available() -> bool:
    ffmpeg = resolve_ffmpeg()
    if not ffmpeg:
        return False
    try:
        result = subprocess.run(
            [ffmpeg, "-version"],
            capture_output=True,
            check=False,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def new_temp_paths(suffix_in: str = ".webm") -> tuple[Path, Path]:
    config.TEMP_DIR.mkdir(parents=True, exist_ok=True)
    stem = uuid4().hex
    return (
        config.TEMP_DIR / f"{stem}{suffix_in}",
        config.TEMP_DIR / f"{stem}.wav",
    )


def write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def convert_to_wav(src: Path, dest: Path) -> None:
    ffmpeg = resolve_ffmpeg()
    if not ffmpeg:
        raise AudioError("ffmpeg not found on PATH or in common install locations")
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(src),
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(dest),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, check=False, timeout=60)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        raise AudioError(f"ffmpeg failed: {exc}") from exc
    if result.returncode != 0 or not dest.exists():
        err = (result.stderr or b"").decode("utf-8", errors="replace")[:400]
        raise AudioError(f"ffmpeg convert failed: {err}")


def wav_duration_and_rms(wav_path: Path) -> tuple[float, float]:
    with wave.open(str(wav_path), "rb") as wf:
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        n_frames = wf.getnframes()
        frames = wf.readframes(n_frames)
    if n_frames == 0 or framerate == 0:
        return 0.0, 0.0
    duration = n_frames / float(framerate)
    # PCM RMS → scale to float -1..1 (same scale as former audioop.rms).
    if not frames:
        return duration, 0.0
    rms_int = _pcm_rms(frames, sampwidth)
    max_amp = float(1 << (8 * sampwidth - 1))
    rms = rms_int / max_amp if max_amp else 0.0
    # If stereo slipped through, still ok — ffmpeg forces mono
    _ = n_channels
    return duration, rms


def is_silence(wav_path: Path) -> bool:
    duration, rms = wav_duration_and_rms(wav_path)
    return duration < config.MIN_AUDIO_SECONDS or rms < config.RMS_MIN


def delete_quiet(*paths: Path | None) -> None:
    for path in paths:
        if path is None:
            continue
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass


def sweep_temp_dir(*, keep_names: frozenset[str] | None = None) -> int:
    """Remove orphaned mic temps under ``data/tmp`` (e.g. after a crash).

    Keeps warmup silence by default so lifespan can reuse it.
    """
    keep = keep_names if keep_names is not None else frozenset({"warmup-silence.wav"})
    if not config.TEMP_DIR.is_dir():
        return 0
    removed = 0
    for path in config.TEMP_DIR.iterdir():
        if not path.is_file() or path.name in keep:
            continue
        try:
            path.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def resolve_audio_slug(slug: str) -> Path | None:
    """Prefer human override, else generated. Returns path or None."""
    if not slug or "/" in slug or "\\" in slug or ".." in slug:
        return None
    human = config.AUDIO_HUMAN / f"{slug}.wav"
    if human.is_file():
        return human
    generated = config.AUDIO_GENERATED / f"{slug}.wav"
    if generated.is_file():
        return generated
    return None


# Per-word Kokoro overrides: (spoken_text, speed). Speeds stay near natural
# speech (≈0.95–1.0). Prefer punctuation lengthening over crawling <0.9.
#
# IMPORTANT: spoken_text must be ONLY the on-screen word (optional . ! ?).
# Never add carrier words — the child hears TTS while reading one word.
#
# Keep this allowlist small. Default path in tts_render covers most CVCs.
_TTS_WORD_OVERRIDES: dict[str, tuple[str, float]] = {
    # Bare "a." adds a burst; leave unpunctuated.
    "a": ("a", 0.95),
    # Plosive / short words that clip without a firm release.
    "cup": ("cup!", 1.0),
    "sit": ("sit.", 0.95),  # sit! → Whisper "Z"
    "hop": ("hop!", 1.0),
    "top": ("top.", 0.95),
    "path": ("path!", 1.0),
    "thin": ("thin!", 1.0),
    "when": ("when!", 1.0),
    "your": ("your.", 0.95),
    # Hard /g/ — period + near-natural speed (slow crawl → "frogeh").
    "dog": ("dog.", 0.95),
    "pig": ("pig", 0.95),  # bare + Lewis; perioded Emma/Alice → Peggy
    "frog": ("frog.", 0.95),
    "log": ("log.", 0.95),
    "bug": ("bug.", 0.95),
    "big": ("big.", 0.95),
}

# Per-word voice overrides. Default is bf_emma (config.KOKORO_VOICE_ID).
# Only list voices that Emma smears; stay British unless proven otherwise.
_TTS_VOICE_OVERRIDES: dict[str, tuple[str, str]] = {
    "sit": ("bf_alice", "en-gb"),
    "top": ("bm_lewis", "en-gb"),
    "path": ("bm_lewis", "en-gb"),
    "when": ("bm_lewis", "en-gb"),
    "dog": ("bf_alice", "en-gb"),
    "log": ("bf_alice", "en-gb"),
    "bug": ("bf_alice", "en-gb"),
    "big": ("bf_alice", "en-gb"),
    "pig": ("bm_lewis", "en-gb"),  # Alice/Emma → Peggy; Lewis closer
}

# Phrase voice overrides — Emma is default; only exceptions that smear.
_TTS_PHRASE_VOICES: dict[str, tuple[str, str]] = {
    "the hot sun": ("bf_alice", "en-gb"),
    "a hot sun": ("bf_alice", "en-gb"),
    "my blue pen": ("bm_lewis", "en-gb"),
    "three red hats": ("bf_alice", "en-gb"),
    "a quick fox": ("bf_alice", "en-gb"),
    "a tall ship": ("bf_alice", "en-gb"),
    "one fast van": ("bm_lewis", "en-gb"),
    "hop to the red box": ("bf_alice", "en-gb"),
    "little boy blue come blow your horn": ("bm_lewis", "en-gb"),
    # Alice on final /g/ invents "So/It's" before "a wet log".
    "a wet log": ("bf_emma", "en-gb"),
    "my big bag": ("bf_emma", "en-gb"),
    # Emma can turn "fox" into a slur on this line.
    "the fox sat on top": ("bm_lewis", "en-gb"),
}

# Explicit phrase spoken + speed when the default rule is not enough.
# Spoken must keep the same on-screen words (optional trailing . ! ? only).
_TTS_PHRASE_RENDERS: dict[str, tuple[str, float]] = {
    "my blue pen": ("my blue pen", 0.95),
    "three red hats": ("three red hats", 0.95),
    "the hot sun": ("the hot sun", 0.95),
    "a hot sun": ("a hot sun", 0.95),
    "rain rain go away": ("rain rain go away", 0.95),
    "a wet log": ("a wet log", 0.95),
    "my big bag": ("my big bag", 0.95),
    "a quick fox": ("a quick fox.", 0.95),
    "a tall ship": ("a tall ship.", 0.95),
    "one fast van": ("one fast van.", 0.95),
    "hop to the red box": ("Hop to the red box", 1.0),
    "little boy blue come blow your horn": (
        "Little Boy Blue come blow your horn",
        0.95,
    ),
    "the fox sat on top": ("The fox sat on top", 0.95),
}

_DEFAULT_PHRASE_VOICE: tuple[str, str] = ("bf_emma", "en-gb")


def _single_word_core(text: str) -> str | None:
    stripped = (text or "").strip()
    words = stripped.split()
    if len(words) == 1 and len(words[0]) <= 10:
        return words[0].rstrip(".!?").lower()
    return None


def spoken_matches_target(target: str, spoken: str) -> bool:
    """True when spoken is only ``target`` plus optional trailing punctuation."""
    core = _single_word_core(target)
    if not core:
        return True
    tokens = (spoken or "").strip().split()
    if len(tokens) != 1:
        return False
    return tokens[0].rstrip(".!?").lower() == core


def _phrase_key(text: str) -> str:
    stripped = (text or "").strip().rstrip(".!?")
    return " ".join(stripped.lower().split())


def _last_word_slow_plosive(word: str) -> bool:
    """True when a final /b d g/ (not /ŋ/) needs extra time so it doesn't smear.

    Used for *single-word* cards only. On phrases, slowing a final /g/ often
    invents an audible schwa ("frog"→"frogeh"); those use a fast release.
    """
    core = (word or "").rstrip(".!?").lower()
    if not core or core.endswith("ng"):
        return False
    if core[-1:] in "bdg":
        return True
    return len(core) >= 2 and core.endswith("e") and core[-2] in "bdgkpt"


def _ends_hard_g(word: str) -> bool:
    """Final /g/ (frog/dog/pig/log), not /ŋ/ (bring/long)."""
    core = (word or "").rstrip(".!?").lower()
    return bool(core) and core.endswith("g") and not core.endswith("ng")


def _phrase_final_speed(word: str) -> float:
    """Phrase-final speed near natural speech; /g/ stays at 1.0 (no schwa)."""
    core = (word or "").rstrip(".!?").lower()
    if _ends_hard_g(core):
        return 1.0
    if _last_word_slow_plosive(core):
        return 0.95
    return 0.95


def tts_voice(text: str) -> tuple[str | None, str | None]:
    """Optional (voice_id, lang) override for one word or a known phrase.

    Default generator voice is bf_emma (config). Only return an override when
    Emma smears that token; otherwise None → session default.
    """
    core = _single_word_core(text)
    if core and core in _TTS_VOICE_OVERRIDES:
        return _TTS_VOICE_OVERRIDES[core]
    key = _phrase_key(text)
    phrase = _TTS_PHRASE_VOICES.get(key)
    if phrase:
        return phrase
    words = (text or "").strip().split()
    if len(words) >= 2:
        last = words[-1].rstrip(".!?").lower()
        # Alice cuts a clean /g/ release on short phrases; Emma → "frogeh".
        if 2 <= len(words) <= 3 and _ends_hard_g(last):
            return ("bf_alice", "en-gb")
        # Long "… can hop" lines: Emma turns hop→help; Alice keeps hop.
        if len(words) >= 4 and last == "hop":
            return ("bf_alice", "en-gb")
        return _DEFAULT_PHRASE_VOICE
    return None, None


def tts_render(text: str) -> tuple[str, float]:
    """Pick Kokoro text + speed for natural, clear kid listen clips.

    Prefer near-natural speed (≈0.95–1.0) and a trailing period for length.
    Slow crawls (<0.9) make short words sound machine-stretched. Overrides
    must never invent extra words — only the on-screen token (+ optional .!?).

    Multi-word clips stay bare (no forced period): Emma + natural speed avoids
    Isabella's trailing-syllable smear (ducks→duckses). Phrase-final /g/ is
    rendered at 1.0 — slowing it adds "eh".
    """
    stripped = (text or "").strip()
    if not stripped:
        return text, 1.0
    words = stripped.split()
    if len(words) == 1 and len(words[0]) <= 10:
        spoken = words[0]
        core = spoken.rstrip(".!?").lower()
        if core in _TTS_WORD_OVERRIDES:
            override_spoken, override_speed = _TTS_WORD_OVERRIDES[core]
            if not spoken_matches_target(core, override_spoken):
                # Safety net: never play a multi-word carrier for a single word.
                override_spoken = core + (
                    override_spoken[-1] if override_spoken[-1:] in ".!?" else ""
                )
            return override_spoken, override_speed
        if spoken[-1] not in ".!?":
            spoken = spoken + "."
        # Final /b d g/ (not /ŋ/): period + natural speed.
        if core[-1:] in "bdg" and not core.endswith("ng"):
            return core + ".", 0.95
        # Tiny function / CVC words: period lengthens without dragging.
        if len(core) <= 4:
            return spoken, 0.95
        return spoken, 1.0
    # Multi-word: honor explicit phrase renders, else bare text @ ~0.95.
    # Long lines (≥4 words): trailing ellipsis gives Kokoro a falling decay
    # without the "Period." dummy-trim (that left "period" audible). Short
    # 2–3 word kid phrases stay bare — ellipsis A/B'd into duckses/piggy.
    key = _phrase_key(stripped)
    if key in _TTS_PHRASE_RENDERS:
        # Explicit renders already tuned — do not auto-append ellipsis.
        return _TTS_PHRASE_RENDERS[key]
    if len(words) >= 2:
        spoken = stripped.rstrip(".!?")
        if len(words) <= 3:
            return spoken, _phrase_final_speed(words[-1])
        # Long untuned lines: ellipsis gives a falling decay (short phrases smear).
        return spoken + "...", 0.95
    return stripped, 0.95


# Short listen words need generous silence around the speech so onsets/plosives
# are not cut off by players or Bluetooth buffering.
_LISTEN_LEAD_MS = 350
_LISTEN_TRAIL_SEC = 0.50

# Tail cleanup: Kokoro often leaves a metallic extra syllable after the real
# last phoneme. Ellipsis / "Period." dummy-trims A/B'd worse on short kid
# phrases (ducks→ducts, pig→piggy). Instead: VAD cut after last speech + fade.
_TAIL_HANGOVER_MS = 100
_TAIL_FADE_MS = 80
_TAIL_RMS_WIN_MS = 10
_TAIL_RMS_REL = 0.06  # fraction of peak RMS; above smear, below quiet /p/


def _read_wav_mono_i16(path: Path) -> tuple[array.array, int]:
    with wave.open(str(path), "rb") as wf:
        if wf.getsampwidth() != 2:
            raise AudioError(f"expected 16-bit wav, got sampwidth={wf.getsampwidth()}")
        rate = wf.getframerate()
        nch = wf.getnchannels()
        frames = wf.readframes(wf.getnframes())
    samples = array.array("h")
    samples.frombytes(frames)
    if nch > 1:
        mono = array.array("h")
        for i in range(0, len(samples), nch):
            mono.append(samples[i])
        samples = mono
    return samples, rate


def _write_wav_mono_i16(path: Path, samples: array.array, rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(samples.tobytes())


def tighten_tail_samples(
    samples: array.array,
    rate: int,
    *,
    hangover_ms: int = _TAIL_HANGOVER_MS,
    fade_ms: int = _TAIL_FADE_MS,
    win_ms: int = _TAIL_RMS_WIN_MS,
    rms_rel: float = _TAIL_RMS_REL,
) -> array.array:
    """Cut after last real speech (+ hangover), then exponential-ish linear fade.

    Drops Kokoro's trailing smear without a hard noise gate (gates ate /p/ /t/).
    """
    if rate <= 0 or len(samples) < rate // 10:
        return samples
    win = max(1, int(rate * win_ms / 1000))
    # Peak RMS over windows
    peak = 0.0
    last_loud = -1
    for i in range(0, len(samples) - win + 1, win):
        chunk = samples[i : i + win]
        mean = sum(s * s for s in chunk) / len(chunk)
        rms = math.sqrt(mean)
        if rms > peak:
            peak = rms
    if peak <= 1.0:
        return samples
    thr = peak * rms_rel
    for i in range(0, len(samples) - win + 1, win):
        chunk = samples[i : i + win]
        mean = sum(s * s for s in chunk) / len(chunk)
        if math.sqrt(mean) >= thr:
            last_loud = i + win
    if last_loud < 0:
        return samples
    hang = int(rate * hangover_ms / 1000)
    end = min(len(samples), last_loud + hang)
    # Never cut away more than the last 35% (safety for soft onsets-only clips).
    min_keep = max(win, int(len(samples) * 0.65))
    end = max(end, min_keep)
    out = array.array("h", samples[:end])
    fade_n = min(int(rate * fade_ms / 1000), len(out) // 3)
    if fade_n >= 2:
        for i in range(fade_n):
            # Linear fade ≈ short exponential for 50–80 ms tails.
            gain = (fade_n - 1 - i) / (fade_n - 1)
            idx = len(out) - fade_n + i
            out[idx] = int(out[idx] * gain)
    return out


def postprocess_generated_wav(src: Path, dest: Path) -> None:
    """Mono 16-bit PCM at Kokoro native 24 kHz: trim, norm, tighten tail, pad.

    Never use stop-period silenceremove — final plosives in cup/map/cat are quiet.

    Order: start-trim → soft loudnorm → VAD hangover cut + micro fade → lead/trail
    pads. Keep 24 kHz. Pads after norm so silence does not crush quiet tails.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    rate = int(config.AUDIO_SAMPLE_RATE)
    ffmpeg = resolve_ffmpeg()
    if not ffmpeg:
        raise AudioError("ffmpeg not found on PATH or in common install locations")

    mid = dest.with_suffix(".norm.wav")
    tight = dest.with_suffix(".tight.wav")
    try:
        # 1) Lead trim + soft loudnorm at native rate (no pad yet).
        af_norm = (
            "silenceremove=start_periods=1:start_duration=0.02:start_threshold=-55dB,"
            "loudnorm=I=-16:TP=-1.5:LRA=14"
        )
        cmd_norm = [
            ffmpeg,
            "-y",
            "-i",
            str(src),
            "-ac",
            "1",
            "-ar",
            str(rate),
            "-c:a",
            "pcm_s16le",
            "-af",
            af_norm,
            str(mid),
        ]
        try:
            result = subprocess.run(cmd_norm, capture_output=True, check=False, timeout=60)
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            raise AudioError(f"ffmpeg postprocess failed: {exc}") from exc
        if result.returncode != 0 or not mid.exists():
            err = (result.stderr or b"").decode("utf-8", errors="replace")[:400]
            raise AudioError(f"ffmpeg postprocess failed: {err}")

        # 2) Drop trailing smear; micro-fade the new end.
        samples, got_rate = _read_wav_mono_i16(mid)
        samples = tighten_tail_samples(samples, got_rate or rate)
        _write_wav_mono_i16(tight, samples, got_rate or rate)

        # 3) Lead/trail pads for players / Bluetooth.
        af_pad = (
            f"adelay={_LISTEN_LEAD_MS}|{_LISTEN_LEAD_MS},"
            f"apad=pad_dur={_LISTEN_TRAIL_SEC}"
        )
        cmd_pad = [
            ffmpeg,
            "-y",
            "-i",
            str(tight),
            "-ac",
            "1",
            "-ar",
            str(rate),
            "-c:a",
            "pcm_s16le",
            "-af",
            af_pad,
            str(dest),
        ]
        try:
            result = subprocess.run(cmd_pad, capture_output=True, check=False, timeout=60)
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            raise AudioError(f"ffmpeg postprocess failed: {exc}") from exc
        if result.returncode != 0 or not dest.exists():
            err = (result.stderr or b"").decode("utf-8", errors="replace")[:400]
            raise AudioError(f"ffmpeg postprocess failed: {err}")
    finally:
        for tmp in (mid, tight):
            try:
                if tmp.is_file():
                    tmp.unlink()
            except OSError:
                pass


def generated_audio_ready(slugs: list[str] | None = None) -> bool:
    """True when every slug has human or generated wav (M2 health)."""
    if slugs is None:
        return True
    return all(resolve_audio_slug(slug) is not None for slug in slugs)


def proportional_word_timings(
    text: str, duration_seconds: float
) -> list[dict[str, float | str]]:
    """Split duration evenly across tokens (fallback when Kokoro has no align)."""
    import re

    words = [w for w in re.findall(r"[A-Za-z']+", text or "") if w]
    if not words:
        return []
    dur = max(0.05, float(duration_seconds))
    # Leave a small lead-in for padded listen clips.
    lead = min(0.12, dur * 0.08)
    usable = max(0.05, dur - lead)
    slot = usable / len(words)
    out: list[dict[str, float | str]] = []
    t = lead
    for w in words:
        start = round(t, 3)
        end = round(min(dur, t + slot), 3)
        out.append({"word": w, "start": start, "end": end})
        t = end
    if out:
        out[-1]["end"] = round(dur, 3)
    return out


def timings_path_for_slug(slug: str) -> Path:
    return config.AUDIO_GENERATED / f"{slug}.json"


def load_or_build_timings(
    slug: str,
    text: str,
    *,
    force: bool = False,
) -> list[dict[str, float | str]]:
    """Return word timings; write proportional JSON beside the generated wav.

    Pass ``force=True`` after a human override so duration matches the new clip.
    """
    import json

    path = timings_path_for_slug(slug)
    wav = resolve_audio_slug(slug)
    if force and path.is_file():
        try:
            path.unlink()
        except OSError:
            pass
    elif path.is_file() and not force:
        # Rebuild when the active wav (human or generated) is newer than cache.
        stale = False
        if wav is not None and wav.is_file():
            try:
                stale = wav.stat().st_mtime > path.stat().st_mtime + 0.01
            except OSError:
                stale = True
        if not stale:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                words = data.get("words") if isinstance(data, dict) else data
                if isinstance(words, list) and words:
                    return words
            except (OSError, ValueError, TypeError):
                pass
    duration = 1.0
    if wav is not None:
        try:
            duration, _ = wav_duration_and_rms(wav)
        except Exception:  # noqa: BLE001
            duration = 1.0
    words = proportional_word_timings(text, duration)
    try:
        config.AUDIO_GENERATED.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"slug": slug, "words": words, "source": str(wav) if wav else ""}, indent=2)
            + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass
    return words
