from __future__ import annotations

import asyncio
import dataclasses
import logging
import re
import socket
import subprocess
import threading
import time
from pathlib import Path

from app.core.dither import bezier_points, gaussian_click
from app.core.geometry import normalize_to_device
from app.device import packages
from app.device.adb import AdbRunner
from app.device.base import (
    AirplaneResult,
    AppStatus,
    DeviceAdapter,
    DeviceInfo,
    Frame,
    MirrorSession,
    SwipeResult,
    TapResult,
    UserListResult,
    UserSwitchResult,
    keycode_for,
)
from app.device.scrcpy_session import ScrcpySession
from app.device.screen import ScreencapPoller
from app.errors import (
    AdbError,
    AirplaneModeFailed,
    ApiError,
    DeviceNotFound,
    DeviceUnauthorized,
    MirrorLost,
    ScrcpyUnavailable,
    SessionNotFound,
    UserSwitchFailed,
)

log = logging.getLogger("capyauto.adb")


def detect_scrcpy_version(scrcpy_bin: str) -> str:
    proc = subprocess.run([scrcpy_bin, "--version"], capture_output=True, timeout=15)
    if proc.returncode != 0:
        raise ScrcpyUnavailable(f"{scrcpy_bin} --version 失败")
    match = re.search(r"scrcpy\s+(\d+\.\d+(?:\.\d+)?)", proc.stdout.decode("utf-8", "replace"))
    if not match:
        raise ScrcpyUnavailable("无法解析 scrcpy 版本号")
    return match.group(1)


def _is_port_free(port: int) -> bool:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        probe.close()


class AdbScrcpyDevice(DeviceAdapter):
    name = "adb"

    def __init__(
        self,
        adb: AdbRunner,
        server_bin: str,
        server_jar: Path | None,
        server_version: str | None,
        tcp_port: int,
        fps: int,
        bitrate: int,
        jpeg_quality: int,
        display_width: int,
        frame_timeout: float,
        allow_fallback: bool,
        game_package: str = "",
    ) -> None:
        self._adb = adb
        self._server_bin = server_bin
        self._server_jar = server_jar
        self._server_version = server_version
        self._tcp_port = tcp_port
        self._fps = fps
        self._bitrate = bitrate
        self._jpeg_quality = jpeg_quality
        self._display_width = display_width
        self._frame_timeout = frame_timeout
        self._allow_fallback = allow_fallback
        self.game_package = game_package
        self._sessions: dict[str, MirrorSession] = {}
        self._scrcpy: dict[str, ScrcpySession] = {}
        self._pollers: dict[str, ScreencapPoller] = {}
        self._ports_in_use: set[int] = set()
        self._session_ports: dict[str, int] = {}
        self._port_lock = threading.Lock()
        self._next_id = 1
        self._id_lock = threading.Lock()

    # ---------- 基础能力 ----------

    def _version(self) -> str:
        if self._server_version:
            return self._server_version
        return detect_scrcpy_version(self._server_bin)

    def _health_sync(self) -> dict:
        payload: dict = {
            "ok": False,
            "device_backend": self.name,
            "adb_version": None,
            "scrcpy_version": None,
            "ocr_engine": None,
            "hint": None,
        }
        try:
            payload["adb_version"] = self._adb.version()
        except ApiError as exc:
            payload["hint"] = f"{exc.message}；安装：brew install scrcpy"
            return payload
        try:
            payload["scrcpy_version"] = self._version()
        except Exception as exc:  # noqa: BLE001
            payload["hint"] = f"scrcpy 不可用: {exc}"
            return payload
        if self._server_jar is None:
            payload["hint"] = "未找到 scrcpy-server jar，请 brew install scrcpy"
            return payload
        payload["ok"] = True
        return payload

    async def health(self) -> dict:
        return await asyncio.to_thread(self._health_sync)

    def _probe(self, serial: str) -> DeviceInfo:
        match = next((d for d in self._adb.devices() if d.serial == serial), None)
        if match is None:
            raise DeviceNotFound(f"未找到设备 {serial}")
        if match.state == "unauthorized":
            raise DeviceUnauthorized("设备未授权，请在手机上确认 USB 调试授权")
        if match.state != "device":
            raise DeviceNotFound(f"设备 {serial} 状态为 {match.state}")
        wm_raw, width, height = self._adb.wm_size(serial)
        return dataclasses.replace(
            match,
            model=self._adb.getprop(serial, "ro.product.model"),
            abi=self._adb.getprop(serial, "ro.product.cpu.abi"),
            android=self._adb.getprop(serial, "ro.build.version.sdk"),
            wm_size=wm_raw,
            width=width,
            height=height,
        )

    def _list_sync(self) -> list[DeviceInfo]:
        infos: list[DeviceInfo] = []
        for info in self._adb.devices():
            if info.state != "device":
                infos.append(info)
                continue
            try:
                infos.append(self._probe(info.serial))
            except ApiError:
                infos.append(info)
        return infos

    async def list_devices(self) -> list[DeviceInfo]:
        return await asyncio.to_thread(self._list_sync)

    # ---------- 会话 ----------

    def _new_session_id(self) -> str:
        # 单调递增，绝不因关闭会话而回退复用（复用会覆盖现存会话）；
        # _create_sync 在 asyncio.to_thread 中并发执行，自增必须加锁。
        with self._id_lock:
            session_id = f"s{self._next_id}"
            self._next_id += 1
        return session_id

    def _allocate_port(self) -> int:
        # 每个 scrcpy 会话需要独立的 local tcp 端口，否则第二个 adb forward 会覆盖第一个，
        # 且任一会话 close 的 forward_remove 会摘掉别人的 forward。
        with self._port_lock:
            if self._tcp_port not in self._ports_in_use and _is_port_free(self._tcp_port):
                self._ports_in_use.add(self._tcp_port)
                return self._tcp_port
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            finally:
                probe.close()
            self._ports_in_use.add(port)
            return port

    def _release_port(self, port: int | None) -> None:
        if port is None:
            return
        with self._port_lock:
            self._ports_in_use.discard(port)

    def _create_sync(self, serial: str, fps: int) -> MirrorSession:
        info = self._probe(serial)
        session_id = self._new_session_id()
        # 会话尺寸是坐标换算与前端 meta 的唯一基准：scrcpy 用视频 meta 尺寸，screencap 用 wm size。
        fallback_width = info.width or 1080
        fallback_height = info.height or 2340

        if self._server_jar is None:
            if not self._allow_fallback:
                raise ScrcpyUnavailable("未找到 scrcpy-server jar，且 screencap 降级已禁用")
        else:
            transport: ScrcpySession | None = None
            port = self._allocate_port()
            try:
                transport = ScrcpySession(
                    session_id=session_id,
                    serial=serial,
                    adb=self._adb,
                    server_jar=self._server_jar,
                    server_version=self._version(),
                    tcp_port=port,
                    fps=fps,
                    bitrate=self._bitrate,
                    jpeg_quality=self._jpeg_quality,
                    display_width=self._display_width,
                )
                meta = transport.start()
            except Exception as exc:  # noqa: BLE001 - 版本探测/建连失败统一走降级
                self._release_port(port)
                if transport is not None:
                    transport.stop()
                if not self._allow_fallback:
                    if isinstance(exc, ScrcpyUnavailable):
                        raise
                    raise ScrcpyUnavailable(f"scrcpy 启动失败: {exc}") from exc
                log.warning("scrcpy 启动失败，降级 screencap: %s", exc)
            else:
                session = MirrorSession(
                    id=session_id,
                    serial=serial,
                    width=meta.width,
                    height=meta.height,
                    fps=fps,
                    mode="scrcpy",
                    size_mismatch=bool(
                        info.width and (info.width, info.height) != (meta.width, meta.height)
                    ),
                )
                self._sessions[session_id] = session
                self._scrcpy[session_id] = transport
                self._session_ports[session_id] = port
                return session

        # 降级通道按约 1fps 轮询：每次 screencap 都是完整 PNG 解码+JPEG 编码，开销远高于 scrcpy 复用码流。
        fallback_fps = min(fps, 1)
        poller = ScreencapPoller(
            self._adb,
            serial,
            fallback_width,
            fallback_height,
            fallback_fps,
            self._jpeg_quality,
            self._display_width,
        )
        poller.start()
        session = MirrorSession(
            id=session_id,
            serial=serial,
            width=fallback_width,
            height=fallback_height,
            fps=fallback_fps,
            degraded=True,
            mode="screencap",
        )
        self._sessions[session_id] = session
        self._pollers[session_id] = poller
        return session

    async def create_session(self, serial: str, fps: int) -> MirrorSession:
        return await asyncio.to_thread(self._create_sync, serial, fps)

    async def close_session(self, session_id: str) -> None:
        await asyncio.to_thread(self._close_sync, session_id)

    def _close_sync(self, session_id: str) -> None:
        # close 必须尽力而为且幂等：即使 transport/poller 清理失败（如 adb 二进制消失），
        # 也必须先把三个会话表清空，避免残留表项让 DELETE 返回 503。
        transport = self._scrcpy.pop(session_id, None)
        poller = self._pollers.pop(session_id, None)
        port = self._session_ports.pop(session_id, None)
        try:
            if transport is not None:
                transport.stop()
            if poller is not None:
                poller.stop()
        except Exception:  # noqa: BLE001 - 清理失败只告警
            log.warning("关闭会话 %s 时清理失败（会话表已清空）", session_id, exc_info=True)
        finally:
            self._sessions.pop(session_id, None)
            self._release_port(port)

    def get_session(self, session_id: str) -> MirrorSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise SessionNotFound(f"会话不存在: {session_id}")
        return session

    async def frames(self, session_id: str):
        session = self.get_session(session_id)
        transport = self._scrcpy.get(session_id)
        poller = self._pollers.get(session_id)
        last_seq = -1
        deadline = time.monotonic() + self._frame_timeout
        tick = min(1.0 / max(session.fps, 1), 0.25) / 4
        while True:
            if self._sessions.get(session_id) is None:
                return
            frame: Frame | None = None
            if transport is not None:
                # 重连/旋转后视频尺寸可能变化，会话尺寸与前端 meta 已固化，不能静默沿用旧值
                meta = transport.meta
                if meta is not None and (meta.width, meta.height) != (session.width, session.height):
                    raise MirrorLost("视频尺寸已变化，请重建会话")
                frame = transport.latest()
            elif poller is not None:
                frame = poller.latest()
            if frame is not None and frame.seq != last_seq:
                last_seq = frame.seq
                deadline = time.monotonic() + self._frame_timeout
                # Frame.width/height 是缩放后的展示尺寸，不可用于坐标换算
                yield frame
            elif transport is not None:
                # scrcpy 静态画面约 10s 才出一个关键帧，不能用 deadline 判失联；
                # 只认流存活：重连期间 stream_alive 仍为 True，拔插不会打断镜像。
                if not transport.stream_alive:
                    if self._sessions.get(session_id) is None:
                        return
                    raise MirrorLost(f"scrcpy 流已断开（mode={session.mode}）")
            elif time.monotonic() > deadline:
                raise MirrorLost(f"{self._frame_timeout}s 内没有新帧（mode={session.mode}）")
            await asyncio.sleep(tick)

    # ---------- 注入 ----------

    def _tap_sync(
        self, session_id: str, x: float, y: float, press_ms: float, sigma: float, press_stdev: float
    ) -> TapResult:
        session = self.get_session(session_id)
        plan = gaussian_click(
            x,
            y,
            session.width,
            session.height,
            sigma=sigma,
            press_mean=press_ms,
            press_stdev=press_stdev,
        )
        transport = self._scrcpy.get(session_id)
        if transport is not None and transport.control_available:
            transport.tap(plan.real_x, plan.real_y, plan.press_ms)
            via = "scrcpy"
        else:
            self._adb.run(
                "shell",
                "input",
                "swipe",
                plan.real_x,
                plan.real_y,
                plan.real_x,
                plan.real_y,
                plan.press_ms,
                serial=session.serial,
            )
            via = "input"
        return TapResult(
            target_x=plan.target_x,
            target_y=plan.target_y,
            real_x=plan.real_x,
            real_y=plan.real_y,
            press_ms=plan.press_ms,
            injected_via=via,
        )

    async def tap(
        self,
        session_id: str,
        x: float,
        y: float,
        press_ms: float,
        sigma: float,
        press_stdev: float = 20.0,
    ) -> TapResult:
        return await asyncio.to_thread(self._tap_sync, session_id, x, y, press_ms, sigma, press_stdev)

    def _swipe_sync(
        self, session_id: str, x1: float, y1: float, x2: float, y2: float, duration_ms: int
    ) -> SwipeResult:
        session = self.get_session(session_id)
        px1, py1 = normalize_to_device(x1, y1, session.width, session.height)
        px2, py2 = normalize_to_device(x2, y2, session.width, session.height)
        points = bezier_points(px1, py1, px2, py2)
        transport = self._scrcpy.get(session_id)
        if transport is not None and transport.control_available:
            transport.swipe(points, duration_ms)
            via = "scrcpy"
        else:
            self._adb.run(
                "shell",
                "input",
                "swipe",
                px1,
                py1,
                px2,
                py2,
                duration_ms,
                serial=session.serial,
            )
            via = "input"
        return SwipeResult(points=points, injected_via=via)

    async def swipe(
        self,
        session_id: str,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        duration_ms: int,
    ) -> SwipeResult:
        return await asyncio.to_thread(self._swipe_sync, session_id, x1, y1, x2, y2, duration_ms)

    def _key_sync(self, session_id: str, key: str) -> None:
        session = self.get_session(session_id)
        keycode = keycode_for(key)
        transport = self._scrcpy.get(session_id)
        if transport is not None and transport.control_available:
            transport.key(keycode)
        else:
            self._adb.run("shell", "input", "keyevent", keycode, serial=session.serial)

    async def key(self, session_id: str, key: str) -> None:
        await asyncio.to_thread(self._key_sync, session_id, key)

    async def screenshot(self, session_id: str) -> bytes:
        session = self.get_session(session_id)
        return await asyncio.to_thread(self._adb.exec_out, session.serial, "screencap", "-p")

    # ---------- 应用 / 用户 / 网络 ----------

    def _launch_sync(self, session_id: str, package: str, user: int | None) -> AppStatus:
        session = self.get_session(session_id)
        activity, pid = packages.launch_app(self._adb, session.serial, package, user=user)
        return AppStatus(
            package=package, activity=activity, running=pid is not None, pid=pid, user=user
        )

    async def launch_app(
        self, session_id: str, package: str, user: int | None = None
    ) -> AppStatus:
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
        supported, reason = packages.switch_support(
            self._adb, session.serial, self.game_package, rows
        )
        return UserListResult(users=rows, switch_supported=supported, reason=reason)

    async def list_users(self, session_id: str) -> UserListResult:
        return await asyncio.to_thread(self._users_sync, session_id)

    def _switch_sync(self, session_id: str, user_id: int) -> UserSwitchResult:
        result = self._users_sync(session_id)
        if not result.switch_supported:
            return UserSwitchResult(
                ok=False, user_id=user_id, switch_supported=False, reason=result.reason
            )
        if user_id not in {row.id for row in result.users}:
            return UserSwitchResult(
                ok=False, user_id=user_id, switch_supported=True, reason=f"未知用户 {user_id}"
            )
        session = self.get_session(session_id)
        try:
            packages.switch_user(self._adb, session.serial, user_id)
        except ApiError as exc:
            raise UserSwitchFailed(exc.message) from exc
        # am switch-user 是异步切换，立即回读可能仍是旧用户，需要短暂重试
        actual: int | None = None
        for attempt in range(10):
            try:
                actual = packages.parse_current_user(
                    self._adb.shell(session.serial, "am", "get-current-user")
                )
            except ApiError as exc:
                raise UserSwitchFailed(exc.message, detail=exc.detail) from exc
            if actual == user_id:
                return UserSwitchResult(ok=True, user_id=user_id, switch_supported=True)
            if attempt < 9:
                time.sleep(0.3)
        raise UserSwitchFailed(f"切换用户失败：期望 {user_id}，实际 {actual}")

    async def switch_user(self, session_id: str, user_id: int) -> UserSwitchResult:
        return await asyncio.to_thread(self._switch_sync, session_id, user_id)

    def _airplane_sync(self, session_id: str, enable: bool) -> AirplaneResult:
        session = self.get_session(session_id)
        sdk = packages.parse_sdk(self._adb.getprop(session.serial, "ro.build.version.sdk"))
        try:
            via = packages.set_airplane_mode(self._adb, session.serial, enable, sdk)
            actual = packages.read_airplane_mode(self._adb, session.serial)
        except ApiError as exc:
            raise AirplaneModeFailed(exc.message, detail=exc.detail) from exc
        if actual != enable:
            raise AirplaneModeFailed(f"飞行模式读回不一致：期望 {enable}，实际 {actual}")
        return AirplaneResult(ok=True, airplane_mode_on=actual, applied_via=via)

    async def set_airplane_mode(self, session_id: str, enable: bool) -> AirplaneResult:
        return await asyncio.to_thread(self._airplane_sync, session_id, enable)
