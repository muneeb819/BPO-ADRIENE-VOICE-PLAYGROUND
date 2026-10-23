"""Optional LiveKit Cloud room and dispatch adapter."""

from __future__ import annotations

from datetime import timedelta
import os
import re
from urllib.parse import urlsplit

from .base import VoiceProviderError

ROOM_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def validate_room(name: str) -> str:
    name = name.strip()
    if not ROOM_PATTERN.fullmatch(name):
        raise VoiceProviderError("Room names must be 1-64 letters, numbers, underscores, or hyphens", 400)
    return name


class LiveKitCloudService:
    def __init__(self, url: str, api_key: str, api_secret: str, agent_name: str = ""):
        self.url = url.strip()
        self.api_key = api_key.strip()
        self.api_secret = api_secret.strip()
        self.agent_name = agent_name.strip()

    @property
    def host(self) -> str:
        return urlsplit(self.url).netloc

    def status(self) -> dict:
        return {
            "configured": True,
            "connected": None,
            "host": self.host,
            "agentName": self.agent_name,
            "message": "Credentials configured. List rooms to verify connectivity.",
        }

    def _client(self):
        from livekit import api
        return api.LiveKitAPI(self.url, self.api_key, self.api_secret)

    @staticmethod
    async def _close(client) -> None:
        try:
            await client.aclose()
        except Exception:
            pass

    async def list_rooms(self) -> list[dict]:
        from livekit import api
        client = self._client()
        try:
            response = await client.room.list_rooms(api.ListRoomsRequest())
            rooms = list(getattr(response, "rooms", response) or [])
            return [{
                "name": getattr(room, "name", ""),
                "participants": int(getattr(room, "num_participants", 0) or 0),
                "emptyTimeoutSec": int(getattr(room, "empty_timeout", 0) or 0),
                "maxParticipants": int(getattr(room, "max_participants", 0) or 0),
            } for room in rooms]
        except Exception as exc:
            raise VoiceProviderError("LiveKit room list failed", 502) from exc
        finally:
            await self._close(client)

    async def create_room(self, name: str) -> dict:
        from livekit import api
        name = validate_room(name)
        client = self._client()
        try:
            room = await client.room.create_room(api.CreateRoomRequest(
                name=name, empty_timeout=1800, max_participants=20,
            ))
            return {"name": getattr(room, "name", name), "created": True}
        except Exception as exc:
            raise VoiceProviderError("LiveKit room creation failed", 502) from exc
        finally:
            await self._close(client)

    async def delete_room(self, name: str) -> dict:
        from livekit import api
        name = validate_room(name)
        client = self._client()
        try:
            await client.room.delete_room(api.DeleteRoomRequest(room=name))
            return {"name": name, "deleted": True}
        except Exception as exc:
            raise VoiceProviderError("LiveKit room deletion failed", 502) from exc
        finally:
            await self._close(client)

    async def mint_token(self, room: str, identity: str) -> dict:
        from livekit import api
        room = validate_room(room)
        rooms = await self.list_rooms()
        if room not in {item["name"] for item in rooms}:
            raise VoiceProviderError("LiveKit room not found", 404)
        token = api.AccessToken(self.api_key, self.api_secret)
        token = token.with_identity(identity)
        token = token.with_ttl(timedelta(minutes=10))
        token = token.with_grants(api.VideoGrants(
            room_join=True,
            room=room,
            can_publish=True,
            can_subscribe=True,
            can_publish_data=True,
            can_update_own_metadata=False,
        ))
        return {
            "token": token.to_jwt(),
            "url": self.url,
            "room": room,
            "identity": identity,
            "expiresInSec": 600,
        }

    async def dispatch(self, room: str, agent_name: str = "") -> dict:
        from livekit import api
        room = validate_room(room)
        target = agent_name.strip() or self.agent_name
        if not target:
            raise VoiceProviderError("No LiveKit agent name is configured", 400)
        if len(target) > 120:
            raise VoiceProviderError("Agent name is too long", 400)
        client = self._client()
        try:
            dispatch = await client.agent_dispatch.create_dispatch(
                api.CreateAgentDispatchRequest(room=room, agent_name=target)
            )
            return {
                "dispatchId": getattr(dispatch, "id", "") or "",
                "room": room,
                "agentName": target,
            }
        except Exception as exc:
            raise VoiceProviderError("LiveKit agent dispatch failed", 502) from exc
        finally:
            await self._close(client)


def build_livekit_service() -> LiveKitCloudService | None:
    url = os.environ.get("LIVEKIT_URL", "").strip()
    key = os.environ.get("LIVEKIT_API_KEY", "").strip()
    secret = os.environ.get("LIVEKIT_API_SECRET", "").strip()
    agent = os.environ.get("LIVEKIT_AGENT_NAME", "").strip()
    if not (url and key and secret):
        return None
    if not url.startswith(("wss://", "https://")):
        raise ValueError("LIVEKIT_URL must use wss:// or https://")
    return LiveKitCloudService(url, key, secret, agent)
