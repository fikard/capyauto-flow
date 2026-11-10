import asyncio
from pathlib import Path

from app.device.adb import parse_devices
from app.device.adb_device import AdbScrcpyDevice

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


def build_device(adb, server_jar: Path | None) -> AdbScrcpyDevice:
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
        frame_timeout=10.0,
        allow_fallback=True,
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
