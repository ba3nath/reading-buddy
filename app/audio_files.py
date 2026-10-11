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
# - Bare a/bring/log/net: period + slow speed adds a trailing vowel burst.
# - sit!: "sit." @ 0.84 voices the onset (/zIt/); bang + full speed keeps /s/.
_TTS_WORD_OVERRIDES: dict[str, tuple[str, float]] = {
    "a": ("a", 0.88),
    "bring": ("bring", 0.88),
    "log": ("log", 0.88),
    "net": ("net", 0.96),
    "sit": ("sit!", 1.0),
}


def tts_render(text: str) -> tuple[str, float]:
    """Pick Kokoro text + speed so short words keep plosives and length.

    Bare "cup"/"map"/"the" come out clipped; a terminal period gives natural
    lengthening, and a slightly slower speed helps kids hear each sound.
    Voiced plosive endings (dog/pig) need even more time or the burst dies.

    Some words need explicit overrides (see _TTS_WORD_OVERRIDES).
    """
    stripped = (text or "").strip()
    if not stripped:
        return text, 1.0
    words = stripped.split()
    if len(words) == 1 and len(words[0]) <= 10:
        spoken = words[0]
        core = spoken.rstrip(".!?").lower()
        if core in _TTS_WORD_OVERRIDES:
            return _TTS_WORD_OVERRIDES[core]
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
        # Tiny function words (sir/the/you) need a touch more time.
        if len(core) <= 3:
            return spoken, 0.84
        return spoken, 0.88
    # Short kid phrases ("a long train"): period + slight slowdown for clarity.
    if 2 <= len(words) <= 3:
        spoken = stripped if stripped[-1] in ".!?" else stripped + "."
        return spoken, 0.90
    return stripped, 0.95


def postprocess_generated_wav(src: Path, dest: Path) -> None:
    """Mono 16-bit PCM, gentle lead trim, loudness-normalize (ffmpeg).

    Never strip trailing silence — final plosives in cup/map/cat are quiet and
    get eaten by stop-period silenceremove. Pad both ends so listen-then-say
    is not abrupt.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Lead trim only (start_periods). No stop_periods — keeps /p/ /t/ /k/.
    # adelay/apad: ~200ms lead + 280ms trail for short kid words.
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
        "silenceremove=start_periods=1:start_duration=0.05:start_threshold=-45dB,"
        "adelay=200|200,apad=pad_dur=0.28,"
        "loudnorm=I=-16:TP=-1.5:LRA=11",
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
