import json

from app import accounts as accounts_module


def test_record_work_creates_account_entry(tmp_path, monkeypatch):
    path = tmp_path / "accounts.json"
    monkeypatch.setenv("CAPYAUTO_ACCOUNTS", str(path))

    entry = accounts_module.record_work("风叁", "daily", power=268200, stamina=70, at=100.0)

    assert entry["name"] == "风叁"
    assert entry["works"]["daily"]["count"] == 1
    assert entry["works"]["daily"]["doneAt"] == 100.0
    saved = json.loads(path.read_text("utf-8"))
    assert saved["accounts"][0]["power"] == 268200


def test_record_work_accumulates_and_keeps_other_works(tmp_path, monkeypatch):
    monkeypatch.setenv("CAPYAUTO_ACCOUNTS", str(tmp_path / "accounts.json"))

    accounts_module.record_work("风叁", "daily", at=100.0)
    accounts_module.record_work("风叁", "stage", at=200.0)
    entry = accounts_module.record_work("风叁", "daily", at=300.0)

    assert entry["works"]["daily"]["count"] == 2
    assert entry["works"]["daily"]["doneAt"] == 300.0
    assert entry["works"]["stage"]["doneAt"] == 200.0
    assert len(accounts_module.load_accounts()) == 1


def test_record_work_ignores_unknown_work_or_empty_name(tmp_path, monkeypatch):
    monkeypatch.setenv("CAPYAUTO_ACCOUNTS", str(tmp_path / "accounts.json"))

    assert accounts_module.record_work("", "daily") is None
    assert accounts_module.record_work("风叁", "arena") is None
    assert accounts_module.load_accounts() == []


def test_account_summary_marks_finished_works(tmp_path, monkeypatch):
    monkeypatch.setenv("CAPYAUTO_ACCOUNTS", str(tmp_path / "accounts.json"))
    accounts_module.record_work("风叁", "daily", at=100.0)

    summary = accounts_module.account_summary()

    assert summary[0]["name"] == "风叁"
    assert summary[0]["works"]["daily"]["done"] is True
    assert summary[0]["works"]["guild"]["done"] is False
    assert [work for work in accounts_module.WORK_KEYS] == ["daily", "guild", "ship", "stage"]


def test_ensure_account_registers_without_work(tmp_path, monkeypatch):
    monkeypatch.setenv("CAPYAUTO_ACCOUNTS", str(tmp_path / "accounts.json"))

    entry = accounts_module.ensure_account("风陆", power=175700, stamina=491)

    assert entry["works"] == {}
    summary = accounts_module.account_summary()
    assert summary[0]["name"] == "风陆"
    assert summary[0]["power"] == 175700
    assert summary[0]["works"]["daily"]["done"] is False


def test_accounts_api_returns_collection(client, tmp_path, monkeypatch):
    monkeypatch.setenv("CAPYAUTO_ACCOUNTS", str(tmp_path / "accounts.json"))
    accounts_module.record_work("风叁", "guild", at=100.0)

    response = client.get("/api/accounts")

    assert response.status_code == 200
    payload = response.json()
    assert payload["accounts"][0]["name"] == "风叁"
    assert payload["accounts"][0]["works"]["guild"]["done"] is True


def test_record_account_run_tracks_lifecycle_and_keeps_works(tmp_path, monkeypatch):
    monkeypatch.setenv("CAPYAUTO_ACCOUNTS", str(tmp_path / "accounts.json"))
    accounts_module.record_work("风贰", "daily", at=100.0)

    accounts_module.record_account_run(
        "风贰",
        "run-1",
        "running",
        current_phase="travel",
        progress={"travelSpent": 100},
        at=200.0,
    )
    entry = accounts_module.record_account_run(
        "风贰",
        "run-1",
        "completed",
        current_phase="done",
        progress={"travelSpent": 200, "stageRuns": 1},
        at=300.0,
    )

    assert entry["works"]["daily"]["count"] == 1
    assert entry["lastRun"] == {
        "runId": "run-1",
        "status": "completed",
        "currentPhase": "done",
        "error": "",
        "startedAt": 200.0,
        "updatedAt": 300.0,
        "progress": {"travelSpent": 200, "stageRuns": 1},
    }
    assert accounts_module.account_summary()[0]["lastRun"] == entry["lastRun"]


def test_save_accounts_replaces_file_atomically(tmp_path, monkeypatch):
    path = tmp_path / "accounts.json"
    monkeypatch.setenv("CAPYAUTO_ACCOUNTS", str(path))
    replacements = []
    real_replace = accounts_module.os.replace

    def replace(src, dst):
        replacements.append((src, dst))
        real_replace(src, dst)

    monkeypatch.setattr(accounts_module.os, "replace", replace)
    accounts_module.ensure_account("风零", at=100.0)

    assert len(replacements) == 1
    assert replacements[0][1] == path
    assert json.loads(path.read_text("utf-8"))["accounts"][0]["name"] == "风零"
    assert list(tmp_path.iterdir()) == [path]


def test_account_run_report_api_records_autox_progress(client, tmp_path, monkeypatch):
    monkeypatch.setenv("CAPYAUTO_ACCOUNTS", str(tmp_path / "accounts.json"))

    response = client.post(
        "/api/accounts/report",
        json={
            "runId": "autox-run-1",
            "account": "风贰",
            "status": "completed",
            "currentPhase": "done",
            "travelSpent": 100,
            "error": "",
        },
    )

    assert response.status_code == 200
    last_run = response.json()["account"]["lastRun"]
    assert last_run["runId"] == "autox-run-1"
    assert last_run["status"] == "completed"
    assert last_run["progress"] == {"travelSpent": 100}


def test_account_run_report_api_records_autox_stamina(client, tmp_path, monkeypatch):
    monkeypatch.setenv("CAPYAUTO_ACCOUNTS", str(tmp_path / "accounts.json"))

    response = client.post(
        "/api/accounts/report",
        json={
            "runId": "autox-run-2",
            "account": "风贰",
            "status": "completed",
            "currentPhase": "done",
            "travelSpent": 100,
            "staminaBefore": 125,
        },
    )

    assert response.status_code == 200
    assert response.json()["account"]["lastRun"]["progress"] == {
        "travelSpent": 100,
        "staminaBefore": 125,
    }


def test_account_run_report_api_rejects_negative_stamina(client, tmp_path, monkeypatch):
    monkeypatch.setenv("CAPYAUTO_ACCOUNTS", str(tmp_path / "accounts.json"))

    response = client.post(
        "/api/accounts/report",
        json={
            "runId": "autox-run-3",
            "account": "风贰",
            "status": "completed",
            "staminaBefore": -1,
        },
    )

    assert response.status_code == 422
