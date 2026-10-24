"""Shared fixtures: temp DB, settings, Whisper double, audio samples."""

from __future__ import annotations

import json
import struct
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config
from app.db import connect, init_schema, save_settings, upsert_items_from_json
from app.whisper_engine import AttemptTranscript, TranscriptWord, WhisperDouble

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def transcript_case():
    def _load(name: str) -> dict:
        path = FIXTURES / "transcripts" / f"{name}.json"
        with path.open(encoding="utf-8") as f:
            return json.load(f)

    return _load


@pytest.fixture
def tmp_env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    models = tmp_path / "models"
    tmp = data / "tmp"
    kept = data / "kept"
    for p in (data, models, tmp, kept):
        p.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setattr(config, "DB_PATH", data / "reading.db")
    monkeypatch.setattr(config, "SETTINGS_PATH", data / "settings.json")
    monkeypatch.setattr(config, "MODELS_DIR", models)
    monkeypatch.setattr(config, "TEMP_DIR", tmp)
    monkeypatch.setattr(config, "KEPT_DIR", kept)
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")

    save_settings(dict(config.DEFAULT_SETTINGS))
    conn = connect(config.DB_PATH)
    init_schema(conn)
    upsert_items_from_json(conn)
    yield {"conn": conn, "data": data, "tmp": tmp}
    conn.close()


def _write_tone_wav(path: Path, seconds: float = 0.5, freq: float = 440.0) -> None:
    rate = 16000
    n = int(rate * seconds)
    import math

    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        frames = bytearray()
        for i in range(n):
            val = int(12000 * math.sin(2 * math.pi * freq * (i / rate)))
            frames.extend(struct.pack("<h", val))
        wf.writeframes(frames)


def _write_silence_wav(path: Path, seconds: float = 0.1) -> None:
    rate = 16000
    n = int(rate * seconds)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"\x00\x00" * n)


@pytest.fixture
def tone_wav(tmp_path) -> Path:
    path = tmp_path / "tone.wav"
    _write_tone_wav(path)
    return path


@pytest.fixture
def silence_wav(tmp_path) -> Path:
    path = tmp_path / "silence.wav"
    _write_silence_wav(path)
    return path


@pytest.fixture
def whisper_double():
    return WhisperDouble(
        AttemptTranscript(
            transcript="cat",
            words=[TranscriptWord(word="cat", probability=0.95)],
            no_speech_prob=0.1,
        )
    )


@pytest.fixture
def client(tmp_env, whisper_double, monkeypatch):
    from contextlib import asynccontextmanager

    import app.audio_files as audio_files
    import app.main as main_mod
    import app.whisper_engine as we

    monkeypatch.setattr(main_mod, "engine", whisper_double)
    monkeypatch.setattr(we, "engine", whisper_double)
    monkeypatch.setattr(main_mod, "ffmpeg_available", lambda: True)
    monkeypatch.setattr(audio_files, "ffmpeg_available", lambda: True)

    # Bypass ffmpeg convert: copy upload bytes if already wav, else write tone wav
    def fake_convert(src: Path, dest: Path) -> None:
        data = src.read_bytes()
        if data[:4] == b"RIFF":
            dest.write_bytes(data)
        else:
            _write_tone_wav(dest, seconds=0.5)

    monkeypatch.setattr(main_mod, "convert_to_wav", fake_convert)
    monkeypatch.setattr(audio_files, "convert_to_wav", fake_convert)
    monkeypatch.setattr(main_mod, "is_silence", audio_files.is_silence)

    @asynccontextmanager
    async def quiet_lifespan(app):
        # DB/items already prepared by tmp_env; keep Whisper double as-is.
        yield

    monkeypatch.setattr(main_mod.app.router, "lifespan_context", quiet_lifespan)
    main_mod.reset_conn_for_tests(tmp_env["conn"])

    with TestClient(main_mod.app, raise_server_exceptions=True) as c:
        main_mod.reset_conn_for_tests(tmp_env["conn"])
        monkeypatch.setattr(main_mod, "engine", whisper_double)
        yield c
    main_mod.reset_conn_for_tests(None)


@pytest.fixture
def assert_attempt_shape():
    def _assert(payload: dict, *, words_total: int | None = None) -> None:
        required = {
            "result",
            "transcript",
            "word_scores",
            "words_correct",
            "words_total",
            "stars_awarded",
            "stars_total",
            "message",
            "retry",
            "again",
            "skipped",
            "outcome",
            "assisted",
            "mastery_eligible",
            "reason_code",
        }
        assert required <= set(payload.keys())
        assert payload["result"] in {
            "correct",
            "close",
            "missed",
            "retry",
            "skipped",
        }
        assert payload["outcome"] in {
            "correct",
            "incorrect",
            "uncertain",
            "silence",
            "skipped",
        }
        assert isinstance(payload["assisted"], bool)
        assert isinstance(payload["mastery_eligible"], bool)
        assert isinstance(payload["reason_code"], str)
        if payload["outcome"] in ("uncertain", "silence", "skipped"):
            assert payload["mastery_eligible"] is False
        if payload["assisted"]:
            assert payload["mastery_eligible"] is False
        assert isinstance(payload["transcript"], str)
        assert isinstance(payload["word_scores"], list)
        assert isinstance(payload["words_correct"], int)
        assert isinstance(payload["words_total"], int)
        assert isinstance(payload["stars_awarded"], int)
        assert isinstance(payload["stars_total"], int)
        assert isinstance(payload["message"], str)
        assert isinstance(payload["retry"], bool)
        assert isinstance(payload["again"], bool)
        assert isinstance(payload["skipped"], bool)
        assert payload["retry"] == (payload["result"] == "retry")
        assert payload["skipped"] == (payload["result"] == "skipped")
        assert payload["stars_awarded"] >= 0
        if payload["result"] in ("retry", "skipped"):
            assert payload["word_scores"] == []
            assert payload["words_correct"] == 0
            assert payload["transcript"] == ""
            if words_total is not None:
                assert payload["words_total"] == words_total
        for ws in payload["word_scores"]:
            assert set(ws.keys()) >= {"word", "heard", "confidence", "result"}
            assert isinstance(ws["word"], str)
            assert isinstance(ws["heard"], str)
            assert ws["result"] in {"correct", "close", "missed"}

    return _assert


@pytest.fixture
def assert_error_envelope():
    def _assert(payload: dict, *, code: str | None = None) -> None:
        assert "error" in payload
        assert isinstance(payload["error"], dict)
        assert "code" in payload["error"]
        assert "message" in payload["error"]
        assert isinstance(payload["error"]["code"], str)
        assert isinstance(payload["error"]["message"], str)
        if code is not None:
            assert payload["error"]["code"] == code

    return _assert
