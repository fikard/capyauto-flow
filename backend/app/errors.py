from __future__ import annotations

from typing import Any


class ApiError(Exception):
    status_code = 400
    code = "BAD_REQUEST"

    def __init__(
        self,
        message: str | None = None,
        *,
        status_code: int | None = None,
        code: str | None = None,
        detail: Any = None,
    ) -> None:
        self.message = message or code or self.code
        if status_code is not None:
            self.status_code = status_code
        if code is not None:
            self.code = code
        self.detail = detail
        super().__init__(self.message)

    def to_payload(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message, "detail": self.detail}}


class OutOfBounds(ApiError):
    status_code = 400
    code = "OUT_OF_BOUNDS"


class UnknownKey(ApiError):
    status_code = 400
    code = "UNKNOWN_KEY"


class DeviceNotFound(ApiError):
    status_code = 404
    code = "DEVICE_NOT_FOUND"


class SessionNotFound(ApiError):
    status_code = 404
    code = "SESSION_NOT_FOUND"


class DeviceUnauthorized(ApiError):
    status_code = 409
    code = "DEVICE_UNAUTHORIZED"


class MultipleDevices(ApiError):
    status_code = 409
    code = "MULTIPLE_DEVICES"


class AdbNotFound(ApiError):
    status_code = 503
    code = "ADB_NOT_FOUND"


class AdbError(ApiError):
    status_code = 502
    code = "ADB_FAILED"


class AdbTimeout(AdbError):
    status_code = 504
    code = "ADB_TIMEOUT"


class ScrcpyUnavailable(ApiError):
    status_code = 503
    code = "SCRCPY_UNAVAILABLE"


class MirrorLost(ApiError):
    status_code = 502
    code = "MIRROR_LOST"


class InjectionFailed(ApiError):
    status_code = 502
    code = "INJECTION_FAILED"
