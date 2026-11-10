from dataclasses import asdict

from fastapi import APIRouter

from app.deps import get_adapter
from app.schemas import CreateSessionRequest

router = APIRouter(prefix="/api", tags=["devices"])


@router.get("/devices")
async def list_devices() -> dict:
    devices = await get_adapter().list_devices()
    return {"devices": [asdict(device) for device in devices]}


@router.post("/session")
async def create_session(req: CreateSessionRequest) -> dict:
    session = await get_adapter().create_session(req.serial, req.fps)
    return {
        "sessionId": session.id,
        "serial": session.serial,
        "width": session.width,
        "height": session.height,
        "fps": session.fps,
        "degraded": session.degraded,
        "mode": session.mode,
        "sizeMismatch": session.size_mismatch,
    }


@router.delete("/session/{session_id}")
async def close_session(session_id: str) -> dict:
    await get_adapter().close_session(session_id)
    return {"ok": True}
