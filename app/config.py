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
ALLOWED_SESSION_LENGTHS = (5, 10)


def normalize_session_length(value: object) -> int:
    """Sessions are uniform: only 5 or 10 words/phrases."""
    try:
        n = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_SESSION_LENGTH
    if n in ALLOWED_SESSION_LENGTHS:
        return n
    return 5 if abs(n - 5) <= abs(n - 10) else 10


# Four difficulty tiers (settings/session ``level``). Content rows keep item.level 1–7.
DIFFICULTY_TIERS: dict[int, dict[str, object]] = {
    1: {"key": "words", "label": "Words", "content_levels": (1, 2, 3)},
    2: {"key": "phrases", "label": "Phrases", "content_levels": (4,)},
    3: {"key": "rhymes", "label": "Rhymes", "content_levels": (6, 7)},
    4: {"key": "stories", "label": "Stories", "content_levels": (5,)},
}
MAX_DIFFICULTY = 4
# Each difficulty has this many ordered sets (stages) the child works through.
STAGES_PER_DIFFICULTY = 8


def content_levels_for_difficulty(difficulty: int) -> tuple[int, ...]:
    tier = DIFFICULTY_TIERS.get(int(difficulty))
    if not tier:
        return (1, 2, 3)
    return tuple(tier["content_levels"])  # type: ignore[arg-type]


def difficulty_label(difficulty: int) -> str:
    tier = DIFFICULTY_TIERS.get(int(difficulty))
    return str(tier["label"]) if tier else "Words"


def normalize_stage(value: object) -> int:
    try:
        n = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 1
    if n < 1:
        return 1
    if n > STAGES_PER_DIFFICULTY:
        return STAGES_PER_DIFFICULTY
    return n


def default_stage_by_difficulty() -> dict[str, int]:
    return {str(d): 1 for d in range(1, MAX_DIFFICULTY + 1)}


def stage_label(difficulty: int, stage: int) -> str:
    """Kid-facing badge, e.g. ``Words · Set 2/8``."""
    return (
        f"{difficulty_label(difficulty)} · Set "
        f"{normalize_stage(stage)}/{STAGES_PER_DIFFICULTY}"
    )


def stage_slice_bounds(
    pool_size: int, stage: int, stages: int = STAGES_PER_DIFFICULTY
) -> tuple[int, int]:
    """Return [start, end) indices for an even split of ``pool_size`` into stages."""
    stage = normalize_stage(stage)
    stages = max(1, int(stages))
    n = max(0, int(pool_size))
    if n == 0:
        return 0, 0
    base, rem = divmod(n, stages)
    sizes = [base + (1 if i < rem else 0) for i in range(stages)]
    start = sum(sizes[: stage - 1])
    return start, start + sizes[stage - 1]


def migrate_legacy_level_to_difficulty(level: object) -> int:
    """Map old content levels 1–7 onto difficulty tiers 1–4."""
    try:
        n = int(level)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 1
    if n <= 3:
        return 1  # words
    if n == 4:
        return 2  # phrases
    if n == 5:
        return 4  # stories
    if n >= 6:
        return 3  # rhymes
    return 1


def normalize_difficulty(value: object) -> int:
    try:
        n = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 1
    if n < 1:
        return 1
    if n > MAX_DIFFICULTY:
        return migrate_legacy_level_to_difficulty(n)
    return n


MASTERED_EVERY_N_SESSIONS = 7
AUTO_STRICT_SESSIONS = 3  # consecutive move-up sessions → mode=strict when auto_strict

MSG_RETRY = "I didn't catch that — please read it again."
MSG_CLOSE = "Almost — read it one more time!"
# Locked close (second take done) — must NOT ask for another read.
MSG_CLOSE_OK = "Nice try — on to the next!"
MSG_MISS = "That one's tricky, we'll visit it again."
MSG_SKIP = "We'll try that one another time."
MSG_CORRECT = "You got it!"


def msg_retry(next_try: int, tries_max: int) -> str:
    """Kind prompt that another read is required.

    ``next_try`` is the upcoming attempt number (2..tries_max), not the
    failed take that just finished.
    """
    n = max(2, int(next_try))
    m = max(n, int(tries_max))
    return f"I didn't catch that — please read it again (try {n} of {m})."

DEFAULT_SETTINGS = {
    "profile_name": "",
    "mode": "beginner",
    "level": 1,  # difficulty tier 1–4 (words / phrases / rhymes / stories)
    "difficulty_migrated": True,
    "stage": 1,  # set 1–8 within the current difficulty
    "stage_by_difficulty": {  # per-difficulty set progress
        "1": 1,
        "2": 1,
        "3": 1,
        "4": 1,
    },
    "session_length": DEFAULT_SESSION_LENGTH,
    "keep_audio": False,
    "buddy": "krishna",  # krishna | unicorn
    "auto_strict": True,
    "auto_strict_sessions": AUTO_STRICT_SESSIONS,
    "low_streak": 0,
    "move_up_streak": 0,
    "garden_growth": 0,  # completed sessions; only increases
    # Play stats (growth-only kindness: streaks reset quietly, never scold)
    "lifetime_stars": 0,
    "day_streak": 0,
    "last_play_date": "",
    "badges_earned": [],  # list of badge ids
}

BUDDIES = ("krishna", "unicorn")


def ensure_dirs() -> None:
    for path in (DATA_DIR, MODELS_DIR, AUDIO_GENERATED, AUDIO_HUMAN, TEMP_DIR, KEPT_DIR):
        path.mkdir(parents=True, exist_ok=True)


def is_offline_configured() -> bool:
    value = os.environ.get("HF_HUB_OFFLINE", "")
    return value.strip() in {"1", "true", "True", "yes", "YES"}
