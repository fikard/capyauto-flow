from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

from app.device.base import DeviceInfo
from app.errors import AdbError, AdbNotFound, AdbTimeout, ApiError

ExecFn = Callable[[list[str], float], tuple[int, bytes, bytes]]


def _subprocess_exec(argv: list[str], timeout: float) -> tuple[int, bytes, bytes]:
    proc = subprocess.run(argv, capture_output=True, timeout=timeout)
    return proc.returncode, proc.stdout, proc.stderr


def parse_devices(output: str) -> list[DeviceInfo]:
    devices: list[DeviceInfo] = []
    for raw in output.splitlines():
        line = raw.strip()
        if not line or line.startswith("List of devices") or line.startswith("*"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        extra: dict[str, str] = {}
        for token in parts[2:]:
            if ":" in token:
                key, value = token.split(":", 1)
                extra.setdefault(key, value)
        devices.append(
            DeviceInfo(
                serial=parts[0],
                state=parts[1],
                model=extra.get("model"),
                transport_id=extra.get("transport_id"),
            )
        )
    return devices


def parse_wm_size(output: str) -> tuple[str, int | None, int | None]:
    override: str | None = None
    physical: str | None = None
    for raw in output.splitlines():
        line = raw.strip()
        if line.startswith("Override size:"):
            override = line.split(":", 1)[1].strip()
        elif line.startswith("Physical size:"):
            physical = line.split(":", 1)[1].strip()
    chosen = override or physical
    if not chosen or "x" not in chosen:
        return output.strip(), None, None
    width_text, height_text = chosen.split("x", 1)
    try:
        return output.strip(), int(width_text), int(height_text)
    except ValueError:
        return output.strip(), None, None


class AdbRunner:
    def __init__(self, adb_path: str = "adb", default_timeout: float = 10.0, exec_fn: ExecFn | None = None) -> None:
        self.adb_path = adb_path
        self.default_timeout = default_timeout
        self._exec_fn = exec_fn or _subprocess_exec

    def run(self, *args, serial: str | None = None, timeout: float | None = None, binary: bool = False):
        argv = [self.adb_path]
        if serial:
            argv += ["-s", serial]
        argv += [str(arg) for arg in args]
        effective_timeout = timeout or self.default_timeout
        try:
            code, out, err = self._exec_fn(argv, effective_timeout)
        except FileNotFoundError as exc:
            raise AdbNotFound("未找到 adb，请先执行 brew install scrcpy") from exc
        except subprocess.TimeoutExpired as exc:
            raise AdbTimeout(f"adb 超时（{effective_timeout}s）: {' '.join(argv)}") from exc
        if code != 0:
            raise AdbError(
                f"adb 命令失败（{code}）: {' '.join(argv)}",
                detail={"stderr": err.decode("utf-8", "replace")[:500]},
            )
        return out if binary else out.decode("utf-8", "replace").strip()

    def version(self) -> str:
        lines = str(self.run("version")).splitlines()
        return lines[0] if lines else "adb"

    def devices(self) -> list[DeviceInfo]:
        return parse_devices(str(self.run("devices", "-l")))

    def getprop(self, serial: str, prop: str) -> str:
        return str(self.run("shell", "getprop", prop, serial=serial))

    def wm_size(self, serial: str) -> tuple[str, int | None, int | None]:
        return parse_wm_size(str(self.run("shell", "wm", "size", serial=serial)))

    def push(self, serial: str, local: Path, remote: str) -> None:
        self.run("push", str(local), remote, serial=serial, timeout=60)

    def forward(self, serial: str, local_port: int, remote_spec: str) -> None:
        self.run("forward", f"tcp:{local_port}", remote_spec, serial=serial)

    def forward_remove(self, serial: str, local_port: int) -> None:
        # 清理路径必须尽力而为：adb 消失（AdbNotFound）或超时（AdbTimeout）都不应中断 close
        try:
            self.run("forward", "--remove", f"tcp:{local_port}", serial=serial)
        except ApiError:
            pass

    def exec_out(self, serial: str, *args) -> bytes:
        return self.run("exec-out", *args, serial=serial, binary=True, timeout=20)

    def popen_shell(self, serial: str, command: str) -> subprocess.Popen:
        try:
            return subprocess.Popen(
                [self.adb_path, "-s", serial, "shell", command],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise AdbNotFound("未找到 adb，请先执行 brew install scrcpy") from exc
