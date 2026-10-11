"""Paths, thresholds, bind address, and kindness message strings."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = ROOT / "data"
MODELS_DIR = ROOT / "models"
AUDIO_GENERATED = ROOT / "audio" / "generated"
AUDIO_HUMAN = ROOT / "audio" / "human"
CONTENT_ITEMS = ROOT / "content" / "items.json"
SETTINGS_PATH = DATA_DIR / "settings.json"
DB_PATH = DATA_DIR / "reading.db"
STATIC_DIR = ROOT / "static"
TEMP_DIR = DATA_DIR / "tmp"
KEPT_DIR = DATA_DIR / "kept"

HOST = "127.0.0.1"
PORT = 8765

RMS_MIN = 0.01
MIN_AUDIO_SECONDS = 0.3
NO_SPEECH_PROB_MAX = 0.60
LOW_TOKEN_PROB = 0.25
BEGINNER_CORRECT_MIN_PROB = 0.60
STRICT_CORRECT_MIN_PROB = 0.85

WHISPER_MODEL = "small.en"
WHISPER_DEVICE = "cpu"
WHISPER_COMPUTE_TYPE = "int8"
WHISPER_COMPUTE_TYPE_FALLBACK = "int8_float32"
WHISPER_BEAM_SIZE = 3  # short kid words; 1 was too lossy on CPU small.en

# Kokoro ONNX (M2) — voice id must exist in the installed voices bin.
# Chosen by synthesizing the/thin/a big red ship across bf_emma, bf_alice,
# bf_isabella and picking the clearest (presence × low silence); see m2 notes.
KOKORO_MODEL_PATH = MODELS_DIR / "kokoro" / "kokoro-v1.0.onnx"
KOKORO_VOICES_PATH = MODELS_DIR / "kokoro" / "voices-v1.0.bin"
KOKORO_VOICE_ID = "bf_isabella"
KOKORO_LANG = "en-gb"
AUDIO_SAMPLE_RATE = 24000  # Kokoro native; served files normalized to 16 kHz mono

MAX_RETRIES_PER_ITEM = 3
DEFAULT_SESSION_LENGTH = 10
MASTERED_EVERY_N_SESSIONS = 7
AUTO_STRICT_SESSIONS = 3  # consecutive move-up sessions → mode=strict when auto_strict

MSG_RETRY = "I didn't catch that — please read it again."
MSG_CLOSE = "Almost — read it one more time!"
MSG_CLOSE_OK = "Almost!"
MSG_MISS = "That one's tricky, we'll visit it again."
MSG_SKIP = "We'll try that one another time."
MSG_CORRECT = "You got it!"


def msg_retry(try_number: int, tries_max: int) -> str:
    """Kind prompt that another read is required (with try count)."""
    n = max(1, int(try_number))
    m = max(n, int(tries_max))
    return f"I didn't catch that — please read it again ({n} of {m})."

DEFAULT_SETTINGS = {
    "profile_name": "",
    "mode": "beginner",
    "level": 1,
    "session_length": DEFAULT_SESSION_LENGTH,
    "keep_audio": False,
    "buddy": "cat",  # cat | krishna | mouse
    "auto_strict": True,
    "auto_strict_sessions": AUTO_STRICT_SESSIONS,
    "low_streak": 0,
    "move_up_streak": 0,
    "garden_growth": 0,  # completed sessions; only increases
}

BUDDIES = ("cat", "krishna", "mouse")


def ensure_dirs() -> None:
    for path in (DATA_DIR, MODELS_DIR, AUDIO_GENERATED, AUDIO_HUMAN, TEMP_DIR, KEPT_DIR):
        path.mkdir(parents=True, exist_ok=True)


def is_offline_configured() -> bool:
    value = os.environ.get("HF_HUB_OFFLINE", "")
    return value.strip() in {"1", "true", "True", "yes", "YES"}
