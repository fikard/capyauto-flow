def test_health_mock(client):
    body = client.get("/api/health").json()
    assert body["ok"] is True
    assert body["device_backend"] == "mock"


def test_list_devices(client):
    body = client.get("/api/devices").json()
    assert body["devices"][0]["serial"] == "MOCK-0001"
    assert body["devices"][0]["state"] == "device"


def test_session_roundtrip(client):
    resp = client.post("/api/session", json={"serial": "MOCK-0001", "fps": 5})
    assert resp.status_code == 200
    body = resp.json()
    assert body["sessionId"].startswith("mock-")
    assert (body["width"], body["height"]) == (1080, 2400)
    assert body["degraded"] is False
    assert client.delete(f"/api/session/{body['sessionId']}").json() == {"ok": True}


def test_session_unknown_device(client):
    resp = client.post("/api/session", json={"serial": "NOPE"})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "DEVICE_NOT_FOUND"
