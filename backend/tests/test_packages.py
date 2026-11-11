import pytest

from app.device.packages import (
    current_component,
    launch_app,
    parse_airplane_mode,
    parse_component,
    parse_current_user,
    parse_front_component,
    parse_pid,
    parse_sdk,
    parse_users,
    pid_of,
    read_airplane_mode,
    resolve_activity,
    set_airplane_mode,
    stop_app,
    switch_support,
    switch_user,
    users,
)
from app.errors import AdbError


class FakeAdb:
    def __init__(self, responses: dict[str, str]):
        self.responses = responses
        self.calls: list[tuple[str, str]] = []

    def shell(self, serial: str, *args, timeout: float | None = None) -> str:
        key = " ".join(str(arg) for arg in args)
        self.calls.append((serial, key))
        return self.responses.get(key, "")


def test_parse_users_reads_name_and_running_flag():
    rows = parse_users("Users:\n\tUserInfo{0:机主:4c13} running\n\tUserInfo{999:分身:5d20}\n")
    assert [(u.id, u.name, u.current) for u in rows] == [(0, "机主", True), (999, "分身", False)]


def test_parse_component_handles_dumpsys_and_brief_output():
    dumpsys = (
        "  mResumedActivity: ActivityRecord{21ea3 u0 "
        "com.hb.cncapy.and/com.habby.sdkhubv2.ui.GameStartNativeUIActivty t42}"
    )
    assert parse_component(dumpsys) == (
        "com.hb.cncapy.and",
        "com.habby.sdkhubv2.ui.GameStartNativeUIActivty",
    )
    brief = "priority=0 preferredOrder=0 match=0x108000\ncom.hb.cncapy.and/com.habby.sdkhubv2.ui.GameStartNativeUIActivty"
    assert parse_component(brief) == (
        "com.hb.cncapy.and",
        "com.habby.sdkhubv2.ui.GameStartNativeUIActivty",
    )


def test_parse_pid_and_airplane_sdk():
    assert parse_pid("12345\n") == 12345
    assert parse_pid("") is None
    assert parse_airplane_mode("1\n") is True
    assert parse_airplane_mode("0\n") is False
    assert parse_sdk("34\n") == 34
    assert parse_sdk("unknown") == 0
    assert parse_current_user("0\n") == 0
    assert parse_current_user("") is None


def test_resolve_activity_only_returns_requested_package():
    adb = FakeAdb(
        {
            "cmd package resolve-activity --brief com.hb.cncapy.and": (
                "priority=0\ncom.hb.cncapy.and/com.habby.sdkhubv2.ui.GameStartNativeUIActivty"
            )
        }
    )
    assert resolve_activity(adb, "S", "com.hb.cncapy.and") == "com.habby.sdkhubv2.ui.GameStartNativeUIActivty"
    adb.responses["cmd package resolve-activity --brief com.other"] = "com.other/com.other.Main"
    assert resolve_activity(adb, "S", "com.other") == "com.other.Main"


def test_launch_app_builds_component_command_and_reads_pid():
    adb = FakeAdb(
        {
            "am start -W -n com.hb.cncapy.and/com.habby.sdkhubv2.ui.GameStartNativeUIActivty --user 0": (
                "Status: ok\nLaunchState: COLD\n"
            ),
            "pidof com.hb.cncapy.and": "4321\n",
        }
    )
    activity, pid = launch_app(
        adb,
        "S",
        "com.hb.cncapy.and",
        activity="com.habby.sdkhubv2.ui.GameStartNativeUIActivty",
        user=0,
    )
    assert activity == "com.habby.sdkhubv2.ui.GameStartNativeUIActivty"
    assert pid == 4321


def test_launch_app_raises_on_am_error():
    adb = FakeAdb({"am start -W -n bad/pkg": "Error: Activity class does not exist.\n"})
    with pytest.raises(AdbError):
        launch_app(adb, "S", "bad", activity="pkg")


def test_stop_user_switch_and_airplane_commands():
    adb = FakeAdb(
        {
            "am force-stop com.hb.cncapy.and": "",
            "pm list users": "Users:\n\tUserInfo{0:机主:4c13} running\n",
            "am get-current-user": "0\n",
            "pm list packages --user 0 com.hb.cncapy.and": "package:com.hb.cncapy.and\n",
            "settings get global airplane_mode_on": "1\n",
        }
    )
    rows = users(adb, "S")
    assert [u.current for u in rows] == [True]
    stop_app(adb, "S", "com.hb.cncapy.and")
    assert ("S", "am force-stop com.hb.cncapy.and") in adb.calls
    supported, reason = switch_support(adb, "S", "com.hb.cncapy.and", rows)
    assert supported is False
    assert "仅有一个用户" in (reason or "")
    assert read_airplane_mode(adb, "S") is True


def test_airplane_uses_cmd_on_modern_android():
    adb = FakeAdb({})
    assert set_airplane_mode(adb, "S", True, sdk=34) == "cmd"
    assert ("S", "cmd connectivity airplane-mode enable") in adb.calls


def test_airplane_falls_back_to_settings_before_android_11():
    adb = FakeAdb({})
    assert set_airplane_mode(adb, "S", False, sdk=29) == "settings"
    assert ("S", "settings put global airplane_mode_on 0") in adb.calls
    assert any("AIRPLANE_MODE" in call[1] for call in adb.calls)


def test_parse_front_component_only_matches_resumed_lines():
    assert parse_front_component(
        "  topResumedActivity=ActivityRecord{21ea3 u0 "
        "com.hb.cncapy.and/com.habby.sdkhubv2.ui.GameStartNativeUIActivty t42}"
    ) == ("com.hb.cncapy.and", "com.habby.sdkhubv2.ui.GameStartNativeUIActivty")
    assert (
        parse_front_component(
            "  mLastPausedActivity: ActivityRecord{99 u0 com.old/com.old.Main t1}\n"
            "  * Task{abc #42 type=standard}\n"
            "    com.history/com.history.Detail\n"
        )
        is None
    )


def test_current_component_reads_top_resumed_and_ignores_history():
    dumpsys = (
        "  mLastPausedActivity: ActivityRecord{99 u0 com.old/com.old.Main t1}\n"
        "  topResumedActivity=ActivityRecord{21ea3 u0 "
        "com.hb.cncapy.and/com.habby.sdkhubv2.ui.GameStartNativeUIActivty t42}\n"
    )
    adb = FakeAdb({"dumpsys activity activities": dumpsys})
    assert current_component(adb, "S") == (
        "com.hb.cncapy.and",
        "com.habby.sdkhubv2.ui.GameStartNativeUIActivty",
    )
    adb.responses["dumpsys activity activities"] = (
        "  mLastPausedActivity: ActivityRecord{99 u0 com.old/com.old.Main t1}\n"
        "    com.history/com.history.Detail\n"
    )
    assert current_component(adb, "S") is None


def test_pid_of_reads_numeric_pid_and_handles_empty_output():
    adb = FakeAdb({"pidof com.foo": "4321 4319\n"})
    assert pid_of(adb, "S", "com.foo") == 4321
    assert pid_of(adb, "S", "com.missing") is None
    assert ("S", "pidof com.missing") in adb.calls


def test_users_falls_back_to_running_flag_without_numeric_current_user():
    adb = FakeAdb(
        {
            "pm list users": "Users:\n\tUserInfo{0:机主:4c13} running\n\tUserInfo{999:分身:5d20}\n",
            "am get-current-user": "unknown\n",
        }
    )
    rows = users(adb, "S")
    assert [(u.id, u.current) for u in rows] == [(0, True), (999, False)]


def test_resolve_activity_supports_explicit_user():
    adb = FakeAdb(
        {"cmd package resolve-activity --brief --user 999 com.foo": "com.foo/com.foo.Main"}
    )
    assert resolve_activity(adb, "S", "com.foo", user=999) == "com.foo.Main"
    assert ("S", "cmd package resolve-activity --brief --user 999 com.foo") in adb.calls


def test_launch_app_resolves_activity_for_requested_user():
    adb = FakeAdb(
        {
            "cmd package resolve-activity --brief --user 999 com.foo": "com.foo/com.foo.Main",
            "am start -W -n com.foo/com.foo.Main --user 999": "Status: ok\n",
            "pidof com.foo": "88\n",
        }
    )
    assert launch_app(adb, "S", "com.foo", user=999) == ("com.foo.Main", 88)


def test_launch_app_falls_back_to_launcher_intent_with_package():
    adb = FakeAdb(
        {
            "cmd package resolve-activity --brief com.foo": "",
            "am start -W -a android.intent.action.MAIN -c android.intent.category.LAUNCHER -p com.foo": (
                "Status: ok\n"
            ),
            "pidof com.foo": "777\n",
        }
    )
    activity, pid = launch_app(adb, "S", "com.foo")
    assert activity is None
    assert pid == 777
    assert (
        "S",
        "am start -W -a android.intent.action.MAIN -c android.intent.category.LAUNCHER -p com.foo",
    ) in adb.calls


def test_switch_support_matches_package_exactly():
    adb = FakeAdb(
        {
            "pm list users": "Users:\n\tUserInfo{0:机主:4c13} running\n\tUserInfo{999:分身:5d20}\n",
            "am get-current-user": "0\n",
            "pm list packages --user 0 com.foo": "package:com.foo\n",
            "pm list packages --user 999 com.foo": "package:com.foobar\n",
        }
    )
    rows = users(adb, "S")
    supported, reason = switch_support(adb, "S", "com.foo", rows)
    assert supported is False
    assert "999" in (reason or "")


def test_switch_user_requires_at_least_two_installed_users():
    adb = FakeAdb(
        {
            "pm list users": "Users:\n\tUserInfo{0:机主:4c13} running\n\tUserInfo{999:分身:5d20}\n",
            "am get-current-user": "0\n",
            "pm list packages --user 0 com.hb.cncapy.and": "package:com.hb.cncapy.and\n",
            "pm list packages --user 999 com.hb.cncapy.and": "",
        }
    )
    rows = users(adb, "S")
    supported, reason = switch_support(adb, "S", "com.hb.cncapy.and", rows)
    assert supported is False
    assert "999" in (reason or "")
    switch_user(adb, "S", 999)
    assert ("S", "am switch-user 999") in adb.calls
