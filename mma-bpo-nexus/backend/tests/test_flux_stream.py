"""Flux transport and authenticated WebSocket streaming tests."""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import create_app
from app.providers.flux import DeepgramFluxStreamProvider
from conftest import authenticate_client


class FakeSocket:
    def __init__(self):
        self.sent = []
        self.closed = False
        self.events = [{"event": "StartOfTurn", "turn_index": 1}]
        self.end_sent = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.close()

    async def send(self, data):
        self.sent.append(data)

    async def recv(self):
        if self.events:
            return json.dumps(self.events.pop(0))
        while not self.sent:
            await asyncio.sleep(0.001)
        while self.sent and not self.end_sent:
            self.end_sent = True
            return json.dumps({
                "event": "EndOfTurn",
                "turn_index": 1,
                "transcript": "Yes, I am the account holder",
                "end_of_turn_confidence": 0.91,
            })
        await asyncio.Future()

    async def send_audio(self, data):
        await self.send(data)

    async def receive(self):
        return await self.recv()

    async def close(self):
        self.closed = True


class FakeFluxProvider:
    def __init__(self):
        self.socket = FakeSocket()

    def connect(self):
        return self.socket


def configure_flux(client):
    response = client.put("/api/v1/agent/mma-nexus-intake", json={
        "name": "MMA Nexus Flux",
        "campaign": "Streaming intake",
        "greeting": "This is the configured greeting for a Flux streaming session.",
        "transfersEnabled": True,
        "requireConsent": True,
        "sttProvider": "deepgram-flux",
        "sttModel": "flux-general-en",
        "ttsProvider": "browser",
        "ttsVoice": "aura-asteria-en",
    })
    assert response.status_code == 200, response.text


def create_flux_client(tmp_path, with_provider=True):
    provider = FakeFluxProvider() if with_provider else None
    app = create_app(
        tmp_path / "flux.db",
        flux_provider=provider,
    )
    client = TestClient(app, base_url="https://testserver", raise_server_exceptions=False)
    return client, provider


def test_flux_transport_uses_v2_pcm_and_backend_secret():
    seen = {}
    socket = FakeSocket()

    async def factory(url, **kwargs):
        seen["url"] = url
        seen["kwargs"] = kwargs
        return socket

    async def run():
        provider = DeepgramFluxStreamProvider("test-secret", connect_factory=factory)
        async with provider.connect() as connection:
            await connection.send_audio(b"\x01\x02")
            payload = json.loads(await connection.receive())
            assert payload["event"] == "StartOfTurn"

    asyncio.run(run())
    assert "/v2/listen" in seen["url"]
    assert "model=flux-general-en" in seen["url"]
    assert "encoding=linear16" in seen["url"]
    assert "sample_rate=16000" in seen["url"]
    assert seen["kwargs"]["additional_headers"]["Authorization"] == "Token test-secret"
    assert socket.sent == [b"\x01\x02"]
    assert socket.closed is True


def test_authenticated_flux_stream_and_turn_evidence(tmp_path):
    with create_flux_client(tmp_path)[0] as client:
        # Re-acquire the provider from application state for assertions.
        provider = client.app.state.flux_provider
        authenticate_client(client)
        configure_flux(client)
        current = client.post("/api/v1/sessions", json={"agentId": "mma-nexus-intake"}).json()
        with client.websocket_connect(f"wss://testserver/api/v1/voice/stream?sessionId={current['id']}") as stream:
            start = stream.receive_json()
            assert start["event"] == "StartOfTurn"
            assert start["source"] == "deepgram-flux"
            stream.send_bytes(b"\x01\x00" * 160)
            end = stream.receive_json()
            assert end["event"] == "EndOfTurn"
            assert end["transcript"] == "Yes, I am the account holder"
            assert end["end_of_turn_confidence"] == 0.91
            stream.send_json({"type": "close"})
        assert provider.socket.sent == [b"\x01\x00" * 160]
        assert provider.socket.closed is True
        restored = client.get(f"/api/v1/sessions/{current['id']}").json()
        records = restored["voiceRequests"]
        assert len(records) == 1
        assert records[0]["provider"] == "deepgram-flux"
        assert records[0]["source"] == "server"
        assert records[0]["status"] == "success"
        turn = client.post(f"/api/v1/sessions/{current['id']}/turns", json={
            "content": end["transcript"],
            "inputMethod": "deepgram-flux-stt",
            "sttLatencyMs": records[0]["latencyMs"],
        })
        assert turn.status_code == 200, turn.text
        assert turn.json()["turns"][-2]["inputMethod"] == "deepgram-flux-stt"


def test_flux_requires_provider_configuration(tmp_path):
    with create_flux_client(tmp_path, with_provider=False)[0] as client:
        authenticate_client(client)
        configure_flux(client)
        current = client.post("/api/v1/sessions", json={"agentId": "mma-nexus-intake"}).json()
        with pytest.raises(WebSocketDisconnect) as caught:
            with client.websocket_connect(f"wss://testserver/api/v1/voice/stream?sessionId={current['id']}"):
                pass
        assert caught.value.code == 1011


def test_flux_rejects_cross_origin_and_unauthenticated(tmp_path):
    with create_flux_client(tmp_path)[0] as client:
        authenticate_client(client)
        configure_flux(client)
        current = client.post("/api/v1/sessions", json={"agentId": "mma-nexus-intake"}).json()
        with pytest.raises(WebSocketDisconnect) as caught:
            with client.websocket_connect(
                f"wss://testserver/api/v1/voice/stream?sessionId={current['id']}",
                headers={"Origin": "https://attacker.invalid"},
            ):
                pass
        assert caught.value.code == 1008
        client.cookies.clear()
        with pytest.raises(WebSocketDisconnect) as caught:
            with client.websocket_connect(f"wss://testserver/api/v1/voice/stream?sessionId={current['id']}"):
                pass
        assert caught.value.code == 1008
