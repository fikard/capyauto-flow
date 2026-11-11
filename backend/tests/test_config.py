from dataclasses import FrozenInstanceError

import pytest

from app.config import Settings


def test_defaults_when_env_missing(monkeypatch):
    for name in (
        "CAPYAUTO_BACKEND_PORT",
        "CAPYAUTO_FRONTEND_PORT",
        "CAPYAUTO_DEVICE_BACKEND",
        "CAPYAUTO_MIRROR_FPS",
    ):
        monkeypatch.delenv(name, raising=False)
    cfg = Settings()
    assert cfg.backend_port == 8084
    assert cfg.frontend_port == 5178
    assert cfg.device_backend == "mock"
    assert cfg.mirror_fps == 5


def test_env_override(monkeypatch):
    monkeypatch.setenv("CAPYAUTO_BACKEND_PORT", "9099")
    monkeypatch.setenv("CAPYAUTO_DEVICE_BACKEND", "adb")
    cfg = Settings()
    assert cfg.backend_port == 9099
    assert cfg.device_backend == "adb"


def test_empty_string_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("CAPYAUTO_BACKEND_PORT", "")
    monkeypatch.setenv("CAPYAUTO_FRAME_TIMEOUT", "")
    cfg = Settings()
    assert cfg.backend_port == 8084
    assert cfg.frame_timeout == 10.0


def test_non_numeric_backend_port_raises_system_exit(monkeypatch):
    monkeypatch.setenv("CAPYAUTO_BACKEND_PORT", "abc")
    with pytest.raises(SystemExit):
        Settings()


def test_non_numeric_frame_timeout_raises_system_exit(monkeypatch):
    monkeypatch.setenv("CAPYAUTO_FRAME_TIMEOUT", "abc")
    with pytest.raises(SystemExit):
        Settings()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("CAPYAUTO_BACKEND_PORT", "70000"),
        ("CAPYAUTO_MIRROR_FPS", "0"),
        ("CAPYAUTO_JPEG_QUALITY", "999"),
        ("CAPYAUTO_DISPLAY_WIDTH", "0"),
    ],
)
def test_out_of_range_raises_system_exit(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(SystemExit):
        Settings()


def test_frame_timeout_accepts_float(monkeypatch):
    monkeypatch.setenv("CAPYAUTO_FRAME_TIMEOUT", "2.5")
    assert Settings().frame_timeout == 2.5


def test_ocr_max_ms_defaults_and_override(monkeypatch):
    monkeypatch.delenv("CAPYAUTO_OCR_MAX_MS", raising=False)
    assert Settings().ocr_max_ms == 5000.0
    monkeypatch.setenv("CAPYAUTO_OCR_MAX_MS", "1500")
    assert Settings().ocr_max_ms == 1500.0


def test_ocr_max_ms_rejects_value_beyond_ocr_timeout(monkeypatch):
    monkeypatch.setenv("CAPYAUTO_OCR_MAX_MS", "30001")
    with pytest.raises(SystemExit):
        Settings()


def test_allow_screencap_fallback_false(monkeypatch):
    monkeypatch.setenv("CAPYAUTO_ALLOW_SCREENCAP_FALLBACK", "false")
    assert Settings().allow_screencap_fallback is False


def test_empty_scrcpy_version_is_none(monkeypatch):
    monkeypatch.setenv("CAPYAUTO_SCRCPY_VERSION", "")
    assert Settings().scrcpy_version is None


def test_settings_is_frozen():
    cfg = Settings()
    with pytest.raises(FrozenInstanceError):
        setattr(cfg, "backend_port", 1234)
