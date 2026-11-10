from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise SystemExit(f"环境变量 {name} 必须是整数，实际为 {raw!r}") from exc


def _detect_scrcpy_server() -> Path | None:
    explicit = os.environ.get("CAPYAUTO_SCRCPY_SERVER")
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    for prefix in ("/opt/homebrew", "/usr/local"):
        candidates.append(Path(prefix) / "share/scrcpy/scrcpy-server")
        cellar = Path(prefix) / "Cellar/scrcpy"
        if cellar.is_dir():
            candidates.extend(sorted(cellar.glob("*/share/scrcpy/scrcpy-server"), reverse=True))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


@dataclass(frozen=True)
class Settings:
    backend_port: int = field(default_factory=lambda: _env_int("CAPYAUTO_BACKEND_PORT", 8084))
    frontend_port: int = field(default_factory=lambda: _env_int("CAPYAUTO_FRONTEND_PORT", 5178))
    device_backend: str = field(default_factory=lambda: os.environ.get("CAPYAUTO_DEVICE_BACKEND", "mock"))
    adb_path: str = field(default_factory=lambda: os.environ.get("CAPYAUTO_ADB", "adb"))
    scrcpy_bin: str = field(default_factory=lambda: os.environ.get("CAPYAUTO_SCRCPY", "scrcpy"))
    scrcpy_server: Path | None = field(default_factory=_detect_scrcpy_server)
    scrcpy_version: str | None = field(default_factory=lambda: os.environ.get("CAPYAUTO_SCRCPY_VERSION"))
    scrcpy_tcp_port: int = field(default_factory=lambda: _env_int("CAPYAUTO_SCRCPY_TCP_PORT", 27183))
    mirror_fps: int = field(default_factory=lambda: _env_int("CAPYAUTO_MIRROR_FPS", 5))
    display_width: int = field(default_factory=lambda: _env_int("CAPYAUTO_DISPLAY_WIDTH", 720))
    jpeg_quality: int = field(default_factory=lambda: _env_int("CAPYAUTO_JPEG_QUALITY", 70))
    scrcpy_bitrate: int = field(default_factory=lambda: _env_int("CAPYAUTO_SCRCPY_BITRATE", 8_000_000))
    frame_timeout: float = field(default_factory=lambda: float(os.environ.get("CAPYAUTO_FRAME_TIMEOUT", "10")))
    allow_screencap_fallback: bool = field(
        default_factory=lambda: os.environ.get("CAPYAUTO_ALLOW_SCREENCAP_FALLBACK", "1") != "0"
    )


settings = Settings()
