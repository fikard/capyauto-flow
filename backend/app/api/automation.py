from __future__ import annotations

from fastapi import APIRouter

from app.automation import get_engine
from app.schemas import AutomationStartRequest

router = APIRouter(prefix="/api/automation", tags=["automation"])


@router.post("/start")
async def start(req: AutomationStartRequest) -> dict:
    engine = get_engine()
    return await engine.start(
        req.sessionId,
        task=req.task,
        max_runs=req.maxRuns,
        skill_priority=req.skillPriorityList,
    )


@router.post("/stop")
async def stop() -> dict:
    return get_engine().stop()


@router.get("/status")
async def status() -> dict:
    return get_engine().status()
