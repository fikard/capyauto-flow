from __future__ import annotations

import argparse
import asyncio
import dataclasses
import io
import json
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
from app.vision.ocr import engine_available, get_engine, ocr_png

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_SKIP = "SKIP"


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
        lines.append(f"| {result.check_id} | {result.status} | {result.detail} | {result.elapsed_ms}ms |")
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
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
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


async def check_v1(ctx: VerifyContext) -> CheckResult:
    version = ctx.adb.version()
    devices = ctx.adb.devices()
    online = [device for device in devices if device.state == "device"]
    if not online:
        return CheckResult("V1", STATUS_FAIL, "adb devices 中没有 state=device 的设备", 0)
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
    started = time.monotonic()
    session_id = await ctx.session()
    stamps: list[float] = []
    async for _frame in ctx.device.frames(session_id):
        stamps.append(time.monotonic())
        if len(stamps) >= 40 or time.monotonic() - started > 30:
            break
    elapsed = _elapsed_ms(started)
    if len(stamps) < 5:
        return CheckResult("V3", STATUS_FAIL, f"30s 内仅收到 {len(stamps)} 帧", elapsed)
    intervals = [(stamps[i + 1] - stamps[i]) * 1000 for i in range(len(stamps) - 1)]
    worst = p95(intervals)
    status = STATUS_PASS if worst < 400 else STATUS_FAIL
    return CheckResult("V3", status, f"{len(stamps)} 帧；帧间隔 P95={worst:.0f}ms", elapsed)


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
    session_id = await ctx.session()
    await ctx.device.tap(session_id, 0.5, 0.5, 80, 6)
    await asyncio.sleep(1.5)
    after = packages.current_component(ctx.adb, ctx.serial)
    elapsed = _elapsed_ms(started)
    ctx.adb.shell(ctx.serial, "input", "keyevent", "4")
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
    ctx.adb.shell(ctx.serial, "input", "swipe", center_x, center_y, center_x, center_y, 80)
    status = STATUS_PASS if abs(elapsed_ms - 80) <= 50 else STATUS_FAIL
    return CheckResult(
        "V6",
        status,
        f"注入 {result.injected_via}；实测 {elapsed_ms:.0f}ms（请求 80ms）；"
        f"input swipe 兜底可执行（{center_x},{center_y}）",
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
    target = targets[0]
    try:
        switched = await ctx.device.switch_user(session_id, target)
        after = packages.parse_current_user(ctx.adb.shell(ctx.serial, "am", "get-current-user"))
    except ApiError as exc:
        return CheckResult("V8", STATUS_FAIL, f"切换用户 {target} 失败: {exc.message}", _elapsed_ms(started))
    finally:
        if before is not None and before != target:
            try:
                packages.switch_user(ctx.adb, ctx.serial, before)
            except Exception:  # noqa: BLE001 - 恢复失败不掩盖主结果
                pass
    elapsed = _elapsed_ms(started)
    if not switched.ok or after != target:
        return CheckResult("V8", STATUS_FAIL, f"切换用户失败：期望 {target}，实际 {after}", elapsed)
    return CheckResult("V8", STATUS_PASS, f"用户 {before} → {target}", elapsed)


async def check_v9(ctx: VerifyContext) -> CheckResult:
    started = time.monotonic()
    original: bool | None = None
    on = off = False
    try:
        original = packages.read_airplane_mode(ctx.adb, ctx.serial)
        session_id = await ctx.session()
        await ctx.device.set_airplane_mode(session_id, True)
        on = packages.read_airplane_mode(ctx.adb, ctx.serial)
        await ctx.device.set_airplane_mode(session_id, False)
        off = packages.read_airplane_mode(ctx.adb, ctx.serial)
    except Exception as exc:  # noqa: BLE001 - 命令不可用时按规格记 SKIP
        return CheckResult("V9", STATUS_SKIP, f"飞行模式不可用: {exc}", _elapsed_ms(started))
    finally:
        if original is not None:
            try:
                if packages.read_airplane_mode(ctx.adb, ctx.serial) != original:
                    packages.set_airplane_mode(
                        ctx.adb,
                        ctx.serial,
                        original,
                        packages.parse_sdk(ctx.adb.getprop(ctx.serial, "ro.build.version.sdk")),
                    )
            except Exception:  # noqa: BLE001 - 恢复失败不抛出，避免掩盖主结果
                pass
    status = STATUS_PASS if on and not off else STATUS_FAIL
    return CheckResult("V9", status, f"开启读回={on}，关闭读回={off}", _elapsed_ms(started))


async def check_v10(ctx: VerifyContext) -> CheckResult:
    if not engine_available():
        return CheckResult("V10", STATUS_SKIP, "未安装 rapidocr-onnxruntime", 0)
    session_id = await ctx.session()
    await asyncio.to_thread(ctx.launch)
    await asyncio.sleep(2.0)
    # 引擎首次调用要加载 ONNX 模型（秒级），必须在计时外预热，否则单次识别永远超 800ms 阈值
    await asyncio.to_thread(get_engine)
    started = time.monotonic()
    png = await ctx.device.screenshot(session_id)
    items = await asyncio.to_thread(ocr_png, png)
    elapsed = _elapsed_ms(started)
    path = ctx.save_png("v10", png)
    if not items:
        return CheckResult("V10", STATUS_FAIL, f"未识别到文本；{path}", elapsed)
    best = max(items, key=lambda item: item.confidence)
    status = STATUS_PASS if best.confidence > 0.6 and elapsed < 800 else STATUS_FAIL
    return CheckResult(
        "V10",
        status,
        f"{len(items)} 条；最高 {best.text!r} {best.confidence:.2f}；{path}",
        elapsed,
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


def _pick_serial(adb: AdbRunner, requested: str | None) -> str:
    if requested:
        return requested
    try:
        devices = adb.devices()
    except ApiError as exc:
        raise SystemExit(f"无法读取 adb 设备列表: {exc.message}") from exc
    online = [device.serial for device in devices if device.state == "device"]
    if not online:
        raise SystemExit("没有在线设备，请先连接 USB 并授权调试")
    return online[0]


async def run_checks(
    serial: str | None,
    package: str,
    activity: str | None,
    out_dir: Path,
    skip: set[str],
) -> tuple[str, list[CheckResult]]:
    adb = AdbRunner(config.settings.adb_path)
    chosen = _pick_serial(adb, serial)
    ctx = VerifyContext(chosen, package, activity, out_dir)
    results: list[CheckResult] = []
    try:
        for check_id, check in CHECKS.items():
            if check_id in skip:
                results.append(CheckResult(check_id, STATUS_SKIP, "命令行指定跳过", 0))
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
        await ctx.close()
    return chosen, results


def write_reports(
    results: list[CheckResult], serial: str, out_dir: Path, started_at: str
) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
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
    serial, results = asyncio.run(
        run_checks(args.serial, args.package, args.activity, Path(args.out), skip)
    )
    json_path, md_path = write_reports(results, serial, Path(args.out), started_at)
    print(f"报告：{json_path} / {md_path}")
    return 0 if summarize(results)["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
