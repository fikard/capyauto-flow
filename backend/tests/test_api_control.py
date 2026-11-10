def _session(client) -> str:
    return client.post("/api/session", json={"serial": "MOCK-0001", "fps": 5}).json()["sessionId"]


def test_tap_returns_target_and_real(client):
    session_id = _session(client)
    body = client.post(
        "/api/control/tap",
        json={"sessionId": session_id, "x": 0.5, "y": 0.5, "sigma": 0, "pressMs": 80, "pressStdev": 0},
    ).json()
    assert (body["targetX"], body["targetY"]) == (540, 1200)
    assert (body["realX"], body["realY"]) == (540, 1200)
    assert body["pressMs"] == 80
    assert body["injectedVia"] == "mock"
    assert (body["deviceWidth"], body["deviceHeight"]) == (1080, 2400)


def test_tap_out_of_bounds(client):
    session_id = _session(client)
    resp = client.post("/api/control/tap", json={"sessionId": session_id, "x": 1.4, "y": 0.5})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "OUT_OF_BOUNDS"


def test_tap_unknown_session(client):
    resp = client.post("/api/control/tap", json={"sessionId": "nope", "x": 0.5, "y": 0.5})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "SESSION_NOT_FOUND"


def test_swipe_returns_points(client):
    session_id = _session(client)
    body = client.post(
        "/api/control/swipe",
        json={"sessionId": session_id, "x1": 0.5, "y1": 0.8, "x2": 0.5, "y2": 0.2, "durationMs": 300},
    ).json()
    assert len(body["points"]) == 11
    assert body["points"][0] == [540, 1920]
    assert body["injectedVia"] == "mock"


def test_key_unknown(client):
    session_id = _session(client)
    resp = client.post("/api/control/key", json={"sessionId": session_id, "key": "nope"})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "UNKNOWN_KEY"


def test_key_back_ok(client):
    session_id = _session(client)
    assert client.post("/api/control/key", json={"sessionId": session_id, "key": "back"}).json() == {"ok": True}
