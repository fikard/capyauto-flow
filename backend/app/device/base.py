from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator, Literal


@dataclass
class DeviceInfo:
    serial: str
    state: str
    model: str | None = None
    android: str | None = None
    abi: str | None = None
    wm_size: str | None = None
    width: int | None = None
    height: int | None = None
    transport_id: str | None = None


@dataclass
class MirrorSession:
    id: str
    serial: str
    width: int
    height: int
    fps: int
    degraded: bool = False
    mode: Literal["scrcpy", "screencap", "mock"] = "mock"
    size_mismatch: bool = False


@dataclass
class Frame:
    seq: int
    jpeg: bytes
    width: int
    height: int
    ts: float


@dataclass
class TapResult:
    target_x: int
    target_y: int
    real_x: int
    real_y: int
    press_ms: int
    injected_via: str


@dataclass
class SwipeResult:
    points: list[tuple[int, int]]
    injected_via: str


class DeviceAdapter(ABC):
    name: str = "base"

    @abstractmethod
    async def health(self) -> dict:
        ...

    @abstractmethod
    async def list_devices(self) -> list[DeviceInfo]:
        ...

    @abstractmethod
    async def create_session(self, serial: str, fps: int) -> MirrorSession:
        ...

    @abstractmethod
    async def close_session(self, session_id: str) -> None:
        ...

    @abstractmethod
    def get_session(self, session_id: str) -> MirrorSession:
        ...

    @abstractmethod
    def frames(self, session_id: str) -> AsyncIterator[Frame]:
        ...

    @abstractmethod
    async def tap(
        self,
        session_id: str,
        x: float,
        y: float,
        press_ms: float,
        sigma: float,
        press_stdev: float = 20.0,
    ) -> TapResult:
        ...

    @abstractmethod
    async def swipe(
        self,
        session_id: str,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        duration_ms: int,
    ) -> SwipeResult:
        ...

    @abstractmethod
    async def key(self, session_id: str, key: str) -> None:
        ...

    @abstractmethod
    async def screenshot(self, session_id: str) -> bytes:
        ...
