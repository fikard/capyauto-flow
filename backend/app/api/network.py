from __future__ import annotations

from fastapi import APIRouter

from app.deps import get_adapter
from app.schemas import AirplaneRequest

router = APIRouter(prefix="/api/network", tags=["network"])


@router.post("/airplane")
async def airplane(req: AirplaneRequest) -> dict:
    result = await get_adapter().set_airplane_mode(req.sessionId, req.enable)
    return {
        "ok": result.ok,
        "airplaneModeOn": result.airplane_mode_on,
        "appliedVia": result.applied_via,
    }
