#!/usr/bin/env python3
"""scrcpy 协议探测（P0 技术闸门）。

用法：
    python scripts/scrcpy_probe.py --seconds 10 --tap 0.5 0.5 --press-ms 80

成功时退出码 0，并打印 JSON 指标；失败退出码 1。
"""
from __future__ import annotations

import argparse
import json
import re
import socket
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

META_LEN = 76
PACKET_HEADER_LEN = 12
CODEC_IDS = {0x68323634: "h264", 0x68323635: "h265", 0x00617631: "av1"}
MSG_INJECT_TOUCH = 2
ACTION_DOWN, ACTION_UP = 0, 1
SCID = "1234abcd"  # scrcpy 3.x: 抽象 socket 名为 scrcpy_<scid>
CONFIG_FLAG = 1 << 63  # 12 字节包头的 pts 高位标记（原 flags 字节不存在）


def sh(argv: list[str], timeout: float = 20.0, binary: bool = False):
    proc = subprocess.run(argv, capture_output=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(
            f"命令失败({proc.returncode}): {' '.join(argv)}\n{proc.stderr.decode('utf-8', 'replace')}"
        )
    return proc.stdout if binary else proc.stdout.decode("utf-8", "replace").strip()


def pick_serial(explicit: str | None) -> str:
    if explicit:
        return explicit
    out = sh(["adb", "devices"])
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            return parts[0]
    raise SystemExit("没有 state=device 的设备，请检查 USB 调试授权")


def scrcpy_version() -> str:
    out = sh(["scrcpy", "--version"])
    match = re.search(r"scrcpy\s+(\d+\.\d+(?:\.\d+)?)", out)
    if not match:
        raise SystemExit(f"无法解析 scrcpy 版本: {out!r}")
    return match.group(1)


def server_jar() -> Path:
    prefix = sh(["brew", "--prefix"])
    candidates = [Path(prefix) / "share/scrcpy/scrcpy-server"]
    cellar = Path(prefix) / "Cellar/scrcpy"
    if cellar.is_dir():
        candidates += sorted(cellar.glob("*/share/scrcpy/scrcpy-server"), reverse=True)
    for path in candidates:
        if path.is_file():
            return path
    raise SystemExit("未找到 scrcpy-server jar，请先 brew install scrcpy")


def recv_exact(sock: socket.socket, size: int) -> bytes:
    buf = b""
    while len(buf) < size:
        chunk = sock.recv(size - len(buf))
        if not chunk:
            raise ConnectionError(f"socket 关闭，缺 {size - len(buf)} 字节")
        buf += chunk
    return buf


def connect(port: int, deadline: float = 8.0) -> socket.socket:
    end = time.time() + deadline
    last: Exception | None = None
    while time.time() < end:
        try:
            sock = socket.create_connection(("127.0.0.1", port), timeout=2.0)
            sock.settimeout(5.0)
            return sock
        except OSError as exc:
            last = exc
            time.sleep(0.1)
    raise RuntimeError(f"连接本地端口 {port} 失败: {last}")


def open_session(port: int, deadline: float = 10.0) -> tuple[socket.socket, socket.socket, bytes]:
    """连接 video/control 并读取元数据。

    server 启动前 adb forward 就已监听本地端口，此时连接会被立即关闭，故需重试。
    """
    end = time.time() + deadline
    last: Exception | None = None
    while time.time() < end:
        video = control = None
        try:
            video = connect(port)
            # scrcpy 3.x server 在 video 与 control 两个 socket 都被 accept 后才发送元数据
            control = connect(port)
            return video, control, recv_exact(video, META_LEN)
        except (OSError, ConnectionError) as exc:
            last = exc
            for sock in (control, video):
                if sock is not None:
                    sock.close()
            time.sleep(0.2)
    raise RuntimeError(f"未能建立 scrcpy 会话: {last}")


def touch_message(action: int, x: int, y: int, width: int, height: int) -> bytes:
    pressure = 0xFFFF if action == ACTION_DOWN else 0
    return struct.pack(">BBQiiHHHII", MSG_INJECT_TOUCH, action, 0, x, y, width, height, pressure, 0, 0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", default=None)
    parser.add_argument("--seconds", type=float, default=10.0)
    parser.add_argument("--tap", nargs=2, type=float, default=[0.5, 0.5])
    parser.add_argument("--press-ms", type=int, default=80)
    parser.add_argument("--port", type=int, default=27183)
    args = parser.parse_args()

    import av  # 延迟导入，便于快速报错

    serial = pick_serial(args.serial)
    version = scrcpy_version()
    jar = server_jar()
    remote = "/data/local/tmp/scrcpy-server.jar"

    sh(["adb", "-s", serial, "push", str(jar), remote])
    try:
        sh(["adb", "-s", serial, "forward", "--remove", f"tcp:{args.port}"])
    except Exception:
        pass
    sh(
        [
            "adb",
            "-s",
            serial,
            "forward",
            f"tcp:{args.port}",
            f"localabstract:scrcpy_{SCID}",
        ]
    )

    server_cmd = (
        f"CLASSPATH={remote} app_process / com.genymobile.scrcpy.Server {version} "
        f"scid={SCID} log_level=info tunnel_forward=true audio=false video=true control=true "
        f"send_dummy_byte=false max_fps=10 video_bit_rate=8000000 max_size=0 cleanup=true"
    )
    server_log = tempfile.NamedTemporaryFile(prefix="scrcpy-server-", suffix=".log", delete=False)
    server_log_path = Path(server_log.name)
    server = subprocess.Popen(
        ["adb", "-s", serial, "shell", server_cmd],
        stdout=subprocess.DEVNULL,
        stderr=server_log,
    )
    server_log.close()

    def server_log_tail(lines: int = 20) -> str:
        try:
            text = server_log_path.read_text("utf-8", "replace")
        except OSError:
            return ""
        return "\n".join(text.splitlines()[-lines:])

    result: dict[str, object] = {"serial": serial, "scrcpy": version, "server_jar": str(jar)}
    video = None
    control = None
    try:
        video, control, meta = open_session(args.port)
        name = meta[:64].split(b"\x00", 1)[0].decode("utf-8", "replace")
        codec_id, width, height = struct.unpack(">III", meta[64:])
        if codec_id not in CODEC_IDS:
            raise RuntimeError(f"未知 codec id 0x{codec_id:08x}")
        result.update({"device_name": name, "codec": CODEC_IDS[codec_id], "width": width, "height": height})

        ctx = av.CodecContext.create(CODEC_IDS[codec_id], "r")
        frames = 0
        intervals: list[float] = []
        first_packet_s = None
        last_emit = 0.0
        start = time.time()
        while time.time() - start < args.seconds:
            try:
                pts, size = struct.unpack(">QI", recv_exact(video, PACKET_HEADER_LEN))
                if size > 16 << 20:
                    raise RuntimeError(f"异常包长 {size}")
                payload = recv_exact(video, size)
            except socket.timeout:
                break  # 静态画面期间编码器不产帧，按已采集的帧结束
            is_config = bool(pts & CONFIG_FLAG)
            if not is_config and first_packet_s is None:
                first_packet_s = time.time() - start
            for packet in ctx.parse(payload):
                for frame in ctx.decode(packet):
                    if is_config:
                        continue
                    frames += 1
                    now = time.time()
                    if last_emit:
                        intervals.append(now - last_emit)
                    last_emit = now
        result.update(
            {
                "frames": frames,
                "first_packet_s": round(first_packet_s or -1, 3),
                "mean_interval_ms": round(1000 * sum(intervals) / len(intervals), 1) if intervals else None,
            }
        )

        x, y = int(args.tap[0] * (width - 1)), int(args.tap[1] * (height - 1))
        t0 = time.perf_counter()
        control.sendall(touch_message(ACTION_DOWN, x, y, width, height))
        time.sleep(args.press_ms / 1000)
        control.sendall(touch_message(ACTION_UP, x, y, width, height))
        elapsed_ms = (time.perf_counter() - t0) * 1000
        result.update({"tap_xy": [x, y], "inject_ms": round(elapsed_ms, 1), "press_ms_target": args.press_ms})
    except Exception:
        print(f"server 日志（末 20 行）:\n{server_log_tail()}", file=sys.stderr)
        raise
    finally:
        for sock in (control, video):
            if sock is not None:
                sock.close()
        server.terminate()
        try:
            server.wait(timeout=2)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()
        try:
            sh(["adb", "-s", serial, "forward", "--remove", f"tcp:{args.port}"])
        except Exception:
            pass
        log_tail = server_log_tail()
        server_log_path.unlink(missing_ok=True)

    inject_ms = float(result.get("inject_ms", -1))
    ok = int(result.get("frames", 0)) >= 5 and 0.8 * args.press_ms <= inject_ms <= 3 * args.press_ms
    result["gate"] = "PASS" if ok else "FAIL"
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not ok and log_tail:
        print(f"server 日志（末 20 行）:\n{log_tail}", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
