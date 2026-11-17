import dataclasses

import pytest
from fastapi.testclient import TestClient

from app import config, deps
from app.main import app


@pytest.fixture(autouse=True)
def mock_backend(monkeypatch):
    cfg = dataclasses.replace(config.settings, device_backend="mock")
    monkeypatch.setattr(config, "settings", cfg)
    deps.reset_adapter()
    yield
    deps.reset_adapter()


@pytest.fixture(autouse=True)
def isolated_runtime_data(tmp_path, monkeypatch):
    """推关录制脚本和账号集合写到临时目录，避免测试污染仓库内的运行数据"""
    monkeypatch.setenv("CAPYAUTO_STAGE_SCRIPT", str(tmp_path / "stage_script.json"))
    monkeypatch.setenv("CAPYAUTO_ACCOUNTS", str(tmp_path / "accounts.json"))


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
