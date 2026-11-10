from __future__ import annotations

from fastapi import APIRouter

from app.deps import get_adapter
from app.schemas import KeyRequest, SwipeRequest, TapRequest

router = APIRouter(prefix="/api/control", tags=["control"])


@router.post("/tap")
async def tap(req: TapRequest) -> dict:
    adapter = get_adapter()
    session = adapter.get_session(req.sessionId)
    result = await adapter.tap(
        req.sessionId, req.x, req.y, req.pressMs, req.sigma, req.pressStdev
    )
    return {
        "targetX": result.target_x,
        "targetY": result.target_y,
        "realX": result.real_x,
        "realY": result.real_y,
        "pressMs": result.press_ms,
        "injectedVia": result.injected_via,
        "deviceWidth": session.width,
        "deviceHeight": session.height,
    }


@router.post("/swipe")
async def swipe(req: SwipeRequest) -> dict:
    result = await get_adapter().swipe(
        req.sessionId, req.x1, req.y1, req.x2, req.y2, req.durationMs
    )
    return {
        "points": [list(point) for point in result.points],
        "injectedVia": result.injected_via,
    }


@router.post("/key")
async def key(req: KeyRequest) -> dict:
    await get_adapter().key(req.sessionId, req.key)
    return {"ok": True}
