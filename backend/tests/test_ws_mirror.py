import json

import pytest
from starlette.websockets import WebSocketDisconnect


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
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_text()
        assert exc.value.code == 4404


def test_ws_ping_pong_survives_invalid_json(client):
    session_id = _new_session(client)
    with client.websocket_connect(f"/ws/mirror?sessionId={session_id}") as ws:
        assert json.loads(ws.receive_text())["type"] == "meta"
        ws.send_text("not-json")
        ws.send_text(json.dumps({"type": "ping"}))
        for _ in range(40):
            message = ws.receive()
            text = message.get("text")
            if text and json.loads(text).get("type") == "pong":
                return
        pytest.fail("非 JSON 文本后未收到 pong")
