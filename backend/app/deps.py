from __future__ import annotations

from app import config
from app.device.base import DeviceAdapter
from app.device.mock_device import MockDevice

_adapter: DeviceAdapter | None = None


def build_adapter(cfg: config.Settings | None = None) -> DeviceAdapter:
    cfg = cfg or config.settings
    if cfg.device_backend == "mock":
        return MockDevice(jpeg_quality=cfg.jpeg_quality)
    if cfg.device_backend == "adb":
        from app.device.adb import AdbRunner
        from app.device.adb_device import AdbScrcpyDevice

        return AdbScrcpyDevice(
            adb=AdbRunner(cfg.adb_path),
            server_bin=cfg.scrcpy_bin,
            server_jar=cfg.scrcpy_server,
            server_version=cfg.scrcpy_version,
            tcp_port=cfg.scrcpy_tcp_port,
            fps=cfg.mirror_fps,
            bitrate=cfg.scrcpy_bitrate,
            jpeg_quality=cfg.jpeg_quality,
            display_width=cfg.display_width,
            frame_timeout=cfg.frame_timeout,
            allow_fallback=cfg.allow_screencap_fallback,
        )
    raise SystemExit(f"未知 CAPYAUTO_DEVICE_BACKEND={cfg.device_backend}，可选 mock|adb")


def get_adapter() -> DeviceAdapter:
    global _adapter
    if _adapter is None:
        _adapter = build_adapter()
    return _adapter


def reset_adapter() -> None:
    global _adapter
    _adapter = None
