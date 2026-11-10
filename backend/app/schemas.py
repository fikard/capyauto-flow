from __future__ import annotations

from pydantic import BaseModel, Field


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
