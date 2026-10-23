"""LiveKit room, dispatch, and scoped token tests."""

import asyncio
import base64
import json
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.providers.livekit import LiveKitCloudService, validate_room
from app.providers import VoiceProviderError
from conftest import authenticate_client


class FakeLiveKit:
    def __init__(self):
        self.rooms = [{"name": "existing-room", "participants": 0, "emptyTimeoutSec": 1800, "maxParticipants": 20}]

    def status(self):
        return {"configured": True, "connected": None, "host": "project.livekit.test", "agentName": "nexus-agent", "message": "verify"}

    async def list_rooms(self):
        return self.rooms

    async def create_room(self, name):
        room = {"name": name, "participants": 0, "emptyTimeoutSec": 1800, "maxParticipants": 20}
        self.rooms.append(room)
        return {"name": name, "created": True}

    async def delete_room(self, name):
        self.rooms = [room for room in self.rooms if room["name"] != name]
        return {"name": name, "deleted": True}

    async def mint_token(self, room, identity):
        if room not in {item["name"] for item in self.rooms}:
            raise VoiceProviderError("LiveKit room not found", 404)
        return {"token": "scoped-test-token", "url": "wss://project.livekit.test", "room": room, "identity": identity, "expiresInSec": 600}

    async def dispatch(self, room, agent_name=""):
        return {"dispatchId": "dispatch-1", "room": room, "agentName": agent_name or "nexus-agent"}


def test_livekit_room_token_dispatch_lifecycle(tmp_path):
    app = create_app(tmp_path / "livekit.db", livekit_service=FakeLiveKit())
    with TestClient(app, base_url="https://testserver", raise_server_exceptions=False) as client:
        authenticate_client(client)
        status = client.get("/api/v1/livekit/status")
        assert status.json()["configured"] is True
        created = client.post("/api/v1/livekit/rooms", json={"name": "stage4-room"})
        assert created.status_code == 201, created.text
        rooms = client.get("/api/v1/livekit/rooms").json()
        assert rooms["connected"] is True
        assert {room["name"] for room in rooms["rooms"]} == {"existing-room", "stage4-room"}
        token = client.post("/api/v1/livekit/token", json={"room": "stage4-room"})
        assert token.status_code == 200, token.text
        assert token.json()["token"] == "scoped-test-token"
        assert token.json()["identity"].startswith("operator-")
        assert token.json()["expiresInSec"] == 600
        assert "apiSecret" not in token.json()
        missing = client.post("/api/v1/livekit/token", json={"room": "missing-room"})
        assert missing.status_code == 404
        dispatch = client.post("/api/v1/livekit/dispatch", json={"room": "stage4-room"})
        assert dispatch.status_code == 200
        assert dispatch.json()["agentName"] == "nexus-agent"
        deleted = client.delete("/api/v1/livekit/rooms/stage4-room")
        assert deleted.status_code == 200
        assert deleted.json()["deleted"] is True
        actions = {row["action"] for row in client.get("/api/v1/auth/audit").json()}
        assert "livekit_room_created" in actions
        assert "livekit_token_issued" in actions
        assert "livekit_agent_dispatched" in actions
        assert "livekit_room_deleted" in actions


def test_livekit_unconfigured_is_explicit(tmp_path):
    app = create_app(tmp_path / "livekit-off.db")
    with TestClient(app, base_url="https://testserver", raise_server_exceptions=False) as client:
        authenticate_client(client)
        status = client.get("/api/v1/livekit/status")
        assert status.status_code == 200
        assert status.json()["configured"] is False
        assert status.json()["connected"] is False
        rooms = client.get("/api/v1/livekit/rooms")
        assert rooms.status_code == 503
        assert "not configured" in rooms.json()["error"]


def test_room_validation_rejects_unsafe_names():
    with pytest.raises(VoiceProviderError):
        validate_room("bad room/name")
    with pytest.raises(VoiceProviderError):
        validate_room("space is invalid")
    assert validate_room("safe-room_1") == "safe-room_1"


def test_real_token_is_room_scoped_and_short_lived():
    service = LiveKitCloudService(
        "wss://project.livekit.test",
        "test-api-key",
        "test-api-secret-with-enough-entropy",
        "nexus-agent",
    )
    service.list_rooms = AsyncMock(return_value=[{"name": "scoped-room"}])
    result = asyncio.run(service.mint_token("scoped-room", "operator-test"))
    encoded = result["token"].split(".")[1]
    payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    assert payload["sub"] == "operator-test"
    assert payload["video"]["room"] == "scoped-room"
    assert payload["video"]["roomJoin"] is True
    assert payload["exp"] - payload["nbf"] == 600
    assert "roomAdmin" not in payload["video"]
    assert "test-api-secret-with-enough-entropy" not in result["token"]
