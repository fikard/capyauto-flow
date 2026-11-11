from __future__ import annotations

from fastapi import APIRouter

from app.device.base import AppStatus
from app.deps import get_adapter
from app.schemas import LaunchAppRequest, StopAppRequest, SwitchUserRequest

router = APIRouter(prefix="/api/app", tags=["app"])


def _app_payload(status: AppStatus) -> dict:
    return {
        "package": status.package,
        "activity": status.activity,
        "running": status.running,
        "pid": status.pid,
    }


@router.post("/launch")
async def launch(req: LaunchAppRequest) -> dict:
    status = await get_adapter().launch_app(req.sessionId, req.package, req.user)
    return {**_app_payload(status), "ok": status.running, "usedUser": status.user}


@router.post("/stop")
async def stop(req: StopAppRequest) -> dict:
    await get_adapter().stop_app(req.sessionId, req.package)
    return {"ok": True}


@router.get("/current")
async def current(sessionId: str) -> dict:
    status = await get_adapter().current_app(sessionId)
    return _app_payload(status)


@router.get("/users")
async def users(sessionId: str) -> dict:
    result = await get_adapter().list_users(sessionId)
    return {
        "users": [
            {"id": row.id, "name": row.name, "current": row.current} for row in result.users
        ],
        "switchSupported": result.switch_supported,
        "reason": result.reason,
    }


@router.post("/switch-user")
async def switch_user(req: SwitchUserRequest) -> dict:
    result = await get_adapter().switch_user(req.sessionId, req.userId)
    return {
        "ok": result.ok,
        "userId": result.user_id,
        "switchSupported": result.switch_supported,
        "reason": result.reason,
    }
