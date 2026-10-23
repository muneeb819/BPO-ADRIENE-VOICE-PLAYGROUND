"""MMA BPO NEXUS application factory and request security boundary."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
import hmac
import logging
import os
from pathlib import Path
import secrets
import time
import uuid
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api.auth import COOKIE_NAME
from .api.auth import router as auth_router
from .api.routes import router
from .api.stream import router as stream_router
from .api.livekit import router as livekit_router
from .config import APP_NAME, DATABASE_PATH, FRONTEND_DIR, MAX_AUDIO_BYTES, MAX_REQUEST_BYTES, STAGE
from .db import Database
from .providers import VoiceProviderError, build_flux_provider, build_livekit_service, build_voice_provider
from .repositories import AuthRepository, ConflictError, NexusRepository, NotFoundError

logger = logging.getLogger("mma-bpo-nexus")

PUBLIC_API_PATHS = {
    "/api/v1",
    "/api/v1/health",
    "/api/v1/auth/status",
    "/api/v1/auth/setup",
    "/api/v1/auth/login",
}
MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def create_app(
    db_path: str | Path | None = None,
    voice_provider=None,
    flux_provider=None,
    livekit_service=None,
    preview_bypass: bool = False,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async def retention_worker():
            while True:
                try:
                    deleted = app.state.repository.cleanup_expired()
                    if deleted:
                        logger.info("Retention removed %s expired sessions", deleted)
                except Exception:
                    logger.exception("Retention cleanup failed")
                await asyncio.sleep(3600)

        task = asyncio.create_task(retention_worker())
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    app = FastAPI(
        title=APP_NAME,
        version=__version__,
        description=f"Stage {STAGE} deterministic, auditable BPO intake and voice foundation.",
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    database = Database(db_path or DATABASE_PATH)
    app.state.repository = NexusRepository(database)
    app.state.auth = AuthRepository(database)
    app.state.voice_provider = voice_provider if voice_provider is not None else build_voice_provider()
    app.state.flux_provider = flux_provider if flux_provider is not None else build_flux_provider()
    app.state.livekit = livekit_service if livekit_service is not None else build_livekit_service()
    app.state.preview_auth = None
    if preview_bypass or os.environ.get("NEXUS_PREVIEW_BYPASS", "").lower() == "true":
        app.state.preview_auth = {
            "user": {
                "id": None,
                "username": "preview-admin",
                "displayName": "Preview Administrator",
                "role": "admin",
                "active": True,
                "createdAt": None,
                "lastLoginAt": None,
            },
            "csrfToken": secrets.token_urlsafe(24),
            "expiresAt": None,
            "previewBypass": True,
        }
    auth_attempts: dict[str, list[float]] = {}

    @app.middleware("http")
    async def request_guard(request: Request, call_next):
        incoming_id = request.headers.get("x-request-id", "")
        request.state.request_id = incoming_id if incoming_id and len(incoming_id) <= 64 else uuid.uuid4().hex
        path = request.url.path
        mutating = request.method in MUTATING_METHODS
        if path.startswith("/api/") and mutating:
            if request.headers.get("sec-fetch-site", "").lower() == "cross-site":
                return JSONResponse(status_code=403, content={"error": "Cross-site writes are not allowed"})
            origin = request.headers.get("origin")
            if origin and urlsplit(origin).netloc != request.headers.get("host", ""):
                return JSONResponse(status_code=403, content={"error": "Origin does not match this application"})
            raw_length = request.headers.get("content-length")
            try:
                length = int(raw_length or 0)
            except ValueError:
                return JSONResponse(status_code=400, content={"error": "Invalid Content-Length"})
            is_audio_upload = path == "/api/v1/voice/stt"
            if length > (MAX_AUDIO_BYTES if is_audio_upload else MAX_REQUEST_BYTES):
                return JSONResponse(status_code=413, content={"error": "Request body is too large"})
            content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
            if length and not is_audio_upload and content_type != "application/json":
                return JSONResponse(status_code=415, content={"error": "JSON content is required"})
            if length and is_audio_upload and not content_type.startswith("audio/"):
                return JSONResponse(status_code=415, content={"error": "Audio content is required"})

        if path in {"/api/v1/auth/login", "/api/v1/auth/setup"}:
            ip = request.client.host if request.client else "unknown"
            now = time.monotonic()
            attempts = [stamp for stamp in auth_attempts.get(ip, []) if now - stamp < 300]
            if len(attempts) >= 12:
                return JSONResponse(status_code=429, content={"error": "Too many authentication attempts"})
            attempts.append(now)
            auth_attempts[ip] = attempts

        if path.startswith("/api/v1/") and path not in PUBLIC_API_PATHS:
            auth_session = app.state.preview_auth or app.state.auth.get_session(request.cookies.get(COOKIE_NAME))
            if not auth_session:
                return JSONResponse(status_code=401, content={"error": "Authentication is required"})
            request.state.auth_session = auth_session
            request.state.user = auth_session["user"]
            if mutating:
                csrf = request.headers.get("x-csrf-token", "")
                if not csrf or not hmac.compare_digest(csrf, auth_session["csrfToken"]):
                    return JSONResponse(status_code=403, content={"error": "CSRF validation failed"})
                if path != "/api/v1/auth/logout" and auth_session["user"]["role"] != "admin":
                    return JSONResponse(status_code=403, content={"error": "Read-only access cannot modify data"})

        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "microphone=(self), camera=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "font-src 'self'; connect-src 'self'; media-src 'self' blob:; object-src 'none'; base-uri 'self'; "
            "frame-ancestors 'none'; form-action 'self'"
        )
        if path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(VoiceProviderError)
    async def provider_error(_, exc: VoiceProviderError):
        return JSONResponse(status_code=exc.status_code, content={"error": exc.message})

    @app.exception_handler(NotFoundError)
    async def not_found(_, exc: NotFoundError):
        return JSONResponse(status_code=404, content={"error": str(exc)})

    @app.exception_handler(ConflictError)
    async def conflict(_, exc: ConflictError):
        return JSONResponse(status_code=409, content={"error": str(exc)})

    @app.exception_handler(RequestValidationError)
    async def validation_error(_, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={"error": "Request validation failed", "details": jsonable_encoder(exc.errors())},
        )

    @app.exception_handler(HTTPException)
    async def http_error(_, exc: HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})

    @app.exception_handler(Exception)
    async def unhandled_error(request: Request, exc: Exception):
        logger.exception("%s Unhandled request error: %s", getattr(request.state, "request_id", "unknown"), exc)
        return JSONResponse(status_code=500, content={"error": "Internal server error"})

    app.include_router(auth_router)
    app.include_router(router)
    app.include_router(stream_router)
    app.include_router(livekit_router)
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
    return app
