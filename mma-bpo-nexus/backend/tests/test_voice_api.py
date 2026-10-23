"""Voice API, metadata, fallback, and migration tests."""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.db import Database
from app.main import create_app
from app.providers import SpeechResult, TranscriptionResult, VoiceProvider
from conftest import authenticate_client


class FakeVoiceProvider(VoiceProvider):
    async def transcribe(self, audio: bytes, content_type: str, model: str) -> TranscriptionResult:
        assert len(audio) >= 200
        assert content_type == "audio/webm"
        return TranscriptionResult("Yes, I am the account holder", "deepgram", model, 12.5)

    async def synthesize(self, text: str, voice: str) -> SpeechResult:
        return SpeechResult(b"ID3-fake-test-audio", "audio/mpeg", "deepgram", voice, 8.25)


@pytest.fixture
def voice_client(tmp_path):
    app = create_app(tmp_path / "voice-test.db", voice_provider=FakeVoiceProvider())
    with TestClient(app, base_url="https://testserver", raise_server_exceptions=False) as client:
        authenticate_client(client)
        yield client


def configure_deepgram(client):
    response = client.put("/api/v1/agent/mma-nexus-intake", json={
        "name": "MMA Nexus Voice",
        "campaign": "Voice intake",
        "greeting": "This is the configured greeting for a Stage 2 voice session.",
        "transfersEnabled": True,
        "requireConsent": True,
        "sttProvider": "deepgram",
        "sttModel": "nova-2",
        "ttsProvider": "deepgram",
        "ttsVoice": "aura-asteria-en",
    })
    assert response.status_code == 200, response.text


def new_session(client):
    response = client.post("/api/v1/sessions", json={"agentId": "mma-nexus-intake"})
    assert response.status_code == 201, response.text
    return response.json()


def test_default_voice_status_is_honest(client):
    response = client.get("/api/v1/voice/status")
    assert response.status_code == 200
    data = response.json()
    assert data["deepgramConfigured"] is False
    assert data["sttProvider"] == "browser"
    assert data["ttsProvider"] == "browser"
    assert data["audioStored"] is False
    assert "Browser speech services may process audio externally" in data["disclosure"]


def test_deepgram_stt_and_tts_round_trip_with_metadata(voice_client):
    configure_deepgram(voice_client)
    current = new_session(voice_client)
    session_id = current["id"]
    stt = voice_client.post(
        f"/api/v1/voice/stt?sessionId={session_id}",
        content=b"x" * 300,
        headers={"Content-Type": "audio/webm"},
    )
    assert stt.status_code == 200, stt.text
    transcript = stt.json()
    assert transcript["transcript"] == "Yes, I am the account holder"
    assert transcript["latencyMs"] == 12.5
    assert transcript["audioStored"] is False

    current = voice_client.post(f"/api/v1/sessions/{session_id}/turns", json={
        "content": transcript["transcript"],
        "inputMethod": "deepgram-stt",
        "sttLatencyMs": transcript["latencyMs"],
    }).json()
    user_turn = current["turns"][-2]
    assert user_turn["inputMethod"] == "deepgram-stt"
    assert user_turn["sttLatencyMs"] == 12.5
    stt_records = [row for row in current["voiceRequests"] if row["operation"] == "stt"]
    assert len(stt_records) == 1
    assert stt_records[0]["source"] == "server"
    assert stt_records[0]["status"] == "success"

    tts = voice_client.post(
        f"/api/v1/voice/tts?sessionId={session_id}", json={"text": "Speak this reply"}
    )
    assert tts.status_code == 200, tts.text
    assert tts.content == b"ID3-fake-test-audio"
    assert tts.headers["content-type"].startswith("audio/mpeg")
    assert tts.headers["x-tts-provider"] == "deepgram"
    assert tts.headers["x-tts-latency-ms"] == "8.25"
    restored = voice_client.get(f"/api/v1/sessions/{session_id}").json()
    tts_records = [row for row in restored["voiceRequests"] if row["operation"] == "tts"]
    assert len(tts_records) == 1
    assert tts_records[0]["source"] == "server"
    assert tts_records[0]["latencyMs"] == 8.25


def test_unconfigured_deepgram_returns_actionable_fallback(client):
    configure_deepgram(client)
    current = new_session(client)
    response = client.post(
        f"/api/v1/voice/stt?sessionId={current['id']}",
        content=b"x" * 300,
        headers={"Content-Type": "audio/webm"},
    )
    assert response.status_code == 503
    assert response.json()["fallback"] == "text-input"
    assert "not configured" in response.json()["error"]


def test_browser_session_rejects_deepgram_upload(client):
    current = new_session(client)
    response = client.post(
        f"/api/v1/voice/stt?sessionId={current['id']}",
        content=b"x" * 300,
        headers={"Content-Type": "audio/webm"},
    )
    assert response.status_code == 409
    assert "browser STT" in response.json()["error"]


def test_audio_size_and_type_limits(voice_client):
    configure_deepgram(voice_client)
    current = new_session(voice_client)
    tiny = voice_client.post(
        f"/api/v1/voice/stt?sessionId={current['id']}",
        content=b"tiny",
        headers={"Content-Type": "audio/webm"},
    )
    assert tiny.status_code == 400
    wrong_type = voice_client.post(
        f"/api/v1/voice/stt?sessionId={current['id']}",
        content=b"x" * 300,
        headers={"Content-Type": "text/plain"},
    )
    assert wrong_type.status_code == 415
    oversized = voice_client.post(
        f"/api/v1/voice/stt?sessionId={current['id']}",
        content=b"x" * 8_000_001,
        headers={"Content-Type": "audio/webm"},
    )
    assert oversized.status_code == 413


def test_browser_metrics_are_labeled_and_persisted(client):
    current = new_session(client)
    stt = client.post(f"/api/v1/sessions/{current['id']}/voice-metrics", json={
        "operation": "stt", "status": "success", "latencyMs": 42.5,
        "message": "Browser elapsed recognition time",
    })
    assert stt.status_code == 200, stt.text
    tts = client.post(f"/api/v1/sessions/{current['id']}/voice-metrics", json={
        "operation": "tts", "status": "success", "latencyMs": 18.0,
        "message": "Browser speech synthesis",
    })
    assert tts.status_code == 200, tts.text
    records = tts.json()["voiceRequests"]
    assert [(row["operation"], row["source"], row["latencyMs"]) for row in records] == [
        ("stt", "browser", 42.5), ("tts", "browser", 18.0),
    ]
    assert any(event["type"] == "voice_tts_success" for event in tts.json()["events"])


def test_voice_input_requires_matching_provider_and_measurement(client):
    current = new_session(client)
    wrong_provider = client.post(f"/api/v1/sessions/{current['id']}/turns", json={
        "content": "hello", "inputMethod": "deepgram-stt", "sttLatencyMs": 10,
    })
    assert wrong_provider.status_code == 409
    missing_measurement = client.post(f"/api/v1/sessions/{current['id']}/turns", json={
        "content": "hello", "inputMethod": "browser-stt",
    })
    assert missing_measurement.status_code == 422


def test_stage1_schema_is_migrated_without_replacement(tmp_path):
    path = tmp_path / "old-stage1.db"
    with sqlite3.connect(path) as conn:
        conn.execute("""CREATE TABLE agent_versions (
            id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, version INTEGER NOT NULL,
            name TEXT NOT NULL, campaign TEXT NOT NULL, greeting TEXT NOT NULL,
            transfers_enabled INTEGER NOT NULL, require_consent INTEGER NOT NULL,
            max_turns INTEGER NOT NULL DEFAULT 20, created_at TEXT NOT NULL,
            UNIQUE(agent_id, version)
        )""")
        conn.execute("""CREATE TABLE turns (
            id TEXT PRIMARY KEY, session_id TEXT NOT NULL, seq INTEGER NOT NULL,
            role TEXT NOT NULL, content TEXT NOT NULL, intent TEXT NOT NULL,
            latency_ms REAL NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
            UNIQUE(session_id, seq)
        )""")
    Database(path).initialize()
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        agent_columns = {row["name"] for row in conn.execute("PRAGMA table_info(agent_versions)")}
        turn_columns = {row["name"] for row in conn.execute("PRAGMA table_info(turns)")}
        assert {"stt_provider", "stt_model", "tts_provider", "tts_voice", "persona_preset", "purpose", "tone"} <= agent_columns
        assert {"input_method", "stt_latency_ms"} <= turn_columns
        assert conn.execute("SELECT COUNT(*) FROM voice_requests").fetchone()[0] == 0
