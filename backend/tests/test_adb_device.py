import asyncio
import inspect
import time
from pathlib import Path

import pytest

from app.device import adb_device
from app.device.adb import parse_devices
from app.device.adb_device import AdbScrcpyDevice
from app.device.base import Frame
from app.device.scrcpy_session import VideoMeta
from app.errors import AdbNotFound, MirrorLost, ScrcpyUnavailable

DEVICES_OUTPUT = """List of devices attached
R58M12ABCDE            device product:beyond1q model:SM_G9730 device:beyond1 transport_id:1
0123456789ABCDEF       unauthorized usb:1-2 transport_id:2
"""

PROPS = {
    "ro.product.model": "SM-G9730",
    "ro.product.cpu.abi": "arm64-v8a",
    "ro.build.version.sdk": "34",
}


class FakeAdb:
    def __init__(self) -> None:
        self.pushed: list[str] = []
        self.runs: list[tuple] = []

    def version(self) -> str:
        return "Android Debug Bridge version 1.0.41"

    def devices(self):
        return parse_devices(DEVICES_OUTPUT)

    def getprop(self, serial: str, prop: str) -> str:
        return PROPS[prop]

    def wm_size(self, serial: str):
        return "Physical size: 1080x2340", 1080, 2340

    def push(self, serial: str, local: Path, remote: str) -> None:
        self.pushed.append(remote)

    def run(self, *args, serial: str | None = None) -> str:
        self.runs.append(args)
        return ""


def make_fake_scrcpy(*, stream_alive=True, control_available=True, start_error=None):
    class FakeScrcpySession:
        instances: list = []

        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs
            self.stream_alive = stream_alive
            self.control_available = control_available
            self.meta: VideoMeta | None = None
            self.frame: Frame | None = None
            self.stop_calls = 0
            self.taps: list[tuple[int, int, int]] = []
            type(self).instances.append(self)

        def start(self) -> VideoMeta:
            if start_error is not None:
                raise start_error
            self.meta = VideoMeta(device_name="fake", codec="h264", width=1080, height=2340)
            return self.meta

        def latest(self) -> Frame | None:
            return self.frame

        def stop(self) -> None:
            self.stop_calls += 1
            self.stream_alive = False

        def tap(self, x: int, y: int, press_ms: int) -> None:
            self.taps.append((x, y, press_ms))

    return FakeScrcpySession


def make_fake_poller():
    class FakePoller:
        instances: list = []

        def __init__(self, adb, serial, width, height, fps, jpeg_quality, display_width) -> None:
            self.fps = fps
            self.frame: Frame | None = None
            self.started = False
            self.stop_calls = 0
            type(self).instances.append(self)

        def start(self) -> None:
            self.started = True

        def stop(self) -> None:
            self.stop_calls += 1

        def latest(self) -> Frame | None:
            return self.frame

    return FakePoller


def build_device(
    adb,
    server_jar: Path | None,
    *,
    allow_fallback: bool = True,
    frame_timeout: float = 10.0,
) -> AdbScrcpyDevice:
    return AdbScrcpyDevice(
        adb=adb,
        server_bin="scrcpy",
        server_jar=server_jar,
        server_version="3.1",
        tcp_port=27183,
        fps=5,
        bitrate=8_000_000,
        jpeg_quality=70,
        display_width=720,
        frame_timeout=frame_timeout,
        allow_fallback=allow_fallback,
    )


def test_list_devices_probes_props():
    device = build_device(FakeAdb(), Path("/nonexistent.jar"))
    infos = asyncio.run(device.list_devices())
    assert infos[0].serial == "R58M12ABCDE"
    assert infos[0].model == "SM-G9730"
    assert infos[0].abi == "arm64-v8a"
    assert (infos[0].width, infos[0].height) == (1080, 2340)
    assert infos[1].state == "unauthorized"
    assert infos[1].model is None


def test_health_reports_missing_jar():
    device = build_device(FakeAdb(), None)
    payload = asyncio.run(device.health())
    assert payload["adb_version"].startswith("Android Debug Bridge")
    assert payload["ok"] is False
    assert "scrcpy-server" in payload["hint"]


def test_health_ok_with_jar():
    device = build_device(FakeAdb(), Path("/tmp/scrcpy-server.jar"))
    payload = asyncio.run(device.health())
    assert payload["ok"] is True
    assert payload["scrcpy_version"] == "3.1"


def test_session_ids_are_monotonic_and_unique(monkeypatch):
    fake = make_fake_scrcpy()
    monkeypatch.setattr(adb_device, "ScrcpySession", fake)
    device = build_device(FakeAdb(), Path("/tmp/scrcpy-server.jar"))

    first = asyncio.run(device.create_session("R58M12ABCDE", 5))
    asyncio.run(device.close_session(first.id))
    second = asyncio.run(device.create_session("R58M12ABCDE", 5))
    assert second.id != first.id
    assert int(second.id[1:]) > int(first.id[1:])

    async def burst():
        return await asyncio.gather(
            *(device.create_session("R58M12ABCDE", 5) for _ in range(8))
        )

    ids = [session.id for session in asyncio.run(burst())]
    assert len(set(ids)) == len(ids) == 8
    assert second.id not in ids


def test_start_failure_without_fallback_raises_and_cleans_up(monkeypatch):
    fake = make_fake_scrcpy(start_error=ScrcpyUnavailable("启动失败"))
    monkeypatch.setattr(adb_device, "ScrcpySession", fake)
    device = build_device(FakeAdb(), Path("/tmp/scrcpy-server.jar"), allow_fallback=False)

    with pytest.raises(ScrcpyUnavailable):
        asyncio.run(device.create_session("R58M12ABCDE", 5))

    assert fake.instances[0].stop_calls == 1
    assert device._sessions == {}
    assert device._scrcpy == {}


def test_fallback_poller_limited_to_one_fps(monkeypatch):
    fake_scrcpy = make_fake_scrcpy(start_error=RuntimeError("adb 掉线"))
    fake_poller = make_fake_poller()
    monkeypatch.setattr(adb_device, "ScrcpySession", fake_scrcpy)
    monkeypatch.setattr(adb_device, "ScreencapPoller", fake_poller)
    device = build_device(FakeAdb(), Path("/tmp/scrcpy-server.jar"))

    session = asyncio.run(device.create_session("R58M12ABCDE", 5))

    assert session.degraded is True
    assert session.mode == "screencap"
    assert session.fps == 1
    poller = fake_poller.instances[0]
    assert poller.fps == 1
    assert poller.started is True


def test_frames_is_async_generator_function():
    assert inspect.isasyncgenfunction(AdbScrcpyDevice.frames)


def test_frames_raises_when_stream_dead(monkeypatch):
    fake = make_fake_scrcpy(stream_alive=True)
    monkeypatch.setattr(adb_device, "ScrcpySession", fake)
    device = build_device(FakeAdb(), Path("/tmp/scrcpy-server.jar"))
    session = asyncio.run(device.create_session("R58M12ABCDE", 5))
    fake.instances[0].stream_alive = False

    async def consume():
        async for _ in device.frames(session.id):
            pytest.fail("失联流不应产出帧")

    # frame_timeout 仍为 10s：必须在流死亡时立即发现，而不是等 deadline
    with pytest.raises(MirrorLost):
        asyncio.run(asyncio.wait_for(consume(), timeout=1.0))


def test_frames_waits_on_static_stream_then_ends_after_close(monkeypatch):
    fake = make_fake_scrcpy(stream_alive=True)
    monkeypatch.setattr(adb_device, "ScrcpySession", fake)
    device = build_device(FakeAdb(), Path("/tmp/scrcpy-server.jar"), frame_timeout=0.05)
    session = asyncio.run(device.create_session("R58M12ABCDE", 5))
    transport = fake.instances[0]

    async def scenario():
        stream = device.frames(session.id)
        pending = asyncio.ensure_future(stream.__anext__())
        await asyncio.sleep(0.15)  # 3 倍 frame_timeout，静态画面不得被判失联
        assert not pending.done()
        transport.frame = Frame(seq=1, jpeg=b"\xff\xd8\xff\xd9", width=720, height=1560, ts=time.time())
        frame = await asyncio.wait_for(pending, timeout=1.0)
        assert frame.seq == 1
        await device.close_session(session.id)
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(stream.__anext__(), timeout=1.0)

    asyncio.run(scenario())


def test_frames_screencap_still_times_out(monkeypatch):
    fake_poller = make_fake_poller()
    monkeypatch.setattr(adb_device, "ScreencapPoller", fake_poller)
    device = build_device(FakeAdb(), None, frame_timeout=0.05)
    session = asyncio.run(device.create_session("R58M12ABCDE", 5))
    assert fake_poller.instances[0].fps == 1

    async def consume():
        async for _ in device.frames(session.id):
            pytest.fail("无帧不应产出")

    with pytest.raises(MirrorLost):
        asyncio.run(consume())


def test_tap_falls_back_to_adb_input_when_control_unavailable(monkeypatch):
    fake = make_fake_scrcpy(control_available=False)
    monkeypatch.setattr(adb_device, "ScrcpySession", fake)
    adb = FakeAdb()
    device = build_device(adb, Path("/tmp/scrcpy-server.jar"))
    session = asyncio.run(device.create_session("R58M12ABCDE", 5))

    result = asyncio.run(device.tap(session.id, 0.5, 0.5, 60, 4))

    assert result.injected_via == "input"
    assert adb.runs and adb.runs[0][:3] == ("shell", "input", "swipe")
    assert fake.instances[0].taps == []


def test_sessions_allocate_distinct_tcp_ports(monkeypatch):
    """两个会话不能共用同一 local tcp 端口，否则第二个 forward 会覆盖第一个。"""
    monkeypatch.setattr(adb_device, "_is_port_free", lambda port: True)
    fake = make_fake_scrcpy()
    monkeypatch.setattr(adb_device, "ScrcpySession", fake)
    device = build_device(FakeAdb(), Path("/tmp/scrcpy-server.jar"))

    asyncio.run(device.create_session("R58M12ABCDE", 5))
    asyncio.run(device.create_session("R58M12ABCDE", 5))

    first_port = fake.instances[0].kwargs["tcp_port"]
    second_port = fake.instances[1].kwargs["tcp_port"]
    assert first_port == 27183
    assert second_port != first_port


def test_closed_session_releases_its_tcp_port(monkeypatch):
    monkeypatch.setattr(adb_device, "_is_port_free", lambda port: True)
    fake = make_fake_scrcpy()
    monkeypatch.setattr(adb_device, "ScrcpySession", fake)
    device = build_device(FakeAdb(), Path("/tmp/scrcpy-server.jar"))

    first = asyncio.run(device.create_session("R58M12ABCDE", 5))
    asyncio.run(device.create_session("R58M12ABCDE", 5))
    asyncio.run(device.close_session(first.id))
    asyncio.run(device.create_session("R58M12ABCDE", 5))

    first_port, second_port, third_port = (item.kwargs["tcp_port"] for item in fake.instances)
    assert first_port == 27183
    assert second_port != first_port
    assert third_port == first_port  # 关闭后端口已释放，可复用且不与在用会话冲突


def test_close_session_cleans_up_even_if_transport_stop_raises(monkeypatch, caplog):
    """adb 二进制消失时 transport.stop() 会抛 AdbNotFound，close 仍须幂等且清空会话表。"""
    fake = make_fake_scrcpy()
    monkeypatch.setattr(adb_device, "ScrcpySession", fake)
    device = build_device(FakeAdb(), Path("/tmp/scrcpy-server.jar"))
    session = asyncio.run(device.create_session("R58M12ABCDE", 5))

    def failing_stop() -> None:
        raise AdbNotFound("未找到 adb，请先执行 brew install scrcpy")

    monkeypatch.setattr(fake.instances[0], "stop", failing_stop)
    with caplog.at_level("WARNING", logger="capyauto.adb"):
        asyncio.run(device.close_session(session.id))

    assert device._sessions == {}
    assert device._scrcpy == {}
    assert device._pollers == {}
    assert device._session_ports == {}
    assert any(record.levelname == "WARNING" for record in caplog.records)


def test_frames_raises_when_transport_meta_size_changes(monkeypatch):
    """重连/旋转后视频尺寸变化：必须报错重建，不能继续用旧会话尺寸换算坐标。"""
    fake = make_fake_scrcpy()
    monkeypatch.setattr(adb_device, "ScrcpySession", fake)
    device = build_device(FakeAdb(), Path("/tmp/scrcpy-server.jar"))
    session = asyncio.run(device.create_session("R58M12ABCDE", 5))
    fake.instances[0].meta = VideoMeta(device_name="fake", codec="h264", width=2340, height=1080)

    async def consume():
        async for _ in device.frames(session.id):
            pytest.fail("尺寸变化后不应继续按旧尺寸推流")

    with pytest.raises(MirrorLost):
        asyncio.run(asyncio.wait_for(consume(), timeout=1.0))
