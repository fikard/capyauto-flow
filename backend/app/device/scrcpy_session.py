from __future__ import annotations

import io
import logging
import random
import re
import socket
import struct
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import av
from PIL import Image

from app.device.adb import AdbRunner
from app.device.base import Frame
from app.errors import InjectionFailed, ScrcpyUnavailable

log = logging.getLogger("capyauto.scrcpy")

DEVICE_NAME_LEN = 64
META_LEN = 76
PACKET_HEADER_LEN = 12
MAX_PACKET_SIZE = 8 * 1024 * 1024

# scrcpy 静态画面时默认约 10s 才发一个关键帧，读超时必须大于该间隔并留余量，
# 否则「屏幕静止」会被误判为断流；拔线时仍能在 ≤ VIDEO_READ_TIMEOUT 内感知。
VIDEO_READ_TIMEOUT = 20.0
# 握手期（读 76 字节 meta）与 control socket 沿用较短的 5s，避免建立失败时长时间卡住。
META_READ_TIMEOUT = 5.0
CONTROL_READ_TIMEOUT = 5.0

CODEC_IDS = {0x68323634: "h264", 0x68323635: "h265", 0x00617631: "av1"}

# 拔线 5s 内插回必须能自动恢复：重连按时间预算而非次数，退避指数增长但封顶 3s（0.5/1/2/3/3…）。
RECONNECT_BUDGET_S = 30.0
RECONNECT_BACKOFF_BASE_S = 0.5
RECONNECT_BACKOFF_MAX_S = 3.0
SERVER_VERSION_RE = re.compile(r"^\d+(\.\d+){1,2}$")

# 设备端 max_fps 已把帧率限制在目标值附近，客户端再严格按 1/fps 丢帧会因抖动
# 把略早到达的帧丢掉、再等下一个周期，实测 P95 间隔接近 2 倍目标间隔（5fps → 约 400ms）。
# 留 20% 容差后客户端最多放行到 1.25×fps，实际帧率仍由设备端 max_fps 兜底。
FPS_THROTTLE_TOLERANCE = 0.8

ACTION_DOWN, ACTION_UP, ACTION_MOVE = 0, 1, 2
MSG_INJECT_KEYCODE = 0
MSG_INJECT_TOUCH_EVENT = 2


def recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionError(f"socket 提前关闭，仍缺 {remaining} 字节")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


@dataclass(frozen=True)
class VideoMeta:
    device_name: str
    codec: str
    width: int
    height: int


def parse_device_meta(blob: bytes) -> VideoMeta:
    """scrcpy >= 2.0 视频 socket 头：64 字节设备名 + 4 字节 codec + 4+4 宽高。"""
    if len(blob) != META_LEN:
        raise ScrcpyUnavailable(f"视频头长度应为 {META_LEN}，实际 {len(blob)}")
    name = blob[:DEVICE_NAME_LEN].split(b"\x00", 1)[0].decode("utf-8", "replace")
    codec_id, width, height = struct.unpack(">III", blob[DEVICE_NAME_LEN:])
    if codec_id not in CODEC_IDS:
        raise ScrcpyUnavailable(
            f"未知 codec id 0x{codec_id:08x}，需要 scrcpy >= 2.0 且 video_codec=h264"
        )
    if width <= 0 or height <= 0:
        raise ScrcpyUnavailable(f"视频尺寸非法: {width}x{height}")
    return VideoMeta(device_name=name, codec=CODEC_IDS[codec_id], width=width, height=height)


def parse_packet_header(header: bytes) -> tuple[int, bool, bool, int]:
    """12 字节包头：8 字节 pts+flags（bit63=配置帧，bit62=关键帧）+ 4 字节长度。"""
    if len(header) != PACKET_HEADER_LEN:
        raise ValueError(f"包头长度应为 {PACKET_HEADER_LEN}，实际 {len(header)}")
    pts_flags, size = struct.unpack(">QI", header)
    return pts_flags & 0x3FFF_FFFF_FFFF_FFFF, bool(pts_flags >> 63), bool((pts_flags >> 62) & 1), size


def build_touch(
    action: int,
    pointer_id: int,
    x: int,
    y: int,
    width: int,
    height: int,
    pressure: int = 0xFFFF,
    buttons: int = 0,
) -> bytes:
    pressure = 0 if action == ACTION_UP else pressure
    return struct.pack(
        ">BBQiiHHHII", MSG_INJECT_TOUCH_EVENT, action, pointer_id, x, y, width, height, pressure, 0, buttons
    )


def build_key(action: int, keycode: int, repeat: int = 0, meta_state: int = 0) -> bytes:
    return struct.pack(">BBIII", MSG_INJECT_KEYCODE, action, keycode, repeat, meta_state)


class ScrcpySession:
    """单个设备的 scrcpy 会话：video socket 解码为 JPEG，control socket 注入事件。"""

    def __init__(
        self,
        session_id: str,
        serial: str,
        adb: AdbRunner,
        server_jar: Path,
        server_version: str,
        tcp_port: int,
        fps: int,
        bitrate: int,
        jpeg_quality: int,
        display_width: int,
    ) -> None:
        self.session_id = session_id
        self.serial = serial
        self.meta: VideoMeta | None = None
        self._adb = adb
        self._server_jar = server_jar
        self._server_version = server_version
        self._scid = ""
        self._tcp_port = tcp_port
        self._fps = max(1, fps)
        self._bitrate = bitrate
        self._jpeg_quality = jpeg_quality
        self._display_width = display_width
        self._lock = threading.Lock()
        self._inject_lock = threading.Lock()
        self._frame: Frame | None = None
        self._seq = 0
        self._decoded_count = 0
        self._stream_alive = False
        self._stop = threading.Event()
        self._video: socket.socket | None = None
        self._control: socket.socket | None = None
        self._server: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None

    @property
    def control_available(self) -> bool:
        return self._control is not None

    @property
    def stream_alive(self) -> bool:
        return self._stream_alive

    def start(self) -> VideoMeta:
        self._open_transport()
        if self.meta is None:
            raise ScrcpyUnavailable("scrcpy 会话未建立")
        self._stream_alive = True
        self._thread = threading.Thread(target=self._decode_loop, name=f"scrcpy-{self.session_id}", daemon=True)
        self._thread.start()
        return self.meta

    def _open_transport(self) -> None:
        if self._stop.is_set():
            raise ScrcpyUnavailable("scrcpy 会话已停止")
        # server_version 会原样拼进设备端 shell 命令，必须先校验格式
        if not SERVER_VERSION_RE.match(self._server_version):
            raise ScrcpyUnavailable(f"scrcpy 版本号非法: {self._server_version!r}")
        remote = "/data/local/tmp/scrcpy-server.jar"
        # scrcpy 3.x 的抽象 socket 名带 scid，且 scid 按 16 进制 int32 解析
        self._scid = f"{random.randrange(1, 0x7FFF_FFFF):08x}"
        try:
            self._adb.forward(self.serial, self._tcp_port, f"localabstract:scrcpy_{self._scid}")
            self._adb.push(self.serial, self._server_jar, remote)
            command = (
                f"CLASSPATH={remote} app_process / com.genymobile.scrcpy.Server {self._server_version} "
                f"log_level=info tunnel_forward=true audio=false video=true control=true "
                f"scid={self._scid} send_dummy_byte=false "
                f"max_fps={self._fps} video_bit_rate={self._bitrate} max_size=0 cleanup=true"
            )
            self._server = self._adb.popen_shell(self.serial, command)
            # server 必须等 video 与 control 两个 socket 都 accept 后才发 76 字节元数据；
            # adb forward 先于 server 监听时会立刻 EOF，所以整体重试。
            deadline = time.time() + 10.0
            last: Exception | None = None
            while time.time() < deadline and not self._stop.is_set():
                try:
                    self._video = self._connect(deadline_s=1.0, read_timeout=META_READ_TIMEOUT)
                    self._control = self._connect(deadline_s=1.0, read_timeout=CONTROL_READ_TIMEOUT)
                    self.meta = parse_device_meta(recv_exact(self._video, META_LEN))
                    self._video.settimeout(VIDEO_READ_TIMEOUT)
                    return
                except (OSError, ConnectionError, ScrcpyUnavailable) as exc:
                    last = exc
                    for sock in (self._control, self._video):
                        if sock is not None:
                            try:
                                sock.close()
                            except OSError:
                                pass
                    self._control = None
                    self._video = None
                    time.sleep(0.2)
            if self._stop.is_set():
                raise ScrcpyUnavailable("scrcpy 会话已停止")
            raise ScrcpyUnavailable(f"scrcpy 会话建立失败: {last}")
        except BaseException:
            # forward/push/server 可能已建立（尤其 stop() 在这几步之间介入），
            # 任何失败出口都必须回收，否则 server 进程与 adb forward 会永久残留。
            self._close_transport()
            raise

    def _connect(self, deadline_s: float = 8.0, read_timeout: float = META_READ_TIMEOUT) -> socket.socket:
        end = time.time() + deadline_s
        last: Exception | None = None
        while time.time() < end and not self._stop.is_set():
            try:
                sock = socket.create_connection(("127.0.0.1", self._tcp_port), timeout=3.0)
                sock.settimeout(read_timeout)
                return sock
            except OSError as exc:
                last = exc
                time.sleep(0.1)
        if self._stop.is_set():
            raise ScrcpyUnavailable("scrcpy 会话已停止")
        raise ScrcpyUnavailable(f"连接 scrcpy 端口 {self._tcp_port} 失败: {last}")

    def latest(self) -> Frame | None:
        with self._lock:
            return self._frame

    def _decode_loop(self) -> None:
        attempt = 0
        budget_deadline: float | None = None
        try:
            while not self._stop.is_set():
                decoded_before = self._decoded_count
                try:
                    self._decode_once()
                    return
                except Exception as exc:  # noqa: BLE001 - 任何异常都进入重连
                    if self._stop.is_set():
                        return
                    if self._decoded_count > decoded_before:
                        # 本轮已成功解出帧：视为新一次断流，失败计数与重连预算都从头开始
                        attempt = 0
                        budget_deadline = None
                    if budget_deadline is None:
                        budget_deadline = time.monotonic() + RECONNECT_BUDGET_S
                    attempt += 1
                    if time.monotonic() >= budget_deadline:
                        log.exception("scrcpy 重连 %.0fs 预算耗尽，放弃重连: %s", RECONNECT_BUDGET_S, exc)
                        self._close_transport()
                        return
                    backoff = min(
                        RECONNECT_BACKOFF_BASE_S * 2 ** (attempt - 1), RECONNECT_BACKOFF_MAX_S
                    )
                    log.warning("scrcpy 流中断（%s），第 %d 次重连，%.1fs 后重试", exc, attempt, backoff)
                    # Event.wait 可被 stop() 立即唤醒，避免 DELETE 被最长 3s 的退避拖住
                    if self._stop.wait(backoff):
                        return
                    try:
                        self._close_transport()
                        self._open_transport()
                    except Exception as restart_exc:  # noqa: BLE001
                        if self._stop.is_set():
                            # _open_transport 已自清理，这里只是兜底，避免任何路径留下 server/forward
                            self._close_transport()
                            return
                        log.error("重启 scrcpy 失败: %s", restart_exc)
        finally:
            self._stream_alive = False

    def _decode_once(self) -> None:
        video = self._video
        meta = self.meta
        if video is None or meta is None:
            raise ScrcpyUnavailable("scrcpy 会话尚未启动")
        ctx = av.CodecContext.create(meta.codec, "r")
        last_emit = 0.0
        while not self._stop.is_set():
            _pts_flags, is_config, _is_key, size = parse_packet_header(
                recv_exact(video, PACKET_HEADER_LEN)
            )
            if size <= 0 or size > MAX_PACKET_SIZE:
                raise ConnectionError(f"帧长度异常: {size}")
            payload = recv_exact(video, size)
            if is_config:
                # scrcpy 把 SPS/PPS 单独放在 config 包里，必须喂给解码器否则关键帧无法解出
                for packet in ctx.parse(payload):
                    ctx.decode(packet)
                continue
            for packet in ctx.parse(payload):
                for decoded in ctx.decode(packet):
                    now = time.monotonic()
                    if now - last_emit < (1.0 / self._fps) * FPS_THROTTLE_TOLERANCE:
                        continue
                    last_emit = now
                    self._store(decoded)

    def _store(self, decoded) -> None:
        image = decoded.to_image().convert("RGB")
        if image.width > self._display_width:
            ratio = self._display_width / image.width
            image = image.resize((self._display_width, max(1, int(image.height * ratio))), Image.BILINEAR)
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", quality=self._jpeg_quality)
        self._decoded_count += 1
        with self._lock:
            self._seq += 1
            self._frame = Frame(
                seq=self._seq, jpeg=buffer.getvalue(), width=image.width, height=image.height, ts=time.time()
            )

    def tap(self, x: int, y: int, press_ms: int) -> None:
        meta = self.meta
        if meta is None:
            raise InjectionFailed("scrcpy 会话尚未启动")
        with self._inject_lock:
            self._send(build_touch(ACTION_DOWN, 0, x, y, meta.width, meta.height))
            time.sleep(press_ms / 1000)
            self._send(build_touch(ACTION_UP, 0, x, y, meta.width, meta.height))

    def swipe(self, points: list[tuple[int, int]], duration_ms: int) -> None:
        meta = self.meta
        if meta is None:
            raise InjectionFailed("scrcpy 会话尚未启动")
        if not points:
            raise InjectionFailed("滑轨为空")
        step = (duration_ms / 1000) / max(len(points) - 1, 1)
        with self._inject_lock:
            cur_x, cur_y = points[0]
            self._send(build_touch(ACTION_DOWN, 0, cur_x, cur_y, meta.width, meta.height))
            released = False
            try:
                for px, py in points[1:-1]:
                    time.sleep(step)
                    cur_x, cur_y = px, py
                    self._send(build_touch(ACTION_MOVE, 0, cur_x, cur_y, meta.width, meta.height))
                time.sleep(step)
                cur_x, cur_y = points[-1]
                self._send(build_touch(ACTION_UP, 0, cur_x, cur_y, meta.width, meta.height))
                released = True
            finally:
                if not released:
                    # 中途失败也必须补发 UP，避免设备端残留按下状态
                    try:
                        self._send(build_touch(ACTION_UP, 0, cur_x, cur_y, meta.width, meta.height))
                    except Exception:  # noqa: BLE001
                        log.warning("补发 ACTION_UP 失败", exc_info=True)

    def key(self, keycode: int) -> None:
        with self._inject_lock:
            self._send(build_key(0, keycode))
            time.sleep(0.02)
            self._send(build_key(1, keycode))

    def _send(self, payload: bytes) -> None:
        sock = self._control
        if sock is None:
            raise InjectionFailed("control socket 不可用")
        try:
            sock.sendall(payload)
        except OSError as exc:
            self._control = None
            try:
                sock.close()
            except OSError:
                pass
            raise InjectionFailed(f"control socket 写入失败: {exc}") from exc

    def _close_transport(self) -> None:
        for sock in (self._control, self._video):
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
        self._control = None
        self._video = None
        if self._server is not None:
            self._server.terminate()
            try:
                self._server.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._server.kill()
            self._server = None
        self._adb.forward_remove(self.serial, self._tcp_port)

    def stop(self) -> None:
        self._stop.set()
        self._close_transport()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=3)
        self._stream_alive = False
