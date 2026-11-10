from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _check_range(name: str, value: int | float, lo: int | float | None, hi: int | float | None) -> None:
    if lo is not None and value < lo:
        raise SystemExit(f"环境变量 {name} 不能小于 {lo}，实际为 {value!r}")
    if hi is not None and value > hi:
        raise SystemExit(f"环境变量 {name} 不能大于 {hi}，实际为 {value!r}")


def _env_int(name: str, default: int, *, lo: int | None = None, hi: int | None = None) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        value = default
    else:
        try:
            value = int(raw)
        except ValueError as exc:
            raise SystemExit(f"环境变量 {name} 必须是整数，实际为 {raw!r}") from exc
    _check_range(name, value, lo, hi)
    return value


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise SystemExit(f"环境变量 {name} 必须是数字，实际为 {raw!r}") from exc
    if value <= 0:
        raise SystemExit(f"环境变量 {name} 必须大于 0，实际为 {raw!r}")
    return value


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off", ""}


def _cellar_version_key(path: Path) -> tuple[int, ...]:
    version = path.parents[2].name
    return tuple(int(part) for part in version.split(".") if part.isdigit())


def _detect_scrcpy_server() -> Path | None:
    explicit = os.environ.get("CAPYAUTO_SCRCPY_SERVER")
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    for prefix in ("/opt/homebrew", "/usr/local"):
        candidates.append(Path(prefix) / "share/scrcpy/scrcpy-server")
        cellar = Path(prefix) / "Cellar/scrcpy"
        if cellar.is_dir():
            candidates.extend(sorted(cellar.glob("*/share/scrcpy/scrcpy-server"), key=_cellar_version_key, reverse=True))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


@dataclass(frozen=True)
class Settings:
    backend_port: int = field(default_factory=lambda: _env_int("CAPYAUTO_BACKEND_PORT", 8084, lo=1, hi=65535))
    frontend_port: int = field(default_factory=lambda: _env_int("CAPYAUTO_FRONTEND_PORT", 5178))
    device_backend: str = field(default_factory=lambda: os.environ.get("CAPYAUTO_DEVICE_BACKEND", "mock"))
    adb_path: str = field(default_factory=lambda: os.environ.get("CAPYAUTO_ADB", "adb"))
    scrcpy_bin: str = field(default_factory=lambda: os.environ.get("CAPYAUTO_SCRCPY", "scrcpy"))
    scrcpy_server: Path | None = field(default_factory=_detect_scrcpy_server)
    scrcpy_version: str | None = field(default_factory=lambda: os.environ.get("CAPYAUTO_SCRCPY_VERSION"))
    scrcpy_tcp_port: int = field(
        default_factory=lambda: _env_int("CAPYAUTO_SCRCPY_TCP_PORT", 27183, lo=1, hi=65535)
    )
    mirror_fps: int = field(default_factory=lambda: _env_int("CAPYAUTO_MIRROR_FPS", 5, lo=1, hi=10))
    display_width: int = field(default_factory=lambda: _env_int("CAPYAUTO_DISPLAY_WIDTH", 720))
    jpeg_quality: int = field(default_factory=lambda: _env_int("CAPYAUTO_JPEG_QUALITY", 70, lo=1, hi=100))
    scrcpy_bitrate: int = field(default_factory=lambda: _env_int("CAPYAUTO_SCRCPY_BITRATE", 8_000_000, lo=1))
    frame_timeout: float = field(default_factory=lambda: _env_float("CAPYAUTO_FRAME_TIMEOUT", 10.0))
    allow_screencap_fallback: bool = field(
        default_factory=lambda: _env_bool("CAPYAUTO_ALLOW_SCREENCAP_FALLBACK", True)
    )


settings = Settings()
