import json

import pytest
from fastapi.testclient import TestClient

from app import accounts as accounts_module
from app.main import app


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = tmp_path / "accounts.json"
    monkeypatch.setenv("CAPYAUTO_ACCOUNTS", str(path))
    return path


def seed(store):
    """三个账号，各有 works / lastRun / 存档指标。"""
    accounts_module.ensure_account("风零", power=100, stamina=50, at=1.0)
    accounts_module.ensure_account("风壹", power=200, stamina=60, at=2.0)
    accounts_module.ensure_account("你瞅啥呢", power=999, stamina=99, at=3.0)
    accounts_module.record_work("风零", "daily", at=10.0)
    accounts_module.record_work("风零", "stage", at=11.0)
    accounts_module.record_work("风壹", "guild", at=12.0)
    accounts_module.record_account_run("风零", "run1", "completed", at=13.0)


def test_reset_all_clears_works_but_keeps_identity_and_history(store):
    seed(store)

    result = accounts_module.reset_account_works()

    assert result["reset"] == 3
    by_name = {a["name"]: a for a in accounts_module.load_accounts()}
    for name in ("风零", "风壹", "你瞅啥呢"):
        assert by_name[name]["works"] == {}
        assert by_name[name]["power"] > 0  # 指标保留
        assert "createdAt" in by_name[name]
    assert by_name["风零"]["lastRun"]["runId"] == "run1"  # lastRun 保留


def test_reset_subset_only_targets_named_accounts(store):
    seed(store)

    result = accounts_module.reset_account_works(names=["风壹"])

    assert result["reset"] == 1
    by_name = {a["name"]: a for a in accounts_module.load_accounts()}
    assert by_name["风壹"]["works"] == {}
    assert "daily" in by_name["风零"]["works"]  # 其他账号不受影响


def test_reset_unknown_name_is_ignored(store):
    seed(store)

    result = accounts_module.reset_account_works(names=["不存在"])

    assert result["reset"] == 0
    assert accounts_module.load_accounts()[0]["works"]


def test_reset_at_timestamp_is_recorded(store):
    seed(store)

    result = accounts_module.reset_account_works(at=999.0)

    assert result["at"] == 999.0
    raw = json.loads(store.read_text("utf-8"))
    for entry in raw["accounts"]:
        assert entry["worksResetAt"] == 999.0


def test_reset_api_endpoint(store):
    seed(store)
    client = TestClient(app)

    resp = client.post("/api/accounts/reset", json={"names": ["风零"]})

    assert resp.status_code == 200
    assert resp.json()["reset"] == 1
    by_name = {a["name"]: a for a in accounts_module.load_accounts()}
    assert by_name["风零"]["works"] == {}
    assert "guild" in by_name["风壹"]["works"]
