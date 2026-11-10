import json


def _new_session(client) -> str:
    resp = client.post("/api/session", json={"serial": "MOCK-0001", "fps": 5})
    return resp.json()["sessionId"]


def test_ws_meta_then_jpeg(client):
    session_id = _new_session(client)
    with client.websocket_connect(f"/ws/mirror?sessionId={session_id}") as ws:
        meta = json.loads(ws.receive_text())
        assert meta["type"] == "meta"
        assert meta["width"] == 1080
        assert meta["degraded"] is False
        frame = ws.receive_bytes()
        assert frame[:2] == b"\xff\xd8"
        assert frame[-2:] == b"\xff\xd9"


def test_ws_unknown_session_reports_error(client):
    with client.websocket_connect("/ws/mirror?sessionId=nope") as ws:
        payload = json.loads(ws.receive_text())
        assert payload["type"] == "error"
        assert payload["code"] == "SESSION_NOT_FOUND"
