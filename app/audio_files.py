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


def postprocess_generated_wav(src: Path, dest: Path) -> None:
    """Mono 16-bit PCM, trim silence, loudness-normalize (ffmpeg)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
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
        "silenceremove=start_periods=1:start_silence=0.05:start_threshold=-40dB:"
        "stop_periods=1:stop_silence=0.08:stop_threshold=-40dB,"
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
