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
        speed=req.speed,
        tower_floors=req.towerFloors,
        max_stage_fails=req.maxStageFails,
        travel_stamina=req.travelStamina,
        allow_gem_talent_breakthrough=req.allowGemTalentBreakthrough,
        stage_mode=req.stageMode,
        fast_stage_check_every=req.fastStageCheckEvery,
        account=req.account,
        accounts=req.accounts,
        server_from=req.serverFrom,
        server_to=req.serverTo,
        server_dry_run=req.serverDryRun,
    )


@router.post("/stop")
async def stop() -> dict:
    return get_engine().stop()


@router.get("/status")
async def status() -> dict:
    return get_engine().status()
