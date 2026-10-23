"""Optional LiveKit Cloud control endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request

from ..repositories.nexus import utc_now
from ..schemas import LiveKitRoomAction, LiveKitRoomCreate
from .routes import audit

router = APIRouter(prefix="/api/v1/livekit", tags=["LiveKit Cloud"])


def service(request: Request):
    service = request.app.state.livekit
    if service is None:
        raise HTTPException(
            status_code=503,
            detail="LiveKit is not configured. Set LIVEKIT_URL, LIVEKIT_API_KEY, and LIVEKIT_API_SECRET.",
        )
    return service


@router.get("/status")
def livekit_status(request: Request) -> dict:
    if request.app.state.livekit is None:
        return {
            "configured": False,
            "connected": False,
            "host": "",
            "agentName": "",
            "message": "LiveKit credentials are not configured.",
        }
    return request.app.state.livekit.status()


@router.get("/rooms")
async def rooms(request: Request) -> dict:
    rooms = await service(request).list_rooms()
    return {"rooms": rooms, "connected": True, "verifiedAt": utc_now()}


@router.post("/rooms", status_code=201)
async def create_room(payload: LiveKitRoomCreate, request: Request) -> dict:
    result = await service(request).create_room(payload.name)
    audit(request, "livekit_room_created", "livekit_room", result["name"], {})
    return result


@router.delete("/rooms/{room_name}")
async def delete_room(room_name: str, request: Request) -> dict:
    result = await service(request).delete_room(room_name)
    audit(request, "livekit_room_deleted", "livekit_room", room_name, {})
    return result


@router.post("/token")
async def join_token(payload: LiveKitRoomAction, request: Request) -> dict:
    identity = f"operator-{uuid.uuid4().hex[:10]}"
    result = await service(request).mint_token(payload.room, identity)
    audit(request, "livekit_token_issued", "livekit_room", payload.room, {"identity": identity})
    return result


@router.post("/dispatch")
async def dispatch(payload: LiveKitRoomAction, request: Request) -> dict:
    result = await service(request).dispatch(payload.room, payload.agentName or "")
    audit(request, "livekit_agent_dispatched", "livekit_room", payload.room, {"agentName": result["agentName"]})
    return result
