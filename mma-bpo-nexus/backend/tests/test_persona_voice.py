"""Persona, voice catalogue, and preview tests."""

import sqlite3

from fastapi.testclient import TestClient

from app.main import create_app
from app.providers import SpeechResult, TranscriptionResult, VoiceProvider
from app.schemas import AgentUpdate
from conftest import authenticate_client


class PreviewProvider(VoiceProvider):
    def __init__(self):
        self.last_voice = None

    async def transcribe(self, audio: bytes, content_type: str, model: str) -> TranscriptionResult:
        return TranscriptionResult("test transcript", "deepgram", model, 1.0)

    async def synthesize(self, text: str, voice: str) -> SpeechResult:
        self.last_voice = voice
        return SpeechResult(b"ID3-preview-audio", "audio/mpeg", "deepgram", voice, 9.5)


def test_catalog_contains_deepgram_options_without_false_verification(client):
    response = client.get("/api/v1/voice/catalog")
    assert response.status_code == 200
    data = response.json()
    voices = data["ttsVoices"]
    assert len([voice for voice in voices if voice["family"] == "Flux"]) == 36
    assert len([voice for voice in voices if voice["family"] == "Aura"]) == 5
    assert len(voices) == 41
    assert len(data["sttModels"]) == 4
    assert len(data["personaPresets"]) == 6
    assert data["accountVerified"] is False
    assert data["deepgramConfigured"] is False


def test_every_catalog_voice_is_accepted_by_agent_schema():
    client_voices = []
    # Validate against the public catalogue itself, not a second hard-coded list.
    from app.providers.catalog import TTS_VOICES
    for voice in TTS_VOICES:
        payload = AgentUpdate(
            name="MMA Voice Agent",
            campaign="Voice testing",
            greeting="This is a valid greeting for the selected voice.",
            ttsVoice=voice["id"],
        )
        client_voices.append(payload.ttsVoice)
    assert client_voices == [voice["id"] for voice in TTS_VOICES]


def test_persona_and_voice_settings_are_versioned_and_affect_wording(client):
    updated = client.put("/api/v1/agent/mma-nexus-intake", json={
        "name": "MMA Financial Intake",
        "campaign": "Financial services",
        "greeting": "This is the exact greeting for the financial persona.",
        "personaPreset": "financial",
        "purpose": "Financial account and advisor review",
        "tone": "empathetic",
        "transfersEnabled": True,
        "requireConsent": True,
        "sttProvider": "deepgram",
        "sttModel": "nova-3",
        "ttsProvider": "deepgram",
        "ttsVoice": "flux-brittany-en",
    })
    assert updated.status_code == 200, updated.text
    data = updated.json()
    assert data["personaPreset"] == "financial"
    assert data["purpose"] == "Financial account and advisor review"
    assert data["tone"] == "empathetic"
    assert data["sttModel"] == "nova-3"
    assert data["ttsVoice"] == "flux-brittany-en"
    current = client.post("/api/v1/sessions", json={"agentId": "mma-nexus-intake"}).json()
    assert current["turns"][0]["content"] == "This is the exact greeting for the financial persona."
    assert current["policy"]["personaPreset"] == "financial"
    assert current["policy"]["purpose"] == "Financial account and advisor review"
    assert current["policy"]["ttsVoice"] == "flux-brittany-en"
    pricing = client.post(f"/api/v1/sessions/{current['id']}/turns", json={"content": "What is the price?"})
    assert pricing.status_code == 200
    reply = pricing.json()["turns"][-1]["content"]
    assert "I understand pricing matters for Financial account and advisor review" in reply
    versions = client.get("/api/v1/agent/mma-nexus-intake/versions").json()
    assert versions[0]["personaPreset"] == "financial"
    assert versions[0]["ttsVoice"] == "flux-brittany-en"


def test_invalid_persona_and_voice_combinations_are_rejected(client):
    base = {
        "name": "MMA Voice Agent",
        "campaign": "Voice testing",
        "greeting": "This is a valid greeting for validation.",
        "transfersEnabled": True,
        "requireConsent": True,
        "sttProvider": "browser",
        "sttModel": "browser",
        "ttsProvider": "deepgram",
        "ttsVoice": "aura-asteria-en",
    }
    bad_voice = client.put("/api/v1/agent/mma-nexus-intake", json={**base, "ttsVoice": "not-a-voice"})
    assert bad_voice.status_code == 422
    bad_persona = client.put("/api/v1/agent/mma-nexus-intake", json={**base, "personaPreset": "not-a-persona"})
    assert bad_persona.status_code == 422
    bad_route = client.put("/api/v1/agent/mma-nexus-intake", json={**base, "sttModel": "nova-3"})
    assert bad_route.status_code == 422


def test_voice_preview_success_records_metadata_without_session(tmp_path):
    provider = PreviewProvider()
    app = create_app(tmp_path / "preview.db", voice_provider=provider)
    with TestClient(app, base_url="https://testserver", raise_server_exceptions=False) as client:
        authenticate_client(client)
        response = client.post("/api/v1/voice/preview", json={
            "text": "Hello from the selected voice", "voice": "flux-hannah-en",
        })
        assert response.status_code == 200, response.text
        assert response.content == b"ID3-preview-audio"
        assert response.headers["x-tts-voice"] == "flux-hannah-en"
        assert response.headers["x-tts-latency-ms"] == "9.5"
        assert provider.last_voice == "flux-hannah-en"
        with sqlite3.connect(tmp_path / "preview.db") as conn:
            row = conn.execute("SELECT session_id, operation, provider, source, status, latency_ms FROM voice_requests").fetchone()
        assert row == (None, "tts", "deepgram", "server", "success", 9.5)


def test_voice_preview_requires_configuration(client):
    response = client.post("/api/v1/voice/preview", json={
        "text": "Preview text", "voice": "aura-luna-en",
    })
    assert response.status_code == 503
    assert response.json()["fallback"] == "no-equivalent-browser-voice"
