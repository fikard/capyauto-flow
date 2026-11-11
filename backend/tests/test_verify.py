import asyncio
import time
from types import SimpleNamespace

from app import verify
from app.errors import AdbNotFound
from app.verify import CheckResult, p95, render_markdown, summarize


def test_p95_uses_nearest_rank_on_unordered_input():
    assert p95([300, 100, 500, 200, 400]) == 500
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


def test_summarize_only_skip_is_ok():
    summary = summarize(
        [
            CheckResult("V2", "SKIP", "无在线设备", 0),
            CheckResult("V3", "SKIP", "无在线设备", 0),
        ]
    )
    assert summary == {"passed": 0, "failed": 0, "skipped": 2, "ok": True}


def test_render_markdown_contains_status_and_reason():
    markdown = render_markdown(
        [CheckResult("V8", "SKIP", "设备仅有一个用户", 12)],
        serial="S",
        started="2026-11-11T10:00:00",
    )
    assert "| V8 | SKIP | 设备仅有一个用户 | 12ms |" in markdown
    assert "serial: S" in markdown


def test_render_markdown_escapes_pipe_in_detail():
    markdown = render_markdown(
        [CheckResult("V6", "PASS", "a|b", 1)],
        serial="S",
        started="2026-11-11T10:00:00",
    )
    assert "| V6 | PASS | a\\|b | 1ms |" in markdown


class _NoDeviceAdb:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def devices(self):
        return []


def test_run_checks_without_device_still_returns_results(tmp_path, monkeypatch):
    monkeypatch.setattr(verify, "AdbRunner", _NoDeviceAdb)
    serial, results, serial_online = asyncio.run(
        verify.run_checks(None, "com.example", None, tmp_path, set())
    )
    assert serial == ""
    assert serial_online is False
    statuses = {result.check_id: result.status for result in results}
    assert statuses["V1"] == "FAIL"
    assert [statuses[f"V{i}"] for i in range(2, 11)] == ["SKIP"] * 9
    assert summarize(results)["ok"] is False


def test_v1_fails_when_selected_serial_is_not_online():
    ctx = SimpleNamespace(
        serial="S",
        adb=SimpleNamespace(version=lambda: "adb 1.0", devices=lambda: []),
    )
    result = asyncio.run(verify.check_v1(ctx))
    assert result.status == "FAIL"
    assert "S" in result.detail


def test_v1_fails_with_adb_error_message():
    def boom():
        raise AdbNotFound("未找到 adb")

    ctx = SimpleNamespace(serial="S", adb=SimpleNamespace(version=boom, devices=lambda: []))
    result = asyncio.run(verify.check_v1(ctx))
    assert result.status == "FAIL"
    assert "未找到 adb" in result.detail


def test_is_serial_online_handles_empty_offline_and_online():
    assert verify.is_serial_online("", ["S"]) is False
    assert verify.is_serial_online(None, ["S"]) is False
    assert verify.is_serial_online("MISSING", ["S"]) is False
    assert verify.is_serial_online("S", ["S", "T"]) is True


class _OtherDeviceAdb(_NoDeviceAdb):
    def devices(self):
        return [SimpleNamespace(serial="OTHER", state="device")]

    def version(self):
        return "adb 1.0"


def test_run_checks_with_offline_serial_skips_rest(tmp_path, monkeypatch):
    monkeypatch.setattr(verify, "AdbRunner", _OtherDeviceAdb)
    serial, results, serial_online = asyncio.run(
        verify.run_checks("MISSING", "com.example", None, tmp_path, set())
    )
    assert serial == "MISSING"
    assert serial_online is False
    statuses = {result.check_id: result.status for result in results}
    assert statuses["V1"] == "FAIL"
    assert "MISSING" in results[0].detail
    assert "OTHER" in results[0].detail
    assert [statuses[f"V{i}"] for i in range(2, 11)] == ["SKIP"] * 9
    assert all(result.detail == "所选设备不在线" for result in results[1:])


def test_restore_airplane_reports_readback_mismatch(monkeypatch):
    ctx = SimpleNamespace(
        serial="S", adb=SimpleNamespace(getprop=lambda *args: "30")
    )
    monkeypatch.setattr(verify.packages, "read_airplane_mode", lambda adb, serial: True)
    monkeypatch.setattr(verify.packages, "set_airplane_mode", lambda *args, **kwargs: "")
    assert verify._restore_airplane(ctx, False) == "恢复失败: 读回 True"


def test_main_returns_1_without_device_even_when_v1_skipped(tmp_path, monkeypatch):
    async def fake_run_checks(serial, package, activity, out_dir, skip):
        results = [CheckResult(f"V{i}", "SKIP", "无在线设备", 0) for i in range(1, 11)]
        return "", results, False

    monkeypatch.setattr(verify, "run_checks", fake_run_checks)
    assert verify.main(["--skip", "V1", "--out", str(tmp_path)]) == 1


def test_main_returns_1_with_offline_serial_even_when_v1_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(verify, "AdbRunner", _OtherDeviceAdb)
    assert verify.main(["--serial", "MISSING", "--skip", "V1", "--out", str(tmp_path)]) == 1


def test_main_returns_0_when_online_and_all_pass(tmp_path, monkeypatch):
    async def fake_run_checks(serial, package, activity, out_dir, skip):
        results = [CheckResult(f"V{i}", "PASS", "ok", 0) for i in range(1, 11)]
        return "OTHER", results, True

    monkeypatch.setattr(verify, "run_checks", fake_run_checks)
    assert verify.main(["--serial", "OTHER", "--out", str(tmp_path)]) == 0


async def _resolved(value):
    return value


def test_v3_hard_timeout_fails_when_frames_insufficient(monkeypatch):
    async def frames(session_id):
        yield object()
        yield object()
        await asyncio.sleep(60)

    ctx = SimpleNamespace(
        serial="S",
        session=lambda: _resolved("sid"),
        device=SimpleNamespace(frames=frames),
    )
    monkeypatch.setattr(verify, "FRAME_TIMEOUT_S", 0.1)
    result = asyncio.run(verify.check_v3(ctx))
    assert result.status == "FAIL"
    assert "仅收到 2 帧" in result.detail


async def _no_sleep(seconds):
    return None


def _v10_ctx(png: bytes, tmp_path):
    return SimpleNamespace(
        package="com.example",
        session=lambda: _resolved("sid"),
        device=SimpleNamespace(screenshot=lambda session_id: _resolved(png)),
        launch=lambda: ("com.example/.Main", 1),
        save_png=lambda check_id, data: str(tmp_path / f"{check_id}.png"),
    )


def test_v10_warmup_ocr_not_counted_in_timing(monkeypatch, tmp_path):
    png = b"\x89PNG v10"
    calls = []

    def fake_ocr(payload):
        calls.append(payload)
        if len(calls) == 1:
            time.sleep(0.3)
            return []
        return [SimpleNamespace(text="开始游戏", confidence=0.92)]

    monkeypatch.setattr(verify, "engine_available", lambda: True)
    monkeypatch.setattr(verify, "ocr_png", fake_ocr)
    monkeypatch.setattr(verify.asyncio, "sleep", _no_sleep)

    result = asyncio.run(verify.check_v10(_v10_ctx(png, tmp_path)))

    assert len(calls) == 2
    assert calls[0] == png
    assert calls[1] == png
    assert result.status == "PASS"
    # 预热那一次睡了 0.3s，若被计入 elapsed_ms 就不可能小于 150
    assert result.elapsed_ms < 150
    assert "ocrMs=" in result.detail


def test_v10_warmup_ocr_timeout_fails_without_timing(monkeypatch, tmp_path):
    calls = []

    def fake_ocr(payload):
        calls.append(payload)
        time.sleep(0.3)
        return []

    monkeypatch.setattr(verify, "engine_available", lambda: True)
    monkeypatch.setattr(verify, "ocr_png", fake_ocr)
    monkeypatch.setattr(verify, "OCR_TIMEOUT_S", 0.05)
    monkeypatch.setattr(verify.asyncio, "sleep", _no_sleep)

    result = asyncio.run(verify.check_v10(_v10_ctx(b"\x89PNG v10", tmp_path)))

    assert len(calls) == 1
    assert result.status == "FAIL"
    assert "预热超时" in result.detail


def test_v10_timed_ocr_timeout_fails(monkeypatch, tmp_path):
    calls = []

    def fake_ocr(payload):
        calls.append(payload)
        if len(calls) == 1:
            return []
        time.sleep(0.3)
        return []

    monkeypatch.setattr(verify, "engine_available", lambda: True)
    monkeypatch.setattr(verify, "ocr_png", fake_ocr)
    monkeypatch.setattr(verify, "OCR_TIMEOUT_S", 0.05)
    monkeypatch.setattr(verify.asyncio, "sleep", _no_sleep)

    result = asyncio.run(verify.check_v10(_v10_ctx(b"\x89PNG v10", tmp_path)))

    assert len(calls) == 2
    assert result.status == "FAIL"
    assert "识别超时" in result.detail
