"""Versioned HTTP routes for deterministic intake and voice."""

import json

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse

from ..config import MAX_AUDIO_BYTES
from ..providers import (
    PERSONA_PRESETS, STT_MODELS, TONES, TTS_VOICE_IDS, TTS_VOICES, VoiceProviderError,
)
from ..repositories import ConflictError
from ..schemas import AgentUpdate, BrowserVoiceMetric, SessionCreate, SynthesizeRequest, TurnCreate, VoicePreviewRequest


router = APIRouter(prefix="/api/v1", tags=["MMA BPO NEXUS"])


def audit(request: Request, action: str, entity_type: str, entity_id: str | None, detail: dict) -> None:
    detail = {**detail, "requestId": getattr(request.state, "request_id", "")}
    request.app.state.auth.audit(
        request.state.user["id"], action, entity_type, entity_id, detail,
        request.client.host if request.client else "unknown",
    )


@router.get("")
def api_root() -> dict:
    return {
        "service": "MMA BPO NEXUS",
        "stage": 4,
        "mode": "secure-conversation-voice-and-livekit",
        "health": "/api/v1/health",
    }


@router.get("/health")
def health(request: Request) -> dict:
    data = request.app.state.repository.health()
    data["voice"] = {
        "deepgramConfigured": request.app.state.voice_provider is not None,
        "audioStored": False,
        "sttModels": ["nova-2", "nova-3", "flux-general-en"],
        "ttsVoices": sorted(TTS_VOICE_IDS),
    }
    return data


@router.get("/agent")
def current_agent(request: Request) -> dict:
    return request.app.state.repository.get_agent()


@router.put("/agent/{agent_id}")
def update_agent(agent_id: str, payload: AgentUpdate, request: Request) -> dict:
    result = request.app.state.repository.update_agent(agent_id, payload.model_dump())
    audit(request, "agent_version_created", "agent", agent_id, {"version": result["version"]})
    return result


@router.get("/agent/{agent_id}/versions")
def agent_versions(agent_id: str, request: Request) -> list[dict]:
    return request.app.state.repository.list_agent_versions(agent_id)


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
def create_session(payload: SessionCreate, request: Request) -> dict:
    result = request.app.state.repository.create_session(payload.agentId)
    audit(request, "session_created", "session", result["id"], {"agentVersion": result["agentVersion"]})
    return result


@router.get("/sessions")
def sessions(request: Request, limit: int = Query(default=25, ge=1, le=100)) -> list[dict]:
    return request.app.state.repository.list_sessions(limit)


@router.get("/sessions/{session_id}")
def session_detail(session_id: str, request: Request) -> dict:
    return request.app.state.repository.get_session(session_id)


@router.get("/sessions/{session_id}/export")
def export_session(session_id: str, request: Request) -> Response:
    session = request.app.state.repository.get_session(session_id)
    audit(request, "session_exported", "session", session_id, {})
    return Response(
        content=json.dumps(session, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="mma-nexus-{session_id}.json"'},
    )


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str, request: Request) -> dict:
    request.app.state.repository.delete_session(session_id)
    audit(request, "session_deleted", "session", session_id, {})
    return {"ok": True, "deleted": session_id}


@router.post("/sessions/{session_id}/turns")
def add_turn(session_id: str, payload: TurnCreate, request: Request) -> dict:
    return request.app.state.repository.add_turn(
        session_id, payload.content, payload.inputMethod, payload.sttLatencyMs
    )


@router.post("/sessions/{session_id}/end")
def end_session(session_id: str, request: Request) -> dict:
    result = request.app.state.repository.end_session(session_id)
    audit(request, "session_ended", "session", session_id, {})
    return result


@router.get("/voice/status")
def voice_status(request: Request) -> dict:
    agent = request.app.state.repository.get_agent()
    configured = request.app.state.voice_provider is not None
    return {
        "deepgramConfigured": configured,
        "fluxConfigured": request.app.state.flux_provider is not None,
        "sttProvider": agent["sttProvider"],
        "sttModel": agent["sttModel"],
        "ttsProvider": agent["ttsProvider"],
        "ttsVoice": agent["ttsVoice"],
        "personaPreset": agent["personaPreset"],
        "purpose": agent["purpose"],
        "tone": agent["tone"],
        "audioStored": False,
        "disclosure": (
            "Microphone audio is handled by the selected browser or Deepgram provider. "
            "Browser speech services may process audio externally. Audio is never written to SQLite."
        ),
    }


@router.get("/voice/catalog")
def voice_catalog(request: Request) -> dict:
    return {
        "source": "curated-deepgram-catalogue",
        "accountVerified": False,
        "verification": "Account/model availability is verified only by an actual preview or session request.",
        "deepgramConfigured": request.app.state.voice_provider is not None,
        "fluxConfigured": request.app.state.flux_provider is not None,
        "sttModels": STT_MODELS,
        "ttsVoices": TTS_VOICES,
        "personaPresets": PERSONA_PRESETS,
        "tones": TONES,
    }


@router.post("/voice/preview")
async def preview_voice(payload: VoicePreviewRequest, request: Request):
    provider = request.app.state.voice_provider
    if provider is None:
        return JSONResponse(status_code=503, content={
            "error": "Deepgram is not configured. Voice preview requires a server-side key.",
            "fallback": "no-equivalent-browser-voice",
        })
    try:
        result = await provider.synthesize(payload.text, payload.voice)
    except VoiceProviderError as exc:
        request.app.state.repository.record_voice_request(
            None, "tts", "deepgram", "server", "error", exc.latency_ms,
            f"Voice preview failed for {payload.voice}: {exc.message}",
        )
        raise
    request_id = request.app.state.repository.record_voice_request(
        None, "tts", "deepgram", "server", "success", result.latency_ms,
        f"Voice preview completed for {result.voice}",
    )
    return Response(
        content=result.audio,
        media_type=result.content_type,
        headers={
            "Cache-Control": "no-store",
            "X-Voice-Request-Id": request_id,
            "X-TTS-Provider": result.provider,
            "X-TTS-Voice": result.voice,
            "X-TTS-Latency-Ms": str(result.latency_ms),
        },
    )


@router.post("/voice/stt")
async def transcribe(request: Request, sessionId: str = Query(min_length=1, max_length=80)):
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    allowed = {"audio/webm", "audio/ogg", "audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp4"}
    if content_type not in allowed:
        raise HTTPException(status_code=415, detail="Unsupported audio content type")
    audio = await request.body()
    if len(audio) < 200:
        raise HTTPException(status_code=400, detail="Audio clip is too short")
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Audio clip exceeds 8 MB")

    repository = request.app.state.repository
    session = repository.get_session(sessionId)
    if session["status"] != "active":
        raise ConflictError("Only active sessions accept audio")
    if session["policy"]["sttProvider"] != "deepgram":
        raise ConflictError("This session is bound to browser STT")
    provider = request.app.state.voice_provider
    if provider is None:
        return JSONResponse(status_code=503, content={
            "error": "Deepgram is not configured. Add DEEPGRAM_API_KEY or use browser STT.",
            "fallback": "text-input",
        })
    try:
        result = await provider.transcribe(audio, content_type, session["policy"]["sttModel"])
    except VoiceProviderError as exc:
        repository.record_voice_request(
            sessionId, "stt", "deepgram", "server", "error", exc.latency_ms, exc.message
        )
        return JSONResponse(status_code=exc.status_code, content={
            "error": exc.message, "fallback": "text-input",
        })
    request_id = repository.record_voice_request(
        sessionId, "stt", "deepgram", "server", "success", result.latency_ms,
        f"{result.model} transcription completed",
    )
    return {
        "requestId": request_id,
        "transcript": result.text,
        "provider": result.provider,
        "model": result.model,
        "latencyMs": result.latency_ms,
        "audioStored": False,
    }


@router.post("/voice/tts")
async def synthesize(payload: SynthesizeRequest, request: Request, sessionId: str = Query(min_length=1, max_length=80)):
    repository = request.app.state.repository
    session = repository.get_session(sessionId)
    if session["policy"]["ttsProvider"] != "deepgram":
        raise ConflictError("This session is bound to browser TTS")
    provider = request.app.state.voice_provider
    if provider is None:
        return JSONResponse(status_code=503, content={
            "error": "Deepgram is not configured. Browser TTS fallback is available.",
            "fallback": "browser-tts",
        })
    try:
        result = await provider.synthesize(payload.text, session["policy"]["ttsVoice"])
    except VoiceProviderError as exc:
        repository.record_voice_request(
            sessionId, "tts", "deepgram", "server", "error", exc.latency_ms, exc.message
        )
        return JSONResponse(status_code=exc.status_code, content={
            "error": exc.message, "fallback": "browser-tts",
        })
    request_id = repository.record_voice_request(
        sessionId, "tts", "deepgram", "server", "success", result.latency_ms,
        f"{result.voice} synthesis completed",
    )
    return Response(
        content=result.audio,
        media_type=result.content_type,
        headers={
            "Cache-Control": "no-store",
            "X-Voice-Request-Id": request_id,
            "X-TTS-Provider": result.provider,
            "X-TTS-Latency-Ms": str(result.latency_ms),
        },
    )


@router.post("/sessions/{session_id}/voice-metrics")
def record_browser_voice_metric(session_id: str, payload: BrowserVoiceMetric, request: Request) -> dict:
    repository = request.app.state.repository
    repository.record_voice_request(
        session_id,
        payload.operation,
        "browser",
        "browser",
        payload.status,
        payload.latencyMs,
        payload.message,
    )
    return repository.get_session(session_id)
