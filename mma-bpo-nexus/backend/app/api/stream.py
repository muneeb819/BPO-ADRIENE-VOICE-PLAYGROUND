"""Authenticated browser ↔ Deepgram Flux PCM16 WebSocket proxy."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from urllib.parse import urlsplit

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .auth import COOKIE_NAME
from ..providers import VoiceProviderError
from ..repositories import ConflictError, NotFoundError

logger = logging.getLogger("mma-bpo-nexus.flux")
router = APIRouter(tags=["Flux streaming"])

ALLOWED_EVENTS = {
    "event", "transcript", "turn_index", "end_of_turn_confidence",
    "is_final", "type", "channel_index", "duration",
}


@router.websocket("/api/v1/voice/stream")
async def flux_stream(websocket: WebSocket, sessionId: str):
    origin = websocket.headers.get("origin")
    if origin and urlsplit(origin).netloc != websocket.headers.get("host", ""):
        await websocket.close(code=1008, reason="Origin mismatch")
        return
    auth_session = websocket.app.state.auth.get_session(websocket.cookies.get(COOKIE_NAME))
    if not auth_session or auth_session["user"]["role"] != "admin":
        await websocket.close(code=1008, reason="Administrator access required")
        return
    repository = websocket.app.state.repository
    try:
        session = repository.get_session(sessionId)
    except NotFoundError:
        await websocket.close(code=1008, reason="Session not found")
        return
    if session["status"] != "active" or session["policy"]["sttProvider"] != "deepgram-flux":
        await websocket.close(code=1008, reason="Session is not configured for Flux streaming")
        return
    provider = websocket.app.state.flux_provider
    if provider is None:
        await websocket.close(code=1011, reason="Deepgram is not configured")
        return

    await websocket.accept()
    started = time.monotonic()
    completed_turns: set[str] = set()
    tasks = []

    async def browser_to_provider(connection):
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return
            if message.get("bytes") is not None:
                audio = message["bytes"]
                if len(audio) > 64_000:
                    raise ConflictError("PCM chunk is too large")
                await connection.send_audio(audio)
            elif message.get("text") is not None:
                try:
                    control = json.loads(message["text"])
                except ValueError:
                    await websocket.send_json({"event": "error", "error": "Invalid stream control message"})
                    continue
                if control.get("type") == "close":
                    return

    async def provider_to_browser(connection):
        while True:
            raw = await connection.receive()
            try:
                payload = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(payload, dict):
                continue
            filtered = {key: payload[key] for key in ALLOWED_EVENTS if key in payload}
            filtered["source"] = "deepgram-flux"
            await websocket.send_json(filtered)
            transcript = str(filtered.get("transcript") or "").strip()
            if filtered.get("event") == "EndOfTurn" and transcript:
                marker = str(filtered.get("turn_index") or transcript[:80])
                if marker not in completed_turns:
                    completed_turns.add(marker)
                    elapsed = round((time.monotonic() - started) * 1000, 3)
                    repository.record_voice_request(
                        sessionId, "stt", "deepgram-flux", "server", "success",
                        elapsed, f"Flux EndOfTurn {marker} transcription completed",
                    )

    try:
        async with provider.connect() as connection:
            tasks = [
                asyncio.create_task(browser_to_provider(connection)),
                asyncio.create_task(provider_to_browser(connection)),
            ]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            for task in done:
                exception = task.exception()
                if exception:
                    raise exception
    except WebSocketDisconnect:
        pass
    except (VoiceProviderError, ConflictError) as exc:
        message = exc.message if isinstance(exc, VoiceProviderError) else str(exc)
        try:
            await websocket.send_json({"event": "error", "error": message})
        except Exception:
            pass
    except Exception:
        logger.exception("Flux stream failed")
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        try:
            await websocket.close()
        except Exception:
            pass
