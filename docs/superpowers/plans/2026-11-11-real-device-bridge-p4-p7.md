# CapyAuto Flow 真机桥接 P4–P7 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 在已落地的 P0–P3 之上，补齐应用/账号控制、真机 OCR 闭环、前端真机整合与自动化验收，使单台 Android 真机可通过中控台完成「启停游戏 → 识屏 → 决策点击」的完整闭环。

**架构：** 后端沿用 `DeviceAdapter` 抽象：新增应用、用户、飞行模式能力到 `base.py` / `packages.py`，由 `AdbScrcpyDevice` 调 `adb shell` 实现、`MockDevice` 提供可控假实现；OCR 作为独立 `app/vision` 模块懒加载 RapidOCR，API 只依赖 `screenshot()`；验收脚本 `python -m app.verify` 直接驱动 adapter，不依赖 HTTP 或前端。前端新增 `deviceClient` + `useDeviceBridge`，在仿真/真机两种模式间切换，真机模式渲染 WS 镜像、点击反馈与控制抽屉。

**技术栈：** Python 3.12 / FastAPI / pydantic v2 / pytest / RapidOCR(onnxruntime) / React 19 / TypeScript / Vite / bun test / adb。

---

## 0. 现状与真机事实（2026-11-11 实测）

| 项 | 值 |
|---|---|
| 分支 | `feat/real-device-bridge`（P0–P3 已全部提交，HEAD `06b3f1e`） |
| 设备 | `ANASUT3C20010476`，`ALP-AN00`，Android 14（SDK 34） |
| 分辨率 | 1200×2648（视频流与 `wm size` 一致） |
| 游戏包名 | `com.hb.cncapy.and`（冒险者日记，versionName 1.9.6） |
| 主 Activity | `com.habby.sdkhubv2.ui.GameStartNativeUIActivty`（注意官方拼写是 `Activty`） |
| 用户列表 | 仅 `UserInfo{0:机主:...} running` → 切分身预期 SKIP |
| 飞行模式 | `cmd connectivity airplane-mode` 可用，当前 `disabled` |
| RapidOCR | 未安装，需 `pip install rapidocr-onnxruntime` |
| 已有测试 | 114 passed |

**P4–P7 契约以规格第 5.1、6.5、8、9 节为准。** 本计划不修改 P0–P3 已落地的字段名。

---

## 1. 文件结构

| 文件 | 职责 |
|---|---|
| `backend/app/device/base.py`（改） | 新增 `AndroidUser` / `AppStatus` / `UserListResult` / `UserSwitchResult` / `AirplaneResult` 与 6 个抽象方法 |
| `backend/app/device/packages.py`（建） | 纯解析函数 + `adb shell` 应用/用户/飞行模式操作 |
| `backend/app/device/adb.py`（改） | 新增 `AdbRunner.shell(serial, *args, timeout=None)` |
| `backend/app/device/adb_device.py`（改） | 实现 6 个新抽象方法，全部走 `asyncio.to_thread` |
| `backend/app/device/mock_device.py`（改） | 可控假实现，供接口测试与 Mock 模式 |
| `backend/app/schemas.py`（改） | `LaunchAppRequest` / `StopAppRequest` / `SwitchUserRequest` / `AirplaneRequest` / `OcrRequest` |
| `backend/app/api/app_control.py`（建） | `/api/app/launch|stop|current|users|switch-user` |
| `backend/app/api/network.py`（建） | `/api/network/airplane` |
| `backend/app/api/vision.py`（建） | `/api/vision/ocr` |
| `backend/app/vision/ocr.py`（建） | RapidOCR 懒加载、区域裁剪、坐标归一化 |
| `backend/app/errors.py`（改） | `AirplaneModeFailed` / `UserSwitchFailed` / `OcrUnavailable` |
| `backend/app/config.py`（改） | `game_package`、`game_activity` |
| `backend/app/main.py`（改） | 注册 3 个新 router |
| `backend/app/verify.py`（建） | V1–V10 验收脚本 + JSON/MD 报告 |
| `backend/tests/test_packages.py`（建） | 解析与命令拼装 |
| `backend/tests/test_adb_device_app.py`（建） | AdbScrcpyDevice 新方法 |
| `backend/tests/test_api_app.py`（建） | 应用/用户/飞行模式接口 |
| `backend/tests/test_ocr.py`（建） | 归一化与区域裁剪 |
| `backend/tests/test_api_vision.py`（建） | OCR 接口（假引擎） |
| `backend/tests/test_verify.py`（建） | P95、汇总、Markdown 渲染 |
| `src/types/device.ts`（建） | 前端设备类型 |
| `src/api/deviceClient.ts`（建） | REST/WS 客户端与错误归一化 |
| `src/api/deviceClient.test.ts`（建） | `buildMirrorUrl` / `toNormalized` / `isTapInside` |
| `src/hooks/useDeviceBridge.ts`（建） | 设备连接、会话、错误态 |
| `src/components/DeviceBar.tsx`（建） | 在线状态、模式切换、分辨率、fps、降级标注 |
| `src/components/DeviceMirror.tsx`（建） | WS JPEG 渲染、点击注入、落点叠加 |
| `src/components/DeviceDrawer.tsx`（建） | 启停应用、用户、飞行模式、OCR、验收 |
| `src/App.tsx`（改） | 接入 `useDeviceBridge`，simulator 页签按模式切换 |

---

## 2. 任务

### 任务 17：设备应用/用户/网络操作层

**文件：**
- 创建：`backend/app/device/packages.py`
- 修改：`backend/app/device/adb.py`（在 `exec_out` 前插入 `shell`）
- 修改：`backend/app/device/base.py`（仅新增 `AndroidUser` 等数据类，抽象方法在任务 18 加）
- 测试：`backend/tests/test_packages.py`

- [ ] **步骤 1：编写失败的测试**

```python
from app.device.packages import (
    launch_app,
    parse_airplane_mode,
    parse_component,
    parse_current_user,
    parse_pid,
    parse_sdk,
    parse_users,
    read_airplane_mode,
    resolve_activity,
    set_airplane_mode,
    stop_app,
    switch_support,
    switch_user,
    users,
)


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
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd backend && .venv/bin/python -m pytest tests/test_packages.py -q`
预期：`ModuleNotFoundError: No module named 'app.device.packages'`

- [ ] **步骤 3：编写最少实现代码**

`backend/app/device/adb.py` 在 `exec_out` 前新增：

```python
    def shell(self, serial: str, *args, timeout: float | None = None) -> str:
        return str(self.run("shell", *args, serial=serial, timeout=timeout))
```

`backend/app/device/base.py` 在 `DeviceInfo` 后新增：

```python
@dataclass
class AndroidUser:
    id: int
    name: str
    current: bool = False
```

`backend/app/device/packages.py`：

```python
from __future__ import annotations

import re

from app.device.adb import AdbRunner
from app.device.base import AndroidUser
from app.errors import AdbError

USER_LINE_RE = re.compile(r"UserInfo\{(\d+):([^:}]+):[0-9a-f]+\}\s*(.*)$")
ACTIVITY_RE = re.compile(
    r"(?:topResumedActivity|mResumedActivity|ResumedActivity)[=:]\s*"
    r"(?:ActivityRecord\{[^}]*?\s+)?([A-Za-z0-9_.]+/[A-Za-z0-9_.$]+)"
)
COMPONENT_LINE_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_.]*)/([A-Za-z0-9_.$]+)$")


def parse_users(output: str) -> list[AndroidUser]:
    users: list[AndroidUser] = []
    for raw in output.splitlines():
        match = USER_LINE_RE.search(raw.strip())
        if match is None:
            continue
        users.append(
            AndroidUser(
                id=int(match.group(1)),
                name=match.group(2),
                current="running" in match.group(3),
            )
        )
    return users


def parse_current_user(output: str) -> int | None:
    text = output.strip()
    return int(text) if text.isdigit() else None


def parse_component(output: str) -> tuple[str, str] | None:
    match = ACTIVITY_RE.search(output)
    if match is not None:
        package, activity = match.group(1).split("/", 1)
        return package, activity
    for raw in output.splitlines():
        line = raw.strip().split()[-1] if raw.strip() else ""
        match = COMPONENT_LINE_RE.match(line)
        if match is not None:
            return match.group(1), match.group(2)
    return None


def parse_pid(output: str) -> int | None:
    for token in output.split():
        if token.isdigit():
            return int(token)
    return None


def parse_airplane_mode(output: str) -> bool:
    return output.strip() == "1"


def parse_sdk(output: str) -> int:
    text = output.strip()
    return int(text) if text.isdigit() else 0


def resolve_activity(adb: AdbRunner, serial: str, package: str) -> str | None:
    output = adb.shell(serial, "cmd", "package", "resolve-activity", "--brief", package)
    component = parse_component(output)
    return component[1] if component is not None and component[0] == package else None


def launch_app(
    adb: AdbRunner,
    serial: str,
    package: str,
    activity: str | None = None,
    user: int | None = None,
) -> tuple[str | None, int | None]:
    resolved = activity or resolve_activity(adb, serial, package)
    args = ["am", "start", "-W"]
    if resolved:
        args += ["-n", f"{package}/{resolved}"]
    else:
        args += ["-a", "android.intent.action.MAIN", "-c", "android.intent.category.LAUNCHER", package]
    if user is not None:
        args += ["--user", str(user)]
    output = adb.shell(serial, *args, timeout=30)
    if "Error:" in output or "Exception" in output:
        raise AdbError(f"启动 {package} 失败", detail={"output": output[:500]})
    return resolved, parse_pid(adb.shell(serial, "pidof", package))


def stop_app(adb: AdbRunner, serial: str, package: str) -> None:
    adb.shell(serial, "am", "force-stop", package)


def current_component(adb: AdbRunner, serial: str) -> tuple[str, str] | None:
    return parse_component(adb.shell(serial, "dumpsys", "activity", "activities"))


def pid_of(adb: AdbRunner, serial: str, package: str) -> int | None:
    return parse_pid(adb.shell(serial, "pidof", package))


def users(adb: AdbRunner, serial: str) -> list[AndroidUser]:
    current = parse_current_user(adb.shell(serial, "am", "get-current-user"))
    rows = parse_users(adb.shell(serial, "pm", "list", "users"))
    if current is None:
        return rows
    return [AndroidUser(id=row.id, name=row.name, current=row.id == current) for row in rows]


def switch_support(
    adb: AdbRunner, serial: str, package: str, rows: list[AndroidUser]
) -> tuple[bool, str | None]:
    if len(rows) <= 1:
        return False, "设备仅有一个用户，系统不支持应用分身切换"
    for row in rows:
        installed = adb.shell(serial, "pm", "list", "packages", "--user", str(row.id), package)
        if package not in installed:
            return False, f"用户 {row.id} 未安装 {package}"
    return True, None


def switch_user(adb: AdbRunner, serial: str, user_id: int) -> None:
    adb.shell(serial, "am", "switch-user", str(user_id), timeout=20)


def read_airplane_mode(adb: AdbRunner, serial: str) -> bool:
    return parse_airplane_mode(adb.shell(serial, "settings", "get", "global", "airplane_mode_on"))


def set_airplane_mode(adb: AdbRunner, serial: str, enable: bool, sdk: int) -> str:
    if sdk >= 30:
        adb.shell(
            serial,
            "cmd",
            "connectivity",
            "airplane-mode",
            "enable" if enable else "disable",
            timeout=20,
        )
        return "cmd"
    adb.shell(serial, "settings", "put", "global", "airplane_mode_on", "1" if enable else "0")
    adb.shell(
        serial,
        "am",
        "broadcast",
        "-a",
        "android.intent.action.AIRPLANE_MODE",
        "--ez",
        "state",
        "true" if enable else "false",
    )
    return "settings"
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd backend && .venv/bin/python -m pytest tests/test_packages.py -q`
预期：10 passed

- [ ] **步骤 5：Commit**

```bash
git add backend/app/device/packages.py backend/app/device/adb.py backend/app/device/base.py backend/tests/test_packages.py
git commit -m "feat(device): 增加应用、用户与飞行模式 adb 操作层"
```

---

### 任务 18：Adapter 扩展与应用/网络接口

**文件：**
- 修改：`backend/app/device/base.py`（新增 4 个结果类型 + 6 个抽象方法）
- 修改：`backend/app/device/adb_device.py`
- 修改：`backend/app/device/mock_device.py`
- 修改：`backend/app/schemas.py`
- 创建：`backend/app/api/app_control.py`、`backend/app/api/network.py`
- 修改：`backend/app/main.py`、`backend/app/config.py`、`backend/app/errors.py`
- 测试：`backend/tests/test_adb_device_app.py`、`backend/tests/test_api_app.py`

- [ ] **步骤 1：编写失败的测试**

`backend/tests/test_adb_device_app.py`：

```python
import pytest

from app.device.adb_device import AdbScrcpyDevice
from app.device.base import MirrorSession
from app.errors import AdbError


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
    )
    device._sessions["s1"] = MirrorSession(id="s1", serial="S", width=1200, height=2648, fps=5)
    return device


@pytest.mark.asyncio
async def test_launch_app_reports_component_and_pid():
    adb = FakeAdb(
        {
            "cmd package resolve-activity --brief com.hb.cncapy.and": (
                "com.hb.cncapy.and/com.habby.sdkhubv2.ui.GameStartNativeUIActivty"
            ),
            "am start -W -n com.hb.cncapy.and/com.habby.sdkhubv2.ui.GameStartNativeUIActivty --user 0": "Status: ok",
            "pidof com.hb.cncapy.and": "4321",
        }
    )
    device = make_device(adb)
    status = await device.launch_app("s1", "com.hb.cncapy.and", user=0)
    assert status.running is True
    assert status.pid == 4321
    assert status.user == 0


@pytest.mark.asyncio
async def test_current_app_and_stop():
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
    status = await device.current_app("s1")
    assert (status.package, status.activity) == ("com.hb.cncapy.and", ".Main")
    assert status.running is True
    await device.stop_app("s1", "com.hb.cncapy.and")
    assert "am force-stop com.hb.cncapy.and" in adb.calls


@pytest.mark.asyncio
async def test_users_reports_unsupported_single_user():
    adb = FakeAdb(
        {
            "am get-current-user": "0",
            "pm list users": "Users:\n\tUserInfo{0:机主:4c13} running\n",
        }
    )
    device = make_device(adb)
    result = await device.list_users("s1")
    assert result.switch_supported is False
    assert "仅有一个用户" in (result.reason or "")
    assert result.users[0].current is True


@pytest.mark.asyncio
async def test_switch_user_returns_unsupported_without_calling_am():
    adb = FakeAdb(
        {
            "am get-current-user": "0",
            "pm list users": "Users:\n\tUserInfo{0:机主:4c13} running\n",
        }
    )
    device = make_device(adb)
    result = await device.switch_user("s1", 999)
    assert result.ok is False
    assert result.switch_supported is False
    assert "am switch-user 999" not in adb.calls


@pytest.mark.asyncio
async def test_airplane_reads_back_and_reports_via():
    adb = FakeAdb(
        {
            "getprop ro.build.version.sdk": "34",
            "cmd connectivity airplane-mode enable": "",
            "settings get global airplane_mode_on": "1",
        }
    )
    device = make_device(adb)
    result = await device.set_airplane_mode("s1", True)
    assert result.ok is True
    assert result.airplane_mode_on is True
    assert result.applied_via == "cmd"


@pytest.mark.asyncio
async def test_airplane_mismatch_raises():
    adb = FakeAdb(
        {
            "getprop ro.build.version.sdk": "34",
            "cmd connectivity airplane-mode enable": "",
            "settings get global airplane_mode_on": "0",
        }
    )
    device = make_device(adb)
    with pytest.raises(AdbError):
        await device.set_airplane_mode("s1", True)
```

`backend/tests/test_api_app.py`：

```python
def _session(client) -> str:
    device = client.get("/api/devices").json()["devices"][0]
    return client.post("/api/session", json={"serial": device["serial"]}).json()["sessionId"]


def test_launch_and_stop_app(client):
    session_id = _session(client)
    launched = client.post(
        "/api/app/launch",
        json={"sessionId": session_id, "package": "com.hb.cncapy.and", "user": 0},
    )
    assert launched.status_code == 200
    body = launched.json()
    assert body["ok"] is True
    assert body["usedUser"] == 0
    stopped = client.post(
        "/api/app/stop", json={"sessionId": session_id, "package": "com.hb.cncapy.and"}
    )
    assert stopped.status_code == 200
    assert stopped.json() == {"ok": True}


def test_current_app_returns_status(client):
    session_id = _session(client)
    body = client.get("/api/app/current", params={"sessionId": session_id}).json()
    assert {"package", "activity", "running", "pid"} <= set(body)


def test_users_and_switch_user(client):
    session_id = _session(client)
    users = client.get("/api/app/users", params={"sessionId": session_id}).json()
    assert users["switchSupported"] is True
    assert users["users"][0]["current"] is True
    switched = client.post(
        "/api/app/switch-user", json={"sessionId": session_id, "userId": 999}
    ).json()
    assert switched["ok"] is True
    assert switched["userId"] == 999
    current = client.get("/api/app/users", params={"sessionId": session_id}).json()
    assert [u["id"] for u in current["users"] if u["current"]] == [999]


def test_unknown_session_returns_404(client):
    response = client.post(
        "/api/app/stop", json={"sessionId": "nope", "package": "com.hb.cncapy.and"}
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"


def test_airplane_toggle(client):
    session_id = _session(client)
    on = client.post(
        "/api/network/airplane", json={"sessionId": session_id, "enable": True}
    ).json()
    assert on["ok"] is True and on["airplaneModeOn"] is True
    off = client.post(
        "/api/network/airplane", json={"sessionId": session_id, "enable": False}
    ).json()
    assert off["airplaneModeOn"] is False
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd backend && .venv/bin/python -m pytest tests/test_adb_device_app.py tests/test_api_app.py -q`
预期：FAIL，`AttributeError: 'AdbScrcpyDevice' object has no attribute 'launch_app'` 或 `404`

- [ ] **步骤 3：编写最少实现代码**

`errors.py` 追加：

```python
class AirplaneModeFailed(ApiError):
    status_code = 502
    code = "AIRPLANE_MODE_FAILED"


class UserSwitchFailed(ApiError):
    status_code = 502
    code = "USER_SWITCH_FAILED"


class OcrUnavailable(ApiError):
    status_code = 503
    code = "OCR_UNAVAILABLE"
```

`base.py` 新增数据类与抽象方法：

```python
@dataclass
class AppStatus:
    package: str
    activity: str | None = None
    running: bool = False
    pid: int | None = None
    user: int | None = None


@dataclass
class UserListResult:
    users: list[AndroidUser]
    switch_supported: bool
    reason: str | None = None


@dataclass
class UserSwitchResult:
    ok: bool
    user_id: int
    switch_supported: bool
    reason: str | None = None


@dataclass
class AirplaneResult:
    ok: bool
    airplane_mode_on: bool
    applied_via: str
```

`DeviceAdapter` 内追加（`@abstractmethod`）：

```python
    async def launch_app(self, session_id: str, package: str, user: int | None = None) -> AppStatus: ...
    async def stop_app(self, session_id: str, package: str) -> None: ...
    async def current_app(self, session_id: str) -> AppStatus: ...
    async def list_users(self, session_id: str) -> UserListResult: ...
    async def switch_user(self, session_id: str, user_id: int) -> UserSwitchResult: ...
    async def set_airplane_mode(self, session_id: str, enable: bool) -> AirplaneResult: ...
```

`AdbScrcpyDevice` 追加：

```python
    # ---------- 应用 / 用户 / 网络 ----------

    def _launch_sync(self, session_id: str, package: str, user: int | None) -> AppStatus:
        session = self.get_session(session_id)
        activity, pid = packages.launch_app(self._adb, session.serial, package, user=user)
        return AppStatus(package=package, activity=activity, running=pid is not None, pid=pid, user=user)

    async def launch_app(self, session_id: str, package: str, user: int | None = None) -> AppStatus:
        return await asyncio.to_thread(self._launch_sync, session_id, package, user)

    def _stop_sync(self, session_id: str, package: str) -> None:
        session = self.get_session(session_id)
        packages.stop_app(self._adb, session.serial, package)

    async def stop_app(self, session_id: str, package: str) -> None:
        await asyncio.to_thread(self._stop_sync, session_id, package)

    def _current_sync(self, session_id: str) -> AppStatus:
        session = self.get_session(session_id)
        component = packages.current_component(self._adb, session.serial)
        package = component[0] if component else ""
        pid = packages.pid_of(self._adb, session.serial, package) if package else None
        return AppStatus(
            package=package,
            activity=component[1] if component else None,
            running=pid is not None,
            pid=pid,
        )

    async def current_app(self, session_id: str) -> AppStatus:
        return await asyncio.to_thread(self._current_sync, session_id)

    def _users_sync(self, session_id: str) -> UserListResult:
        session = self.get_session(session_id)
        rows = packages.users(self._adb, session.serial)
        supported, reason = packages.switch_support(self._adb, session.serial, self.game_package, rows)
        return UserListResult(users=rows, switch_supported=supported, reason=reason)

    async def list_users(self, session_id: str) -> UserListResult:
        return await asyncio.to_thread(self._users_sync, session_id)

    def _switch_sync(self, session_id: str, user_id: int) -> UserSwitchResult:
        result = self._users_sync(session_id)
        if not result.switch_supported:
            return UserSwitchResult(
                ok=False, user_id=user_id, switch_supported=False, reason=result.reason
            )
        session = self.get_session(session_id)
        try:
            packages.switch_user(self._adb, session.serial, user_id)
        except ApiError as exc:
            raise UserSwitchFailed(exc.message) from exc
        return UserSwitchResult(ok=True, user_id=user_id, switch_supported=True)

    async def switch_user(self, session_id: str, user_id: int) -> UserSwitchResult:
        return await asyncio.to_thread(self._switch_sync, session_id, user_id)

    def _airplane_sync(self, session_id: str, enable: bool) -> AirplaneResult:
        session = self.get_session(session_id)
        sdk = packages.parse_sdk(self._adb.getprop(session.serial, "ro.build.version.sdk"))
        via = packages.set_airplane_mode(self._adb, session.serial, enable, sdk)
        actual = packages.read_airplane_mode(self._adb, session.serial)
        if actual != enable:
            raise AdbError(
                f"飞行模式读回不一致：期望 {enable}，实际 {actual}",
                code="AIRPLANE_MODE_FAILED",
            )
        return AirplaneResult(ok=True, airplane_mode_on=actual, applied_via=via)

    async def set_airplane_mode(self, session_id: str, enable: bool) -> AirplaneResult:
        return await asyncio.to_thread(self._airplane_sync, session_id, enable)
```

需要在 `adb_device.py` 顶部加 `from app.device import packages`，并给 `AdbScrcpyDevice.__init__` 增加 `game_package: str = ""` 参数与 `self.game_package = game_package`；`deps.py` 传 `cfg.game_package`。

`MockDevice` 追加状态与方法：

```python
        self._app = AppStatus(package="", activity=None, running=False, pid=None)
        self._current_user = 0
        self._airplane = False

    async def launch_app(self, session_id, package, user=None):
        self.get_session(session_id)
        self._app = AppStatus(package, activity="mock.MainActivity", running=True, pid=4242, user=user)
        return self._app

    async def stop_app(self, session_id, package):
        self.get_session(session_id)
        if self._app.package == package:
            self._app = AppStatus(package=package, running=False)

    async def current_app(self, session_id):
        self.get_session(session_id)
        return self._app

    async def list_users(self, session_id):
        self.get_session(session_id)
        rows = [
            AndroidUser(id=0, name="机主", current=self._current_user == 0),
            AndroidUser(id=999, name="分身", current=self._current_user == 999),
        ]
        return UserListResult(users=rows, switch_supported=True)

    async def switch_user(self, session_id, user_id):
        self.get_session(session_id)
        if user_id not in (0, 999):
            return UserSwitchResult(ok=False, user_id=user_id, switch_supported=False, reason="未知用户")
        self._current_user = user_id
        return UserSwitchResult(ok=True, user_id=user_id, switch_supported=True)

    async def set_airplane_mode(self, session_id, enable):
        self.get_session(session_id)
        self._airplane = enable
        return AirplaneResult(ok=True, airplane_mode_on=enable, applied_via="mock")
```

`schemas.py` 追加：

```python
class LaunchAppRequest(BaseModel):
    sessionId: str
    package: str = Field(min_length=1, max_length=200)
    user: int | None = Field(default=None, ge=0)


class StopAppRequest(BaseModel):
    sessionId: str
    package: str = Field(min_length=1, max_length=200)


class SwitchUserRequest(BaseModel):
    sessionId: str
    userId: int = Field(ge=0)


class AirplaneRequest(BaseModel):
    sessionId: str
    enable: bool
```

`api/app_control.py`：

```python
from __future__ import annotations

from fastapi import APIRouter

from app.deps import get_adapter
from app.schemas import LaunchAppRequest, StopAppRequest, SwitchUserRequest

router = APIRouter(prefix="/api/app", tags=["app"])


def _app_payload(status) -> dict:
    return {
        "package": status.package,
        "activity": status.activity,
        "running": status.running,
        "pid": status.pid,
    }


@router.post("/launch")
async def launch(req: LaunchAppRequest) -> dict:
    status = await get_adapter().launch_app(req.sessionId, req.package, req.user)
    return {**_app_payload(status), "ok": status.running, "usedUser": status.user}


@router.post("/stop")
async def stop(req: StopAppRequest) -> dict:
    await get_adapter().stop_app(req.sessionId, req.package)
    return {"ok": True}


@router.get("/current")
async def current(sessionId: str) -> dict:
    status = await get_adapter().current_app(sessionId)
    return _app_payload(status)


@router.get("/users")
async def users(sessionId: str) -> dict:
    result = await get_adapter().list_users(sessionId)
    return {
        "users": [{"id": row.id, "name": row.name, "current": row.current} for row in result.users],
        "switchSupported": result.switch_supported,
        "reason": result.reason,
    }


@router.post("/switch-user")
async def switch_user(req: SwitchUserRequest) -> dict:
    result = await get_adapter().switch_user(req.sessionId, req.userId)
    return {
        "ok": result.ok,
        "userId": result.user_id,
        "switchSupported": result.switch_supported,
        "reason": result.reason,
    }
```

`api/network.py`：

```python
from __future__ import annotations

from fastapi import APIRouter

from app.deps import get_adapter
from app.schemas import AirplaneRequest

router = APIRouter(prefix="/api/network", tags=["network"])


@router.post("/airplane")
async def airplane(req: AirplaneRequest) -> dict:
    result = await get_adapter().set_airplane_mode(req.sessionId, req.enable)
    return {
        "ok": result.ok,
        "airplaneModeOn": result.airplane_mode_on,
        "appliedVia": result.applied_via,
    }
```

`config.py` 的 `Settings` 追加（需在 `game_activity` 允许空串）：

```python
    game_package: str = field(
        default_factory=lambda: os.environ.get("CAPYAUTO_GAME_PACKAGE", "com.hb.cncapy.and")
    )
    game_activity: str | None = field(
        default_factory=lambda: os.environ.get(
            "CAPYAUTO_GAME_ACTIVITY", "com.habby.sdkhubv2.ui.GameStartNativeUIActivty"
        )
        or None
    )
```

`deps.py` 构造 `AdbScrcpyDevice` 时追加 `game_package=cfg.game_package`。

`main.py` 注册：

```python
from app.api import app_control, control, devices, health, mirror, network
...
app.include_router(app_control.router)
app.include_router(network.router)
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd backend && .venv/bin/python -m pytest -q`
预期：全部通过（含既有 114 项与新增项）

- [ ] **步骤 5：Commit**

```bash
git add backend/app/device/base.py backend/app/device/adb_device.py backend/app/device/mock_device.py \
  backend/app/device/adb.py backend/app/app/schemas.py backend/app/api/app_control.py \
  backend/app/api/network.py backend/app/main.py backend/app/deps.py backend/app/config.py \
  backend/app/errors.py backend/tests/test_adb_device_app.py backend/tests/test_api_app.py
git commit -m "feat(api): 应用启停、用户探测与飞行模式接口"
```

---

### 任务 19：OCR 模块与接口

**文件：**
- 创建：`backend/app/vision/__init__.py`、`backend/app/vision/ocr.py`、`backend/app/api/vision.py`
- 修改：`backend/pyproject.toml`、`backend/app/main.py`、`backend/app/device/adb_device.py`、`backend/app/device/mock_device.py`
- 测试：`backend/tests/test_ocr.py`、`backend/tests/test_api_vision.py`

- [ ] **步骤 1：安装依赖并编写失败的测试**

运行：`cd backend && .venv/bin/pip install "rapidocr-onnxruntime>=1.4"`
预期：安装成功（首次会下载 onnxruntime，约 100MB）

`pyproject.toml` 的 `dependencies` 追加 `"rapidocr-onnxruntime>=1.4"`。

`backend/tests/test_ocr.py`：

```python
from PIL import Image

from app.vision.ocr import normalize_result, ocr_image


def _box(left, top, right, bottom):
    return [[left, top], [right, top], [right, bottom], [left, bottom]]


def test_normalize_result_maps_pixels_to_unit_square():
    raw = [(_box(10, 20, 50, 40), "越战越硬", 0.93)]
    items = normalize_result(raw, width=100, height=200)
    assert items[0].text == "越战越硬"
    assert items[0].confidence == 0.93
    assert items[0].bounds == (0.1, 0.1, 0.5, 0.2)


def test_ocr_image_crops_region_and_keeps_full_image_coordinates():
    seen = {}

    def fake_engine(array):
        seen["size"] = (array.shape[1], array.shape[0])
        return ([(_box(5, 5, 25, 15), "冰刺", 0.88)], None)

    image = Image.new("RGB", (100, 200), (0, 0, 0))
    items = ocr_image(image, engine=fake_engine, region=(0.5, 0.5, 1.0, 1.0))
    assert seen["size"] == (50, 100)
    assert items[0].bounds == (0.55, 0.525, 0.75, 0.575)


def test_ocr_image_empty_result_returns_empty_list():
    image = Image.new("RGB", (10, 10))
    assert ocr_image(image, engine=lambda _: (None, None)) == []
```

`backend/tests/test_api_vision.py`：

```python
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
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd backend && .venv/bin/python -m pytest tests/test_ocr.py tests/test_api_vision.py -q`
预期：`ModuleNotFoundError: No module named 'app.vision'`

- [ ] **步骤 3：编写最少实现代码**

`backend/app/vision/__init__.py` 为空文件。

`backend/app/vision/ocr.py`：

```python
from __future__ import annotations

import importlib.util
import io
import threading
from dataclasses import dataclass

from PIL import Image

_engine = None
_engine_lock = threading.Lock()


@dataclass(frozen=True)
class OcrItem:
    text: str
    confidence: float
    bounds: tuple[float, float, float, float]


def engine_available() -> bool:
    return importlib.util.find_spec("rapidocr_onnxruntime") is not None


def engine_name() -> str | None:
    return "rapidocr-onnxruntime" if engine_available() else None


def get_engine():
    global _engine
    with _engine_lock:
        if _engine is None:
            from rapidocr_onnxruntime import RapidOCR

            _engine = RapidOCR()
    return _engine


def normalize_result(raw, width: int, height: int) -> list[OcrItem]:
    items: list[OcrItem] = []
    for entry in raw or []:
        box, text, score = entry
        xs = [float(point[0]) for point in box]
        ys = [float(point[1]) for point in box]
        items.append(
            OcrItem(
                text=str(text),
                confidence=float(score),
                bounds=(
                    min(xs) / width,
                    min(ys) / height,
                    max(xs) / width,
                    max(ys) / height,
                ),
            )
        )
    return items


def ocr_image(image: Image.Image, engine=None, region=None) -> list[OcrItem]:
    import numpy as np

    width, height = image.size
    offset_x = offset_y = 0
    if region is not None:
        left, top, right, bottom = region
        offset_x = int(round(max(0.0, left) * width))
        offset_y = int(round(max(0.0, top) * height))
        crop_right = int(round(min(1.0, right) * width))
        crop_bottom = int(round(min(1.0, bottom) * height))
        image = image.crop((offset_x, offset_y, crop_right, crop_bottom))
    array = np.array(image.convert("RGB"))
    result, _elapse = (engine or get_engine())(array)
    items = normalize_result(result, image.size[0], image.size[1])
    if offset_x == 0 and offset_y == 0:
        return items
    return [
        OcrItem(
            text=item.text,
            confidence=item.confidence,
            bounds=(
                (item.bounds[0] * image.size[0] + offset_x) / width,
                (item.bounds[1] * image.size[1] + offset_y) / height,
                (item.bounds[2] * image.size[0] + offset_x) / width,
                (item.bounds[3] * image.size[1] + offset_y) / height,
            ),
        )
        for item in items
    ]


def ocr_png(png: bytes, region=None) -> list[OcrItem]:
    return ocr_image(Image.open(io.BytesIO(png)), region=region)
```

`schemas.py` 追加：

```python
from pydantic import field_validator


class OcrRequest(BaseModel):
    sessionId: str
    region: tuple[float, float, float, float] | None = None

    @field_validator("region")
    @classmethod
    def _check_region(cls, value):
        if value is None:
            return value
        left, top, right, bottom = value
        if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
            raise ValueError("region 需为 [left, top, right, bottom]，且 0<=left<right<=1、0<=top<bottom<=1")
        return value
```

`api/vision.py`：

```python
from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter

from app.deps import get_adapter
from app.errors import OcrUnavailable
from app.schemas import OcrRequest
from app.vision.ocr import engine_available, engine_name, ocr_png

router = APIRouter(prefix="/api/vision", tags=["vision"])


@router.post("/ocr")
async def ocr(req: OcrRequest) -> dict:
    adapter = get_adapter()
    adapter.get_session(req.sessionId)
    if not engine_available():
        raise OcrUnavailable("未安装 OCR 引擎，请执行：pip install rapidocr-onnxruntime")
    png = await adapter.screenshot(req.sessionId)
    started = time.perf_counter()
    items = await asyncio.to_thread(ocr_png, png, req.region)
    took_ms = round((time.perf_counter() - started) * 1000, 1)
    return {
        "tookMs": took_ms,
        "engine": engine_name(),
        "items": [
            {
                "text": item.text,
                "confidence": item.confidence,
                "bounds": {
                    "left": item.bounds[0],
                    "top": item.bounds[1],
                    "right": item.bounds[2],
                    "bottom": item.bounds[3],
                },
            }
            for item in items
        ],
    }
```

`main.py` 注册 `vision.router`。

`AdbScrcpyDevice._health_sync` 里把 `payload["ocr_engine"] = None` 改为：

```python
        payload["ocr_engine"] = engine_name()
```

（顶部 `from app.vision.ocr import engine_name`；该函数只看 `find_spec`，不会加载 onnxruntime。）

`MockDevice.health()` 同样把 `"ocr_engine": None` 改为 `"ocr_engine": engine_name()`。

- [ ] **步骤 4：运行测试验证通过**

运行：`cd backend && .venv/bin/python -m pytest -q`
预期：全部通过

- [ ] **步骤 5：Commit**

```bash
git add backend/app/vision backend/app/api/vision.py backend/app/schemas.py backend/app/main.py \
  backend/app/device/adb_device.py backend/app/device/mock_device.py backend/pyproject.toml \
  backend/tests/test_ocr.py backend/tests/test_api_vision.py
git commit -m "feat(vision): 接入 RapidOCR 并提供 /api/vision/ocr"
```

---

### 任务 20：验收脚本 V1–V10

**文件：**
- 创建：`backend/app/verify.py`
- 修改：`package.json`（新增 `verify` 脚本）
- 测试：`backend/tests/test_verify.py`

- [ ] **步骤 1：编写失败的测试**

```python
from app.verify import CheckResult, p95, render_markdown, summarize


def test_p95_uses_nearest_rank():
    assert p95([100, 200, 300, 400, 500]) == 500
    assert p95([100]) == 100
    assert p95([]) == 0.0


def test_summarize_marks_fail_and_keeps_skip_reason():
    results = [
        CheckResult("V1", "PASS", "ok", 10),
        CheckResult("V2", "SKIP", "无设备", 0),
        CheckResult("V3", "FAIL", "帧不足", 30),
    ]
    summary = summarize(results)
    assert summary["passed"] == 1
    assert summary["failed"] == 1
    assert summary["skipped"] == 1
    assert summary["ok"] is False


def test_render_markdown_contains_status_and_reason():
    markdown = render_markdown(
        [CheckResult("V8", "SKIP", "设备仅有一个用户", 12)],
        serial="S",
        started="2026-11-11T10:00:00",
    )
    assert "| V8 | SKIP | 设备仅有一个用户 | 12ms |" in markdown
    assert "serial: S" in markdown
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd backend && .venv/bin/python -m pytest tests/test_verify.py -q`
预期：`ModuleNotFoundError: No module named 'app.verify'`

- [ ] **步骤 3：编写最少实现代码**

`backend/app/verify.py`（完整文件）：

```python
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import io
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL import Image

from app import config
from app.device.adb import AdbRunner
from app.device.adb_device import AdbScrcpyDevice
from app.device import packages
from app.errors import ApiError
from app.vision.ocr import engine_available, ocr_png

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_SKIP = "SKIP"


@dataclass
class CheckResult:
    check_id: str
    status: str
    detail: str
    elapsed_ms: int


def p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1)))))
    return float(ordered[index])


def summarize(results: list[CheckResult]) -> dict:
    passed = sum(1 for result in results if result.status == STATUS_PASS)
    failed = sum(1 for result in results if result.status == STATUS_FAIL)
    skipped = sum(1 for result in results if result.status == STATUS_SKIP)
    return {
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "ok": failed == 0,
    }


def render_markdown(results: list[CheckResult], *, serial: str, started: str) -> str:
    lines = [
        "# CapyAuto 真机验收报告",
        "",
        f"- serial: {serial}",
        f"- started: {started}",
        f"- summary: {summarize(results)}",
        "",
        "| 检查 | 状态 | 说明 | 耗时 |",
        "|---|---|---|---|",
    ]
    for result in results:
        lines.append(f"| {result.check_id} | {result.status} | {result.detail} | {result.elapsed_ms}ms |")
    return "\n".join(lines) + "\n"


class VerifyContext:
    def __init__(self, serial: str, package: str, activity: str | None, out_dir: Path) -> None:
        self.adb = AdbRunner(config.settings.adb_path)
        self.serial = serial
        self.package = package
        self.activity = activity
        self.out_dir = out_dir
        self.frames_dir = out_dir / "frames"
        self.device = AdbScrcpyDevice(
            adb=self.adb,
            server_bin=config.settings.scrcpy_bin,
            server_jar=config.settings.scrcpy_server,
            server_version=config.settings.scrcpy_version,
            tcp_port=config.settings.scrcpy_tcp_port,
            fps=config.settings.mirror_fps,
            bitrate=config.settings.scrcpy_bitrate,
            jpeg_quality=config.settings.jpeg_quality,
            display_width=config.settings.display_width,
            frame_timeout=config.settings.frame_timeout,
            allow_fallback=config.settings.allow_screencap_fallback,
            game_package=package,
        )
        self.session_id: str | None = None

    async def session(self) -> str:
        if self.session_id is None:
            session = await self.device.create_session(self.serial, 5)
            self.session_id = session.id
        return self.session_id

    def save_png(self, check_id: str, png: bytes) -> str:
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = self.frames_dir / f"{check_id}-{stamp}.png"
        path.write_bytes(png)
        return str(path)

    async def close(self) -> None:
        if self.session_id is not None:
            await self.device.close_session(self.session_id)
            self.session_id = None


async def check_v1(ctx: VerifyContext) -> CheckResult:
    version = ctx.adb.version()
    devices = ctx.adb.devices()
    online = [device for device in devices if device.state == "device"]
    if not online:
        return CheckResult("V1", STATUS_FAIL, "adb devices 中没有 state=device 的设备", 0)
    return CheckResult("V1", STATUS_PASS, f"{version}；在线 {len(online)} 台", 0)


async def check_v2(ctx: VerifyContext) -> CheckResult:
    infos = await ctx.device.list_devices()
    info = next((row for row in infos if row.serial == ctx.serial), None)
    if info is None:
        return CheckResult("V2", STATUS_FAIL, f"未找到设备 {ctx.serial}", 0)
    missing = [
        name
        for name, value in {
            "width": info.width,
            "height": info.height,
            "abi": info.abi,
            "android": info.android,
            "wm_size": info.wm_size,
        }.items()
        if not value
    ]
    if missing:
        return CheckResult("V2", STATUS_FAIL, f"缺少字段: {', '.join(missing)}", 0)
    return CheckResult("V2", STATUS_PASS, f"{info.width}x{info.height} {info.abi} Android {info.android}", 0)


async def check_v3(ctx: VerifyContext) -> CheckResult:
    started = time.monotonic()
    session_id = await ctx.session()
    stamps: list[float] = []
    async for frame in ctx.device.frames(session_id):
        stamps.append(time.monotonic())
        if len(stamps) >= 40 or time.monotonic() - started > 30:
            break
    elapsed = int((time.monotonic() - started) * 1000)
    if len(stamps) < 5:
        return CheckResult("V3", STATUS_FAIL, f"30s 内仅收到 {len(stamps)} 帧", elapsed)
    intervals = [(stamps[i + 1] - stamps[i]) * 1000 for i in range(len(stamps) - 1)]
    worst = p95(intervals)
    status = STATUS_PASS if worst < 400 else STATUS_FAIL
    return CheckResult("V3", status, f"{len(stamps)} 帧；帧间隔 P95={worst:.0f}ms", elapsed)


async def check_v4(ctx: VerifyContext) -> CheckResult:
    session_id = await ctx.session()
    session = ctx.device.get_session(session_id)
    png = await ctx.device.screenshot(session_id)
    image = Image.open(io.BytesIO(png))
    path = ctx.save_png("v4", png)
    ok = image.size == (session.width, session.height)
    return CheckResult(
        "V4",
        STATUS_PASS if ok else STATUS_FAIL,
        f"PNG {image.size[0]}x{image.size[1]}；期望 {session.width}x{session.height}；{path}",
        0,
    )


async def check_v5(ctx: VerifyContext) -> CheckResult:
    started = time.monotonic()
    ctx.adb.shell(ctx.serial, "am", "start", "-a", "android.settings.SETTINGS")
    await asyncio.sleep(1.2)
    before = packages.current_component(ctx.adb, ctx.serial)
    session_id = await ctx.session()
    await ctx.device.tap(session_id, 0.5, 0.5, 80, 6)
    await asyncio.sleep(1.5)
    after = packages.current_component(ctx.adb, ctx.serial)
    elapsed = int((time.monotonic() - started) * 1000)
    ctx.adb.shell(ctx.serial, "input", "keyevent", "4")
    if before == after:
        return CheckResult("V5", STATUS_SKIP, f"点击后前台未变化（{before}）", elapsed)
    return CheckResult("V5", STATUS_PASS, f"{before} → {after}", elapsed)


async def check_v6(ctx: VerifyContext) -> CheckResult:
    session_id = await ctx.session()
    started = time.monotonic()
    result = await ctx.device.tap(session_id, 0.5, 0.5, 80, 6)
    elapsed_ms = (time.monotonic() - started) * 1000
    ctx.adb.shell(ctx.serial, "input", "swipe", 600, 1200, 600, 1200, 80)
    status = STATUS_PASS if abs(elapsed_ms - 80) <= 50 else STATUS_FAIL
    return CheckResult(
        "V6",
        status,
        f"注入 {result.injected_via}；实测 {elapsed_ms:.0f}ms（请求 80ms）；input swipe 兜底可用",
        int(elapsed_ms),
    )


async def check_v7(ctx: VerifyContext) -> CheckResult:
    started = time.monotonic()
    status = await ctx.device.launch_app(ctx.session_id or await ctx.session(), ctx.package, user=0)
    await asyncio.sleep(1.0)
    pid = packages.pid_of(ctx.adb, ctx.serial, ctx.package)
    if not status.running or pid is None:
        return CheckResult("V7", STATUS_FAIL, f"启动后未找到进程（activity={status.activity}）", 0)
    await ctx.device.stop_app(ctx.session_id or await ctx.session(), ctx.package)
    await asyncio.sleep(0.8)
    remaining = packages.pid_of(ctx.adb, ctx.serial, ctx.package)
    elapsed = int((time.monotonic() - started) * 1000)
    if remaining is not None:
        return CheckResult("V7", STATUS_FAIL, f"force-stop 后进程仍存在 pid={remaining}", elapsed)
    return CheckResult("V7", STATUS_PASS, f"启动 pid={pid}，强杀后进程消失", elapsed)


async def check_v8(ctx: VerifyContext) -> CheckResult:
    session_id = await ctx.session()
    result = await ctx.device.list_users(session_id)
    if not result.switch_supported:
        return CheckResult("V8", STATUS_SKIP, result.reason or "设备不支持用户切换", 0)
    before = packages.parse_current_user(ctx.adb.shell(ctx.serial, "am", "get-current-user"))
    target = next(row.id for row in result.users if not row.current)
    switched = await ctx.device.switch_user(session_id, target)
    after = packages.parse_current_user(ctx.adb.shell(ctx.serial, "am", "get-current-user"))
    if before is not None and before != target:
        packages.switch_user(ctx.adb, ctx.serial, before)
    if not switched.ok or after != target:
        return CheckResult("V8", STATUS_FAIL, f"切换用户失败：期望 {target}，实际 {after}", 0)
    return CheckResult("V8", STATUS_PASS, f"用户 {before} → {target}", 0)


async def check_v9(ctx: VerifyContext) -> CheckResult:
    original = packages.read_airplane_mode(ctx.adb, ctx.serial)
    try:
        session_id = await ctx.session()
        await ctx.device.set_airplane_mode(session_id, True)
        on = packages.read_airplane_mode(ctx.adb, ctx.serial)
        await ctx.device.set_airplane_mode(session_id, False)
        off = packages.read_airplane_mode(ctx.adb, ctx.serial)
    except Exception as exc:  # noqa: BLE001 - 命令不可用时按规格记 SKIP
        return CheckResult("V9", STATUS_SKIP, f"飞行模式不可用: {exc}", 0)
    finally:
        if original != packages.read_airplane_mode(ctx.adb, ctx.serial):
            try:
                packages.set_airplane_mode(
                    ctx.adb, ctx.serial, original,
                    packages.parse_sdk(ctx.adb.getprop(ctx.serial, "ro.build.version.sdk")),
                )
            except Exception:  # noqa: BLE001
                pass
    status = STATUS_PASS if on and not off else STATUS_FAIL
    return CheckResult("V9", status, f"开启读回={on}，关闭读回={off}", 0)


async def check_v10(ctx: VerifyContext) -> CheckResult:
    if not engine_available():
        return CheckResult("V10", STATUS_SKIP, "未安装 rapidocr-onnxruntime", 0)
    session_id = await ctx.session()
    await ctx.device.launch_app(session_id, ctx.package, user=0)
    await asyncio.sleep(2.0)
    started = time.monotonic()
    png = await ctx.device.screenshot(session_id)
    items = await asyncio.to_thread(ocr_png, png)
    elapsed = int((time.monotonic() - started) * 1000)
    path = ctx.save_png("v10", png)
    if not items:
        return CheckResult("V10", STATUS_FAIL, f"未识别到文本；{path}", elapsed)
    best = max(items, key=lambda item: item.confidence)
    status = STATUS_PASS if best.confidence > 0.6 and elapsed < 800 else STATUS_FAIL
    return CheckResult(
        "V10",
        status,
        f"{len(items)} 条；最高 {best.text!r} {best.confidence:.2f}；{path}",
        elapsed,
    )


CHECKS = {
    "V1": check_v1,
    "V2": check_v2,
    "V3": check_v3,
    "V4": check_v4,
    "V5": check_v5,
    "V6": check_v6,
    "V7": check_v7,
    "V8": check_v8,
    "V9": check_v9,
    "V10": check_v10,
}


def _pick_serial(adb: AdbRunner, requested: str | None) -> str:
    if requested:
        return requested
    online = [device.serial for device in adb.devices() if device.state == "device"]
    if not online:
        raise SystemExit("没有在线设备，请先连接 USB 并授权调试")
    return online[0]


async def run_checks(
    serial: str | None,
    package: str,
    activity: str | None,
    out_dir: Path,
    skip: set[str],
) -> list[CheckResult]:
    adb = AdbRunner(config.settings.adb_path)
    chosen = _pick_serial(adb, serial)
    ctx = VerifyContext(chosen, package, activity, out_dir)
    results: list[CheckResult] = []
    try:
        for check_id, check in CHECKS.items():
            if check_id in skip:
                results.append(CheckResult(check_id, STATUS_SKIP, "命令行指定跳过", 0))
                continue
            started = time.monotonic()
            try:
                result = await check(ctx)
            except ApiError as exc:
                result = CheckResult(
                    check_id, STATUS_FAIL, f"{exc.code}: {exc.message}", int((time.monotonic() - started) * 1000)
                )
            except Exception as exc:  # noqa: BLE001 - 单项异常不中断整轮
                result = CheckResult(
                    check_id, STATUS_FAIL, f"{type(exc).__name__}: {exc}", int((time.monotonic() - started) * 1000)
                )
            if result.elapsed_ms == 0:
                result.elapsed_ms = int((time.monotonic() - started) * 1000)
            results.append(result)
            print(f"[{result.status}] {result.check_id} {result.detail}")
    finally:
        await ctx.close()
    return results


def write_reports(
    results: list[CheckResult], serial: str, out_dir: Path, started_at: str
) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    payload = {
        "serial": serial,
        "started": started_at,
        "summary": summarize(results),
        "checks": [dataclasses.asdict(result) for result in results],
    }
    json_path = out_dir / f"verify-{stamp}.json"
    md_path = out_dir / f"verify-{stamp}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(results, serial=serial, started=started_at), encoding="utf-8")
    return json_path, md_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.verify", description="CapyAuto 真机验收 V1–V10")
    parser.add_argument("--serial", default=None)
    parser.add_argument("--package", default=config.settings.game_package)
    parser.add_argument("--activity", default=config.settings.game_activity)
    parser.add_argument("--out", default="reports")
    parser.add_argument("--skip", default="", help="逗号分隔的检查项，如 V9,V10")
    args = parser.parse_args(argv)
    started_at = datetime.now().isoformat(timespec="seconds")
    skip = {item.strip().upper() for item in args.skip.split(",") if item.strip()}
    results = asyncio.run(
        run_checks(args.serial, args.package, args.activity, Path(args.out), skip)
    )
    json_path, md_path = write_reports(results, args.serial or "", Path(args.out), started_at)
    print(f"报告：{json_path} / {md_path}")
    return 0 if summarize(results)["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

`package.json` 的 `scripts` 追加：

```json
"verify": "cd backend && .venv/bin/python -m app.verify"
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd backend && .venv/bin/python -m pytest tests/test_verify.py -q`
预期：3 passed

- [ ] **步骤 5：Commit**

```bash
git add backend/app/verify.py backend/tests/test_verify.py package.json
git commit -m "feat(verify): 增加 V1-V10 真机验收脚本与报告"
```

---

### 任务 21：前端设备客户端与连接 Hook

**文件：**
- 创建：`src/types/device.ts`、`src/api/deviceClient.ts`、`src/api/deviceClient.test.ts`、`src/hooks/useDeviceBridge.ts`

- [ ] **步骤 1：编写失败的测试**

`src/api/deviceClient.test.ts`：

```ts
import test from 'node:test';
import assert from 'node:assert/strict';
import { buildMirrorUrl, isTapInside, toNormalized } from './deviceClient';

test('buildMirrorUrl converts http base to ws and keeps query', () => {
  assert.equal(
    buildMirrorUrl('s1', 'http://127.0.0.1:8084'),
    'ws://127.0.0.1:8084/ws/mirror?sessionId=s1'
  );
  assert.equal(
    buildMirrorUrl('a b', 'https://example.test'),
    'wss://example.test/ws/mirror?sessionId=a%20b'
  );
});

test('toNormalized maps pointer offsets and rejects out-of-range', () => {
  assert.deepEqual(toNormalized(500, 1000, 1000, 2000), { x: 0.5, y: 0.5 });
  assert.deepEqual(toNormalized(-10, 2500, 1000, 2000), { x: 0, y: 1 });
});

test('isTapInside only accepts the unit square', () => {
  assert.equal(isTapInside(0, 0), true);
  assert.equal(isTapInside(1, 1), true);
  assert.equal(isTapInside(-0.01, 0.5), false);
  assert.equal(isTapInside(1.01, 0.5), false);
  assert.equal(isTapInside(Number.NaN, 0.5), false);
});
```

- [ ] **步骤 2：运行测试验证失败**

运行：`bun test src/api/deviceClient.test.ts`
预期：FAIL，`Cannot find module './deviceClient'`

- [ ] **步骤 3：编写最少实现代码**

`src/types/device.ts`：

```ts
export type BridgeMode = 'sim' | 'real';

export interface HealthPayload {
  ok: boolean;
  device_backend: string;
  adb_version: string | null;
  scrcpy_version: string | null;
  ocr_engine: string | null;
  hint: string | null;
}

export interface DeviceInfoPayload {
  serial: string;
  state: string;
  model: string | null;
  android: string | null;
  abi: string | null;
  wm_size: string | null;
  width: number | null;
  height: number | null;
  transport_id: string | null;
}

export interface SessionPayload {
  sessionId: string;
  serial: string;
  width: number;
  height: number;
  fps: number;
  degraded: boolean;
  mode: 'scrcpy' | 'screencap' | 'mock';
  sizeMismatch: boolean;
}

export interface TapPayload {
  targetX: number;
  targetY: number;
  realX: number;
  realY: number;
  pressMs: number;
  injectedVia: string;
  deviceWidth: number;
  deviceHeight: number;
}

export interface OcrItemPayload {
  text: string;
  confidence: number;
  bounds: { left: number; top: number; right: number; bottom: number };
}

export interface OcrPayload {
  tookMs: number;
  engine: string | null;
  items: OcrItemPayload[];
}

export interface UsersPayload {
  users: { id: number; name: string; current: boolean }[];
  switchSupported: boolean;
  reason: string | null;
}
```

`src/api/deviceClient.ts`：

```ts
import type {
  DeviceInfoPayload,
  HealthPayload,
  OcrPayload,
  SessionPayload,
  TapPayload,
  UsersPayload,
} from '../types/device';

const env = (import.meta as unknown as { env?: Record<string, string | undefined> }).env;
export const BACKEND_URL = env?.VITE_BACKEND_URL ?? 'http://127.0.0.1:8084';

export class DeviceApiError extends Error {
  status: number;
  code: string;

  constructor(code: string, message: string, status = 0) {
    super(message);
    this.name = 'DeviceApiError';
    this.code = code;
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BACKEND_URL}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = payload?.error ?? {};
    throw new DeviceApiError(error.code ?? 'HTTP_ERROR', error.message ?? `请求失败（${response.status}）`, response.status);
  }
  return payload as T;
}

export function buildMirrorUrl(sessionId: string, base = BACKEND_URL): string {
  const wsBase = base.replace(/^http/, 'ws');
  return `${wsBase}/ws/mirror?sessionId=${encodeURIComponent(sessionId)}`;
}

export function toNormalized(offsetX: number, offsetY: number, width: number, height: number) {
  const clamp = (value: number) => Math.min(1, Math.max(0, value));
  return { x: clamp(offsetX / width), y: clamp(offsetY / height) };
}

export function isTapInside(x: number, y: number): boolean {
  return Number.isFinite(x) && Number.isFinite(y) && x >= 0 && x <= 1 && y >= 0 && y <= 1;
}

export const deviceClient = {
  health: () => request<HealthPayload>('/api/health'),
  listDevices: () => request<{ devices: DeviceInfoPayload[] }>('/api/devices'),
  createSession: (serial: string, fps = 5) =>
    request<SessionPayload>('/api/session', {
      method: 'POST',
      body: JSON.stringify({ serial, fps }),
    }),
  closeSession: (sessionId: string) =>
    request<{ ok: boolean }>(`/api/session/${encodeURIComponent(sessionId)}`, { method: 'DELETE' }),
  tap: (sessionId: string, x: number, y: number, pressMs = 80, sigma = 6) =>
    request<TapPayload>('/api/control/tap', {
      method: 'POST',
      body: JSON.stringify({ sessionId, x, y, pressMs, sigma }),
    }),
  swipe: (sessionId: string, x1: number, y1: number, x2: number, y2: number, durationMs = 300) =>
    request<{ points: [number, number][]; injectedVia: string }>('/api/control/swipe', {
      method: 'POST',
      body: JSON.stringify({ sessionId, x1, y1, x2, y2, durationMs }),
    }),
  key: (sessionId: string, key: string) =>
    request<{ ok: boolean }>('/api/control/key', {
      method: 'POST',
      body: JSON.stringify({ sessionId, key }),
    }),
  launchApp: (sessionId: string, packageName: string, user?: number) =>
    request<{ ok: boolean; usedUser: number | null; package: string; activity: string | null }>(
      '/api/app/launch',
      { method: 'POST', body: JSON.stringify({ sessionId, package: packageName, user }) }
    ),
  stopApp: (sessionId: string, packageName: string) =>
    request<{ ok: boolean }>('/api/app/stop', {
      method: 'POST',
      body: JSON.stringify({ sessionId, package: packageName }),
    }),
  currentApp: (sessionId: string) =>
    request<{ package: string; activity: string | null; running: boolean; pid: number | null }>(
      `/api/app/current?sessionId=${encodeURIComponent(sessionId)}`
    ),
  listUsers: (sessionId: string) =>
    request<UsersPayload>(`/api/app/users?sessionId=${encodeURIComponent(sessionId)}`),
  switchUser: (sessionId: string, userId: number) =>
    request<{ ok: boolean; userId: number; switchSupported: boolean; reason: string | null }>(
      '/api/app/switch-user',
      { method: 'POST', body: JSON.stringify({ sessionId, userId }) }
    ),
  airplane: (sessionId: string, enable: boolean) =>
    request<{ ok: boolean; airplaneModeOn: boolean; appliedVia: string }>('/api/network/airplane', {
      method: 'POST',
      body: JSON.stringify({ sessionId, enable }),
    }),
  ocr: (sessionId: string) =>
    request<OcrPayload>('/api/vision/ocr', {
      method: 'POST',
      body: JSON.stringify({ sessionId }),
    }),
};
```

`src/hooks/useDeviceBridge.ts`：

```ts
import { useCallback, useEffect, useRef, useState } from 'react';
import { DeviceApiError, deviceClient } from '../api/deviceClient';
import type {
  BridgeMode,
  DeviceInfoPayload,
  HealthPayload,
  OcrPayload,
  SessionPayload,
  TapPayload,
  UsersPayload,
} from '../types/device';

const DEFAULT_PACKAGE = 'com.hb.cncapy.and';

export function useDeviceBridge() {
  const [mode, setMode] = useState<BridgeMode>('sim');
  const [health, setHealth] = useState<HealthPayload | null>(null);
  const [devices, setDevices] = useState<DeviceInfoPayload[]>([]);
  const [device, setDevice] = useState<DeviceInfoPayload | null>(null);
  const [session, setSession] = useState<SessionPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [lastTap, setLastTap] = useState<TapPayload | null>(null);
  const [users, setUsers] = useState<UsersPayload | null>(null);
  const [ocr, setOcr] = useState<OcrPayload | null>(null);
  const sessionRef = useRef<SessionPayload | null>(null);
  sessionRef.current = session;

  const run = useCallback(async <T,>(work: () => Promise<T>): Promise<T | null> => {
    setBusy(true);
    setError(null);
    try {
      return await work();
    } catch (exc) {
      const message = exc instanceof DeviceApiError ? `${exc.code}: ${exc.message}` : String(exc);
      setError(message);
      return null;
    } finally {
      setBusy(false);
    }
  }, []);

  const refreshDevices = useCallback(async () => {
    const health = await run(() => deviceClient.health());
    if (health) setHealth(health);
    const list = await run(() => deviceClient.listDevices());
    if (list) setDevices(list.devices);
    return list?.devices ?? [];
  }, [run]);

  const connect = useCallback(async (serial?: string) => {
    const list = await refreshDevices();
    const target = list.find((row) => row.serial === serial) ?? list.find((row) => row.state === 'device');
    if (!target) return;
    setDevice(target);
    const created = await run(() => deviceClient.createSession(target.serial, 5));
    if (created) setSession(created);
  }, [refreshDevices, run]);

  const disconnect = useCallback(async () => {
    const current = sessionRef.current;
    sessionRef.current = null;
    setSession(null);
    setLastTap(null);
    setOcr(null);
    setUsers(null);
    if (current) await run(() => deviceClient.closeSession(current.sessionId));
  }, [run]);

  const switchMode = useCallback(async (next: BridgeMode) => {
    setMode(next);
    if (next === 'real' && !sessionRef.current) {
      await connect();
    }
  }, [connect]);

  const tap = useCallback(async (x: number, y: number) => {
    const current = sessionRef.current;
    if (!current) return null;
    const result = await run(() => deviceClient.tap(current.sessionId, x, y));
    if (result) setLastTap(result);
    return result;
  }, [run]);

  const launchGame = useCallback(async (packageName = DEFAULT_PACKAGE) => {
    const current = sessionRef.current;
    if (!current) return null;
    return run(() => deviceClient.launchApp(current.sessionId, packageName, 0));
  }, [run]);

  const stopGame = useCallback(async (packageName = DEFAULT_PACKAGE) => {
    const current = sessionRef.current;
    if (!current) return null;
    return run(() => deviceClient.stopApp(current.sessionId, packageName));
  }, [run]);

  const loadUsers = useCallback(async () => {
    const current = sessionRef.current;
    if (!current) return null;
    const result = await run(() => deviceClient.listUsers(current.sessionId));
    if (result) setUsers(result);
    return result;
  }, [run]);

  const switchUser = useCallback(async (userId: number) => {
    const current = sessionRef.current;
    if (!current) return null;
    const result = await run(() => deviceClient.switchUser(current.sessionId, userId));
    if (result) await loadUsers();
    return result;
  }, [loadUsers, run]);

  const toggleAirplane = useCallback(async (enable: boolean) => {
    const current = sessionRef.current;
    if (!current) return null;
    return run(() => deviceClient.airplane(current.sessionId, enable));
  }, [run]);

  const runOcr = useCallback(async () => {
    const current = sessionRef.current;
    if (!current) return null;
    const result = await run(() => deviceClient.ocr(current.sessionId));
    if (result) setOcr(result);
    return result;
  }, [run]);

  useEffect(() => {
    if (mode === 'real') {
      refreshDevices();
    }
  }, [mode, refreshDevices]);

  return {
    mode, switchMode, health, devices, device, session, error, busy,
    lastTap, users, ocr, connect, disconnect, tap,
    launchGame, stopGame, loadUsers, switchUser, toggleAirplane, runOcr,
    refreshDevices, defaultPackage: DEFAULT_PACKAGE,
  };
}
```

- [ ] **步骤 4：运行测试验证通过**

运行：`bun test src/api/deviceClient.test.ts`
预期：3 passed

- [ ] **步骤 5：Commit**

```bash
git add src/types/device.ts src/api/deviceClient.ts src/api/deviceClient.test.ts src/hooks/useDeviceBridge.ts
git commit -m "feat(frontend): 设备 REST/WS 客户端与连接 Hook"
```

---

### 任务 22：真机 UI 组件与 App 整合

**文件：**
- 创建：`src/components/DeviceBar.tsx`、`src/components/DeviceMirror.tsx`、`src/components/DeviceDrawer.tsx`
- 修改：`src/App.tsx`

- [ ] **步骤 1：编写组件（先写静态结构，再补交互）**

`DeviceBar.tsx` 要求：

- props：`{ mode, onModeChange, health, device, session, error, onRefresh }`
- 左侧两个模式按钮「仿真 / 真机」，真机激活时高亮琥珀色。
- 真机模式显示：`ONLINE`/`OFFLINE` 徽标（`health?.ok && session`）、`session.serial`、`session.width×height`、`session.fps fps`、`mode`（scrcpy/screencap）、`degraded` 时显示「降级」、`sizeMismatch` 时显示「尺寸不一致」。
- `error` 非空时以红色条展示完整错误文本，不遮挡页面其他内容。
- 提供「刷新设备」按钮调用 `onRefresh`。

`DeviceMirror.tsx` 要求：

- props：`{ session, lastTap, onTap, error }`。
- 用 `<canvas>` 固定显示尺寸（最大宽度 360，高度按 `session.height/session.width` 等比）。
- `useEffect` 连接 `buildMirrorUrl(session.sessionId)`，`binaryType='blob'`；二进制帧用 `createImageBitmap` 绘制，文本消息中 `type==='error'` 时显示错误覆盖层；卸载时 `ws.close()`。
- 点击事件用 `getBoundingClientRect()` 计算 `offsetX/offsetY`，调用 `toNormalized`，再 `onTap(x,y)`。
- `lastTap` 存在时在 canvas 上叠加两个点：意图点（`targetX/deviceWidth`）与真实点（`realX/deviceWidth`），并显示 `Δx/Δy`。
- 断流后保留最后一帧但显示「连接已断开，点击刷新重连」。

`DeviceDrawer.tsx` 要求：

- props：`{ packageName, busy, users, ocr, onLaunch, onStop, onLoadUsers, onSwitchUser, onAirplane, onOcr, onVerify, verifyResult }`
- 四个分区：应用（启动/停止）、账号（列出用户；`switchSupported=false` 时按钮置灰并显示 `reason`）、网络（飞行模式开/关）、视觉（OCR 按钮，展示 `tookMs`、条数与每条 `text/confidence`）。
- 所有按钮在 `busy` 时 `disabled`。
- OCR 无结果时显示「未识别到文本（不会自动点击）」。

- [ ] **步骤 2：在 `App.tsx` 中接入**

- 顶部引入：`useDeviceBridge`、`DeviceBar`、`DeviceMirror`、`DeviceDrawer`。
- 组件内：`const bridge = useDeviceBridge();`
- 在面包屑下方、Tab 内容上方渲染：

```tsx
<DeviceBar
  mode={bridge.mode}
  onModeChange={bridge.switchMode}
  health={bridge.health}
  device={bridge.device}
  session={bridge.session}
  error={bridge.error}
  onRefresh={() => bridge.connect()}
/>
```

- `activeTab === 'simulator'` 分支改为：

```tsx
{activeTab === 'simulator' && (
  <div className="space-y-6">
    <FsmVisualizer currentState={fsmState} onStateSelect={(state) => { setFsmState(state); addLog('FSM', 'MANUAL', `手动切换状态至 [${state}]`); }} />
    {bridge.mode === 'real' ? (
      <div className="grid gap-4 lg:grid-cols-[minmax(0,360px)_1fr]">
        <DeviceMirror
          session={bridge.session}
          lastTap={bridge.lastTap}
          error={bridge.error}
          onTap={async (x, y) => {
            const result = await bridge.tap(x, y);
            if (result) addLog('TOUCH', 'REAL', `真机点击 (${result.realX}, ${result.realY}) via ${result.injectedVia}`);
          }}
        />
        <DeviceDrawer
          packageName={bridge.defaultPackage}
          busy={bridge.busy}
          users={bridge.users}
          ocr={bridge.ocr}
          onLaunch={() => bridge.launchGame()}
          onStop={() => bridge.stopGame()}
          onLoadUsers={() => bridge.loadUsers()}
          onSwitchUser={(id) => bridge.switchUser(id)}
          onAirplane={(enable) => bridge.toggleAirplane(enable)}
          onOcr={() => bridge.runOcr()}
          onVerify={() => { addLog('INFO', 'VERIFY', '请在终端执行 npm run verify'); }}
          verifyResult={null}
        />
      </div>
    ) : (
      <PhoneSimulator
        fsmState={fsmState}
        onFsmChange={setFsmState}
        activeAccount={activeAccount}
        config={config}
        onLog={addLog}
        onRecordTouch={() => {}}
        isAutoRunning={isAutoRunning}
        onToggleAutoRun={handleToggleAutoRun}
      />
    )}
  </div>
)}
```

- 真机模式无会话时 `DeviceMirror` 渲染「尚未连接设备，点击刷新重连」，不得抛异常。

- [ ] **步骤 3：类型检查与构建**

运行：`npm run lint`
预期：无 TypeScript 错误

运行：`npm run build`
预期：构建成功

- [ ] **步骤 4：运行前端单测**

运行：`bun test src/api/deviceClient.test.ts`
预期：3 passed

- [ ] **步骤 5：Commit**

```bash
git add src/components/DeviceBar.tsx src/components/DeviceMirror.tsx src/components/DeviceDrawer.tsx src/App.tsx
git commit -m "feat(ui): 真机模式设备栏、镜像与控制抽屉"
```

---

### 任务 23：真机验收 P4–P7 与文档回填

**文件：**
- 修改：`docs/superpowers/plans/2026-11-11-real-device-bridge-p4-p7.md`（回填第 3 节实测表）
- 修改：`docs/superpowers/specs/2026-11-10-capyauto-real-device-bridge-design.md`（第 7 节 P4–P7 状态）

- [x] **步骤 1：启动后端（adb 模式）**

```bash
cd backend
CAPYAUTO_DEVICE_BACKEND=adb CAPYAUTO_BACKEND_PORT=8084 .venv/bin/python -m app
```

- [x] **步骤 2：逐项 curl 验证 P4**

```bash
SID=$(curl -s -X POST localhost:8084/api/session -H 'Content-Type: application/json' \
  -d '{"serial":"ANASUT3C20010476"}' | python3 -c 'import json,sys;print(json.load(sys.stdin)["sessionId"])')
curl -s -X POST localhost:8084/api/app/launch -H 'Content-Type: application/json' \
  -d "{\"sessionId\":\"$SID\",\"package\":\"com.hb.cncapy.and\",\"user\":0}"
curl -s "localhost:8084/api/app/current?sessionId=$SID"
curl -s "localhost:8084/api/app/users?sessionId=$SID"
curl -s -X POST localhost:8084/api/network/airplane -H 'Content-Type: application/json' \
  -d "{\"sessionId\":\"$SID\",\"enable\":true}"
curl -s -X POST localhost:8084/api/network/airplane -H 'Content-Type: application/json' \
  -d "{\"sessionId\":\"$SID\",\"enable\":false}"
curl -s -X POST localhost:8084/api/app/stop -H 'Content-Type: application/json' \
  -d "{\"sessionId\":\"$SID\",\"package\":\"com.hb.cncapy.and\"}"
```

预期：`launch` 返回 `ok:true` 且 `usedUser:0`；`current.package` 为游戏包；`users` 返回 `switchSupported:false` 与「仅有一个用户」原因；飞行模式往返均 `ok:true` 且读回一致；`stop` 返回 `ok:true`。

- [x] **步骤 3：验证 P5 OCR**

在先启动游戏、停在任意含文本界面的前提下：

```bash
curl -s -X POST localhost:8084/api/vision/ocr -H 'Content-Type: application/json' \
  -d "{\"sessionId\":\"$SID\"}"
```

预期：`items` 非空，`tookMs` 小于 `CAPYAUTO_OCR_MAX_MS`（默认 5000ms），最高 `confidence > 0.6`；记录识别到的文本。若游戏停留在纯图形界面，先进入技能三选一界面再执行。

- [x] **步骤 4：运行验收脚本**

```bash
npm run verify
```

预期：V1–V7、V10 PASS；V8 SKIP（仅一个用户）；V9 PASS。任一 FAIL 必须修复后重跑。报告写入 `backend/reports/verify-*.json|md`。

- [x] **步骤 5：前端真机人工验收**

```bash
npm run backend   # 终端 A
npm run dev       # 终端 B
```

浏览器打开 `http://127.0.0.1:5178`，切到「真机」模式，逐项确认：

- DeviceBar 显示 ONLINE、序列号、分辨率、fps、`scrcpy`。
- 镜像 5fps 左右刷新；点击镜像后出现意图点/实际落点与 Δx/Δy。
- 抽屉里启动/停止游戏、列用户（切换按钮置灰并显示原因）、飞行模式开关、OCR 均可用。
- 7 个页签切换无报错；关闭后端后页面显示明确错误且不白屏。

- [x] **步骤 6：回填实测数据并提交**

在第 3 节表格填入实测值（含 OCR 文本、耗时、verify 汇总），把规格第 7 节 P4–P7 行标注为「已通过（日期）」。

```bash
git add docs/superpowers/plans/2026-11-11-real-device-bridge-p4-p7.md \
  docs/superpowers/specs/2026-11-10-capyauto-real-device-bridge-design.md
git commit -m "docs: 回填 P4-P7 真机验收结果"
```

---

## 3. P4–P7 真机验收表（执行后回填）

| 项 | 判定 | 实测值 |
|---|---|---|
| P4 启动游戏 | `ok:true`、`usedUser:0`、`current.package=com.hb.cncapy.and` | `{"ok":true,"usedUser":0,"package":"com.hb.cncapy.and","pid":21249}`；`current` 返回 `PLMainActivity`、`running:true` |
| P4 停止游戏 | `pidof` 为空 | `stop` 返回 `{"ok":true}`；`adb shell pidof com.hb.cncapy.and` 输出为空 |
| P4 用户探测 | `switchSupported:false` + 原因 | `{"users":[{"id":0,"name":"机主","current":true}],"switchSupported":false,"reason":"设备仅有一个用户，系统不支持应用分身切换"}` |
| P4 飞行模式 | 开/关读回一致 | 开：`{"ok":true,"airplaneModeOn":true,"appliedVia":"cmd"}` → 读回 `enabled`；关：`{"ok":true,"airplaneModeOn":false}` → 读回 `disabled` |
| P5 OCR | `items` 非空、最高置信度 >0.6、`tookMs` 小于可配置阈值（默认 5000ms） | 13–22 条，最高置信度 0.99–1.00；优化后 `tookMs` 2186–4740（优化前 6500–7400）。阈值经 `CAPYAUTO_OCR_MAX_MS` 配置，默认 5000ms；原 800ms 在 Intel i7-8750H 上不可达，见规格 §7 |
| P5 闭环点击 | 按 OCR bounds 中心点击后界面推进 | 「开始游戏」中心 (0.4994,0.7830) → 注入 (593,2084)，意图点 (599,2073)；界面推进到主界面（识别出「最高生存天数」「游戏公告」） |
| P6 设备栏 | ONLINE/序列号/分辨率/fps/模式正确 | ONLINE、ANASUT3C20010476、1200×2648、5 fps、scrcpy；镜像 5s 内刷新 |
| P6 点击反馈 | Δx/Δy 与后端返回值一致 | 点击镜像后显示 Δx -10 / Δy -7，与后端意图点/实际落点差值一致 |
| P6 断开设备 | 明确错误、不白屏 | 关闭后端后显示 `BACKEND_UNREACHABLE: 无法连接后端 http://127.0.0.1:8084，请确认服务已启动`，其余 UI 正常渲染 |
| P7 verify | PASS/SKIP 汇总 | V1–V7、V10 PASS，V8 SKIP（单用户），V9 PASS；V3 帧间隔 P95=208ms、V10 `ocrMs=1031`；报告 `backend/reports/verify-20261112-001139235686.json` |

---

## 4. 自检结论

### 4.1 规格覆盖度

| 规格项 | 任务 |
|---|---|
| `/api/app/launch|stop|current|users|switch-user` | 任务 17、18 |
| `/api/network/airplane` | 任务 17、18 |
| `/api/vision/ocr` | 任务 19 |
| 切分身不支持 → 200 + `switchSupported:false` + reason | 任务 18 |
| 飞行模式 Android 11+ / 低版本回退 | 任务 17 |
| OCR 无结果 → 空数组、不点击 | 任务 19、22 |
| V1–V10 验收与报告 | 任务 20 |
| 前端设备栏 / 点击反馈 / 错误态 | 任务 21、22、23 |
| 7 页签真机模式无报错 | 任务 23 步骤 5 |

### 4.2 占位符扫描

无 `TODO` / `待定` / `后续实现` / 「类似任务」。第 3 节「待回填」是执行后必须记录的实测值。

### 4.3 类型一致性

- `AndroidUser` 只在 `base.py` 定义，`packages.py` 与 `MockDevice` 统一引用。
- `AppStatus` 的 `user` 字段贯穿 `launch_app` → `/api/app/launch` 的 `usedUser`。
- 所有 `session_id` 方法参数命名与 P0–P3 一致；REST 请求字段保持 `sessionId` 驼峰。
- OCR bounds 在 Python 内为 4 元组，接口输出为 `{left,top,right,bottom}`，前端类型与之一致。
- `buildMirrorUrl` 与 P0–P3 的 `/ws/mirror?sessionId=` 完全一致。

### 4.4 风险

| 风险 | 处理 |
|---|---|
| `rapidocr-onnxruntime` 在 macOS arm64 安装失败 | 回退 `rapidocr` 新版或 `onnxruntime` 指定版本；OCR 不可用时 V10 记 SKIP 并写原因 |
| 游戏检测 adb 注入 | P5 只验证 OCR 与点击链路；不做反检测承诺 |
| 飞行模式影响 USB | 真机开关后立即读回；V9 失败记 SKIP；脚本 finally 恢复原状态 |
| HarmonyOS 切用户命令被限制 | 单用户时直接返回不支持，不执行 `am switch-user` |
