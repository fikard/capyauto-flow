from app import deps
from app.device.base import UserSwitchResult
from app.errors import AirplaneModeFailed, UserSwitchFailed


def _session(client) -> str:
    device = client.get("/api/devices").json()["devices"][0]
    return client.post("/api/session", json={"serial": device["serial"]}).json()["sessionId"]


def test_launch_and_stop_app(client):
    session_id = _session(client)
    launched = client.post(
        "/api/app/launch",
        json={"sessionId": session_id, "package": "com.hb.cncapy.and", "user": 0},
    )
    assert launched.status_code == 200
    body = launched.json()
    assert body["ok"] is True
    assert body["usedUser"] == 0
    assert body["package"] == "com.hb.cncapy.and"
    assert body["activity"] == "mock.MainActivity"
    assert body["pid"] == 4242
    stopped = client.post(
        "/api/app/stop", json={"sessionId": session_id, "package": "com.hb.cncapy.and"}
    )
    assert stopped.status_code == 200
    assert stopped.json() == {"ok": True}


def test_current_app_returns_status(client):
    session_id = _session(client)
    body = client.get("/api/app/current", params={"sessionId": session_id}).json()
    assert {"package", "activity", "running", "pid"} <= set(body)
    assert body["pid"] is None
    assert body["running"] is False


def test_users_and_switch_user(client):
    session_id = _session(client)
    users = client.get("/api/app/users", params={"sessionId": session_id}).json()
    assert users["switchSupported"] is True
    assert users["users"][0]["current"] is True
    switched = client.post(
        "/api/app/switch-user", json={"sessionId": session_id, "userId": 999}
    ).json()
    assert switched["ok"] is True
    assert switched["userId"] == 999
    current = client.get("/api/app/users", params={"sessionId": session_id}).json()
    assert [u["id"] for u in current["users"] if u["current"]] == [999]


def test_unknown_session_returns_404(client):
    response = client.post(
        "/api/app/stop", json={"sessionId": "nope", "package": "com.hb.cncapy.and"}
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"


def test_unknown_session_for_users_and_current_returns_404(client):
    users = client.get("/api/app/users", params={"sessionId": "nope"})
    assert users.status_code == 404
    assert users.json()["error"]["code"] == "SESSION_NOT_FOUND"
    current = client.get("/api/app/current", params={"sessionId": "nope"})
    assert current.status_code == 404
    assert current.json()["error"]["code"] == "SESSION_NOT_FOUND"


def test_airplane_toggle(client):
    session_id = _session(client)
    on = client.post(
        "/api/network/airplane", json={"sessionId": session_id, "enable": True}
    ).json()
    assert on["ok"] is True and on["airplaneModeOn"] is True
    off = client.post(
        "/api/network/airplane", json={"sessionId": session_id, "enable": False}
    ).json()
    assert off["airplaneModeOn"] is False


def test_airplane_failure_returns_502(client, monkeypatch):
    session_id = _session(client)
    adapter = deps.get_adapter()

    async def fail(session_id: str, enable: bool):
        raise AirplaneModeFailed("飞行模式读回不一致")

    monkeypatch.setattr(adapter, "set_airplane_mode", fail)
    response = client.post(
        "/api/network/airplane", json={"sessionId": session_id, "enable": True}
    )
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "AIRPLANE_MODE_FAILED"


def test_switch_user_failure_returns_502(client, monkeypatch):
    session_id = _session(client)
    adapter = deps.get_adapter()

    async def fail(session_id: str, user_id: int):
        raise UserSwitchFailed(f"切换用户失败：期望 {user_id}，实际 0")

    monkeypatch.setattr(adapter, "switch_user", fail)
    response = client.post(
        "/api/app/switch-user", json={"sessionId": session_id, "userId": 999}
    )
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "USER_SWITCH_FAILED"


def test_switch_user_unsupported_returns_200(client, monkeypatch):
    session_id = _session(client)
    adapter = deps.get_adapter()

    async def unsupported(session_id: str, user_id: int):
        return UserSwitchResult(
            ok=False,
            user_id=user_id,
            switch_supported=False,
            reason="设备仅有一个用户，系统不支持应用分身切换",
        )

    monkeypatch.setattr(adapter, "switch_user", unsupported)
    response = client.post(
        "/api/app/switch-user", json={"sessionId": session_id, "userId": 999}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["switchSupported"] is False
    assert body["reason"]
