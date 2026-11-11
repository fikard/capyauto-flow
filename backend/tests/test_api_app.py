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
    stopped = client.post(
        "/api/app/stop", json={"sessionId": session_id, "package": "com.hb.cncapy.and"}
    )
    assert stopped.status_code == 200
    assert stopped.json() == {"ok": True}


def test_current_app_returns_status(client):
    session_id = _session(client)
    body = client.get("/api/app/current", params={"sessionId": session_id}).json()
    assert {"package", "activity", "running", "pid"} <= set(body)


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
