from __future__ import annotations

import pytest

from app import verify
from app.api import verify_run


class _NoDeviceAdb:
    """桩：模拟 adb 存在但没有任何在线设备。"""

    def __init__(self, *args, **kwargs) -> None:
        pass

    def devices(self):
        return []


@pytest.fixture
def no_device(monkeypatch, tmp_path):
    monkeypatch.setattr(verify, "AdbRunner", _NoDeviceAdb)
    monkeypatch.setattr(verify_run, "REPORT_DIR", tmp_path)


def test_verify_run_returns_all_checks_without_device(client, no_device):
    response = client.post("/api/verify/run", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["serial"] == ""
    assert body["deviceOnline"] is False
    assert {row["checkId"] for row in body["checks"]} == {f"V{i}" for i in range(1, 11)}
    assert len(body["checks"]) == 10
    assert body["summary"] == {"passed": 0, "failed": 1, "skipped": 9, "ok": False}
    assert "在线设备" in body["hint"]


def test_verify_run_honors_skip_list(client, no_device):
    response = client.post("/api/verify/run", json={"skip": ["v3", "V10"]})

    assert response.status_code == 200
    checks = {row["checkId"]: row for row in response.json()["checks"]}
    assert checks["V3"]["status"] == "SKIP"
    assert checks["V10"]["status"] == "SKIP"
    assert "指定跳过" in checks["V3"]["detail"]


def test_verify_run_rejects_unknown_check_id(client, no_device):
    response = client.post("/api/verify/run", json={"skip": ["V99"]})

    assert response.status_code == 422


def test_verify_run_forwards_requested_serial(client, no_device):
    response = client.post("/api/verify/run", json={"serial": "SERIAL-X"})

    assert response.status_code == 200
    assert response.json()["serial"] == "SERIAL-X"


def test_verify_run_rejects_concurrent_run(client, no_device):
    lock = verify_run._RUN_LOCK
    assert lock.acquire(blocking=False)
    try:
        response = client.post("/api/verify/run", json={})
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "VERIFY_BUSY"
    finally:
        lock.release()
