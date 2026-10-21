"""Reading Buddy FastAPI app — Milestones 1–4."""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import config
from app.audio_files import (
    AudioError,
    convert_to_wav,
    delete_quiet,
    ffmpeg_available,
    generated_audio_ready,
    is_silence,
    load_or_build_timings,
    new_temp_paths,
    resolve_audio_slug,
    wav_duration_and_rms,
    write_bytes,
)
from app.db import connect, init_schema, load_settings, upsert_items_from_json
from app.events import pattern_accuracy_by_day
from app.matching import hypothesis_from_whisper_words, score_attempt
from app.parent import (
    accuracy_by_day,
    apply_settings_update,
    export_zip_bytes,
    keep_attempt_wav,
    list_kept_clips,
    mastered_lists,
    pattern_heatmap,
    sound_heatmap,
    tricky_words,
)
from app.session import (
    SessionError,
    apply_attempt,
    apply_passage,
    complete_session,
    open_session_view,
    passage_target_text,
    start_session,
    validate_attempt_access,
)
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
        # Keep the decode path warm so the first kid take is not cold-start slow.
        if engine.ready:
            warm = config.TEMP_DIR / "warmup-silence.wav"
            try:
                if not warm.is_file():
                    import wave

                    config.TEMP_DIR.mkdir(parents=True, exist_ok=True)
                    with wave.open(str(warm), "wb") as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(16000)
                        wf.writeframes(b"\x00\x00" * 1600)
                engine.transcribe(warm, initial_prompt="")
            except Exception as warm_exc:  # noqa: BLE001
                logger.debug("Whisper warm path skipped: %s", warm_exc)
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
    # Bare Starlette 409s are treated as session_closed; SessionError paths
    # set their own codes (session_closed vs already_resolved).
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


@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content=error_body("internal", "Unexpected server error"),
    )


@app.get("/api/health")
def health() -> dict[str, bool]:
    # Additive `audio` flag (M2): all content slugs have human or generated wav.
    audio_ok = False
    try:
        conn = get_conn()
        slugs = [r["slug"] for r in conn.execute("SELECT slug FROM items").fetchall()]
        audio_ok = bool(slugs) and generated_audio_ready(slugs)
    except Exception:  # noqa: BLE001
        audio_ok = False
    return {
        "whisper": bool(engine.ready),
        "ffmpeg": ffmpeg_available(),
        "offline": config.is_offline_configured(),
        "audio": audio_ok,
    }


@app.get("/api/warmup")
def warmup() -> dict[str, Any]:
    """Touch Whisper so the next score is not a cold load."""
    ok = False
    try:
        if not engine.ready:
            engine.load()
        warm = config.TEMP_DIR / "warmup-silence.wav"
        if engine.ready and warm.is_file():
            engine.transcribe(warm, initial_prompt="")
            ok = True
        elif engine.ready:
            ok = True
    except Exception as exc:  # noqa: BLE001
        logger.debug("warmup failed: %s", exc)
    return {"ok": ok, "whisper": bool(engine.ready)}


@app.get("/api/sessions/open")
def get_open_session():
    return open_session_view(get_conn())


@app.post("/api/sessions")
async def create_session(request: Request):
    level = None
    stage = None
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
                    "Only optional fields 'level' and 'stage' are accepted on session create",
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
        if "stage" in payload and payload["stage"] is not None:
            try:
                stage = int(payload["stage"])
            except (TypeError, ValueError):
                return JSONResponse(
                    status_code=400,
                    content=error_body("bad_request", "stage must be an integer"),
                )

    if not ffmpeg_available() or not engine.ready:
        return JSONResponse(
            status_code=503,
            content=error_body("unavailable", "Whisper or ffmpeg unavailable"),
        )

    conn = get_conn()
    try:
        return start_session(conn, level=level, stage=stage)
    except SessionError as exc:
        return JSONResponse(
            status_code=exc.status,
            content=error_body(exc.code, exc.message),
        )


def _score_target_text(
    item_text: str, *, phase: str, replay_word: str
) -> str:
    if phase == "replay":
        return (replay_word or "").strip() or item_text
    return item_text


def _finalize_attempt(
    payload: dict[str, Any],
    *,
    keep_audio: bool,
    wav_path,
) -> dict[str, Any]:
    if keep_audio and payload.get("attempt_id") is not None:
        keep_attempt_wav(int(payload["attempt_id"]), wav_path)
    return payload


async def _post_passage(session_id: int, audio: UploadFile, mode: str):
    """One fluent read of a poem or story. Duration stays off this response."""
    conn = get_conn()
    try:
        target_text = passage_target_text(conn, session_id)
    except SessionError as exc:
        return JSONResponse(
            status_code=exc.status,
            content=error_body(exc.code, exc.message),
        )
    webm_path, wav_path = new_temp_paths(".webm")
    try:
        data = await audio.read()
        if data is None:
            data = b""
        write_bytes(webm_path, data)
        duration = None
        if len(data) == 0:
            match = score_attempt(target_text, "", mode=mode, force_retry=True)
        else:
            try:
                convert_to_wav(webm_path, wav_path)
            except AudioError as exc:
                return JSONResponse(
                    status_code=503,
                    content=error_body("unavailable", exc.message),
                )
            try:
                duration, _rms = wav_duration_and_rms(wav_path)
            except Exception:  # noqa: BLE001
                duration = None
            if is_silence(wav_path):
                match = score_attempt(target_text, "", mode=mode, force_retry=True)
            else:
                try:
                    transcript = engine.transcribe(wav_path, initial_prompt=target_text)
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
                    match = score_attempt(target_text, "", mode=mode, force_retry=True)
                else:
                    heard_text, confidences = hypothesis_from_whisper_words(
                        transcript.words
                    )
                    if not heard_text:
                        heard_text = transcript.transcript
                        confidences = []
                    match = score_attempt(
                        target_text,
                        heard_text,
                        confidences if confidences else None,
                        mode=mode,
                    )
        try:
            payload = apply_passage(
                conn, session_id, match, duration_seconds=duration
            )
        except SessionError as exc:
            return JSONResponse(
                status_code=exc.status,
                content=error_body(exc.code, exc.message),
            )
        payload.pop("duration_seconds", None)
        return payload
    finally:
        delete_quiet(webm_path, wav_path)


@app.post("/api/sessions/{session_id}/attempts")
async def post_attempt(
    session_id: int,
    item_id: int = Form(...),
    phase: str = Form(...),
    audio: UploadFile = File(...),
    queue_index: int | None = Form(None),
    word: str = Form(""),
    client_latency_ms: int | None = Form(None),
):
    if phase not in ("read", "replay", "passage"):
        return JSONResponse(
            status_code=400,
            content=error_body(
                "bad_request",
                "phase must be read, replay, or passage",
            ),
        )

    conn = get_conn()
    settings = load_settings()
    keep_audio = bool(settings.get("keep_audio", False))
    # Prefer the session's mode (frozen at start) over live settings.
    session_row = conn.execute(
        "SELECT mode FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    mode = (
        str(session_row["mode"])
        if session_row
        else str(settings.get("mode", "beginner"))
    ).lower()
    if mode not in ("beginner", "strict"):
        mode = "beginner"
    replay_word = (word or "").strip()
    import time as _time

    score_started = _time.perf_counter()
    latency_ms = None
    if client_latency_ms is not None:
        try:
            latency_ms = max(0, min(120_000, int(client_latency_ms)))
        except (TypeError, ValueError):
            latency_ms = None

    if not ffmpeg_available() or not engine.ready:
        return JSONResponse(
            status_code=503,
            content=error_body("unavailable", "Whisper or ffmpeg unavailable"),
        )

    if phase == "passage":
        return await _post_passage(session_id, audio, mode)

    # Queue / session / resolved-slot checks before ffmpeg or Whisper.
    try:
        item = validate_attempt_access(
            conn,
            session_id,
            item_id,
            phase=phase,
            queue_index=queue_index,
            replay_word=replay_word,
        )
    except SessionError as exc:
        return JSONResponse(
            status_code=exc.status,
            content=error_body(exc.code, exc.message),
        )

    target_text = _score_target_text(
        item["text"], phase=phase, replay_word=replay_word
    )

    def _apply(match, *, silence: bool = False):
        # Prefer client stop→response when present; else server score-path time.
        used_latency = latency_ms
        if used_latency is None:
            used_latency = int((_time.perf_counter() - score_started) * 1000)
        return apply_attempt(
            conn,
            session_id,
            item_id,
            match,
            phase=phase,
            is_silence_path=silence,
            queue_index=queue_index,
            replay_word=replay_word,
            latency_ms=used_latency,
        )

    webm_path, wav_path = new_temp_paths(".webm")
    try:
        data = await audio.read()
        if data is None:
            data = b""
        write_bytes(webm_path, data)

        if len(data) == 0:
            match = score_attempt(target_text, "", mode=mode, force_retry=True)
            try:
                payload = _apply(match, silence=True)
            except SessionError as exc:
                return JSONResponse(
                    status_code=exc.status,
                    content=error_body(exc.code, exc.message),
                )
            return _finalize_attempt(
                payload, keep_audio=keep_audio, wav_path=wav_path
            )

        try:
            convert_to_wav(webm_path, wav_path)
        except AudioError as exc:
            return JSONResponse(
                status_code=503,
                content=error_body("unavailable", exc.message),
            )

        if is_silence(wav_path):
            match = score_attempt(target_text, "", mode=mode, force_retry=True)
            try:
                payload = _apply(match, silence=True)
            except SessionError as exc:
                return JSONResponse(
                    status_code=exc.status,
                    content=error_body(exc.code, exc.message),
                )
            return _finalize_attempt(
                payload, keep_audio=keep_audio, wav_path=wav_path
            )

        try:
            transcript = engine.transcribe(wav_path, initial_prompt=target_text)
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
            match = score_attempt(target_text, "", mode=mode, force_retry=True)
            try:
                payload = _apply(match, silence=True)
            except SessionError as exc:
                return JSONResponse(
                    status_code=exc.status,
                    content=error_body(exc.code, exc.message),
                )
            return _finalize_attempt(
                payload, keep_audio=keep_audio, wav_path=wav_path
            )

        heard_text, confidences = hypothesis_from_whisper_words(transcript.words)
        if not heard_text:
            heard_text = transcript.transcript
            confidences = []
        match = score_attempt(
            target_text,
            heard_text,
            confidences if confidences else None,
            mode=mode,
        )
        if match.result == "retry":
            try:
                payload = _apply(match, silence=True)
            except SessionError as exc:
                return JSONResponse(
                    status_code=exc.status,
                    content=error_body(exc.code, exc.message),
                )
            return _finalize_attempt(
                payload, keep_audio=keep_audio, wav_path=wav_path
            )

        try:
            payload = _apply(match)
        except SessionError as exc:
            return JSONResponse(
                status_code=exc.status,
                content=error_body(exc.code, exc.message),
            )
        return _finalize_attempt(
            payload, keep_audio=keep_audio, wav_path=wav_path
        )
    finally:
        # Temps always deleted; keep_audio copies to data/kept/ first when on.
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


@app.get("/api/parent/settings")
def get_parent_settings():
    from app.parent import play_summary, tomorrow_note

    from app.adaptive import set_progress

    settings = load_settings()
    conn = get_conn()
    settings["play"] = play_summary(settings)
    settings["tomorrow"] = tomorrow_note(conn, settings)
    settings["set_progress"] = set_progress(conn)
    return settings


@app.put("/api/parent/settings")
async def put_parent_settings(request: Request):
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        return JSONResponse(
            status_code=400,
            content=error_body("bad_request", "Invalid JSON body"),
        )
    if not isinstance(payload, dict):
        return JSONResponse(
            status_code=400,
            content=error_body("bad_request", "Body must be a JSON object"),
        )
    try:
        return apply_settings_update(payload)
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content=error_body("bad_request", str(exc)),
        )


@app.get("/api/parent/accuracy")
def parent_accuracy():
    return accuracy_by_day(get_conn())


@app.get("/api/parent/mastered")
def parent_mastered():
    return mastered_lists(get_conn())


@app.get("/api/parent/tricky")
def parent_tricky():
    return tricky_words(get_conn())


@app.get("/api/parent/sounds")
def parent_sounds():
    return sound_heatmap(get_conn())


@app.get("/api/parent/patterns")
def parent_patterns():
    from app.adaptive import current_unlocked_patterns

    conn = get_conn()
    return {
        "heatmap": pattern_heatmap(conn),
        "by_day": pattern_accuracy_by_day(conn),
        "unlocked": current_unlocked_patterns(conn),
    }


@app.post("/api/parent/voice/{slug}")
async def parent_voice_upload(slug: str, audio: UploadFile = File(...)):
    """Save a parent recording as audio/human/{slug}.wav (overrides TTS)."""
    if not slug or "/" in slug or "\\" in slug or ".." in slug:
        return JSONResponse(
            status_code=400,
            content=error_body("bad_request", "Invalid slug"),
        )
    conn = get_conn()
    row = conn.execute(
        "SELECT slug, text FROM items WHERE slug = ?", (slug,)
    ).fetchone()
    if row is None:
        return JSONResponse(
            status_code=404,
            content=error_body("not_found", f"Unknown slug '{slug}'"),
        )
    if not ffmpeg_available():
        return JSONResponse(
            status_code=503,
            content=error_body("unavailable", "ffmpeg unavailable"),
        )
    webm_path, wav_path = new_temp_paths(".webm")
    try:
        data = await audio.read()
        if not data:
            return JSONResponse(
                status_code=400,
                content=error_body("bad_request", "Empty audio"),
            )
        write_bytes(webm_path, data)
        try:
            convert_to_wav(webm_path, wav_path)
        except AudioError as exc:
            return JSONResponse(
                status_code=503,
                content=error_body("unavailable", exc.message),
            )
        if is_silence(wav_path):
            return JSONResponse(
                status_code=400,
                content=error_body("bad_request", "Recording was silent"),
            )
        config.AUDIO_HUMAN.mkdir(parents=True, exist_ok=True)
        dest = config.AUDIO_HUMAN / f"{slug}.wav"
        dest.write_bytes(wav_path.read_bytes())
        # Rebuild timings from the human clip length (invalidate TTS cache).
        load_or_build_timings(slug, str(row["text"]), force=True)
        return {"ok": True, "slug": slug, "path": f"audio/human/{slug}.wav"}
    finally:
        delete_quiet(webm_path, wav_path)


@app.get("/api/parent/kept")
def parent_kept_list():
    return list_kept_clips(get_conn())


@app.get("/api/parent/kept/{attempt_id}")
def parent_kept_clip(attempt_id: int):
    path = config.KEPT_DIR / f"{attempt_id}.wav"
    if not path.is_file():
        return JSONResponse(
            status_code=404,
            content=error_body("not_found", f"No kept audio for attempt {attempt_id}"),
        )
    return FileResponse(path, media_type="audio/wav", filename=f"{attempt_id}.wav")


@app.get("/api/parent/export")
def parent_export():
    data = export_zip_bytes(get_conn())
    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="reading-buddy.zip"',
        },
    )


@app.get("/api/audio/{slug}")
def get_audio(slug: str):
    path = resolve_audio_slug(slug)
    if path is None:
        return JSONResponse(
            status_code=404,
            content=error_body("not_found", f"No audio for slug '{slug}'"),
        )
    return FileResponse(path, media_type="audio/wav", filename=f"{slug}.wav")


@app.get("/api/audio/{slug}/timings")
def get_audio_timings(slug: str):
    """Word timings for read-along highlight during listen playback."""
    conn = get_conn()
    row = conn.execute(
        "SELECT slug, text FROM items WHERE slug = ?", (slug,)
    ).fetchone()
    if row is None:
        return JSONResponse(
            status_code=404,
            content=error_body("not_found", f"No item for slug '{slug}'"),
        )
    if resolve_audio_slug(slug) is None:
        return JSONResponse(
            status_code=404,
            content=error_body("not_found", f"No audio for slug '{slug}'"),
        )
    words = load_or_build_timings(slug, str(row["text"]))
    return {"slug": slug, "words": words}


@app.get("/")
def index():
    return FileResponse(config.STATIC_DIR / "index.html")


@app.get("/parent")
def parent_page():
    return FileResponse(config.STATIC_DIR / "parent.html")


app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")
