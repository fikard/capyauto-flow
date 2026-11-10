from __future__ import annotations

import socket
import struct
import threading
import time
from fractions import Fraction
from pathlib import Path

import pytest
from PIL import Image

import app.device.scrcpy_session as scrcpy_session
from app.device.scrcpy_session import (
    ACTION_DOWN,
    ACTION_MOVE,
    ACTION_UP,
    META_LEN,
    PACKET_HEADER_LEN,
    ScrcpySession,
    VideoMeta,
    parse_device_meta,
    parse_packet_header,
    recv_exact,
)
from app.errors import AdbError, InjectionFailed, ScrcpyUnavailable

TOUCH_MSG_LEN = 32
KEY_MSG_LEN = 14


def recv_into(sock: socket.socket, size: int) -> bytes:
    sock.settimeout(5.0)
    return recv_exact(sock, size)


class _FakeProc:
    def terminate(self) -> None:
        pass

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def kill(self) -> None:
        pass


class _FakeAdb:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def forward(self, serial: str, local_port: int, remote_spec: str) -> None:
        self.calls.append(("forward", serial, local_port, remote_spec))

    def push(self, serial: str, local: Path, remote: str) -> None:
        self.calls.append(("push", serial, str(local), remote))

    def popen_shell(self, serial: str, command: str) -> _FakeProc:
        self.calls.append(("popen_shell", serial, command))
        return _FakeProc()

    def forward_remove(self, serial: str, local_port: int) -> None:
        self.calls.append(("forward_remove", serial, local_port))


def make_session(**overrides) -> tuple[ScrcpySession, _FakeAdb]:
    adb = overrides.pop("adb", None) or _FakeAdb()
    params = {
        "session_id": "s1",
        "serial": "SER123",
        "adb": adb,
        "server_jar": Path("/tmp/scrcpy-server.jar"),
        "server_version": "3.1",
        "tcp_port": 27183,
        "fps": 5,
        "bitrate": 8_000_000,
        "jpeg_quality": 70,
        "display_width": 1080,
    }
    params.update(overrides)
    return ScrcpySession(**params), adb


def attach_control(session: ScrcpySession) -> tuple[socket.socket, socket.socket]:
    """用 socketpair 模拟 control 通道，返回 (客户端读端, session 写入端)。"""
    local, peer = socket.socketpair()
    session._control = peer
    session.meta = VideoMeta(device_name="pixel", codec="h264", width=1080, height=1920)
    return local, peer


def parse_touch(payload: bytes) -> tuple:
    return struct.unpack(">BBQiiHHHII", payload)


def parse_key(payload: bytes) -> tuple:
    return struct.unpack(">BBIII", payload)


class _StubDecoded:
    """假的 PyAV 解码帧，只实现 _store 用到的 to_image()。"""

    def to_image(self) -> Image.Image:
        return Image.new("RGB", (8, 8), (255, 0, 0))


class _FakeClock:
    def __init__(self) -> None:
        self.sleeps: list[float] = []
        self.on_sleep = None

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        if self.on_sleep is not None:
            self.on_sleep()

    def time(self) -> float:
        return time.time()

    def monotonic(self) -> float:
        return time.monotonic()


def build_meta_blob(name: bytes = b"pixel") -> bytes:
    return struct.pack(">64sIII", name, 0x68323634, 1080, 1920)


def build_wire_frame(payload: bytes, *, config: bool = False, key: bool = False) -> bytes:
    flags = 0
    if config:
        flags |= 1 << 63
    if key:
        flags |= 1 << 62
    return struct.pack(">QI", flags, len(payload)) + payload


def split_annexb(data: bytes) -> list[bytes]:
    starts = []
    index = 0
    while True:
        pos = data.find(b"\x00\x00\x01", index)
        if pos < 0:
            break
        starts.append(pos + 3)
        index = pos + 3
    return [
        data[start : starts[i + 1] - 3 if i + 1 < len(starts) else len(data)]
        for i, start in enumerate(starts)
    ]


def encode_h264_stream(width: int = 64, height: int = 48, count: int = 6) -> tuple[bytes, list[bytes]]:
    """本地编码一小段 H.264，返回 (config(SPS/PPS), 帧 payload 列表)。"""
    av = pytest.importorskip("av")
    try:
        ctx = av.CodecContext.create("libx264", "w")
    except Exception as exc:  # noqa: BLE001 - 编码器缺失时跳过真实解码用例
        pytest.skip(f"当前 PyAV 无法编码 h264: {exc}")
    ctx.width = width
    ctx.height = height
    ctx.pix_fmt = "yuv420p"
    ctx.time_base = Fraction(1, 5)
    ctx.framerate = Fraction(5, 1)
    ctx.options = {
        "preset": "ultrafast",
        "tune": "zerolatency",
        "x264-params": "keyint=10:min-keyint=10:repeat-headers=1",
    }
    packets = []
    for i in range(count):
        frame = av.VideoFrame.from_image(Image.new("RGB", (width, height), (i * 30 % 255, 10, 10)))
        frame.pts = i
        packets.extend(ctx.encode(frame))
    packets.extend(ctx.encode(None))

    first_nals = split_annexb(bytes(packets[0]))
    config = b"".join(b"\x00\x00\x00\x01" + nal for nal in first_nals if (nal[0] & 0x1F) in (7, 8))
    keyframe = b"".join(b"\x00\x00\x00\x01" + nal for nal in first_nals if (nal[0] & 0x1F) not in (7, 8))
    frames = [keyframe] + [bytes(packet) for packet in packets[1:]]
    return config, frames


def test_recv_exact_returns_full_buffer():
    left, right = socket.socketpair()
    try:
        left.sendall(b"abcdef")
        assert recv_exact(right, 6) == b"abcdef"
    finally:
        left.close()
        right.close()


def test_recv_exact_raises_on_closed_socket():
    left, right = socket.socketpair()
    left.close()
    try:
        with pytest.raises(ConnectionError):
            recv_exact(right, 4)
    finally:
        right.close()


def test_recv_exact_bad_meta_length():
    with pytest.raises(ScrcpyUnavailable):
        parse_device_meta(b"\x00" * (META_LEN - 1))


def test_packet_header_size_guard():
    _, _, _, size = parse_packet_header(struct.pack(">QI", 0, 1024))
    assert size == 1024
    assert PACKET_HEADER_LEN == 12


def test_tap_sends_down_then_up():
    session, _ = make_session()
    local, _peer = attach_control(session)
    try:
        session.tap(100, 200, 5)
        down = parse_touch(recv_into(local, TOUCH_MSG_LEN))
        up = parse_touch(recv_into(local, TOUCH_MSG_LEN))
    finally:
        local.close()
    assert down[0] == 2 and down[1] == ACTION_DOWN
    assert (down[3], down[4], down[5], down[6]) == (100, 200, 1080, 1920)
    assert down[7] == 0xFFFF
    assert up[1] == ACTION_UP
    assert up[7] == 0


def test_swipe_sends_down_move_up_in_order():
    session, _ = make_session()
    local, _peer = attach_control(session)
    try:
        session.swipe([(0, 0), (10, 20), (30, 40)], 20)
        messages = [parse_touch(recv_into(local, TOUCH_MSG_LEN)) for _ in range(3)]
    finally:
        local.close()
    assert [message[1] for message in messages] == [ACTION_DOWN, ACTION_MOVE, ACTION_UP]
    assert (messages[1][3], messages[1][4]) == (10, 20)
    assert (messages[2][3], messages[2][4]) == (30, 40)


def test_key_sends_down_and_up():
    session, _ = make_session()
    local, _peer = attach_control(session)
    try:
        session.key(4)
        down = parse_key(recv_into(local, KEY_MSG_LEN))
        up = parse_key(recv_into(local, KEY_MSG_LEN))
    finally:
        local.close()
    assert down[:2] == (0, ACTION_DOWN)
    assert up[:2] == (0, ACTION_UP)
    assert down[2] == up[2] == 4


def test_injection_requires_control_and_meta():
    session, _ = make_session()
    session.meta = VideoMeta(device_name="pixel", codec="h264", width=1080, height=1920)
    with pytest.raises(InjectionFailed):
        session.tap(1, 1, 1)

    local, _peer = attach_control(session)
    try:
        session.meta = None
        with pytest.raises(InjectionFailed):
            session.tap(1, 1, 1)
    finally:
        local.close()


def test_swipe_releases_pointer_when_send_fails(monkeypatch):
    session, _ = make_session()
    session.meta = VideoMeta(device_name="pixel", codec="h264", width=1080, height=1920)
    sent: list[bytes] = []

    def failing_send(payload: bytes) -> None:
        sent.append(payload)
        if len(sent) == 2:
            raise InjectionFailed("注入失败")

    monkeypatch.setattr(session, "_send", failing_send)
    with pytest.raises(InjectionFailed):
        session.swipe([(0, 0), (10, 10), (20, 20)], 10)
    actions = [parse_touch(payload)[1] for payload in sent]
    assert actions == [ACTION_DOWN, ACTION_MOVE, ACTION_UP]
    assert parse_touch(sent[-1])[7] == 0


def test_send_failure_disables_control():
    session, _ = make_session()
    session.meta = VideoMeta(device_name="pixel", codec="h264", width=1080, height=1920)
    dead = socket.socket()
    dead.close()
    session._control = dead
    with pytest.raises(InjectionFailed):
        session.key(4)
    assert session.control_available is False


def test_concurrent_taps_do_not_interleave():
    session, _ = make_session()
    local, _peer = attach_control(session)
    errors: list[Exception] = []

    def do_tap(x: int) -> None:
        try:
            session.tap(x, 10, 20)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=do_tap, args=(x,)) for x in (100, 200)]
    try:
        for thread in threads:
            thread.start()
        messages = [parse_touch(recv_into(local, TOUCH_MSG_LEN)) for _ in range(4)]
        for thread in threads:
            thread.join(5)
    finally:
        local.close()
    assert not errors
    assert [message[1] for message in messages] == [ACTION_DOWN, ACTION_UP, ACTION_DOWN, ACTION_UP]
    assert messages[0][3] == messages[1][3]
    assert messages[2][3] == messages[3][3]
    assert messages[0][3] != messages[2][3]


def test_decode_once_stores_jpeg_from_wire_packets():
    config, frames = encode_h264_stream()
    session, _ = make_session(fps=5)
    remote, local = socket.socketpair()
    try:
        session._video = local
        session.meta = VideoMeta(device_name="pixel", codec="h264", width=64, height=48)
        wire = build_wire_frame(config, config=True)
        for index, payload in enumerate(frames):
            wire += build_wire_frame(payload, key=index == 0)
        remote.sendall(wire)
        remote.close()
        with pytest.raises(ConnectionError):
            session._decode_once()
        frame = session.latest()
    finally:
        local.close()
    assert frame is not None
    assert frame.jpeg[:2] == b"\xff\xd8"
    assert (frame.width, frame.height) == (64, 48)


def test_decode_loop_gives_up_and_closes_after_consecutive_failures(monkeypatch, caplog):
    session, _adb = make_session()
    clock = _FakeClock()
    monkeypatch.setattr(scrcpy_session, "time", clock)
    opened: list[int] = []
    closed: list[int] = []

    def fake_open() -> None:
        opened.append(1)
        session.meta = VideoMeta(device_name="pixel", codec="h264", width=64, height=48)

    monkeypatch.setattr(session, "_open_transport", fake_open)
    monkeypatch.setattr(session, "_close_transport", lambda: closed.append(1))

    def always_fail() -> None:
        raise ConnectionError("视频流中断")

    monkeypatch.setattr(session, "_decode_once", always_fail)
    with caplog.at_level("ERROR", logger="capyauto.scrcpy"):
        session.start()
        session._thread.join(5)
    assert not session._thread.is_alive()
    assert len(opened) == 4  # start 1 次 + 3 次重连
    assert len(closed) == 4  # 每次重连前 3 次 + 放弃时 1 次
    assert clock.sleeps == [0.5, 1.0, 2.0]
    assert session.stream_alive is False
    assert any(record.exc_info for record in caplog.records)


def test_decode_loop_resets_attempt_after_decoded_frame(monkeypatch):
    session, _adb = make_session()
    clock = _FakeClock()
    monkeypatch.setattr(scrcpy_session, "time", clock)
    opened: list[int] = []
    closed: list[int] = []

    def fake_open() -> None:
        opened.append(1)
        session.meta = VideoMeta(device_name="pixel", codec="h264", width=64, height=48)

    monkeypatch.setattr(session, "_open_transport", fake_open)
    monkeypatch.setattr(session, "_close_transport", lambda: closed.append(1))

    script = ["fail", "success", "fail", "success", "fail", "stop"]

    def decode_once() -> None:
        step = script.pop(0)
        if step == "success":
            session._store(_StubDecoded())
        if step == "stop":
            session._stop.set()
        raise ConnectionError("视频流中断")

    monkeypatch.setattr(session, "_decode_once", decode_once)
    session.start()
    session._thread.join(5)
    assert not session._thread.is_alive()
    assert script == []
    assert len(opened) == 6  # start 1 次 + 5 次重连：成功过就不再累计失败
    assert session.stream_alive is False


def test_backoff_aborts_reopen_when_stopped(monkeypatch):
    session, _adb = make_session()
    clock = _FakeClock()
    monkeypatch.setattr(scrcpy_session, "time", clock)
    opened: list[int] = []
    monkeypatch.setattr(session, "_open_transport", lambda: opened.append(1))
    monkeypatch.setattr(session, "_close_transport", lambda: None)

    def always_fail() -> None:
        raise ConnectionError("视频流中断")

    monkeypatch.setattr(session, "_decode_once", always_fail)
    clock.on_sleep = session._stop.set
    session._decode_loop()
    assert opened == []


def test_stream_alive_tracks_thread_lifecycle(monkeypatch):
    session, _adb = make_session()

    def fake_open() -> None:
        session.meta = VideoMeta(device_name="pixel", codec="h264", width=64, height=48)

    monkeypatch.setattr(session, "_open_transport", fake_open)
    gate = threading.Event()
    monkeypatch.setattr(session, "_decode_loop", lambda: gate.wait(5))
    try:
        meta = session.start()
        assert meta.device_name == "pixel"
        assert session.stream_alive is True
        gate.set()
        session._thread.join(5)
        session.stop()
    finally:
        gate.set()
    assert session.stream_alive is False


def test_open_transport_uses_long_video_read_timeout(monkeypatch):
    session, adb = make_session()
    video_remote, video_local = socket.socketpair()
    control_remote, control_local = socket.socketpair()
    video_remote.sendall(build_meta_blob())
    pending = [video_local, control_local]

    def fake_connect(deadline_s: float = 8.0, read_timeout: float | None = None) -> socket.socket:
        sock = pending.pop(0)
        sock.settimeout(read_timeout)
        return sock

    monkeypatch.setattr(session, "_connect", fake_connect)
    try:
        session._open_transport()
        assert session.meta == VideoMeta(device_name="pixel", codec="h264", width=1080, height=1920)
        assert video_local.gettimeout() == scrcpy_session.VIDEO_READ_TIMEOUT
        assert control_local.gettimeout() == scrcpy_session.CONTROL_READ_TIMEOUT
        assert adb.calls[0][0] == "forward"
    finally:
        session._close_transport()
        video_remote.close()
        control_remote.close()


def test_connect_applies_requested_read_timeout():
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    session, _adb = make_session(tcp_port=listener.getsockname()[1])
    try:
        sock = session._connect(deadline_s=2.0, read_timeout=2.5)
        try:
            assert sock.gettimeout() == 2.5
        finally:
            sock.close()
    finally:
        listener.close()


def test_open_transport_aborts_when_stopped():
    session, adb = make_session()
    session._stop.set()
    with pytest.raises(ScrcpyUnavailable):
        session._open_transport()
    assert adb.calls == []


class _TrackingProc:
    def __init__(self) -> None:
        self.terminated = 0
        self.waited = 0
        self.killed = 0

    def terminate(self) -> None:
        self.terminated += 1

    def wait(self, timeout: float | None = None) -> int:
        self.waited += 1
        return 0

    def kill(self) -> None:
        self.killed += 1


def test_open_transport_push_failure_removes_forward(monkeypatch):
    """forward 已建立但 push 失败：失败出口必须真实回收 forward，且对象仍可安全 stop()。"""
    session, adb = make_session()

    def failing_push(serial: str, local: Path, remote: str) -> None:
        raise AdbError("push 超时")

    monkeypatch.setattr(adb, "push", failing_push)
    with pytest.raises(AdbError):
        session._open_transport()
    assert [call[0] for call in adb.calls] == ["forward", "forward_remove"]
    assert session._server is None
    assert session._video is None and session._control is None
    assert session.stream_alive is False
    session.stop()  # 失败后 stop() 必须幂等、不抛异常
    assert adb.calls[-1] == ("forward_remove", "SER123", 27183)


def test_open_transport_stop_between_push_and_shell_reaps_server(monkeypatch):
    """覆盖 stop() 在 forward/push/popen_shell 之间介入：server 已 spawn 但 _stop 已置位，
    _open_transport 走「已停止」失败出口；断言真实 terminate + forward_remove 已发生。"""
    session, adb = make_session()
    proc = _TrackingProc()

    def spawning_shell(serial: str, command: str) -> _TrackingProc:
        adb.calls.append(("popen_shell", serial, command))
        session._stop.set()
        return proc

    monkeypatch.setattr(adb, "popen_shell", spawning_shell)
    with pytest.raises(ScrcpyUnavailable):
        session._open_transport()
    assert proc.terminated == 1
    assert proc.waited == 1
    assert session._server is None
    assert adb.calls[-1] == ("forward_remove", "SER123", 27183)
    assert session.stream_alive is False
