import pytest

from app.errors import (
    AdbError,
    AdbNotFound,
    AdbTimeout,
    ApiError,
    DeviceNotFound,
    DeviceUnauthorized,
    InjectionFailed,
    MirrorLost,
    MultipleDevices,
    OutOfBounds,
    ScrcpyUnavailable,
    SessionNotFound,
    UnknownKey,
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


@pytest.mark.parametrize(
    ("error_cls", "status_code", "code"),
    [
        (OutOfBounds, 400, "OUT_OF_BOUNDS"),
        (UnknownKey, 400, "UNKNOWN_KEY"),
        (DeviceNotFound, 404, "DEVICE_NOT_FOUND"),
        (SessionNotFound, 404, "SESSION_NOT_FOUND"),
        (DeviceUnauthorized, 409, "DEVICE_UNAUTHORIZED"),
        (MultipleDevices, 409, "MULTIPLE_DEVICES"),
        (AdbNotFound, 503, "ADB_NOT_FOUND"),
        (AdbError, 502, "ADB_FAILED"),
        (AdbTimeout, 504, "ADB_TIMEOUT"),
        (ScrcpyUnavailable, 503, "SCRCPY_UNAVAILABLE"),
        (MirrorLost, 502, "MIRROR_LOST"),
        (InjectionFailed, 502, "INJECTION_FAILED"),
    ],
)
def test_all_error_classes_status_and_code(error_cls, status_code, code):
    err = error_cls()
    assert err.status_code == status_code
    assert err.code == code


def test_adb_timeout_is_adb_error():
    assert issubclass(AdbTimeout, AdbError)


def test_api_error_defaults():
    err = ApiError()
    assert err.status_code == 400
    assert err.code == "BAD_REQUEST"
    assert err.to_payload() == {
        "error": {"code": "BAD_REQUEST", "message": "BAD_REQUEST", "detail": None}
    }


def test_api_error_instance_overrides():
    err = ApiError("m", status_code=418, code="X", detail={"a": 1})
    assert err.status_code == 418
    assert err.code == "X"
    assert err.message == "m"
    assert err.detail == {"a": 1}
    assert err.to_payload() == {"error": {"code": "X", "message": "m", "detail": {"a": 1}}}


def test_api_error_message_falls_back_to_code():
    assert ApiError(code="Y").message == "Y"
    assert OutOfBounds().message == "OUT_OF_BOUNDS"
