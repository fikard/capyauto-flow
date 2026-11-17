def test_health_mock(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["device_backend"] == "mock"


def test_devgate_frontend_origin_allowed(client):
    origin = "http://frontend.capyauto-flow.test"
    resp = client.get("/api/health", headers={"Origin": origin})
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == origin


def test_list_devices(client):
    resp = client.get("/api/devices")
    assert resp.status_code == 200
    body = resp.json()
    assert body["devices"][0]["serial"] == "MOCK-0001"
    assert body["devices"][0]["state"] == "device"


def test_session_roundtrip(client):
    resp = client.post("/api/session", json={"serial": "MOCK-0001", "fps": 5})
    assert resp.status_code == 200
    body = resp.json()
    assert body["sessionId"].startswith("mock-")
    assert (body["width"], body["height"]) == (1080, 2400)
    assert body["degraded"] is False
    closed = client.delete(f"/api/session/{body['sessionId']}")
    assert closed.status_code == 200
    assert closed.json() == {"ok": True}


def test_session_unknown_device(client):
    resp = client.post("/api/session", json={"serial": "NOPE"})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "DEVICE_NOT_FOUND"


def test_close_unknown_session(client):
    created = client.post("/api/session", json={"serial": "MOCK-0001", "fps": 5})
    assert created.status_code == 200
    session_id = created.json()["sessionId"]
    assert client.delete(f"/api/session/{session_id}").status_code == 200

    again = client.delete(f"/api/session/{session_id}")
    assert again.status_code == 404
    assert again.json()["error"]["code"] == "SESSION_NOT_FOUND"

    nope = client.delete("/api/session/nope")
    assert nope.status_code == 404
    assert nope.json()["error"]["code"] == "SESSION_NOT_FOUND"
