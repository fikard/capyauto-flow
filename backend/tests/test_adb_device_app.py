import asyncio

import pytest

from app.device.adb_device import AdbScrcpyDevice
from app.device.base import MirrorSession
from app.errors import AirplaneModeFailed, UserSwitchFailed

TWO_USERS = {
    "pm list users": "Users:\n\tUserInfo{0:机主:4c13} running\n\tUserInfo{999:分身:4c14}\n",
    "pm list packages --user 0 com.hb.cncapy.and": "package:com.hb.cncapy.and\n",
    "pm list packages --user 999 com.hb.cncapy.and": "package:com.hb.cncapy.and\n",
}


class FakeAdb:
    def __init__(self, responses: dict[str, str]):
        self.responses = responses
        self.calls: list[str] = []

    def shell(self, serial: str, *args, timeout: float | None = None) -> str:
        key = " ".join(str(arg) for arg in args)
        self.calls.append(key)
        return self.responses.get(key, "")

    def getprop(self, serial: str, prop: str) -> str:
        return self.responses.get(f"getprop {prop}", "")


class SwitchableFakeAdb(FakeAdb):
    def __init__(self, responses: dict[str, str], current_user: str):
        super().__init__(responses)
        self.current_user = current_user

    def shell(self, serial: str, *args, timeout: float | None = None) -> str:
        key = " ".join(str(arg) for arg in args)
        if key.startswith("am switch-user "):
            self.calls.append(key)
            self.current_user = key.split()[-1]
            return ""
        if key == "am get-current-user":
            return self.current_user
        return super().shell(serial, *args, timeout=timeout)


def make_device(adb: FakeAdb) -> AdbScrcpyDevice:
    device = AdbScrcpyDevice(
        adb=adb,
        server_bin="scrcpy",
        server_jar=None,
        server_version="3.3.1",
        tcp_port=27183,
        fps=5,
        bitrate=8_000_000,
        jpeg_quality=70,
        display_width=720,
        frame_timeout=10.0,
        allow_fallback=True,
        game_package="com.hb.cncapy.and",
    )
    device._sessions["s1"] = MirrorSession(id="s1", serial="S", width=1200, height=2648, fps=5)
    return device


def test_launch_app_reports_component_and_pid():
    adb = FakeAdb(
        {
            "cmd package resolve-activity --brief --user 0 com.hb.cncapy.and": (
                "com.hb.cncapy.and/com.habby.sdkhubv2.ui.GameStartNativeUIActivty"
            ),
            "am start -W -n com.hb.cncapy.and/com.habby.sdkhubv2.ui.GameStartNativeUIActivty --user 0": "Status: ok",
            "pidof com.hb.cncapy.and": "4321",
        }
    )
    device = make_device(adb)
    status = asyncio.run(device.launch_app("s1", "com.hb.cncapy.and", user=0))
    assert status.activity == "com.habby.sdkhubv2.ui.GameStartNativeUIActivty"
    assert status.running is True
    assert status.pid == 4321
    assert status.user == 0


def test_current_app_and_stop():
    adb = FakeAdb(
        {
            "dumpsys activity activities": (
                "mResumedActivity: ActivityRecord{1 u0 com.hb.cncapy.and/.Main t1}"
            ),
            "pidof com.hb.cncapy.and": "99",
            "am force-stop com.hb.cncapy.and": "",
        }
    )
    device = make_device(adb)
    status = asyncio.run(device.current_app("s1"))
    assert (status.package, status.activity) == ("com.hb.cncapy.and", ".Main")
    assert status.running is True
    asyncio.run(device.stop_app("s1", "com.hb.cncapy.and"))
    assert "am force-stop com.hb.cncapy.and" in adb.calls


def test_users_reports_unsupported_single_user():
    adb = FakeAdb(
        {
            "am get-current-user": "0",
            "pm list users": "Users:\n\tUserInfo{0:机主:4c13} running\n",
        }
    )
    device = make_device(adb)
    result = asyncio.run(device.list_users("s1"))
    assert result.switch_supported is False
    assert "仅有一个用户" in (result.reason or "")
    assert result.users[0].current is True


def test_switch_user_returns_unsupported_without_calling_am():
    adb = FakeAdb(
        {
            "am get-current-user": "0",
            "pm list users": "Users:\n\tUserInfo{0:机主:4c13} running\n",
        }
    )
    device = make_device(adb)
    result = asyncio.run(device.switch_user("s1", 999))
    assert result.ok is False
    assert result.switch_supported is False
    assert "am switch-user 999" not in adb.calls


def test_switch_user_unknown_user_keeps_switch_supported():
    adb = FakeAdb({**TWO_USERS, "am get-current-user": "0"})
    device = make_device(adb)
    result = asyncio.run(device.switch_user("s1", 777))
    assert result.ok is False
    assert result.switch_supported is True
    assert result.reason == "未知用户 777"
    assert "am switch-user 777" not in adb.calls


def test_switch_user_waits_for_current_user_change(monkeypatch):
    monkeypatch.setattr("app.device.adb_device.time.sleep", lambda _seconds: None)
    adb = SwitchableFakeAdb(dict(TWO_USERS), current_user="0")
    device = make_device(adb)
    result = asyncio.run(device.switch_user("s1", 999))
    assert result.ok is True
    assert result.user_id == 999
    assert "am switch-user 999" in adb.calls


def test_switch_user_raises_when_current_user_unchanged(monkeypatch):
    monkeypatch.setattr("app.device.adb_device.time.sleep", lambda _seconds: None)
    adb = FakeAdb({**TWO_USERS, "am get-current-user": "0", "am switch-user 999": ""})
    device = make_device(adb)
    with pytest.raises(UserSwitchFailed) as exc:
        asyncio.run(device.switch_user("s1", 999))
    assert exc.value.code == "USER_SWITCH_FAILED"
    assert exc.value.status_code == 502
    assert "期望 999" in str(exc.value)


def test_switch_user_raises_when_command_reports_error():
    adb = FakeAdb(
        {
            **TWO_USERS,
            "am get-current-user": "0",
            "am switch-user 999": "Error: user 999 does not exist",
        }
    )
    device = make_device(adb)
    with pytest.raises(UserSwitchFailed) as exc:
        asyncio.run(device.switch_user("s1", 999))
    assert "切换用户 999 失败" in str(exc.value)


def test_airplane_reads_back_and_reports_via():
    adb = FakeAdb(
        {
            "getprop ro.build.version.sdk": "34",
            "cmd connectivity airplane-mode enable": "",
            "settings get global airplane_mode_on": "1",
        }
    )
    device = make_device(adb)
    result = asyncio.run(device.set_airplane_mode("s1", True))
    assert result.ok is True
    assert result.airplane_mode_on is True
    assert result.applied_via == "cmd"


def test_airplane_mismatch_raises():
    adb = FakeAdb(
        {
            "getprop ro.build.version.sdk": "34",
            "cmd connectivity airplane-mode enable": "",
            "settings get global airplane_mode_on": "0",
        }
    )
    device = make_device(adb)
    with pytest.raises(AirplaneModeFailed) as exc:
        asyncio.run(device.set_airplane_mode("s1", True))
    assert exc.value.code == "AIRPLANE_MODE_FAILED"
    assert exc.value.status_code == 502
