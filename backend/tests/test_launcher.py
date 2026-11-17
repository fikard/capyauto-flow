from __future__ import annotations

import dataclasses

import pytest

from app import config
from app.device import packages
from app.device.packages import LauncherSpec
from app.errors import AdbError

SERIAL = "ANASUT3C20010476"
GAME = "com.hb.cncapy.and"
HOST = "com.joke.chongya"

# 真机 uiautomator dump 的实际节点（2026-11-15 实测，桌面第 5 行第 4 列）
# HONOR 桌面第一页「YOYO 建议」里的同名小图标：只有 content-desc，点它会直启游戏包
SUGGESTION_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
<node index="2" text="" resource-id="com.hihonor.android.launcher:id/application" content-desc="冒险者日记" clickable="true" bounds="[99,1184][303,1388]" />
</hierarchy>"""

UI_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
<node index="0" text="" class="android.widget.FrameLayout" package="com.hihonor.android.launcher" bounds="[0,0][1200,2652]" />
<node index="19" text="冒险者日记" resource-id="" class="android.widget.TextView" package="com.hihonor.android.launcher" content-desc="冒险者日记" clickable="true" bounds="[882,1540][1164,1870]" />
<node index="20" text="游戏中心" content-desc="游戏中心" clickable="true" bounds="[36,185][282,420]" />
</hierarchy>"""


def _front(package: str = HOST, activity: str = "top.bienvenido.mundo.manifest.MundoActivity$Companion$STUB1") -> str:
    return f"    topResumedActivity=ActivityRecord{{1a8e62d u0 {package}/{activity} t8939 mVisible=true}}"


class FakeAdb:
    """按命令返回脚本化结果，记录所有调用；pidof 的返回值可随调用次数变化。"""

    def __init__(
        self,
        *,
        xml: str = UI_XML,
        xmls: list[str] | None = None,
        host_installed: bool = True,
        pids: list[int | None] | None = None,
        tap_switches_to_host: bool = True,
    ):
        self.calls: list[tuple[str, ...]] = []
        self.xml = xml
        self.xmls = list(xmls) if xmls else None
        self.host_installed = host_installed
        self.pids = list(pids) if pids is not None else [11408]
        self.front = _front()
        self.tap_switches_to_host = tap_switches_to_host

    def shell(self, serial: str, *args, timeout: float | None = None) -> str:
        self.calls.append(args)
        head = args[0] if args else ""
        if head == "pm" and "list" in args:
            return f"package:{HOST}" if self.host_installed else ""
        if head == "uiautomator":
            return "UI hierchary dumped to: /sdcard/capyauto-launcher.xml"
        if head == "cat":
            if self.xmls:
                return self.xmls.pop(0) if len(self.xmls) > 1 else self.xmls[0]
            return self.xml
        if head == "input" and "tap" in args and self.tap_switches_to_host:
            self.front = _front()
        if head == "dumpsys":
            return self.front
        if head == "cmd" and "resolve-activity" in args:
            return f"priority=0\n{GAME}/com.habby.sdkhubv2.ui.GameStartNativeUIActivty"
        if head == "am" and "start" in args:
            return "Status: ok\nActivity: ...\nComplete"
        return ""

    def run(self, *args, serial: str | None = None, check: bool = True, timeout: float | None = None):
        self.calls.append(args)
        if "pidof" in args:
            pid = self.pids.pop(0) if len(self.pids) > 1 else self.pids[0]
            return str(pid) if pid is not None else ""
        return ""

    def wm_size(self, serial: str) -> tuple[str, int | None, int | None]:
        return "Physical size: 1200x2652", 1200, 2652


def spec(**overrides) -> LauncherSpec:
    return dataclasses.replace(LauncherSpec(), **overrides)


# ---------- UI 层级定位 ----------

def test_parse_launcher_bounds_uses_icon_center_from_real_dump():
    assert packages.parse_launcher_bounds(UI_XML, "冒险者日记") == (1023, 1705)


def test_parse_launcher_bounds_matches_content_desc_when_text_is_empty():
    xml = '<node text="" content-desc="冒险者日记" clickable="true" bounds="[10,20][30,40]" />'
    assert packages.parse_launcher_bounds(xml, "冒险者日记") == (20, 30)


def test_parse_launcher_bounds_returns_none_for_unrelated_or_missing_node():
    assert packages.parse_launcher_bounds(UI_XML, "不存在的图标") is None
    assert packages.parse_launcher_bounds('<node text="冒险者日记" />', "冒险者日记") is None


def test_require_text_ignores_suggestion_icon_that_would_launch_native_package():
    assert packages.parse_launcher_bounds(SUGGESTION_XML, "冒险者日记", require_text=True) is None
    assert packages.parse_launcher_bounds(UI_XML, "冒险者日记", require_text=True) == (1023, 1705)


# ---------- 启动模式决策 ----------

@pytest.mark.parametrize(
    "mode,installed,expected",
    [("package", True, False), ("launcher", False, True), ("auto", True, True), ("auto", False, False)],
)
def test_should_use_launcher(mode, installed, expected):
    adb = FakeAdb(host_installed=installed)
    assert packages.should_use_launcher(adb, SERIAL, spec(mode=mode)) is expected


def test_is_host_installed_matches_exact_package_line():
    assert packages.is_host_installed(FakeAdb(host_installed=True), SERIAL, HOST) is True
    assert packages.is_host_installed(FakeAdb(host_installed=False), SERIAL, HOST) is False


# ---------- 通过桌面快捷方式启动 ----------

def test_launcher_reuses_running_sandbox_without_tapping():
    adb = FakeAdb()
    activity, pid = packages.launch_via_launcher(adb, SERIAL, GAME, spec(), sleep=lambda _: None)
    assert pid == 11408
    assert "STUB1" in (activity or "")
    assert not any(call[0] == "input" for call in adb.calls), "已在沙箱运行不应重复点桌面图标"


def test_launcher_goes_home_then_taps_icon_center_and_waits_for_game_process():
    # 首次 pidof：游戏未运行；点击后 pidof：游戏进程出现
    adb = FakeAdb(pids=[None, 11408])
    adb.front = _front("com.hihonor.android.launcher", ".unihome.UniHomeLauncher")
    activity, pid = packages.launch_via_launcher(adb, SERIAL, GAME, spec(), sleep=lambda _: None)
    assert pid == 11408
    commands = [call for call in adb.calls if call[0] in {"am", "input", "uiautomator", "cat"}]
    assert ("input", "keyevent", "3") in commands, "用 HOME 键回桌面，不用 am start -c HOME（会跳页）"
    assert ("input", "tap", "1023", "1705") in commands
    assert commands.index(("uiautomator", "dump", "/sdcard/capyauto-launcher.xml")) < commands.index(
        ("input", "tap", "1023", "1705")
    )


def test_launcher_falls_back_to_configured_normalized_point_when_icon_not_found():
    adb = FakeAdb(xml="<hierarchy><node text='别的' bounds='[0,0][10,10]' /></hierarchy>", pids=[None, 11408])
    adb.front = _front("com.hihonor.android.launcher", ".unihome.UniHomeLauncher")
    _activity, pid = packages.launch_via_launcher(
        adb, SERIAL, GAME, spec(icon_point=(0.5, 0.25)), sleep=lambda _: None
    )
    assert pid == 11408
    assert ("input", "tap", "600", "663") in adb.calls


def test_launcher_raises_instead_of_silently_launching_without_host_when_icon_missing():
    adb = FakeAdb(xml="<hierarchy />", pids=[None])
    adb.front = _front("com.hihonor.android.launcher", ".unihome.UniHomeLauncher")
    with pytest.raises(AdbError, match="未找到"):
        packages.launch_via_launcher(adb, SERIAL, GAME, spec(), sleep=lambda _: None)
    assert not any(call[0] == "input" and "tap" in call for call in adb.calls)


def test_launcher_swipes_past_suggestion_page_to_the_real_text_label():
    adb = FakeAdb(xmls=[SUGGESTION_XML, UI_XML], pids=[None, 11408])
    adb.front = _front("com.hihonor.android.launcher", ".unihome.UniHomeLauncher")
    _activity, pid = packages.launch_via_launcher(adb, SERIAL, GAME, spec(), sleep=lambda _: None)
    assert pid == 11408
    assert [call for call in adb.calls if call[0] == "input" and "tap" in call] == [
        ("input", "tap", "1023", "1705")
    ]
    assert any(call[0] == "input" and "swipe" in call for call in adb.calls)


def test_launcher_rejects_native_package_start_without_sandbox_instead_of_reporting_success():
    adb = FakeAdb(pids=[None, 18792, None], tap_switches_to_host=False)
    adb.front = _front(GAME, "com.habby.sdkhubv2.ui.PLMainActivity")
    with pytest.raises(AdbError, match="未进入"):
        packages.launch_via_launcher(adb, SERIAL, GAME, spec(wait_s=5.0), sleep=lambda _: None)


def test_launcher_times_out_with_clear_error_when_game_never_starts():
    adb = FakeAdb(pids=[None])
    adb.front = _front("com.hihonor.android.launcher", ".unihome.UniHomeLauncher")
    with pytest.raises(AdbError, match="未拉起"):
        packages.launch_via_launcher(adb, SERIAL, GAME, spec(wait_s=0.0), sleep=lambda _: None)


def test_launch_app_delegates_to_launcher_when_auto_detects_host():
    adb = FakeAdb(pids=[None, 11408])
    adb.front = _front("com.hihonor.android.launcher", ".unihome.UniHomeLauncher")
    _activity, pid = packages.launch_app(adb, SERIAL, GAME, user=0, launcher=spec(), sleep=lambda _: None)
    assert pid == 11408
    assert any(call[0] == "input" and "tap" in call for call in adb.calls), "必须点桌面图标而不是直启游戏包"
    assert not any("-n" in call for call in adb.calls), "不得再 am start -n 游戏包"


def test_launch_app_keeps_legacy_direct_start_without_spec():
    adb = FakeAdb()
    _activity, pid = packages.launch_app(adb, SERIAL, GAME, user=0)
    assert pid == 11408
    assert any("-n" in call for call in adb.calls)
    assert not any(call[0] == "input" and "tap" in call for call in adb.calls)


# ---------- 沙箱停止：插件 force-stop 无效时必须强杀宿主 ----------

def test_stop_app_force_stops_host_when_plugin_process_survives():
    adb = FakeAdb(host_installed=True, pids=[11408, 11408, None])
    packages.stop_app(adb, SERIAL, GAME, host_package=HOST, sleep=lambda _: None)
    assert ("am", "force-stop", GAME) in adb.calls
    assert ("am", "force-stop", HOST) in adb.calls


def test_stop_app_does_not_touch_host_when_plugin_already_stopped():
    adb = FakeAdb(host_installed=True, pids=[None])
    packages.stop_app(adb, SERIAL, GAME, host_package=HOST, sleep=lambda _: None)
    assert ("am", "force-stop", HOST) not in adb.calls


def test_stop_app_does_not_touch_host_when_host_not_installed():
    adb = FakeAdb(host_installed=False, pids=[11408])
    packages.stop_app(adb, SERIAL, GAME, host_package=HOST, sleep=lambda _: None)
    assert ("am", "force-stop", HOST) not in adb.calls


def test_stop_app_without_host_package_keeps_legacy_behaviour():
    adb = FakeAdb(pids=[11408])
    packages.stop_app(adb, SERIAL, GAME)
    assert ("am", "force-stop", GAME) in adb.calls
    assert ("am", "force-stop", HOST) not in adb.calls


# ---------- 配置 ----------

def test_config_launcher_defaults(monkeypatch):
    for name in (
        "CAPYAUTO_LAUNCH_MODE", "CAPYAUTO_LAUNCHER_HOST_PACKAGE",
        "CAPYAUTO_LAUNCHER_ICON_LABEL", "CAPYAUTO_LAUNCHER_ICON_POINT", "CAPYAUTO_LAUNCHER_WAIT_S",
    ):
        monkeypatch.delenv(name, raising=False)
    cfg = config.Settings()
    assert cfg.launch_mode == "auto"
    assert cfg.launcher_host_package == HOST
    assert cfg.launcher_icon_label == "冒险者日记"
    assert cfg.launcher_icon_point is None
    assert cfg.launcher_wait_s == 30.0


def test_config_launcher_overrides(monkeypatch):
    monkeypatch.setenv("CAPYAUTO_LAUNCH_MODE", "launcher")
    monkeypatch.setenv("CAPYAUTO_LAUNCHER_ICON_POINT", "0.85,0.64")
    monkeypatch.setenv("CAPYAUTO_LAUNCHER_WAIT_S", "12.5")
    cfg = config.Settings()
    assert cfg.launch_mode == "launcher"
    assert cfg.launcher_icon_point == (0.85, 0.64)
    assert cfg.launcher_wait_s == 12.5


@pytest.mark.parametrize("raw", ["banana", "0.85", "1.5,0.2", "-0.1,0.5", "abc,0.5"])
def test_config_rejects_invalid_launcher_values(monkeypatch, raw):
    monkeypatch.setenv("CAPYAUTO_LAUNCH_MODE" if raw == "banana" else "CAPYAUTO_LAUNCHER_ICON_POINT", raw)
    with pytest.raises(SystemExit):
        config.Settings()


# ---------- /api/app/launch 的运行态必须与 /api/app/current 一致 ----------

def _launcher_device(adb, launch_mode: str):
    from app.device.adb_device import AdbScrcpyDevice
    from app.device.base import MirrorSession

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
        game_package=GAME,
        launcher=spec(mode=launch_mode),
    )
    device._sessions["s1"] = MirrorSession(
        id="s1", serial=SERIAL, width=1200, height=2652, fps=5
    )
    return device


def test_launch_reports_host_component_not_game_package():
    """经变速器启动后，launch 响应必须是宿主包 + STUB1，而不是回显游戏包。"""
    import asyncio

    device = _launcher_device(FakeAdb(pids=[13482]), "launcher")
    status = asyncio.run(device.launch_app("s1", GAME))
    assert status.package == HOST
    assert status.activity is not None and status.activity.endswith("STUB1")
    assert status.running is True
    assert status.pid == 13482


def test_launch_without_launcher_keeps_requested_package():
    """未启用变速器时保持旧行为，避免影响直启回归。"""
    import asyncio

    device = _launcher_device(FakeAdb(pids=[4321]), "package")
    status = asyncio.run(device.launch_app("s1", GAME))
    assert status.package == GAME
    assert status.pid == 4321
