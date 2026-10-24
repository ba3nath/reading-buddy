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


# Per-word Kokoro en-gb overrides: (spoken_text, speed).
#
# IMPORTANT: spoken_text must be ONLY the on-screen word (optional . ! ?).
# Never add carrier words ("fat cat", "a dog", "please sit") — the child
# hears the TTS while reading the single word on screen.
#
# Clarity levers: punctuation, speed, and voice — not extra words.
# Tuned by batch Whisper A/B (single-token only) across weak/fail clips.
_TTS_WORD_OVERRIDES: dict[str, tuple[str, float]] = {
    "a": ('a', 0.88),
    "all": ('all.', 0.94),
    "are": ('are!', 1.0),
    "bed": ('bed.', 0.88),
    "big": ('big', 0.86),
    "bird": ('bird.', 0.86),
    "bike": ('bike.', 0.88),
    "bin": ('bin.', 0.88),
    "book": ('book.', 0.82),
    "box": ('box', 0.88),
    "bring": ('bring', 0.92),
    "brush": ('brush!', 0.95),
    "bug": ('bug', 0.82),
    "bus": ('bus', 1.0),
    "can": ('can!', 0.95),
    "car": ('car.', 0.94),
    "cat": ('cat.', 0.94),
    "chair": ('chair.', 0.82),
    "chip": ('chip!', 0.95),
    "chop": ('chop', 0.94),
    "clap": ('clap.', 0.94),
    "clock": ('clock!', 0.95),
    "cup": ('cup!', 1.0),
    "dog": ('dog.', 0.86),
    "drop": ('drop!', 0.95),
    "drum": ('drum.', 0.94),
    "duck": ('duck.', 0.94),
    "fish": ('fish!', 1.0),
    "flag": ('flag!', 0.95),
    "flash": ('flash!', 1.0),
    "for": ('for', 0.94),
    "fork": ('fork!', 1.0),
    "fox": ('fox', 1.0),
    "frog": ('frog.', 0.94),
    "from": ('from.', 0.88),
    "grass": ('grass!', 1.0),
    "hat": ('hat', 0.94),
    "have": ('have.', 0.94),
    "her": ('her.', 0.78),
    "him": ('him!', 0.95),
    "home": ('home!', 0.95),
    "hop": ('hop!', 1.0),
    "into": ('into.', 0.88),
    "jam": ('jam.', 0.82),
    "kid": ('kid!', 1.0),
    "leg": ('leg.', 0.86),
    "like": ('like.', 0.94),
    "log": ('log', 0.82),
    "mop": ('mop.', 0.88),
    "much": ('much!', 0.95),
    "mud": ('mud.', 0.88),
    "net": ('net.', 0.82),
    "out": ('out.', 0.94),
    "path": ('path!', 1.0),
    "pen": ('pen.', 0.94),
    "pig": ('pig', 0.86),
    "plan": ('plan', 0.94),
    "rain": ('rain.', 0.88),
    "rat": ('rat?', 0.92),
    "run": ('run!', 0.95),
    "said": ('said.', 0.94),
    "she": ('she?', 0.92),
    "sheep": ('sheep.', 0.94),
    "ship": ('ship?', 0.92),
    "shop": ('shop.', 0.94),
    "sit": ('sit!', 1.0),
    "some": ('some', 1.0),
    "spoon": ('spoon?', 0.92),
    "stop": ('stop.', 0.94),
    "sun": ('sun!', 0.95),
    "swim": ('swim!', 1.0),
    "tap": ('tap.', 0.94),
    "the": ('the!', 0.95),
    "there": ('there.', 0.88),
    "they": ('they.', 0.82),
    "thin": ('thin!', 1.0),
    "three": ('three!', 1.0),
    "top": ('top.', 0.88),
    "train": ('train!', 1.0),
    "trap": ('trap', 0.94),
    "tree": ('tree?', 0.92),
    "truck": ('truck.', 0.88),
    "van": ('van!', 1.0),
    "was": ('was!', 1.0),
    "were": ('were.', 0.78),
    "wet": ('wet', 0.94),
    "what": ('what.', 0.88),
    "when": ('when!', 1.0),
    "will": ('will.', 0.94),
    "win": ('win!', 0.95),
    "with": ('with', 0.94),
    "would": ('would', 0.88),
    "your": ('your.', 0.78),
}

# Per-word voice overrides: (voice_id, lang). Default session voice otherwise.
_TTS_VOICE_OVERRIDES: dict[str, tuple[str, str]] = {
    "all": ('bf_emma', 'en-gb'),
    "are": ('af_alloy', 'en-us'),
    "bed": ('bf_emma', 'en-gb'),
    "big": ('bf_alice', 'en-gb'),
    "bird": ('bf_emma', 'en-gb'),
    "bike": ('bf_emma', 'en-gb'),
    "bin": ('bf_alice', 'en-gb'),
    "book": ('bf_emma', 'en-gb'),
    "box": ('bf_emma', 'en-gb'),
    "bring": ('bf_emma', 'en-gb'),
    "brush": ('bf_emma', 'en-gb'),
    "bug": ('bf_alice', 'en-gb'),
    "bus": ('bf_emma', 'en-gb'),
    "can": ('bf_emma', 'en-gb'),
    "cat": ('bf_emma', 'en-gb'),
    "chair": ('bm_lewis', 'en-gb'),
    "chip": ('bf_emma', 'en-gb'),
    "chop": ('bf_emma', 'en-gb'),
    "clap": ('bf_emma', 'en-gb'),
    "clock": ('bf_emma', 'en-gb'),
    "cup": ('bf_emma', 'en-gb'),
    "dog": ('bf_alice', 'en-gb'),
    "drop": ('bf_emma', 'en-gb'),
    "drum": ('bf_emma', 'en-gb'),
    "duck": ('bf_emma', 'en-gb'),
    "fish": ('bf_emma', 'en-gb'),
    "flag": ('bf_alice', 'en-gb'),
    "flash": ('bf_emma', 'en-gb'),
    "for": ('af_heart', 'en-us'),
    "fork": ('af_alloy', 'en-us'),
    "fox": ('bf_emma', 'en-gb'),
    "frog": ('bf_emma', 'en-gb'),
    "from": ('bf_emma', 'en-gb'),
    "grass": ('bf_alice', 'en-gb'),
    "have": ('bf_emma', 'en-gb'),
    "her": ('af_bella', 'en-us'),
    "him": ('bf_emma', 'en-gb'),
    "home": ('bf_emma', 'en-gb'),
    "hop": ('af_bella', 'en-us'),
    "into": ('bf_emma', 'en-gb'),
    "kid": ('bf_emma', 'en-gb'),
    "like": ('bf_emma', 'en-gb'),
    "log": ('bf_alice', 'en-gb'),
    "much": ('bf_emma', 'en-gb'),
    "mud": ('bf_emma', 'en-gb'),
    "out": ('bf_emma', 'en-gb'),
    "path": ('bm_lewis', 'en-gb'),
    "pen": ('bf_emma', 'en-gb'),
    "pig": ('bf_emma', 'en-gb'),
    "red": ('bf_emma', 'en-gb'),
    "plan": ('bf_emma', 'en-gb'),
    "rain": ('bm_lewis', 'en-gb'),
    "run": ('bf_emma', 'en-gb'),
    "said": ('bf_emma', 'en-gb'),
    "sheep": ('bf_emma', 'en-gb'),
    "ship": ('bf_emma', 'en-gb'),
    "shop": ('bf_emma', 'en-gb'),
    "sit": ('bf_alice', 'en-gb'),
    "some": ('bf_emma', 'en-gb'),
    "spoon": ('bf_emma', 'en-gb'),
    "stop": ('bf_emma', 'en-gb'),
    "sun": ('bf_emma', 'en-gb'),
    "swim": ('bf_emma', 'en-gb'),
    "tap": ('bf_emma', 'en-gb'),
    "there": ('bf_emma', 'en-gb'),
    "they": ('bf_emma', 'en-gb'),
    "thin": ('bf_emma', 'en-gb'),
    "three": ('bf_alice', 'en-gb'),
    "top": ('bm_lewis', 'en-gb'),
    "train": ('bf_emma', 'en-gb'),
    "trap": ('bf_emma', 'en-gb'),
    "tree": ('bf_isabella', 'en-gb'),
    "truck": ('bm_lewis', 'en-gb'),
    "van": ('bf_emma', 'en-gb'),
    "was": ('bf_emma', 'en-gb'),
    "were": ('bm_lewis', 'en-gb'),
    "wet": ('bf_alice', 'en-gb'),
    "what": ('bf_emma', 'en-gb'),
    "when": ('bm_lewis', 'en-gb'),
    "will": ('bf_emma', 'en-gb'),
    "win": ('bf_alice', 'en-gb'),
    "with": ('bf_emma', 'en-gb'),
    "would": ('bf_emma', 'en-gb'),
    # Default bf_isabella when absent (batch Whisper winners).
}

# Short phrases: default voice is Emma (see tts_voice). Isabella + a trailing
# period often adds junk syllables ("duckses", "pig eh", "bookie", "moppy").
_TTS_PHRASE_VOICES: dict[str, tuple[str, str]] = {
    # Isabella turns a final "sun" into "sunge" / "sandy". Alice keeps the /n/.
    "the hot sun": ("bf_alice", "en-gb"),
    "a hot sun": ("bf_alice", "en-gb"),
    # Emma pluralizes "pen" → pens; Lewis keeps singular.
    "my blue pen": ("bm_lewis", "en-gb"),
    # Emma @0.78 can onset like "the three…"; Alice keeps bare "three".
    "three red hats": ("bf_alice", "en-gb"),
    # Isabella can release "away" with a /t/-like stop ("await").
    "rain rain go away": ("bf_emma", "en-gb"),
    # Alice @1.0 on final /g/ makes Whisper invent a leading "It's".
    "a wet log": ("bf_emma", "en-gb"),
    "my big bag": ("bf_emma", "en-gb"),
}

# Explicit phrase spoken + speed when the default phrase rule is not enough.
# Spoken must keep the same on-screen words (optional trailing . ! ? only).
_TTS_PHRASE_RENDERS: dict[str, tuple[str, float]] = {
    "a quick fox": ("a quick fox", 0.90),
    "my blue pen": ("my blue pen", 0.78),
    "one fast van": ("one fast van", 0.78),
    "sit and read": ("sit and read", 0.82),
    "sit on top": ("sit on top", 0.90),
    "the cold wind": ("the cold wind", 0.82),
    "the long path": ("the long path.", 0.90),
    "the red box": ("the red box", 0.82),
    "three red hats": ("three red hats", 0.90),
    "rain rain go away": ("rain rain go away", 0.90),
    "a wet log": ("a wet log", 0.95),
    "my big bag": ("my big bag", 0.90),
    # Whisper A/B winners for leftover smears after Emma default.
    "hop to the red box": ("Hop to the red box", 0.82),
    "the red pen is big": ("The red pen is big", 0.82),
    "the dog and the fox can hop": ("The dog and the fox can hop", 0.82),
    "the cat and the dog can hop": ("The cat and the dog can hop", 0.90),
    "the bug and the ship can hop": ("The bug and the ship can hop", 0.95),
    # /g/-final phrases use Alice @ 1.0 via tts_voice + _phrase_final_speed.
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
    """Phrase-final speed: keep /g/ fast so Kokoro does not add a schwa."""
    core = (word or "").rstrip(".!?").lower()
    if _ends_hard_g(core):
        return 1.0
    if _last_word_slow_plosive(core):
        return 0.94  # /b d/ — slight hold, not the slow 0.78 schwa trap
    return 0.86


def tts_voice(text: str) -> tuple[str | None, str | None]:
    """Optional (voice_id, lang) override for one word or a known phrase."""
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
        # Alice cuts a clean /g/ release on short phrases; Emma often leaves
        # "frogeh"/"pigee". Longer lines stay on Emma — Isabella smears
        # endings (away→await, baa→bar, path→pass).
        if 2 <= len(words) <= 3 and _ends_hard_g(last):
            return ("bf_alice", "en-gb")
        # Long "… can hop" lines: Emma turns hop→help; Alice keeps hop.
        if len(words) >= 4 and last == "hop":
            return ("bf_alice", "en-gb")
        return _DEFAULT_PHRASE_VOICE
    return None, None


def tts_render(text: str) -> tuple[str, float]:
    """Pick Kokoro text + speed so short words keep plosives and length.

    Bare "cup"/"map"/"the" come out clipped; a terminal period gives natural
    lengthening, and a slightly slower speed helps kids hear each sound.
    Voiced plosive endings (dog/pig) need even more time or the burst dies.

    Some words need explicit overrides (see _TTS_WORD_OVERRIDES). Overrides
    must never invent extra words — the child hears exactly the on-screen token.

    Short phrases (2–3 words) must not get a forced trailing period: with the
    default Isabella voice that often invents an extra syllable on the last
    word (ducks→duckses, mop→moppy, book→bookie). Emma + bare text is cleaner.
    Phrase-final /g/ is rendered *faster* (Alice @ 1.0) — slowing it adds "eh".
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
        # Final /b d g/ (not /ŋ/): moderate period — bang@1.0 → "froggy"/"biggie",
        # crawl@0.78 → "frogeh". Prefer overrides above when Whisper-tuned.
        if core[-1:] in "bdg" and not core.endswith("ng"):
            return core + ".", 0.86
        if (
            len(core) >= 2
            and core.endswith("e")
            and core[-2] in "bdgkpt"
        ):
            return spoken, 0.78
        # Tiny function words (sir/the/you) and CVC kid words need more time
        # so the body is not a clipped blip — still only the one on-screen word.
        if len(core) <= 3:
            return spoken, 0.82
        if len(core) <= 4:
            return spoken, 0.86
        return spoken, 0.88
    # Multi-word clips: honor explicit phrase renders at any length, then
    # bare text (no forced extra period) + phrase-final speed. Longer story
    # lines keep a steady ~0.90 so endings stay clear under Emma.
    key = _phrase_key(stripped)
    if key in _TTS_PHRASE_RENDERS:
        return _TTS_PHRASE_RENDERS[key]
    if len(words) >= 2:
        spoken = stripped.rstrip(".!?")
        if len(words) <= 3:
            return spoken, _phrase_final_speed(words[-1])
        return spoken, 0.90
    return stripped, 0.95


# Short listen words need generous silence around the speech so onsets/plosives
# are not cut off by players, Bluetooth buffering, or aggressive loudnorm.
_LISTEN_LEAD_MS = 350
_LISTEN_TRAIL_SEC = 0.50


def postprocess_generated_wav(src: Path, dest: Path) -> None:
    """Mono 16-bit PCM, gentle lead trim, loudness-normalize, then pad.

    Never strip trailing silence — final plosives in cup/map/cat are quiet and
    get eaten by stop-period silenceremove.

    Order matters: normalize the speech first, *then* add lead/trail pads.
    Padding before loudnorm lets silence dominate the measure and can crush
    quiet plosive tails (sounds "clipped" even though samples remain).
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Lead trim only (start_periods). No stop_periods — keeps /p/ /t/ /k/.
    # Gentler start_threshold so soft onsets (map/cup) are not bitten.
    af = (
        "silenceremove=start_periods=1:start_duration=0.02:start_threshold=-50dB,"
        "loudnorm=I=-18:TP=-2.0:LRA=11,"
        f"adelay={_LISTEN_LEAD_MS}|{_LISTEN_LEAD_MS},"
        f"apad=pad_dur={_LISTEN_TRAIL_SEC}"
    )
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
        "-af",
        af,
        str(dest),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, check=False, timeout=60)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        raise AudioError(f"ffmpeg postprocess failed: {exc}") from exc
    if result.returncode != 0 or not dest.exists():
        err = (result.stderr or b"").decode("utf-8", errors="replace")[:400]
        raise AudioError(f"ffmpeg postprocess failed: {err}")


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
