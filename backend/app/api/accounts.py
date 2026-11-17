from __future__ import annotations

from fastapi import APIRouter

from app.accounts import account_summary, record_account_run, reset_account_works
from app.schemas import AccountResetRequest, AccountRunReport

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


@router.get("")
async def list_accounts() -> dict:
    return {"accounts": account_summary()}


@router.post("/reset")
async def reset_accounts(req: AccountResetRequest | None = None) -> dict:
    """每日任务状态重置：清空 works，保留账号身份与历史。names 为空表示全部。"""
    return reset_account_works(names=req.names if req else None)


@router.post("/report")
async def report_account_run(req: AccountRunReport) -> dict:
    progress = {"travelSpent": req.travelSpent}
    if req.staminaBefore is not None:
        progress["staminaBefore"] = req.staminaBefore
    entry = record_account_run(
        req.account,
        req.runId,
        req.status,
        current_phase=req.currentPhase,
        error=req.error,
        progress=progress,
    )
    return {"account": entry}
