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


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
