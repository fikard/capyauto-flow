from __future__ import annotations

import asyncio
import threading
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter

from app import config, verify
from app.errors import ApiError
from app.schemas import VerifyRunRequest

router = APIRouter(prefix="/api/verify", tags=["verify"])

# V1–V10 会切用户、开关飞行模式、启停游戏，并发执行会互相干扰，必须串行。
_RUN_LOCK = threading.Lock()
# 与 CLI 的 --out 默认值一致；截图与报告仍由 verify.py 自己落盘。
REPORT_DIR = Path(__file__).parent.parent.parent / "reports"


def _run_in_thread(
    serial: str | None,
    package: str,
    activity: str | None,
    out_dir: Path,
    skip: set[str],
):
    # run_checks 是 async，但内部大量同步 adb 调用；放独立线程避免阻塞事件循环。
    return asyncio.run(verify.run_checks(serial, package, activity, out_dir, skip))


@router.post("/run")
async def run(req: VerifyRunRequest | None = None) -> dict:
    request = req or VerifyRunRequest()
    if not _RUN_LOCK.acquire(blocking=False):
        raise ApiError(
            "已有验收任务正在执行，请等待结束后重试",
            code="VERIFY_BUSY",
            status_code=409,
        )
    started_at = datetime.now().isoformat(timespec="seconds")
    try:
        serial, results, serial_online = await asyncio.to_thread(
            _run_in_thread,
            request.serial or None,
            config.settings.game_package,
            config.settings.game_activity,
            REPORT_DIR,
            set(request.skip),
        )
    finally:
        _RUN_LOCK.release()

    return {
        "serial": serial,
        "started": started_at,
        "deviceOnline": serial_online,
        "summary": verify.summarize(results),
        "checks": [
            {
                "checkId": row.check_id,
                "status": row.status,
                "detail": row.detail,
                "elapsedMs": row.elapsed_ms,
            }
            for row in results
        ],
        "hint": None
        if serial_online
        else "未检测到在线设备，以上结果仅反映当前环境；请连接真机后重新校验",
    }
