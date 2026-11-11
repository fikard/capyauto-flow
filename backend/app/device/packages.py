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


def launch_app(
    adb: AdbRunner,
    serial: str,
    package: str,
    activity: str | None = None,
    user: int | None = None,
) -> tuple[str | None, int | None]:
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


def stop_app(adb: AdbRunner, serial: str, package: str) -> None:
    adb.shell(serial, "am", "force-stop", package)


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
