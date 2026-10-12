"""ffmpeg decode, RMS/duration gates, temp cleanup."""

from __future__ import annotations

import audioop
import subprocess
import wave
from pathlib import Path
from uuid import uuid4

from app import config


class AudioError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def ffmpeg_available() -> bool:
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
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
    cmd = [
        "ffmpeg",
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
    # audioop.rms on 16-bit PCM → scale to float -1..1
    if not frames:
        return duration, 0.0
    rms_int = audioop.rms(frames, sampwidth)
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
    "a": ("a", 0.88),
    "bed": ("bed.", 0.88),
    "bring": ("bring", 0.92),
    "brush": ("brush.", 0.94),
    "bus": ("bus", 1.0),
    "can": ("can.", 0.82),
    "cat": ("cat.", 0.94),
    "chair": ("chair.", 0.94),
    "chop": ("chop", 0.94),
    "clock": ("clock!", 1.0),
    "cup": ("cup!", 1.0),
    "dog": ("dog.", 0.88),
    "drum": ("drum.", 0.94),
    "flag": ("flag!", 0.95),
    "flash": ("flash.", 0.88),
    "fox": ("fox", 0.94),
    "frog": ("frog.", 0.94),
    "from": ("from.", 0.88),
    "grass": ("grass!", 1.0),
    "hat": ("hat", 0.94),
    "her": ("her.", 0.82),
    "him": ("him!", 1.0),
    "into": ("into.", 0.88),
    "jam": ("jam.", 0.82),
    "kid": ("kid!", 1.0),
    "like": ("like.", 0.94),
    "log": ("log.", 0.78),
    "net": ("net.", 0.82),
    "pen": ("pen", 0.88),
    "pig": ("pig.", 0.78),
    "rat": ("rat?", 0.92),
    "said": ("said.", 0.82),
    "sheep": ("sheep.", 0.78),
    "ship": ("ship?", 0.92),
    "sit": ("sit!", 1.0),
    "some": ("some", 1.0),
    "spoon": ("spoon?", 0.92),
    "sun": ("sun.", 0.82),
    "swim": ("swim!", 1.0),
    "the": ("the.", 0.88),
    "there": ("there.", 0.88),
    "they": ("they.", 0.94),
    "thin": ("thin!", 1.0),
    "three": ("three!", 1.0),
    "top": ("top.", 0.88),
    "train": ("train!", 1.0),
    "trap": ("trap.", 0.82),
    "truck": ("truck.", 0.88),
    "van": ("van!", 1.0),
    "were": ("were.", 0.82),
    "wet": ("wet", 0.94),
    "what": ("what.", 0.78),
    "when": ("when!", 1.0),
    "would": ("would", 0.88),
    "your": ("your.", 0.78),
}

# Per-word voice overrides: (voice_id, lang). Default session voice otherwise.
_TTS_VOICE_OVERRIDES: dict[str, tuple[str, str]] = {
    "bed": ("bf_emma", "en-gb"),
    "bring": ("bf_emma", "en-gb"),
    "brush": ("bf_emma", "en-gb"),
    "bus": ("bf_emma", "en-gb"),
    "can": ("bf_emma", "en-gb"),
    "cat": ("bf_emma", "en-gb"),
    "chop": ("bf_emma", "en-gb"),
    "cup": ("bf_emma", "en-gb"),
    "dog": ("bf_emma", "en-gb"),
    "drum": ("bf_emma", "en-gb"),
    "flag": ("bf_emma", "en-gb"),
    "frog": ("bf_emma", "en-gb"),
    "from": ("bf_emma", "en-gb"),
    "grass": ("bf_alice", "en-gb"),
    "her": ("bf_emma", "en-gb"),
    "into": ("bf_emma", "en-gb"),
    "kid": ("bf_emma", "en-gb"),
    "like": ("bf_emma", "en-gb"),
    "log": ("bf_emma", "en-gb"),
    "pig": ("bf_emma", "en-gb"),
    "said": ("bf_emma", "en-gb"),
    "sheep": ("bf_emma", "en-gb"),
    "ship": ("bf_emma", "en-gb"),
    "sit": ("bf_alice", "en-gb"),
    "some": ("bf_emma", "en-gb"),
    "spoon": ("bf_emma", "en-gb"),
    "sun": ("bf_emma", "en-gb"),
    "swim": ("bf_emma", "en-gb"),
    "there": ("bf_emma", "en-gb"),
    "they": ("bf_emma", "en-gb"),
    "thin": ("bf_emma", "en-gb"),
    "three": ("bf_alice", "en-gb"),
    "top": ("bm_lewis", "en-gb"),
    "train": ("bf_emma", "en-gb"),
    "trap": ("bm_lewis", "en-gb"),
    "truck": ("bm_lewis", "en-gb"),
    "van": ("bf_emma", "en-gb"),
    "were": ("bf_emma", "en-gb"),
    "wet": ("bf_alice", "en-gb"),
    "what": ("bf_emma", "en-gb"),
    "when": ("bm_lewis", "en-gb"),
    "would": ("bf_emma", "en-gb"),
    # Default bf_isabella when absent (batch Whisper winners).
}


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


def tts_voice(text: str) -> tuple[str | None, str | None]:
    """Optional (voice_id, lang) override for one word; else (None, None)."""
    core = _single_word_core(text)
    if core and core in _TTS_VOICE_OVERRIDES:
        return _TTS_VOICE_OVERRIDES[core]
    return None, None


def tts_render(text: str) -> tuple[str, float]:
    """Pick Kokoro text + speed so short words keep plosives and length.

    Bare "cup"/"map"/"the" come out clipped; a terminal period gives natural
    lengthening, and a slightly slower speed helps kids hear each sound.
    Voiced plosive endings (dog/pig) need even more time or the burst dies.

    Some words need explicit overrides (see _TTS_WORD_OVERRIDES). Overrides
    must never invent extra words — the child hears exactly the on-screen token.
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
        # Final b/d/g plosives (and silent-e forms like "like"/"slide") fade
        # at 0.88. Do NOT treat -ng as /g/ — that's /ŋ/ (bring/long/reading).
        ends_ng = core.endswith("ng")
        slow_plosive = (not ends_ng) and (
            core[-1:] in "bdg"
            or (len(core) >= 2 and core.endswith("e") and core[-2] in "bdgkpt")
        )
        if slow_plosive:
            return spoken, 0.78
        # Tiny function words (sir/the/you) and CVC kid words need more time
        # so the body is not a clipped blip — still only the one on-screen word.
        if len(core) <= 3:
            return spoken, 0.82
        if len(core) <= 4:
            return spoken, 0.86
        return spoken, 0.88
    # Short kid phrases ("a long train"): period + slight slowdown for clarity.
    if 2 <= len(words) <= 3:
        spoken = stripped if stripped[-1] in ".!?" else stripped + "."
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
    cmd = [
        "ffmpeg",
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
