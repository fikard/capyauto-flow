from __future__ import annotations

import asyncio
import io
import time

from PIL import Image, ImageDraw

from app.core.dither import bezier_points, gaussian_click
from app.core.geometry import normalize_to_device
from app.device.base import (
    DeviceAdapter,
    DeviceInfo,
    Frame,
    MirrorSession,
    SwipeResult,
    TapResult,
    keycode_for,
)
from app.errors import DeviceNotFound, SessionNotFound


class MockDevice(DeviceAdapter):
    name = "mock"

    def __init__(self, width: int = 1080, height: int = 2400, jpeg_quality: int = 70) -> None:
        self._width = width
        self._height = height
        self._jpeg_quality = jpeg_quality
        self._sessions: dict[str, MirrorSession] = {}
        self._next_id = 1
        self._seq = 0
        self._last_tap: tuple[int, int] | None = None
        self._keys: list[str] = []

    async def health(self) -> dict:
        return {
            "ok": True,
            "device_backend": self.name,
            "adb_version": None,
            "scrcpy_version": None,
            "ocr_engine": None,
            "hint": "当前为 Mock 后端，不连接真机",
        }

    async def list_devices(self) -> list[DeviceInfo]:
        return [
            DeviceInfo(
                serial="MOCK-0001",
                state="device",
                model="Mock Pixel 8",
                android="14",
                abi="arm64-v8a",
                wm_size=f"Physical size: {self._width}x{self._height}",
                width=self._width,
                height=self._height,
                transport_id="1",
            )
        ]

    async def create_session(self, serial: str, fps: int) -> MirrorSession:
        if serial != "MOCK-0001":
            raise DeviceNotFound(f"未找到设备 {serial}")
        session_id = f"mock-{self._next_id}"
        self._next_id += 1
        session = MirrorSession(
            id=session_id,
            serial=serial,
            width=self._width,
            height=self._height,
            fps=fps,
            mode="mock",
        )
        self._sessions[session_id] = session
        return session

    async def close_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def get_session(self, session_id: str) -> MirrorSession:
        if session_id not in self._sessions:
            raise SessionNotFound(f"会话不存在: {session_id}")
        return self._sessions[session_id]

    async def frames(self, session_id: str):
        session = self.get_session(session_id)
        while session_id in self._sessions:
            self._seq += 1
            yield Frame(
                seq=self._seq,
                jpeg=self._render(self._seq),
                width=session.width,
                height=session.height,
                ts=time.time(),
            )
            await asyncio.sleep(1.0 / max(session.fps, 1))

    async def tap(
        self,
        session_id: str,
        x: float,
        y: float,
        press_ms: float,
        sigma: float,
        press_stdev: float = 20.0,
    ) -> TapResult:
        session = self.get_session(session_id)
        plan = gaussian_click(
            x,
            y,
            session.width,
            session.height,
            sigma=sigma,
            press_mean=press_ms,
            press_stdev=press_stdev,
        )
        self._last_tap = (plan.real_x, plan.real_y)
        return TapResult(
            target_x=plan.target_x,
            target_y=plan.target_y,
            real_x=plan.real_x,
            real_y=plan.real_y,
            press_ms=plan.press_ms,
            injected_via="mock",
        )

    async def swipe(
        self,
        session_id: str,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        duration_ms: int,
    ) -> SwipeResult:
        session = self.get_session(session_id)
        px1, py1 = normalize_to_device(x1, y1, session.width, session.height)
        px2, py2 = normalize_to_device(x2, y2, session.width, session.height)
        return SwipeResult(points=bezier_points(px1, py1, px2, py2), injected_via="mock")

    async def key(self, session_id: str, key: str) -> None:
        self.get_session(session_id)
        keycode_for(key)
        self._keys.append(key)

    async def screenshot(self, session_id: str) -> bytes:
        self.get_session(session_id)
        image = Image.open(io.BytesIO(self._render(self._seq or 1)))
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        return buffer.getvalue()

    def _render(self, seq: int) -> bytes:
        width, height = self._width // 4, self._height // 4
        image = Image.new("RGB", (width, height), (15, 20, 26))
        draw = ImageDraw.Draw(image)
        draw.rectangle([6, 6, width - 6, height - 6], outline=(70, 200, 160), width=2)
        draw.text((14, 14), f"MOCK seq={seq}", fill=(200, 230, 220))
        draw.text((14, 34), f"tap={self._last_tap}", fill=(160, 200, 255))
        draw.text((14, 54), f"keys={self._keys[-1] if self._keys else None}", fill=(200, 200, 160))
        if self._last_tap:
            px, py = self._last_tap[0] // 4, self._last_tap[1] // 4
            draw.ellipse([px - 6, py - 6, px + 6, py + 6], outline=(255, 120, 120), width=2)
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", quality=self._jpeg_quality)
        return buffer.getvalue()
