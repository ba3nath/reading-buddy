"""Listen-clip audio quality contracts (padding, energy, generated assets)."""

from __future__ import annotations

import array
import math
import wave
from pathlib import Path

import pytest

from app import audio_files, config
from app.audio_files import (
    listen_clip_metrics,
    listen_clip_ok,
    tighten_tail_samples,
    wav_duration_and_rms,
)

ROOT = Path(__file__).resolve().parents[1]

# Spot-check words that have historically clipped or smeared.
_QUALITY_SLUGS = (
    "cat",
    "cup",
    "map",
    "pig",
    "frog",
    "shell",
    "sit",
    "top",
    "net",
    "log",
)


def _write_tone_wav(
    path: Path,
    *,
    rate: int = 24000,
    seconds: float = 0.5,
    amp: int = 8000,
    freq: float = 440.0,
) -> None:
    n = int(rate * seconds)
    samples = array.array("h")
    for i in range(n):
        samples.append(int(amp * math.sin(2 * math.pi * freq * i / rate)))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(samples.tobytes())


def test_listen_clip_metrics_reports_tone(tmp_path):
    wav = tmp_path / "tone.wav"
    _write_tone_wav(wav, seconds=0.6)
    m = listen_clip_metrics(wav)
    assert m["rate"] == 24000
    assert m["channels"] == 1
    assert m["sampwidth"] == 2
    assert 0.55 <= float(m["duration"]) <= 0.65
    assert float(m["rms"]) > 0.05
    dur, rms = wav_duration_and_rms(wav)
    assert abs(dur - float(m["duration"])) < 1e-6
    assert abs(rms - float(m["rms"])) < 1e-6
    assert listen_clip_ok(wav, expect_rate=24000)


def test_listen_clip_ok_rejects_quiet_or_short(tmp_path):
    quiet = tmp_path / "quiet.wav"
    _write_tone_wav(quiet, seconds=0.6, amp=20)
    assert not listen_clip_ok(quiet, expect_rate=24000, min_rms=0.01)

    short = tmp_path / "short.wav"
    _write_tone_wav(short, seconds=0.1, amp=8000)
    assert not listen_clip_ok(short, expect_rate=24000, min_duration=0.35)


def test_tighten_tail_noop_when_no_smear():
    rate = 24000
    n = int(rate * 0.3)
    samples = array.array("h")
    for i in range(n):
        samples.append(int(6000 * math.sin(2 * math.pi * 330 * i / rate)))
    out = tighten_tail_samples(samples, rate, hangover_ms=80, fade_ms=40)
    # Body stays; fade may trim a little hangover but not the speech core.
    assert len(out) >= int(n * 0.85)
    mid = out[len(out) // 4 : (3 * len(out)) // 4]
    assert max(abs(s) for s in mid) > 1000


def test_tighten_tail_empty_or_tiny_unchanged():
    rate = 24000
    tiny = array.array("h", [0, 1, 2])
    assert list(tighten_tail_samples(tiny, rate)) == [0, 1, 2]
    assert list(tighten_tail_samples(array.array("h"), rate)) == []


def test_generated_listen_clips_meet_quality_floor():
    """Real generated assets: 24 kHz mono, padded, audible."""
    missing = []
    bad = []
    checked = 0
    for slug in _QUALITY_SLUGS:
        path = audio_files.resolve_audio_slug(slug)
        if path is None or not path.is_file():
            missing.append(slug)
            continue
        checked += 1
        m = listen_clip_metrics(path)
        if m["rate"] != config.AUDIO_SAMPLE_RATE:
            bad.append((slug, "rate", m["rate"]))
            continue
        if m["channels"] != 1 or m["sampwidth"] != 2:
            bad.append((slug, "format", m))
            continue
        # Lead (~350ms) + speech + trail (~500ms) ⇒ short CVC words ≥ ~0.9s.
        if float(m["duration"]) < 0.7:
            bad.append((slug, "short", m["duration"]))
            continue
        if float(m["rms"]) < 0.02:
            bad.append((slug, "quiet", m["rms"]))
            continue
        if not listen_clip_ok(
            path, expect_rate=config.AUDIO_SAMPLE_RATE, min_duration=0.7, min_rms=0.02
        ):
            bad.append((slug, "ok", m))
    if checked == 0:
        pytest.skip("no generated listen clips present")
    assert not bad, f"clip quality issues: {bad}"
    # Prefer all spot-check slugs present when any audio exists.
    assert checked >= 5, f"only {checked} clips found; missing={missing}"


def test_postprocess_lead_and_trail_constants():
    """Padding must leave room before/after speech so Bluetooth/players don't clip."""
    assert audio_files._LISTEN_LEAD_MS >= 300
    assert audio_files._LISTEN_TRAIL_SEC >= 0.45
    # Tail cleanup must not be so aggressive it eats plosives.
    assert audio_files._TAIL_HANGOVER_MS >= 80
    assert 0.03 <= audio_files._TAIL_RMS_REL <= 0.12
