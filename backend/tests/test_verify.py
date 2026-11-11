from app.verify import CheckResult, p95, render_markdown, summarize


def test_p95_uses_nearest_rank():
    assert p95([100, 200, 300, 400, 500]) == 500
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


def test_render_markdown_contains_status_and_reason():
    markdown = render_markdown(
        [CheckResult("V8", "SKIP", "设备仅有一个用户", 12)],
        serial="S",
        started="2026-11-11T10:00:00",
    )
    assert "| V8 | SKIP | 设备仅有一个用户 | 12ms |" in markdown
    assert "serial: S" in markdown
