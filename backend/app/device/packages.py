from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Callable, Literal

from app.device.adb import AdbRunner
from app.device.base import AndroidUser
from app.errors import AdbError

USER_LINE_RE = re.compile(r"UserInfo\{(\d+):([^:}]+):[0-9a-f]+\}\s*(.*)$")
ACTIVITY_RE = re.compile(
    r"(?:topResumedActivity|mResumedActivity|ResumedActivity)[=:]\s*"
    r"(?:ActivityRecord\{[^}]*?\s+)?([A-Za-z0-9_.]+/[A-Za-z0-9_.$]+)"
)
COMPONENT_LINE_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_.]*)/([A-Za-z0-9_.$]+)$")
UI_NODE_RE = re.compile(r"<node\b[^>]*>", re.S)
UI_BOUNDS_RE = re.compile(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')
UI_DUMP_PATH = "/sdcard/capyauto-launcher.xml"
# 桌面可能有多页：带文字标签的快捷方式未必在 HOME 键回到的那一页，最多翻 4 页找。
LAUNCHER_MAX_PAGES = 4

SleepFn = Callable[[float], None]


@dataclass(frozen=True)
class LauncherSpec:
    """经桌面快捷方式启动游戏的配置（游戏跑在变速器沙箱里时必需）。"""

    host_package: str = "com.joke.chongya"
    icon_label: str = "冒险者日记"
    icon_point: tuple[float, float] | None = None
    wait_s: float = 30.0
    mode: Literal["auto", "package", "launcher"] = "auto"


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


def parse_front_component(output: str) -> tuple[str, str] | None:
    match = ACTIVITY_RE.search(output)
    if match is None:
        return None
    package, activity = match.group(1).split("/", 1)
    return package, activity


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


def resolve_activity(
    adb: AdbRunner, serial: str, package: str, user: int | None = None
) -> str | None:
    args = ["cmd", "package", "resolve-activity", "--brief"]
    if user is not None:
        args += ["--user", str(user)]
    args.append(package)
    output = adb.shell(serial, *args)
    component = parse_component(output)
    return component[1] if component is not None and component[0] == package else None


def parse_launcher_bounds(
    xml: str, label: str, *, require_text: bool = False
) -> tuple[int, int] | None:
    """从 uiautomator dump 找桌面图标，返回可点击中心点。

    require_text=True 只认桌面图标的文字标签：HONOR 的「YOYO 建议」栏也会有
    同名 content-desc 小图标，点它会绕过变速器直接拉起游戏原生包。
    """
    candidates: list[tuple[bool, int, tuple[int, int]]] = []
    for tag in UI_NODE_RE.findall(xml):
        has_text = f'text="{label}"' in tag
        has_desc = f'content-desc="{label}"' in tag
        if not (has_text or has_desc) or (require_text and not has_text):
            continue
        match = UI_BOUNDS_RE.search(tag)
        if match is None:
            continue
        left, top, right, bottom = (int(value) for value in match.groups())
        candidates.append((has_text, (right - left) * (bottom - top), ((left + right) // 2, (top + bottom) // 2)))
    if not candidates:
        return None
    return max(candidates, key=lambda row: (row[0], row[1]))[2]


def is_host_installed(adb: AdbRunner, serial: str, host_package: str) -> bool:
    output = adb.shell(serial, "pm", "list", "packages", host_package)
    return f"package:{host_package}" in {line.strip() for line in output.splitlines()}


def should_use_launcher(adb: AdbRunner, serial: str, spec: LauncherSpec) -> bool:
    if spec.mode == "package":
        return False
    if spec.mode == "launcher":
        return True
    # auto：只有宿主变速器确实装在这台设备上时才改走桌面快捷方式
    return is_host_installed(adb, serial, spec.host_package)


def dump_ui_xml(adb: AdbRunner, serial: str) -> str:
    adb.shell(serial, "uiautomator", "dump", UI_DUMP_PATH, timeout=20)
    return adb.shell(serial, "cat", UI_DUMP_PATH, timeout=20)


def _fallback_point(
    adb: AdbRunner, serial: str, point: tuple[float, float] | None
) -> tuple[int, int] | None:
    if point is None:
        return None
    _raw, width, height = adb.wm_size(serial)
    if not width or not height:
        return None
    return int(width * point[0]), int(height * point[1])


def launch_via_launcher(
    adb: AdbRunner,
    serial: str,
    package: str,
    spec: LauncherSpec,
    *,
    sleep: SleepFn = time.sleep,
) -> tuple[str | None, int | None]:
    """点击桌面「冒险者日记」快捷方式，让变速器沙箱拉起游戏。

    沙箱启动 Activity 未导出，shell 的 am start 会被 SecurityException 拒绝，
    因此只能由 Launcher 触发；直启游戏包会绕过变速器，运行态不等价。
    """
    component = current_component(adb, serial)
    pid = pid_of(adb, serial, package)
    if pid is not None and component is not None and component[0] == spec.host_package:
        # 已经在变速器沙箱里运行：复用，避免重复点图标触发开屏广告
        return component[1], pid

    # 用 HOME 键而不是 am start -c HOME：后者在 HONOR 上会重开桌面并落到另一页
    adb.shell(serial, "input", "keyevent", "3")
    sleep(0.8)
    _raw, width, height = adb.wm_size(serial)
    width, height = width or 1080, height or 1920

    point: tuple[int, int] | None = None
    for page in range(LAUNCHER_MAX_PAGES):
        # 只认带文字标签的桌面图标；同名 content-desc 的「应用建议」会直启游戏包
        point = parse_launcher_bounds(
            dump_ui_xml(adb, serial), spec.icon_label, require_text=True
        )
        if point is not None:
            break
        if page < LAUNCHER_MAX_PAGES - 1:
            adb.shell(
                serial,
                "input",
                "swipe",
                str(int(width * 0.85)),
                str(int(height * 0.5)),
                str(int(width * 0.15)),
                str(int(height * 0.5)),
                "300",
            )
            sleep(0.8)
    if point is None:
        point = _fallback_point(adb, serial, spec.icon_point)
    if point is None:
        raise AdbError(
            f"桌面 {LAUNCHER_MAX_PAGES} 页内未找到 {spec.icon_label!r} 快捷方式，且未配置 CAPYAUTO_LAUNCHER_ICON_POINT",
            detail={"hostPackage": spec.host_package, "hint": "请确认桌面图标名称或显式配置归一化坐标"},
        )
    adb.shell(serial, "input", "tap", str(point[0]), str(point[1]))

    deadline = time.monotonic() + spec.wait_s
    last_component: tuple[str, str] | None = None
    while time.monotonic() < deadline:
        active = current_component(adb, serial)
        running_pid = pid_of(adb, serial, package)
        if running_pid is not None and active is not None and active[0] == spec.host_package:
            return active[1], running_pid
        if running_pid is not None and active is not None and active[0] == package:
            # 误点了「应用建议」等原生入口：游戏起来了但没进变速器沙箱，不能算启动成功
            if pid_of(adb, serial, spec.host_package) is None:
                raise AdbError(
                    f"点击后 {package} 以原生包启动，未进入 {spec.host_package} 沙箱",
                    detail={"tapped": list(point), "hint": "请检查桌面快捷方式标签或被点击的图标"},
                )
        last_component = active
        sleep(1.0)
    raise AdbError(
        f"点击桌面快捷方式后 {spec.wait_s:g}s 内未拉起 {package}",
        detail={
            "tapped": list(point),
            "lastComponent": "/".join(last_component) if last_component else None,
            "hint": "检查开屏广告、登录页或 CAPYAUTO_LAUNCHER_WAIT_S",
        },
    )


def launch_app(
    adb: AdbRunner,
    serial: str,
    package: str,
    activity: str | None = None,
    user: int | None = None,
    *,
    launcher: LauncherSpec | None = None,
    sleep: SleepFn = time.sleep,
) -> tuple[str | None, int | None]:
    if launcher is not None and should_use_launcher(adb, serial, launcher):
        return launch_via_launcher(adb, serial, package, launcher, sleep=sleep)
    resolved = activity or resolve_activity(adb, serial, package, user=user)
    args = ["am", "start", "-W"]
    if resolved:
        args += ["-n", f"{package}/{resolved}"]
    else:
        args += [
            "-a",
            "android.intent.action.MAIN",
            "-c",
            "android.intent.category.LAUNCHER",
            "-p",
            package,
        ]
    if user is not None:
        args += ["--user", str(user)]
    output = adb.shell(serial, *args, timeout=30)
    if "Error:" in output or "Exception" in output:
        raise AdbError(f"启动 {package} 失败", detail={"output": output[:500]})
    return resolved, pid_of(adb, serial, package)


def stop_app(
    adb: AdbRunner,
    serial: str,
    package: str,
    host_package: str | None = None,
    *,
    sleep: SleepFn = time.sleep,
) -> None:
    adb.shell(serial, "am", "force-stop", package)
    if not host_package:
        return
    sleep(0.5)
    if not is_host_installed(adb, serial, host_package):
        return
    # 变速器沙箱里的游戏是插件进程：force-stop 游戏包无效，必须强杀宿主才能停掉。
    # 只有插件确实还活着才动宿主，避免在变速器主页时把它无辜杀掉。
    if pid_of(adb, serial, package) is not None:
        adb.shell(serial, "am", "force-stop", host_package)


def current_component(adb: AdbRunner, serial: str) -> tuple[str, str] | None:
    return parse_front_component(adb.shell(serial, "dumpsys", "activity", "activities"))


def pid_of(adb: AdbRunner, serial: str, package: str) -> int | None:
    # pidof 在进程不存在时以退出码 1 结束，属于正常结果而不是 adb 故障
    output = adb.run("shell", "pidof", package, serial=serial, check=False)
    return parse_pid(str(output))


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
        installed_lines = {line.strip() for line in installed.splitlines()}
        if f"package:{package}" not in installed_lines:
            return False, f"用户 {row.id} 未安装 {package}"
    return True, None


def switch_user(adb: AdbRunner, serial: str, user_id: int) -> None:
    output = adb.shell(serial, "am", "switch-user", str(user_id), timeout=20)
    if "Error:" in output or "Exception" in output:
        raise AdbError(f"切换用户 {user_id} 失败", detail={"output": output[:500]})


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
