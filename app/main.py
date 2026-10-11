"""Reading Buddy FastAPI app — Milestone 1."""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import config
from app.audio_files import (
    AudioError,
    convert_to_wav,
    delete_quiet,
    ffmpeg_available,
    is_silence,
    new_temp_paths,
    write_bytes,
)
from app.db import connect, get_item, init_schema, load_settings, upsert_items_from_json
from app.matching import score_attempt
from app.session import SessionError, apply_attempt, complete_session, start_session
from app.whisper_engine import engine

logger = logging.getLogger(__name__)

_conn = None


def get_conn():
    global _conn
    if _conn is None:
        _conn = connect()
    return _conn


def reset_conn_for_tests(conn=None) -> None:
    """Test helper: replace or clear the process DB connection."""
    global _conn
    if _conn is not None and _conn is not conn:
        try:
            _conn.close()
        except Exception:  # noqa: BLE001
            pass
    _conn = conn


def error_body(code: str, message: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message}}


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.ensure_dirs()
    conn = get_conn()
    init_schema(conn)
    count = upsert_items_from_json(conn)
    load_settings()
    logger.info("Loaded %s items from content/items.json", count)
    try:
        engine.load()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Whisper load error: %s", exc)
    yield
    # Leave the process connection open for the worker lifetime.
    # Tests replace it via reset_conn_for_tests().


app = FastAPI(title="Reading Buddy", lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=400,
        content=error_body("bad_request", str(exc.errors())),
    )


@app.exception_handler(StarletteHTTPException)
async def http_handler(request: Request, exc: StarletteHTTPException):
    code = {
        400: "bad_request",
        404: "not_found",
        409: "session_closed",
        503: "unavailable",
    }.get(exc.status_code, "internal")
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(code, str(exc.detail)),
    )


@app.get("/api/health")
def health() -> dict[str, bool]:
    return {
        "whisper": bool(engine.ready),
        "ffmpeg": ffmpeg_available(),
        "offline": config.is_offline_configured(),
    }


@app.post("/api/sessions")
async def create_session(request: Request):
    level = None
    raw = await request.body()
    if raw and raw.strip() not in (b"", b"null"):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return JSONResponse(
                status_code=400,
                content=error_body("bad_request", "Invalid JSON body"),
            )
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            return JSONResponse(
                status_code=400,
                content=error_body("bad_request", "Body must be a JSON object"),
            )
        if "mode" in payload or "session_length" in payload:
            return JSONResponse(
                status_code=400,
                content=error_body(
                    "bad_request",
                    "Only optional field 'level' is accepted on session create",
                ),
            )
        if "level" in payload and payload["level"] is not None:
            try:
                level = int(payload["level"])
            except (TypeError, ValueError):
                return JSONResponse(
                    status_code=400,
                    content=error_body("bad_request", "level must be an integer"),
                )

    if not ffmpeg_available() or not engine.ready:
        return JSONResponse(
            status_code=503,
            content=error_body("unavailable", "Whisper or ffmpeg unavailable"),
        )

    conn = get_conn()
    try:
        return start_session(conn, level=level)
    except SessionError as exc:
        return JSONResponse(
            status_code=exc.status,
            content=error_body(exc.code, exc.message),
        )


@app.post("/api/sessions/{session_id}/attempts")
async def post_attempt(
    session_id: int,
    item_id: int = Form(...),
    phase: str = Form(...),
    audio: UploadFile = File(...),
):
    if phase != "read":
        return JSONResponse(
            status_code=400,
            content=error_body(
                "bad_request",
                "Milestone 1 only accepts phase=read",
            ),
        )

    conn = get_conn()
    settings = load_settings()
    keep_audio = bool(settings.get("keep_audio", False))

    if not ffmpeg_available() or not engine.ready:
        return JSONResponse(
            status_code=503,
            content=error_body("unavailable", "Whisper or ffmpeg unavailable"),
        )

    webm_path, wav_path = new_temp_paths(".webm")
    try:
        data = await audio.read()
        if data is None:
            data = b""
        write_bytes(webm_path, data)

        item = get_item(conn, item_id)
        if item is None:
            # Still validate session membership via apply_attempt path for planned ids
            pass

        if len(data) == 0:
            target = item["text"] if item else ""
            match = score_attempt(target, "", mode="beginner", force_retry=True)
            try:
                return apply_attempt(
                    conn, session_id, item_id, match, phase=phase, is_silence_path=True
                )
            except SessionError as exc:
                return JSONResponse(
                    status_code=exc.status,
                    content=error_body(exc.code, exc.message),
                )

        try:
            convert_to_wav(webm_path, wav_path)
        except AudioError as exc:
            return JSONResponse(
                status_code=503,
                content=error_body("unavailable", exc.message),
            )

        item = get_item(conn, item_id)
        if item is None:
            return JSONResponse(
                status_code=404,
                content=error_body("not_found", "Unknown item"),
            )

        if is_silence(wav_path):
            match = score_attempt(item["text"], "", mode="beginner", force_retry=True)
            try:
                return apply_attempt(
                    conn, session_id, item_id, match, phase=phase, is_silence_path=True
                )
            except SessionError as exc:
                return JSONResponse(
                    status_code=exc.status,
                    content=error_body(exc.code, exc.message),
                )

        try:
            transcript = engine.transcribe(wav_path, initial_prompt=item["text"])
        except Exception as exc:  # noqa: BLE001
            logger.exception("Whisper failed")
            return JSONResponse(
                status_code=503,
                content=error_body("unavailable", f"Whisper failed: {exc}"),
            )

        if (
            transcript.no_speech_prob >= config.NO_SPEECH_PROB_MAX
            or not (transcript.transcript or "").strip()
        ):
            match = score_attempt(item["text"], "", mode="beginner", force_retry=True)
            try:
                return apply_attempt(
                    conn, session_id, item_id, match, phase=phase, is_silence_path=True
                )
            except SessionError as exc:
                return JSONResponse(
                    status_code=exc.status,
                    content=error_body(exc.code, exc.message),
                )

        confidences = [w.probability for w in transcript.words]
        match = score_attempt(
            item["text"],
            transcript.transcript,
            confidences if confidences else None,
            mode="beginner",
        )
        if match.result == "retry":
            try:
                return apply_attempt(
                    conn, session_id, item_id, match, phase=phase, is_silence_path=True
                )
            except SessionError as exc:
                return JSONResponse(
                    status_code=exc.status,
                    content=error_body(exc.code, exc.message),
                )

        try:
            return apply_attempt(conn, session_id, item_id, match, phase=phase)
        except SessionError as exc:
            return JSONResponse(
                status_code=exc.status,
                content=error_body(exc.code, exc.message),
            )
    finally:
        if not keep_audio:
            delete_quiet(webm_path, wav_path)
        else:
            # M4 keep path not implemented; still delete temps in M1
            delete_quiet(webm_path, wav_path)


@app.post("/api/sessions/{session_id}/complete")
async def post_complete(session_id: int):
    conn = get_conn()
    try:
        return complete_session(conn, session_id)
    except SessionError as exc:
        return JSONResponse(
            status_code=exc.status,
            content=error_body(exc.code, exc.message),
        )


@app.get("/")
def index():
    return FileResponse(config.STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")
