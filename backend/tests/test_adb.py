import subprocess

import pytest

from app.device.adb import AdbRunner, parse_devices, parse_wm_size
from app.errors import AdbError, AdbNotFound, AdbTimeout

DEVICES_OUTPUT = """List of devices attached
R58M12ABCDE            device product:beyond1q model:SM_G9730 device:beyond1 transport_id:1
0123456789ABCDEF       unauthorized usb:1-2 transport_id:2
"""


def fake_exec(returncode=0, stdout=b"", stderr=b"", raise_exc=None):
    calls = []

    def _exec(argv, timeout):
        calls.append((argv, timeout))
        if raise_exc is not None:
            raise raise_exc
        return returncode, stdout, stderr

    _exec.calls = calls
    return _exec


def test_parse_devices():
    devices = parse_devices(DEVICES_OUTPUT)
    assert [d.serial for d in devices] == ["R58M12ABCDE", "0123456789ABCDEF"]
    assert devices[0].state == "device"
    assert devices[0].model == "SM_G9730"
    assert devices[0].transport_id == "1"
    assert devices[1].state == "unauthorized"


def test_parse_wm_size_prefers_override():
    raw, width, height = parse_wm_size("Physical size: 1080x2400\nOverride size: 1080x2340\n")
    assert (width, height) == (1080, 2340)
    assert "Override" in raw


def test_parse_wm_size_missing():
    _, width, height = parse_wm_size("no size here")
    assert (width, height) == (None, None)


def test_run_injects_serial_and_decodes():
    exec_fn = fake_exec(stdout=b"arm64-v8a\n")
    runner = AdbRunner(exec_fn=exec_fn)
    assert runner.getprop("R58M12ABCDE", "ro.product.cpu.abi") == "arm64-v8a"
    argv, _ = exec_fn.calls[0]
    assert argv[:3] == ["adb", "-s", "R58M12ABCDE"]
    assert argv[3:] == ["shell", "getprop", "ro.product.cpu.abi"]


def test_nonzero_exit_raises_adb_error():
    runner = AdbRunner(exec_fn=fake_exec(returncode=1, stderr=b"device offline"))
    with pytest.raises(AdbError) as exc:
        runner.devices()
    assert exc.value.code == "ADB_FAILED"


def test_timeout_raises_adb_timeout():
    runner = AdbRunner(exec_fn=fake_exec(raise_exc=subprocess.TimeoutExpired("adb", 10)))
    with pytest.raises(AdbTimeout) as exc:
        runner.devices()
    assert exc.value.code == "ADB_TIMEOUT"


def test_missing_binary_raises_adb_not_found():
    runner = AdbRunner(exec_fn=fake_exec(raise_exc=FileNotFoundError("adb")))
    with pytest.raises(AdbNotFound) as exc:
        runner.devices()
    assert exc.value.status_code == 503
