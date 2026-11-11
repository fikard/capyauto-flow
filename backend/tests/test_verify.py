import asyncio
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
    serial, results = asyncio.run(verify.run_checks(None, "com.example", None, tmp_path, set()))
    assert serial == ""
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
