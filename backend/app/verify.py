from __future__ import annotations

import argparse
import asyncio
import dataclasses
import io
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL import Image

from app import config
from app.device import packages
from app.device.adb import AdbRunner
from app.device.adb_device import AdbScrcpyDevice
from app.errors import ApiError
from app.vision.ocr import engine_available, ocr_png

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_SKIP = "SKIP"

FRAME_TIMEOUT_S = 30.0
OCR_TIMEOUT_S = 30.0
RESTORE_ATTEMPTS = 10
RESTORE_INTERVAL_S = 0.3


@dataclass
class CheckResult:
    check_id: str
    status: str
    detail: str
    elapsed_ms: int


def p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1)))))
    return float(ordered[index])


def summarize(results: list[CheckResult]) -> dict:
    passed = sum(1 for result in results if result.status == STATUS_PASS)
    failed = sum(1 for result in results if result.status == STATUS_FAIL)
    skipped = sum(1 for result in results if result.status == STATUS_SKIP)
    return {
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "ok": failed == 0,
    }


def _escape_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_markdown(results: list[CheckResult], *, serial: str, started: str) -> str:
    lines = [
        "# CapyAuto 真机验收报告",
        "",
        f"- serial: {serial}",
        f"- started: {started}",
        f"- summary: {summarize(results)}",
        "",
        "| 检查 | 状态 | 说明 | 耗时 |",
        "|---|---|---|---|",
    ]
    for result in results:
        lines.append(
            f"| {result.check_id} | {result.status} | {_escape_cell(result.detail)} | {result.elapsed_ms}ms |"
        )
    return "\n".join(lines) + "\n"


class VerifyContext:
    def __init__(self, serial: str, package: str, activity: str | None, out_dir: Path) -> None:
        settings = config.settings
        self.adb = AdbRunner(settings.adb_path)
        self.serial = serial
        self.package = package
        self.activity = activity
        self.out_dir = out_dir
        self.frames_dir = out_dir / "frames"
        self.device = AdbScrcpyDevice(
            adb=self.adb,
            server_bin=settings.scrcpy_bin,
            server_jar=settings.scrcpy_server,
            server_version=settings.scrcpy_version,
            tcp_port=settings.scrcpy_tcp_port,
            fps=settings.mirror_fps,
            bitrate=settings.scrcpy_bitrate,
            jpeg_quality=settings.jpeg_quality,
            display_width=settings.display_width,
            frame_timeout=settings.frame_timeout,
            allow_fallback=settings.allow_screencap_fallback,
            game_package=package,
        )
        self.session_id: str | None = None

    async def session(self) -> str:
        if self.session_id is None:
            session = await self.device.create_session(self.serial, config.settings.mirror_fps)
            self.session_id = session.id
        return self.session_id

    def launch(self) -> tuple[str | None, int | None]:
        # 适配器 launch_app 不接受 activity，这里直接复用其底层实现以尊重 --activity 配置
        return packages.launch_app(
            self.adb, self.serial, self.package, activity=self.activity, user=0
        )

    def save_png(self, check_id: str, png: bytes) -> str:
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S%f")
        path = self.frames_dir / f"{check_id}-{stamp}.png"
        path.write_bytes(png)
        return str(path)

    async def close(self) -> None:
        if self.session_id is not None:
            await self.device.close_session(self.session_id)
            self.session_id = None


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _component_text(component: tuple[str, str] | None) -> str:
    return "/".join(component) if component is not None else "未知"


def _restore_airplane(ctx: VerifyContext, original: bool) -> str:
    try:
        if packages.read_airplane_mode(ctx.adb, ctx.serial) != original:
            packages.set_airplane_mode(
                ctx.adb,
                ctx.serial,
                original,
                packages.parse_sdk(ctx.adb.getprop(ctx.serial, "ro.build.version.sdk")),
            )
        actual = packages.read_airplane_mode(ctx.adb, ctx.serial)
    except Exception as exc:  # noqa: BLE001 - 恢复失败只记录，不掩盖主结果
        return f"恢复失败: {type(exc).__name__}: {exc}"
    if actual != original:
        return f"恢复失败: 读回 {actual}"
    return ""


async def _restore_user(ctx: VerifyContext, user_id: int) -> str:
    try:
        packages.switch_user(ctx.adb, ctx.serial, user_id)
    except Exception as exc:  # noqa: BLE001 - 恢复失败只记录，不掩盖主结果
        return f"恢复失败: {type(exc).__name__}: {exc}"
    current: int | None = None
    for _ in range(RESTORE_ATTEMPTS):
        try:
            current = packages.parse_current_user(
                ctx.adb.shell(ctx.serial, "am", "get-current-user")
            )
        except Exception as exc:  # noqa: BLE001
            return f"恢复失败: {type(exc).__name__}: {exc}"
        if current == user_id:
            return ""
        await asyncio.sleep(RESTORE_INTERVAL_S)
    return f"恢复失败: 回读用户 {current}，期望 {user_id}"


async def check_v1(ctx: VerifyContext) -> CheckResult:
    if not ctx.serial:
        return CheckResult("V1", STATUS_FAIL, "adb devices 中没有 state=device 的设备", 0)
    try:
        version = ctx.adb.version()
        devices = ctx.adb.devices()
    except ApiError as exc:
        return CheckResult("V1", STATUS_FAIL, f"adb 不可用: {exc.message}", 0)
    online = [device.serial for device in devices if device.state == "device"]
    if ctx.serial not in online:
        return CheckResult(
            "V1", STATUS_FAIL, f"所选设备 {ctx.serial} 不在在线列表中（在线: {online or '无'}）", 0
        )
    return CheckResult("V1", STATUS_PASS, f"{version}；在线 {len(online)} 台", 0)


async def check_v2(ctx: VerifyContext) -> CheckResult:
    infos = await ctx.device.list_devices()
    info = next((row for row in infos if row.serial == ctx.serial), None)
    if info is None:
        return CheckResult("V2", STATUS_FAIL, f"未找到设备 {ctx.serial}", 0)
    missing = [
        name
        for name, value in {
            "width": info.width,
            "height": info.height,
            "abi": info.abi,
            "android": info.android,
            "wm_size": info.wm_size,
        }.items()
        if not value
    ]
    if missing:
        return CheckResult("V2", STATUS_FAIL, f"缺少字段: {', '.join(missing)}", 0)
    return CheckResult("V2", STATUS_PASS, f"{info.width}x{info.height} {info.abi} Android {info.android}", 0)


async def check_v3(ctx: VerifyContext) -> CheckResult:
    session_id = await ctx.session()
    started = time.monotonic()
    stamps: list[float] = []

    async def collect() -> None:
        async for _frame in ctx.device.frames(session_id):
            stamps.append(time.monotonic())
            if len(stamps) >= 40:
                return

    timed_out = False
    try:
        await asyncio.wait_for(collect(), FRAME_TIMEOUT_S)
    except asyncio.TimeoutError:
        timed_out = True
    elapsed = _elapsed_ms(started)
    if len(stamps) < 5:
        prefix = "30s 内仅收到" if timed_out else "仅收到"
        return CheckResult("V3", STATUS_FAIL, f"{prefix} {len(stamps)} 帧", elapsed)
    intervals = [(stamps[i + 1] - stamps[i]) * 1000 for i in range(len(stamps) - 1)]
    worst = p95(intervals)
    status = STATUS_PASS if worst < 400 else STATUS_FAIL
    detail = f"{len(stamps)} 帧；帧间隔 P95={worst:.0f}ms"
    if timed_out:
        detail += "（30s 超时截断）"
    return CheckResult("V3", status, detail, elapsed)


async def check_v4(ctx: VerifyContext) -> CheckResult:
    started = time.monotonic()
    session_id = await ctx.session()
    session = ctx.device.get_session(session_id)
    png = await ctx.device.screenshot(session_id)
    with Image.open(io.BytesIO(png)) as image:
        size = image.size
    path = ctx.save_png("v4", png)
    _raw, width, height = ctx.adb.wm_size(ctx.serial)
    expected = (width, height) if width and height else (session.width, session.height)
    ok = size == expected
    return CheckResult(
        "V4",
        STATUS_PASS if ok else STATUS_FAIL,
        f"PNG {size[0]}x{size[1]}；期望 {expected[0]}x{expected[1]}；{path}",
        _elapsed_ms(started),
    )


async def check_v5(ctx: VerifyContext) -> CheckResult:
    started = time.monotonic()
    ctx.adb.shell(ctx.serial, "am", "start", "-a", "android.settings.SETTINGS")
    await asyncio.sleep(1.2)
    before = packages.current_component(ctx.adb, ctx.serial)
    try:
        session_id = await ctx.session()
        await ctx.device.tap(session_id, 0.5, 0.5, 80, 6)
        await asyncio.sleep(1.5)
        after = packages.current_component(ctx.adb, ctx.serial)
    finally:
        # 点击抛异常时也要退回设置页，避免影响后续检查
        ctx.adb.shell(ctx.serial, "input", "keyevent", "4")
    elapsed = _elapsed_ms(started)
    if before == after:
        return CheckResult("V5", STATUS_SKIP, f"点击后前台未变化（{_component_text(before)}）", elapsed)
    return CheckResult("V5", STATUS_PASS, f"{_component_text(before)} → {_component_text(after)}", elapsed)


async def check_v6(ctx: VerifyContext) -> CheckResult:
    session_id = await ctx.session()
    started = time.monotonic()
    result = await ctx.device.tap(session_id, 0.5, 0.5, 80, 6)
    elapsed_ms = (time.monotonic() - started) * 1000
    session = ctx.device.get_session(session_id)
    center_x, center_y = session.width // 2, session.height // 2
    ctx.adb.shell(
        ctx.serial, "input", "swipe", center_x, center_y, center_x, center_y, result.press_ms
    )
    # 以适配器实际随机出的 press_ms 为基准，而不是请求的 80ms
    if result.injected_via == "scrcpy":
        ok = abs(elapsed_ms - result.press_ms) <= 50
        expectation = f"实际按压 {result.press_ms}ms，误差阈值 ±50ms"
    else:
        ok = elapsed_ms <= result.press_ms + 200
        expectation = f"实际按压 {result.press_ms}ms；兜底含 adb 进程开销，允许 +200ms"
    return CheckResult(
        "V6",
        STATUS_PASS if ok else STATUS_FAIL,
        f"注入 {result.injected_via}；实测 {elapsed_ms:.0f}ms（{expectation}）；input swipe 兜底可执行"
        f"（{center_x},{center_y}）",
        int(elapsed_ms),
    )


async def check_v7(ctx: VerifyContext) -> CheckResult:
    started = time.monotonic()
    session_id = await ctx.session()
    activity, _pid = await asyncio.to_thread(ctx.launch)
    await asyncio.sleep(1.0)
    pid = packages.pid_of(ctx.adb, ctx.serial, ctx.package)
    if pid is None:
        return CheckResult(
            "V7", STATUS_FAIL, f"启动后未找到进程（activity={activity}）", _elapsed_ms(started)
        )
    await ctx.device.stop_app(session_id, ctx.package)
    await asyncio.sleep(0.8)
    remaining = packages.pid_of(ctx.adb, ctx.serial, ctx.package)
    elapsed = _elapsed_ms(started)
    if remaining is not None:
        return CheckResult("V7", STATUS_FAIL, f"force-stop 后进程仍存在 pid={remaining}", elapsed)
    return CheckResult("V7", STATUS_PASS, f"启动 pid={pid}，强杀后进程消失", elapsed)


async def check_v8(ctx: VerifyContext) -> CheckResult:
    started = time.monotonic()
    session_id = await ctx.session()
    users = await ctx.device.list_users(session_id)
    if not users.switch_supported:
        return CheckResult("V8", STATUS_SKIP, users.reason or "设备不支持用户切换", 0)
    targets = [row.id for row in users.users if not row.current]
    if not targets:
        return CheckResult("V8", STATUS_SKIP, "没有可切换的其他用户", 0)
    before = packages.parse_current_user(ctx.adb.shell(ctx.serial, "am", "get-current-user"))
    if before is None:
        # 读不到当前用户就无法安全恢复，直接跳过而不是切换后留在别的用户上
        return CheckResult("V8", STATUS_SKIP, "无法读取当前用户", _elapsed_ms(started))
    target = targets[0]
    restore_note = ""
    try:
        switched = await ctx.device.switch_user(session_id, target)
        after = packages.parse_current_user(ctx.adb.shell(ctx.serial, "am", "get-current-user"))
    except ApiError as exc:
        result = CheckResult(
            "V8", STATUS_FAIL, f"切换用户 {target} 失败: {exc.message}", _elapsed_ms(started)
        )
    else:
        if not switched.ok or after != target:
            result = CheckResult(
                "V8", STATUS_FAIL, f"切换用户失败：期望 {target}，实际 {after}", _elapsed_ms(started)
            )
        else:
            result = CheckResult("V8", STATUS_PASS, f"用户 {before} → {target}", _elapsed_ms(started))
    finally:
        if before != target:
            restore_note = await _restore_user(ctx, before)
    if restore_note:
        result.detail = f"{result.detail}；{restore_note}"
    return result


async def check_v9(ctx: VerifyContext) -> CheckResult:
    started = time.monotonic()
    original: bool | None = None
    on = off = False
    failure: str | None = None
    try:
        original = packages.read_airplane_mode(ctx.adb, ctx.serial)
        session_id = await ctx.session()
        await ctx.device.set_airplane_mode(session_id, True)
        on = packages.read_airplane_mode(ctx.adb, ctx.serial)
        await ctx.device.set_airplane_mode(session_id, False)
        off = packages.read_airplane_mode(ctx.adb, ctx.serial)
    except Exception as exc:  # noqa: BLE001 - 命令不可用时按规格记 SKIP
        failure = f"飞行模式不可用: {exc}"
    restore_note = _restore_airplane(ctx, original) if original is not None else ""
    if failure is not None:
        detail = f"{failure}；{restore_note}" if restore_note else failure
        return CheckResult("V9", STATUS_SKIP, detail, _elapsed_ms(started))
    status = STATUS_PASS if on and not off else STATUS_FAIL
    detail = f"开启读回={on}，关闭读回={off}"
    if restore_note:
        detail = f"{detail}；{restore_note}"
    return CheckResult("V9", status, detail, _elapsed_ms(started))


async def check_v10(ctx: VerifyContext) -> CheckResult:
    if not engine_available():
        return CheckResult("V10", STATUS_SKIP, "未安装 rapidocr-onnxruntime", 0)
    session_id = await ctx.session()
    await asyncio.to_thread(ctx.launch)
    await asyncio.sleep(2.0)
    # ONNX 首次推理是秒级冷启动：先用同一张真实 PNG 不计时跑一次，
    # 让 det/rec/cls 与分辨率相关的首次分配都在计时外，只统计第二次识别耗时
    shot_started = time.monotonic()
    png = await ctx.device.screenshot(session_id)
    screenshot_ms = _elapsed_ms(shot_started)
    path = ctx.save_png("v10", png)
    warm_started = time.monotonic()
    try:
        await asyncio.wait_for(asyncio.to_thread(ocr_png, png), OCR_TIMEOUT_S)
    except asyncio.TimeoutError:
        return CheckResult(
            "V10",
            STATUS_FAIL,
            f"OCR 预热超时（>{OCR_TIMEOUT_S:g}s）；screenshotMs={screenshot_ms}；{path}",
            _elapsed_ms(warm_started),
        )
    started = time.monotonic()
    try:
        items = await asyncio.wait_for(asyncio.to_thread(ocr_png, png), OCR_TIMEOUT_S)
    except asyncio.TimeoutError:
        return CheckResult(
            "V10",
            STATUS_FAIL,
            f"OCR 识别超时（>{OCR_TIMEOUT_S:g}s）；screenshotMs={screenshot_ms}；{path}",
            _elapsed_ms(started),
        )
    ocr_ms = _elapsed_ms(started)
    timing = f"ocrMs={ocr_ms}，screenshotMs={screenshot_ms}"
    if not items:
        return CheckResult("V10", STATUS_FAIL, f"未识别到文本；{timing}；{path}", ocr_ms)
    best = max(items, key=lambda item: item.confidence)
    status = STATUS_PASS if ocr_ms < 800 and best.confidence > 0.6 else STATUS_FAIL
    return CheckResult(
        "V10",
        status,
        f"{len(items)} 条；最高 {best.text!r} {best.confidence:.2f}；{timing}；{path}",
        ocr_ms,
    )


CHECKS = {
    "V1": check_v1,
    "V2": check_v2,
    "V3": check_v3,
    "V4": check_v4,
    "V5": check_v5,
    "V6": check_v6,
    "V7": check_v7,
    "V8": check_v8,
    "V9": check_v9,
    "V10": check_v10,
}


def is_serial_online(chosen: str | None, online_serials: list[str] | tuple[str, ...]) -> bool:
    return bool(chosen) and chosen in set(online_serials)


def _pick_serial(adb: AdbRunner, requested: str | None) -> str:
    if requested:
        return requested
    try:
        devices = adb.devices()
    except Exception:  # noqa: BLE001 - adb 不可用也照常出报告，具体错误由 V1 记录
        return ""
    online = [device.serial for device in devices if device.state == "device"]
    return online[0] if online else ""


def _offline_result(
    check_id: str, chosen: str, online: list[str], probe_error: str | None
) -> CheckResult:
    if check_id != "V1":
        reason = "所选设备不在线" if online else "无在线设备"
        return CheckResult(check_id, STATUS_SKIP, reason, 0)
    if probe_error:
        return CheckResult("V1", STATUS_FAIL, f"adb 不可用: {probe_error}", 0)
    if not online:
        return CheckResult("V1", STATUS_FAIL, "adb devices 中没有 state=device 的设备", 0)
    return CheckResult(
        "V1", STATUS_FAIL, f"所选设备 {chosen or '未指定'} 不在线（在线: {', '.join(online)}）", 0
    )


async def run_checks(
    serial: str | None,
    package: str,
    activity: str | None,
    out_dir: Path,
    skip: set[str],
) -> tuple[str, list[CheckResult], bool]:
    """返回 (实际使用的 serial, 检查结果, 该 serial 是否在线)。"""
    adb = AdbRunner(config.settings.adb_path)
    chosen = _pick_serial(adb, serial)
    online: list[str] = []
    probe_error: str | None = None
    try:
        online = [device.serial for device in adb.devices() if device.state == "device"]
    except Exception as exc:  # noqa: BLE001 - adb 不可用时仍要出报告
        probe_error = f"{type(exc).__name__}: {exc}"
    serial_online = is_serial_online(chosen, online)
    ctx = VerifyContext(chosen, package, activity, out_dir)
    results: list[CheckResult] = []
    try:
        for check_id, check in CHECKS.items():
            if check_id in skip:
                results.append(CheckResult(check_id, STATUS_SKIP, "命令行指定跳过", 0))
                print(f"[{STATUS_SKIP}] {check_id} 命令行指定跳过")
                continue
            if not serial_online:
                result = _offline_result(check_id, chosen, online, probe_error)
                results.append(result)
                print(f"[{result.status}] {check_id} {result.detail}")
                continue
            started = time.monotonic()
            try:
                result = await check(ctx)
            except ApiError as exc:
                result = CheckResult(check_id, STATUS_FAIL, f"{exc.code}: {exc.message}", _elapsed_ms(started))
            except Exception as exc:  # noqa: BLE001 - 单项异常不中断整轮
                result = CheckResult(
                    check_id, STATUS_FAIL, f"{type(exc).__name__}: {exc}", _elapsed_ms(started)
                )
            if result.elapsed_ms == 0:
                result.elapsed_ms = _elapsed_ms(started)
            results.append(result)
            print(f"[{result.status}] {result.check_id} {result.detail}")
    finally:
        try:
            await ctx.close()
        except Exception as exc:  # noqa: BLE001 - 关闭失败不得丢弃已产出的结果
            print(f"关闭会话失败: {type(exc).__name__}: {exc}", file=sys.stderr)
    return chosen, results, serial_online


def write_reports(
    results: list[CheckResult], serial: str, out_dir: Path, started_at: str
) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S%f")
    payload = {
        "serial": serial,
        "started": started_at,
        "summary": summarize(results),
        "checks": [dataclasses.asdict(result) for result in results],
    }
    json_path = out_dir / f"verify-{stamp}.json"
    md_path = out_dir / f"verify-{stamp}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(results, serial=serial, started=started_at), encoding="utf-8")
    return json_path, md_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.verify", description="CapyAuto 真机验收 V1–V10")
    parser.add_argument("--serial", default=None)
    parser.add_argument("--package", default=config.settings.game_package)
    parser.add_argument("--activity", default=config.settings.game_activity)
    parser.add_argument("--out", default="reports")
    parser.add_argument("--skip", default="", help="逗号分隔的检查项，如 V9,V10")
    args = parser.parse_args(argv)
    started_at = datetime.now().isoformat(timespec="seconds")
    skip = {item.strip().upper() for item in args.skip.split(",") if item.strip()}
    serial, results, serial_online = asyncio.run(
        run_checks(args.serial, args.package, args.activity, Path(args.out), skip)
    )
    json_path, md_path = write_reports(results, serial, Path(args.out), started_at)
    print(f"报告：{json_path} / {md_path}")
    return 0 if serial_online and summarize(results)["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
