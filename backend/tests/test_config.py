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
