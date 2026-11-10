from app.errors import (
    AdbNotFound,
    DeviceUnauthorized,
    MirrorLost,
    OutOfBounds,
    ScrcpyUnavailable,
    SessionNotFound,
)


def test_error_codes_and_status():
    assert OutOfBounds().status_code == 400
    assert OutOfBounds("x").code == "OUT_OF_BOUNDS"
    assert DeviceUnauthorized().status_code == 409
    assert AdbNotFound().status_code == 503
    assert SessionNotFound().status_code == 404
    assert ScrcpyUnavailable().status_code == 503
    assert MirrorLost().status_code == 502


def test_payload_shape():
    err = OutOfBounds("坐标越界", detail={"x": 1.2})
    assert err.to_payload() == {
        "error": {"code": "OUT_OF_BOUNDS", "message": "坐标越界", "detail": {"x": 1.2}}
    }
