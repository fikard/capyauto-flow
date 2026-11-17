from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class CreateSessionRequest(BaseModel):
    serial: str
    fps: int = Field(default=5, ge=1, le=10)


class TapRequest(BaseModel):
    # 范围不在 pydantic 里校验：越界要返回 OUT_OF_BOUNDS 而不是 422
    sessionId: str
    x: float
    y: float
    pressMs: float = Field(default=80, ge=20, le=600)
    sigma: float = Field(default=6, ge=0, le=40)
    pressStdev: float = Field(default=20, ge=0, le=200)


class SwipeRequest(BaseModel):
    sessionId: str
    x1: float
    y1: float
    x2: float
    y2: float
    durationMs: int = Field(default=300, ge=50, le=3000)


class KeyRequest(BaseModel):
    sessionId: str
    key: str


class LaunchAppRequest(BaseModel):
    sessionId: str
    package: str = Field(min_length=1, max_length=200)
    user: int | None = Field(default=None, ge=0)


class StopAppRequest(BaseModel):
    sessionId: str
    package: str = Field(min_length=1, max_length=200)


class SwitchUserRequest(BaseModel):
    sessionId: str
    userId: int = Field(ge=0)


class AirplaneRequest(BaseModel):
    sessionId: str
    enable: bool


class OcrRequest(BaseModel):
    sessionId: str
    region: tuple[float, float, float, float] | None = None

    @field_validator("region")
    @classmethod
    def _check_region(cls, value):
        if value is None:
            return value
        left, top, right, bottom = value
        if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
            raise ValueError("region 需为 [left, top, right, bottom]，且 0<=left<right<=1、0<=top<bottom<=1")
        return value


class AccountResetRequest(BaseModel):
    names: list[str] | None = None


class AccountRunReport(BaseModel):
    runId: str = Field(min_length=1, max_length=100)
    account: str = Field(min_length=1, max_length=40)
    status: Literal["pending", "running", "completed", "failed", "stopped"]
    currentPhase: str = Field(default="", max_length=40)
    travelSpent: int = Field(default=0, ge=0)
    # AutoX 端侧在开始游历前 OCR 确认的体力，作为证据写入 lastRun.progress
    staminaBefore: int | None = Field(default=None, ge=0)
    error: str = Field(default="", max_length=500)


class AutomationStartRequest(BaseModel):
    sessionId: str
    task: Literal[
        "growth", "daily", "guild", "ship", "bootstrap", "server_sweep", "account_sweep", "all"
    ] = "all"
    maxRuns: int = Field(default=0, ge=0, le=10)
    skillPriorityList: list[str] = Field(default_factory=list, max_length=50)
    # 速度倍数：1.0 为默认，<1.0 加速（0.5 = 两倍速），>1.0 减速
    speed: float = Field(default=1.0, ge=0.1, le=3.0)
    # 爬塔层数（仅 growth/all 生效），0 表示跳过
    towerFloors: int = Field(default=2, ge=0, le=20)
    # 起号：同一关连续失败上限
    maxStageFails: int = Field(default=2, ge=1, le=5)
    # 起号：游历触发阈值（体力），0 表示不做游历
    travelStamina: int = Field(default=100, ge=0, le=1000)
    # 起号：是否允许天赋整十突破消耗宝石
    allowGemTalentBreakthrough: bool = False
    # 推关模式：full 逐帧识别，lean 按已录制坐标定时点击（适合批量账号）
    stageMode: Literal["full", "lean"] = "full"
    # 精简模式：每 N 次点击做一次界面校验
    fastStageCheckEvery: int = Field(default=8, ge=1, le=50)
    # 账号集合：本次运行归属的账号名，留空时从主城画面识别
    account: str = Field(default="", max_length=40)
    # 账号队列：按给定顺序逐账号执行完整起号流程
    accounts: list[str] = Field(default_factory=list, max_length=20)
    # 区服遍历：起始区服名、结束区服名（空表示最新区）
    serverFrom: str = Field(default="", max_length=40)
    serverTo: str = Field(default="", max_length=40)
    # 区服遍历：只枚举不切换
    serverDryRun: bool = True


VERIFY_CHECK_IDS = tuple(f"V{i}" for i in range(1, 11))


class VerifyRunRequest(BaseModel):
    """界面触发真机验收：可指定设备与跳过的检查项，留空走 CLI 的默认行为。"""

    serial: str = Field(default="", max_length=100)
    skip: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("skip")
    @classmethod
    def _normalize_skip(cls, value: list[str]) -> list[str]:
        normalized = [item.strip().upper() for item in value if item.strip()]
        invalid = [item for item in normalized if item not in VERIFY_CHECK_IDS]
        if invalid:
            raise ValueError(
                f"未知检查项：{', '.join(invalid)}；可用项 {', '.join(VERIFY_CHECK_IDS)}"
            )
        return normalized
