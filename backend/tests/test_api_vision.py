import app.api.vision as vision_api


def _session(client) -> str:
    device = client.get("/api/devices").json()["devices"][0]
    return client.post("/api/session", json={"serial": device["serial"]}).json()["sessionId"]


def test_ocr_returns_items(client, monkeypatch):
    from app.vision.ocr import OcrItem

    monkeypatch.setattr(vision_api, "engine_available", lambda: True)
    monkeypatch.setattr(vision_api, "engine_name", lambda: "fake-ocr")
    monkeypatch.setattr(
        vision_api,
        "ocr_png",
        lambda png, region=None: [OcrItem(text="伤害减免", confidence=0.9, bounds=(0.1, 0.2, 0.3, 0.4))],
    )
    session_id = _session(client)
    body = client.post("/api/vision/ocr", json={"sessionId": session_id}).json()
    assert body["items"][0]["text"] == "伤害减免"
    assert body["items"][0]["confidence"] == 0.9
    assert body["items"][0]["bounds"] == {"left": 0.1, "top": 0.2, "right": 0.3, "bottom": 0.4}
    assert body["tookMs"] >= 0
    assert body["engine"] == "fake-ocr"


def test_ocr_empty_returns_empty_items(client, monkeypatch):
    monkeypatch.setattr(vision_api, "engine_available", lambda: True)
    monkeypatch.setattr(vision_api, "ocr_png", lambda png, region=None: [])
    session_id = _session(client)
    body = client.post("/api/vision/ocr", json={"sessionId": session_id}).json()
    assert body["items"] == []


def test_ocr_unavailable_returns_503(client, monkeypatch):
    monkeypatch.setattr(vision_api, "engine_available", lambda: False)
    session_id = _session(client)
    response = client.post("/api/vision/ocr", json={"sessionId": session_id})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "OCR_UNAVAILABLE"
