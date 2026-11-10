from __future__ import annotations

import io
import logging
import threading
import time

from PIL import Image

from app.device.adb import AdbRunner
from app.device.base import Frame

log = logging.getLogger("capyauto.screencap")


class ScreencapPoller:
    """scrcpy 不可用时的降级通道：按目标帧率轮询 screencap -p，再编码成 JPEG。"""

    def __init__(
        self,
        adb: AdbRunner,
        serial: str,
        width: int,
        height: int,
        fps: int,
        jpeg_quality: int,
        display_width: int,
    ) -> None:
        self._adb = adb
        self._serial = serial
        self.width = width
        self.height = height
        self._fps = max(1, fps)
        self._jpeg_quality = jpeg_quality
        self._display_width = display_width
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._frame: Frame | None = None
        self._seq = 0
        self._thread: threading.Thread | None = None
        self.last_error: str | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name=f"screencap-{self._serial}", daemon=True)
        self._thread.start()

    def latest(self) -> Frame | None:
        with self._lock:
            return self._frame

    def _loop(self) -> None:
        interval = 1.0 / self._fps
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                png = self._adb.exec_out(self._serial, "screencap", "-p")
                image = Image.open(io.BytesIO(png)).convert("RGB")
                self.width, self.height = image.size
                if image.width > self._display_width:
                    ratio = self._display_width / image.width
                    image = image.resize(
                        (self._display_width, max(1, int(image.height * ratio))), Image.BILINEAR
                    )
                buffer = io.BytesIO()
                image.save(buffer, "JPEG", quality=self._jpeg_quality)
                with self._lock:
                    self._seq += 1
                    self._frame = Frame(
                        seq=self._seq,
                        jpeg=buffer.getvalue(),
                        width=image.width,
                        height=image.height,
                        ts=time.time(),
                    )
                self.last_error = None
            except Exception as exc:  # noqa: BLE001 - 降级通道不因单次失败退出
                self.last_error = str(exc)
                log.warning("screencap 失败: %s", exc)
            elapsed = time.monotonic() - started
            time.sleep(max(0.0, interval - elapsed))

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=3)
