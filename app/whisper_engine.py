"""faster-whisper small.en loader and transcription."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app import config

logger = logging.getLogger(__name__)


@dataclass
class TranscriptWord:
    word: str
    probability: float


@dataclass
class AttemptTranscript:
    transcript: str
    words: list[TranscriptWord]
    no_speech_prob: float


class WhisperEngine:
    def __init__(self) -> None:
        self._model: Any = None
        self._compute_type: str | None = None
        self._load_error: str | None = None

    @property
    def ready(self) -> bool:
        return self._model is not None

    @property
    def load_error(self) -> str | None:
        return self._load_error

    def load(self) -> bool:
        """Load small.en from models/ (or cache). Returns True if ready."""
        os.environ.setdefault("HF_HUB_OFFLINE", os.environ.get("HF_HUB_OFFLINE", "0"))
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            self._load_error = f"faster-whisper not installed: {exc}"
            logger.warning(self._load_error)
            return False

        model_dir = config.MODELS_DIR
        model_dir.mkdir(parents=True, exist_ok=True)

        # Prefer a local download directory if present
        local_candidate = model_dir / "whisper-small.en"
        model_id: str | Path
        if local_candidate.exists():
            model_id = local_candidate
        else:
            # faster-whisper will look in download_root / use model name
            model_id = config.WHISPER_MODEL

        for compute_type in (
            config.WHISPER_COMPUTE_TYPE,
            config.WHISPER_COMPUTE_TYPE_FALLBACK,
        ):
            try:
                self._model = WhisperModel(
                    str(model_id),
                    device=config.WHISPER_DEVICE,
                    compute_type=compute_type,
                    download_root=str(model_dir),
                )
                self._compute_type = compute_type
                self._load_error = None
                logger.info("Loaded Whisper %s (%s)", model_id, compute_type)
                return True
            except Exception as exc:  # noqa: BLE001 — report via health
                self._load_error = str(exc)
                logger.warning("Whisper load failed (%s): %s", compute_type, exc)
                self._model = None
        return False

    def transcribe(self, wav_path: Path, initial_prompt: str) -> AttemptTranscript:
        if self._model is None:
            raise RuntimeError(self._load_error or "Whisper model not loaded")

        segments, info = self._model.transcribe(
            str(wav_path),
            language="en",
            beam_size=config.WHISPER_BEAM_SIZE,
            temperature=0.0,
            condition_on_previous_text=False,
            word_timestamps=True,
            vad_filter=True,
            initial_prompt=initial_prompt,
        )
        seg_list = list(segments)
        if not seg_list:
            return AttemptTranscript(transcript="", words=[], no_speech_prob=1.0)

        top = seg_list[0]
        no_speech = float(getattr(top, "no_speech_prob", 0.0) or 0.0)
        words: list[TranscriptWord] = []
        parts: list[str] = []
        for seg in seg_list:
            for w in getattr(seg, "words", None) or []:
                token = (w.word or "").strip()
                if not token:
                    continue
                parts.append(token)
                words.append(
                    TranscriptWord(
                        word=token,
                        probability=float(getattr(w, "probability", 0.0) or 0.0),
                    )
                )
        # Fallback if word timestamps empty
        if not parts:
            text = " ".join((seg.text or "").strip() for seg in seg_list).strip()
            return AttemptTranscript(
                transcript=text,
                words=[],
                no_speech_prob=no_speech,
            )
        return AttemptTranscript(
            transcript=" ".join(parts),
            words=words,
            no_speech_prob=no_speech,
        )


# Process-wide engine; tests may replace `.transcribe` / inject a double.
engine = WhisperEngine()


class WhisperDouble:
    """Test double returning a fixed AttemptTranscript."""

    def __init__(self, fixed: AttemptTranscript | None = None):
        self.fixed = fixed
        self.calls: list[tuple[Path, str]] = []

    @property
    def ready(self) -> bool:
        return True

    def load(self) -> bool:
        return True

    def set_transcript(self, fixed: AttemptTranscript) -> None:
        self.fixed = fixed

    def transcribe(self, wav_path: Path, initial_prompt: str) -> AttemptTranscript:
        self.calls.append((wav_path, initial_prompt))
        if self.fixed is None:
            return AttemptTranscript(transcript="", words=[], no_speech_prob=1.0)
        return self.fixed
