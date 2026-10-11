"""Presence checks for the multi-read / short-word recognition fix."""

from __future__ import annotations

import inspect
from pathlib import Path

from app import config
from app import whisper_engine

ROOT = Path(__file__).resolve().parents[1]
RECORD_JS = (ROOT / "static" / "js" / "record.js").read_text(encoding="utf-8")
GAME_JS = (ROOT / "static" / "js" / "game.js").read_text(encoding="utf-8")


def test_whisper_keeps_short_words_without_vad():
    src = inspect.getsource(whisper_engine.WhisperEngine.transcribe)
    assert "vad_filter=False" in src
    assert "vad_filter=True" not in src
    assert config.WHISPER_BEAM_SIZE >= 3


def test_recorder_gives_trail_pad_and_tap_finish():
    assert "SILENCE_GAP_MS = 1800" in RECORD_JS
    assert "TRAIL_PAD_MS = 350" in RECORD_JS
    assert "noiseSuppression: false" in RECORD_JS
    assert "get isRecording" in RECORD_JS or "isRecording" in RECORD_JS
    assert "_scheduleStop" in RECORD_JS
    assert "onarmed" in RECORD_JS


def test_mic_second_tap_finishes_take():
    assert "Tap when done" in GAME_JS
    assert "tap again when done" in GAME_JS
    assert "isRecording" in GAME_JS
    assert 'state.recorder.stop()' in GAME_JS
