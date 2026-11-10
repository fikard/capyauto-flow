# CapyAuto Flow 真机桥接（P0–P3 设备底座）实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 让 Python 后端能连上安卓真机，把 scrcpy 画面以 5 fps JPEG 推给前端 WebSocket，并接受归一化坐标的点击/滑动/按键注入。

**架构：** 单进程 FastAPI 后端（`backend/app`），通过 `DeviceAdapter` 接口屏蔽设备差异；本计划实现 `MockDevice`（无设备可跑通全链路）与 `AdbScrcpyDevice`（adb 推送 scrcpy-server、双 socket：video 解码出 JPEG、control 注入触摸事件）。前端点击换算成 0–1 归一化坐标发给后端，后端做分辨率换算与高斯抖动。

**技术栈：** Python 3.12 + FastAPI + uvicorn + PyAV（H.264 解码）+ Pillow（JPEG 编码）+ pytest；外部依赖 `adb`、`scrcpy`（brew 安装）；现有 React/Vite 前端不动。

**规格来源：** [2026-11-10-capyauto-real-device-bridge-design.md](../specs/2026-11-10-capyauto-real-device-bridge-design.md)

---

## 0. 计划范围与拆分

规格覆盖 8 个阶段，本文件只实现 **P0–P3**，交付「可独立运行、可被真机验证的设备底座」。

### 0.1 Plan 1（本文件）：P0–P3

| 阶段 | 交付物 | 完成判据 |
|---|---|---|
| P0 | adb/scrcpy 安装、真机连接、协议探测脚本 `scripts/scrcpy_probe.py` | 连续 10 秒不出错收到帧 + 一次 80ms 按压注入写入成功；给出 C1/C2 结论 |
| P1 | FastAPI 骨架、端口登记、`DeviceAdapter`、`MockDevice`、health/devices/session/WS | `pytest` 全绿；Mock 模式下四个接口与 WS 全通 |
| P2 | `AdbScrcpyDevice` 视频通道 + `ScreencapPoller` 降级通道 | 真机 5 fps 连续 10 分钟；拔插恢复；scrcpy 失败时 `degraded=true` |
| P3 | tap / swipe / key 注入、归一化坐标换算、高斯抖动 | 落点由后端返回且与设备读数一致；越界返回 `OUT_OF_BOUNDS`；按压时长误差 < 20ms |

### 0.2 Plan 2（另写一份计划文件）：P4–P7

这份计划在 Plan 1 全部任务打勾后编写，范围已定，不含本次实现细节：

- P4 应用与账号：`/api/app/launch`、`/api/app/stop`、`/api/app/users`、`/api/network/airplane`，含 `pm list users` 探测与 Android 版本分支的飞行模式实现。
- P5 OCR 闭环：`rapidocr-onnxruntime` 接入 `/api/vision/ocr`，前端用 `matchBestSkill` 选卡后回调 tap。
- P6 前端整合：`mode: 'sim' | 'real'`、`DeviceMirror`、`DeviceBar`、`DeviceDrawer`、`useDeviceSession`。
- P7 验收：`python -m app.verify`（V1–V10）、报告与取证截图、`npm run verify` 别名。

---

## 1. 文件结构

### 1.1 新建

```
scripts/
└── scrcpy_probe.py                 P0 技术闸门：独立协议探测脚本（一次性验证器，不参与生产链路）

backend/
├── pyproject.toml                  依赖与 pytest 配置
├── app/
│   ├── __init__.py
│   ├── __main__.py                 端口自检 + uvicorn 启动入口（python -m app）
│   ├── main.py                     FastAPI 实例、CORS、异常映射、路由挂载、调试页
│   ├── config.py                   环境变量与路径探测（端口、adb、scrcpy-server、帧率）
│   ├── errors.py                   ApiError 体系（错误码与 HTTP 状态映射）
│   ├── schemas.py                  请求体 pydantic 模型
│   ├── deps.py                     适配器工厂与单例
│   ├── api/
│   │   ├── __init__.py
│   │   ├── health.py               GET /api/health
│   │   ├── devices.py              GET /api/devices, POST /api/session, DELETE /api/session/{id}
│   │   ├── control.py              POST /api/control/{tap,swipe,key}
│   │   └── mirror.py               WS /ws/mirror
│   ├── core/
│   │   ├── __init__.py
│   │   ├── geometry.py             归一化 → 设备像素、边界校验、clamp
│   │   └── dither.py               高斯点击（对齐 TS 版）、贝塞尔滑动
│   ├── device/
│   │   ├── __init__.py
│   │   ├── base.py                 DeviceAdapter 抽象基类 + 数据类
│   │   ├── adb.py                  AdbRunner：subprocess 封装、devices 解析、wm size 解析
│   │   ├── mock_device.py          MockDevice：无设备也能跑通 REST/WS
│   │   ├── scrcpy_session.py       scrcpy 线格式、视频 socket 解码、control socket 注入、重连
│   │   ├── screen.py               ScreencapPoller：screencap 轮询降级通道
│   │   └── adb_device.py           AdbScrcpyDevice：探测、会话装配、注入调度
│   └── static/
│       └── debug_mirror.html       调试页：看 WS 画面 + 点击回传（P2/P3 人工验证用）
└── tests/
    ├── conftest.py                 mock 后端 fixture
    ├── test_config.py
    ├── test_geometry.py
    ├── test_dither.py
    ├── test_adb.py
    ├── test_scrcpy_wire.py
    ├── test_mock_device.py
    ├── test_api_devices.py
    ├── test_api_control.py
    └── test_ws_mirror.py
```

### 1.2 修改

| 文件 | 改动 |
|---|---|
| `package.json` | `dev` 脚本端口改用 `CAPYAUTO_FRONTEND_PORT`（默认 5178）；新增 `backend` 与 `verify` 占位外的真实命令 |
| `.gitignore` | 追加 `backend/.venv/`、`__pycache__/`、`reports/` |
| `.env.example` | 追加 `CAPYAUTO_*` 变量样例 |
| `~/.config/devgate/registry.yaml`（仓库外） | 通过 `devgate register` 登记 `capyauto-flow` 前后端 |
| `~/.config/trading-ports-check.sh`（仓库外） | `PORTS` 数组追加两项 |

### 1.3 明确不改

`src/App.tsx`、`src/components/PhoneSimulator.tsx`、`src/core/decision.ts`、`src/data/scriptFiles.ts`、`src/types/pipeline.ts` 一律不动。前端整合属于 P6 / Plan 2。

---

## 2. 执行前置约定

- 所有命令默认在项目根 `/Users/fikard/self_project/capyauto-flow` 执行；`backend` 相关命令在该目录的 `backend/` 下执行（计划中已写明 `cwd`）。
- Python 解释器固定用 `/Users/fikard/.local/bin/python3.12`（系统 `python3` 是 3.7.1，不可用）。
- 端口：后端 `8084`、前端 `5178`，均可被 `CAPYAUTO_BACKEND_PORT` / `CAPYAUTO_FRONTEND_PORT` 覆盖。
- 真机验证步骤需要手机已开启「开发者选项 → USB 调试」，并在弹窗中授权。无设备时 P1 的全部测试仍可跑（Mock 后端）。

---

## 3. 任务

### 任务 0：建立 git 基线

当前目录不是 git 仓库，后续每个任务都要 commit，必须先初始化。

**文件：**
- 修改：`.gitignore`
- 创建：`.git/`（由 git init 生成）

- [ ] **步骤 1：初始化仓库并补齐忽略规则**

在 [.gitignore](file:///Users/fikard/self_project/capyauto-flow/.gitignore) 末尾追加：

```gitignore
backend/.venv/
__pycache__/
.pytest_cache/
reports/
.screenshots/
```

- [ ] **步骤 2：提交基线**

运行：

```bash
git init && git add -A && git commit -m "chore: 初始化仓库基线"
```

预期：`git log --oneline -1` 输出一行 `chore: 初始化仓库基线`。

- [ ] **步骤 3：确认忽略生效**

运行：`git status --short`

预期：无 `backend/.venv/`、`__pycache__/` 相关输出（此时它们还没被创建，输出为空即为正常）。

---

### 任务 1：端口登记与前端 dev 端口改造（P1 端口规范）

规格要求两个端口登记到 devgate 注册表，且前端不再占用 3000（该端口属于 travel_design）。

**文件：**
- 修改：`package.json:7`
- 修改：`~/.config/trading-ports-check.sh:16-29`
- 修改（由 devgate 生成）：`~/.config/devgate/registry.yaml`、`~/.config/trading-ports.env`

- [ ] **步骤 1：登记后端与前端服务**

```bash
devgate register capyauto-flow backend --port 8084 --path ~/self_project/capyauto-flow \
  --env-var CAPYAUTO_BACKEND_PORT --cwd backend \
  --cmd ".venv/bin/python -m app" --stop ""
devgate register capyauto-flow frontend --port 5178 --path ~/self_project/capyauto-flow \
  --env-var CAPYAUTO_FRONTEND_PORT --cmd "npm run dev" --stop ""
devgate env --write
```

预期：`grep CAPYAUTO ~/.config/trading-ports.env` 输出两行：

```
CAPYAUTO_BACKEND_PORT=8084
CAPYAUTO_FRONTEND_PORT=5178
```

若提示端口已被占用，改用 `devgate register ... --port 0` 由 devgate 自动分配，并把结果写进下一节的环境变量说明。

- [ ] **步骤 2：把两个端口加入冲突检查脚本**

在 [trading-ports-check.sh](file:///Users/fikard/.config/trading-ports-check.sh#L16-L29) 的 `PORTS` 数组末尾（`STOCK_SIGNAL_CREATOR_WEB_PORT` 那一行之后）追加两行：

```bash
    "CAPYAUTO_BACKEND_PORT:capyauto-flow 后端"
    "CAPYAUTO_FRONTEND_PORT:capyauto-flow 前端"
```

- [ ] **步骤 3：验证检查脚本**

运行：`~/.config/trading-ports-check.sh | grep capyauto`

预期：两行，均为 `✓ ...: 可用`。

- [ ] **步骤 4：改造前端 dev 脚本**

把 [package.json](file:///Users/fikard/self_project/capyauto-flow/package.json#L7) 的 `dev` 改为：

```json
    "dev": "vite --port=${CAPYAUTO_FRONTEND_PORT:-5178} --host 0.0.0.0",
    "backend": "cd backend && .venv/bin/python -m app",
    "test:backend": "cd backend && .venv/bin/python -m pytest -q",
```

- [ ] **步骤 5：验证前端端口**

```bash
npm run dev &
sleep 4
curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:5178/
kill %1
```

预期：输出 `200`。

- [ ] **步骤 6：Commit**

```bash
git add package.json && git commit -m "feat: 前端 dev 端口改为 CAPYAUTO_FRONTEND_PORT 并登记后端命令"
```

---

### 任务 2：安装 adb 与 scrcpy，连接真机（P0）

**文件：** 无代码改动（系统级安装）。

- [ ] **步骤 1：安装 scrcpy（自带 adb）**

```bash
brew install scrcpy
```

预期：结尾出现 `==> Summary` 且无 `Error`。`scrcpy` 安装会满足 `platform-tools` 依赖，从而提供 `adb`。

- [ ] **步骤 2：验证二进制与 server jar**

```bash
adb version
scrcpy --version
ls -l "$(brew --prefix)/share/scrcpy/scrcpy-server"
```

预期：

- `adb version` 首行形如 `Android Debug Bridge version 1.0.41`
- `scrcpy --version` 首行形如 `scrcpy 3.1 <https://github.com/Genymobile/scrcpy>`
- jar 路径存在，例如 `/usr/local/share/scrcpy/scrcpy-server`

记下 scrcpy 版本号（后续脚本会自动解析，不需要硬编码）。

- [ ] **步骤 3：连接真机并授权**

手机开启 USB 调试后插入数据线，运行：

```bash
adb devices -l
```

预期：出现一行 `<序列号>  device product:... model:...`。若状态为 `unauthorized`，在手机上点「允许 USB 调试」，然后再执行一次。

- [ ] **步骤 4：记录设备信息**

```bash
adb shell getprop ro.product.model
adb shell getprop ro.build.version.sdk
adb shell getprop ro.product.cpu.abi
adb shell wm size
```

预期：四条命令均有输出，例如 `SM-G9730` / `34` / `arm64-v8a` / `Physical size: 1080x2340`。把这四个值记到本计划第 4 节「P0 结论记录」中。

---

### 任务 3：scrcpy 协议探测脚本（P0 技术闸门）

一次性验证器：证明「scrcpy-server 能起、video socket 能解出帧、control socket 能注入 80ms 按压」。脚本不参与生产链路，验证完保留为排障工具。

**文件：**
- 创建：`scripts/scrcpy_probe.py`

- [ ] **步骤 1：编写探测脚本**

创建 `scripts/scrcpy_probe.py`：

```python
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
import time
from pathlib import Path

META_LEN = 76
PACKET_HEADER_LEN = 12
CODEC_IDS = {0x68323634: "h264", 0x68323635: "h265", 0x00617631: "av1"}
MSG_INJECT_TOUCH = 2
ACTION_DOWN, ACTION_UP = 0, 1


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
    sh(["adb", "-s", serial, "forward", f"tcp:{args.port}", "localabstract:scrcpy"])

    server_cmd = (
        f"CLASSPATH={remote} app_process / com.genymobile.scrcpy.Server {version} "
        f"log_level=info tunnel_forward=true audio=false video=true control=true "
        f"max_fps=10 video_bit_rate=8000000 max_size=0 cleanup=true"
    )
    server = subprocess.Popen(
        ["adb", "-s", serial, "shell", server_cmd],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    result: dict[str, object] = {"serial": serial, "scrcpy": version, "server_jar": str(jar)}
    video = None
    control = None
    try:
        video = connect(args.port)
        meta = recv_exact(video, META_LEN)
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
            pts, flags, size = struct.unpack(">QBI", recv_exact(video, PACKET_HEADER_LEN))
            payload = recv_exact(video, size)
            if flags & 0x80:
                continue
            if first_packet_s is None:
                first_packet_s = time.time() - start
            for packet in ctx.parse(payload):
                for frame in ctx.decode(packet):
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

        control = connect(args.port)
        x, y = int(args.tap[0] * (width - 1)), int(args.tap[1] * (height - 1))
        t0 = time.perf_counter()
        control.sendall(touch_message(ACTION_DOWN, x, y, width, height))
        time.sleep(args.press_ms / 1000)
        control.sendall(touch_message(ACTION_UP, x, y, width, height))
        elapsed_ms = (time.perf_counter() - t0) * 1000
        result.update({"tap_xy": [x, y], "inject_ms": round(elapsed_ms, 1)})
    finally:
        for sock in (control, video):
            if sock is not None:
                sock.close()
        server.terminate()
        try:
            sh(["adb", "-s", serial, "forward", "--remove", f"tcp:{args.port}"])
        except Exception:
            pass

    ok = int(result.get("frames", 0)) >= 5 and int(result.get("inject_ms", 0)) >= 0
    result["gate"] = "PASS" if ok else "FAIL"
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **步骤 2：先确认脚本在无依赖时报错清晰**

运行（此时 backend 虚拟环境还没建，用系统 Python 会缺 `av`）：

```bash
python3 scripts/scrcpy_probe.py --seconds 2
```

预期：要么报 `ModuleNotFoundError: No module named 'av'`，要么在建 venv 后（任务 4）正常运行。若报错信息不是 ImportError，说明设备或 adb 有问题，先按提示处理。

- [ ] **步骤 3：在真机上运行探测（需先完成任务 4 的 venv）**

```bash
cd backend && .venv/bin/python ../scripts/scrcpy_probe.py --seconds 10 --tap 0.5 0.5 --press-ms 80
```

预期输出（数值因设备而异）：

```json
{
  "serial": "R58M12ABCDE",
  "scrcpy": "3.1",
  "server_jar": "/usr/local/share/scrcpy/scrcpy-server",
  "device_name": "SM-G9730",
  "codec": "h264",
  "width": 1080,
  "height": 2340,
  "frames": 90,
  "first_packet_s": 1.24,
  "mean_interval_ms": 100.0,
  "tap_xy": [539, 1169],
  "inject_ms": 82.4,
  "gate": "PASS"
}
```

判据：`gate` 为 `PASS`（`frames >= 5` 且注入无异常）。若 `frames` 为 0，检查 `scrcpy --version` 是否 ≥ 2.0；若连接超时，检查 `adb forward --list` 是否残留旧端口（`adb forward --remove-all` 后重试）。

- [ ] **步骤 4：Commit**

```bash
git add scripts/scrcpy_probe.py && git commit -m "feat: 新增 scrcpy 协议探测脚本（P0 闸门）"
```

---

### 任务 4：后端工程骨架与配置

**文件：**
- 创建：`backend/pyproject.toml`
- 创建：`backend/app/__init__.py`
- 创建：`backend/app/config.py`
- 创建：`backend/app/__main__.py`
- 创建：`backend/tests/test_config.py`
- 修改：`.env.example`

- [ ] **步骤 1：编写 pyproject.toml 与依赖**

创建 `backend/pyproject.toml`：

```toml
[project]
name = "capyauto-backend"
version = "0.1.0"
description = "CapyAuto Flow 真机桥接后端"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "pydantic>=2.9",
    "av>=13.0",
    "pillow>=10.4",
]

[project.optional-dependencies]
dev = ["pytest>=8.3", "httpx>=0.27"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["."]
include = ["app*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
```

- [ ] **步骤 2：创建虚拟环境并安装依赖**

```bash
cd backend && /Users/fikard/.local/bin/python3.12 -m venv .venv \
  && .venv/bin/python -m pip install -q -U pip \
  && .venv/bin/pip install -q -e ".[dev]"
```

预期：命令退出码 0。`backend/.venv/bin/python -c "import fastapi, av, PIL; print('ok')"` 输出 `ok`。

- [ ] **步骤 3：编写失败的测试**

创建 `backend/tests/test_config.py`：

```python
from app.config import Settings


def test_defaults_when_env_missing(monkeypatch):
    for name in (
        "CAPYAUTO_BACKEND_PORT",
        "CAPYAUTO_FRONTEND_PORT",
        "CAPYAUTO_DEVICE_BACKEND",
        "CAPYAUTO_MIRROR_FPS",
    ):
        monkeypatch.delenv(name, raising=False)
    cfg = Settings()
    assert cfg.backend_port == 8084
    assert cfg.frontend_port == 5178
    assert cfg.device_backend == "mock"
    assert cfg.mirror_fps == 5


def test_env_override(monkeypatch):
    monkeypatch.setenv("CAPYAUTO_BACKEND_PORT", "9099")
    monkeypatch.setenv("CAPYAUTO_DEVICE_BACKEND", "adb")
    cfg = Settings()
    assert cfg.backend_port == 9099
    assert cfg.device_backend == "adb"
```

- [ ] **步骤 4：运行测试确认失败**

运行（cwd 为 `backend`）：`.venv/bin/python -m pytest tests/test_config.py -q`

预期：FAIL，`ModuleNotFoundError: No module named 'app'`（缺少 `app/__init__.py` 与 `config.py`）。

- [ ] **步骤 5：编写配置实现**

创建 `backend/app/__init__.py`（空文件）与 `backend/app/config.py`：

```python
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise SystemExit(f"环境变量 {name} 必须是整数，实际为 {raw!r}") from exc


def _detect_scrcpy_server() -> Path | None:
    explicit = os.environ.get("CAPYAUTO_SCRCPY_SERVER")
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    for prefix in ("/opt/homebrew", "/usr/local"):
        candidates.append(Path(prefix) / "share/scrcpy/scrcpy-server")
        cellar = Path(prefix) / "Cellar/scrcpy"
        if cellar.is_dir():
            candidates.extend(sorted(cellar.glob("*/share/scrcpy/scrcpy-server"), reverse=True))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


@dataclass(frozen=True)
class Settings:
    backend_port: int = field(default_factory=lambda: _env_int("CAPYAUTO_BACKEND_PORT", 8084))
    frontend_port: int = field(default_factory=lambda: _env_int("CAPYAUTO_FRONTEND_PORT", 5178))
    device_backend: str = field(default_factory=lambda: os.environ.get("CAPYAUTO_DEVICE_BACKEND", "mock"))
    adb_path: str = field(default_factory=lambda: os.environ.get("CAPYAUTO_ADB", "adb"))
    scrcpy_bin: str = field(default_factory=lambda: os.environ.get("CAPYAUTO_SCRCPY", "scrcpy"))
    scrcpy_server: Path | None = field(default_factory=_detect_scrcpy_server)
    scrcpy_version: str | None = field(default_factory=lambda: os.environ.get("CAPYAUTO_SCRCPY_VERSION"))
    scrcpy_tcp_port: int = field(default_factory=lambda: _env_int("CAPYAUTO_SCRCPY_TCP_PORT", 27183))
    mirror_fps: int = field(default_factory=lambda: _env_int("CAPYAUTO_MIRROR_FPS", 5))
    display_width: int = field(default_factory=lambda: _env_int("CAPYAUTO_DISPLAY_WIDTH", 720))
    jpeg_quality: int = field(default_factory=lambda: _env_int("CAPYAUTO_JPEG_QUALITY", 70))
    scrcpy_bitrate: int = field(default_factory=lambda: _env_int("CAPYAUTO_SCRCPY_BITRATE", 8_000_000))
    frame_timeout: float = field(default_factory=lambda: float(os.environ.get("CAPYAUTO_FRAME_TIMEOUT", "10")))
    allow_screencap_fallback: bool = field(
        default_factory=lambda: os.environ.get("CAPYAUTO_ALLOW_SCREENCAP_FALLBACK", "1") != "0"
    )


settings = Settings()
```

- [ ] **步骤 6：运行测试确认通过**

运行：`.venv/bin/python -m pytest tests/test_config.py -q`

预期：`2 passed`。

- [ ] **步骤 7：编写端口自检入口**

创建 `backend/app/__main__.py`：

```python
from __future__ import annotations

import socket

import uvicorn

from app.config import settings


def port_busy(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return True
    return False


def main() -> None:
    if port_busy(settings.backend_port):
        raise SystemExit(
            f"[capyauto] 端口 {settings.backend_port} 已被占用，"
            f"用 CAPYAUTO_BACKEND_PORT 指定其他端口后重试"
        )
    uvicorn.run("app.main:app", host="127.0.0.1", port=settings.backend_port, log_level="info")


if __name__ == "__main__":
    main()
```

- [ ] **步骤 8：验证端口自检逻辑**

运行：`.venv/bin/python -c "from app.__main__ import port_busy; print(port_busy(8084))"`

预期：输出 `False`（8084 空闲）。

- [ ] **步骤 9：补充环境变量样例**

在 [.env.example](file:///Users/fikard/self_project/capyauto-flow/.env.example) 末尾追加：

```bash
# 真机桥接后端（Plan 1 P0–P3）
CAPYAUTO_BACKEND_PORT=8084
CAPYAUTO_FRONTEND_PORT=5178
# mock | adb
CAPYAUTO_DEVICE_BACKEND=mock
CAPYAUTO_MIRROR_FPS=5
CAPYAUTO_DISPLAY_WIDTH=720
CAPYAUTO_JPEG_QUALITY=70
```

- [ ] **步骤 10：Commit**

```bash
git add backend/pyproject.toml backend/app/__init__.py backend/app/config.py backend/app/__main__.py backend/tests/test_config.py .env.example
git commit -m "feat: 后端工程骨架与配置（端口、帧率、scrcpy 路径探测）"
```

---
### 任务 5：错误模型

规格第 9 节的每个错误码都要有对应的异常类，HTTP 状态在异常类上固定，避免散落在路由里。

**文件：**
- 创建：`backend/app/errors.py`
- 创建：`backend/tests/test_errors.py`

- [ ] **步骤 1：编写失败的测试**

创建 `backend/tests/test_errors.py`：

```python
from app.errors import (
    AdbNotFound,
    DeviceUnauthorized,
    MirrorLost,
    OutOfBounds,
    ScrcpyUnavailable,
    SessionNotFound,
)


def test_error_codes_and_status():
    assert OutOfBounds().status_code == 400
    assert OutOfBounds("x").code == "OUT_OF_BOUNDS"
    assert DeviceUnauthorized().status_code == 409
    assert AdbNotFound().status_code == 503
    assert SessionNotFound().status_code == 404
    assert ScrcpyUnavailable().status_code == 503
    assert MirrorLost().status_code == 502


def test_payload_shape():
    err = OutOfBounds("坐标越界", detail={"x": 1.2})
    assert err.to_payload() == {
        "error": {"code": "OUT_OF_BOUNDS", "message": "坐标越界", "detail": {"x": 1.2}}
    }
```

- [ ] **步骤 2：运行测试确认失败**

运行：`.venv/bin/python -m pytest tests/test_errors.py -q`

预期：FAIL，`ModuleNotFoundError: No module named 'app.errors'`。

- [ ] **步骤 3：编写实现**

创建 `backend/app/errors.py`：

```python
from __future__ import annotations

from typing import Any


class ApiError(Exception):
    status_code = 400
    code = "BAD_REQUEST"

    def __init__(
        self,
        message: str | None = None,
        *,
        status_code: int | None = None,
        code: str | None = None,
        detail: Any = None,
    ) -> None:
        self.message = message or code or self.code
        if status_code is not None:
            self.status_code = status_code
        if code is not None:
            self.code = code
        self.detail = detail
        super().__init__(self.message)

    def to_payload(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message, "detail": self.detail}}


class OutOfBounds(ApiError):
    status_code = 400
    code = "OUT_OF_BOUNDS"


class UnknownKey(ApiError):
    status_code = 400
    code = "UNKNOWN_KEY"


class DeviceNotFound(ApiError):
    status_code = 404
    code = "DEVICE_NOT_FOUND"


class SessionNotFound(ApiError):
    status_code = 404
    code = "SESSION_NOT_FOUND"


class DeviceUnauthorized(ApiError):
    status_code = 409
    code = "DEVICE_UNAUTHORIZED"


class MultipleDevices(ApiError):
    status_code = 409
    code = "MULTIPLE_DEVICES"


class AdbNotFound(ApiError):
    status_code = 503
    code = "ADB_NOT_FOUND"


class AdbError(ApiError):
    status_code = 502
    code = "ADB_FAILED"


class AdbTimeout(AdbError):
    status_code = 504
    code = "ADB_TIMEOUT"


class ScrcpyUnavailable(ApiError):
    status_code = 503
    code = "SCRCPY_UNAVAILABLE"


class MirrorLost(ApiError):
    status_code = 502
    code = "MIRROR_LOST"


class InjectionFailed(ApiError):
    status_code = 502
    code = "INJECTION_FAILED"
```

- [ ] **步骤 4：运行测试确认通过**

运行：`.venv/bin/python -m pytest tests/test_errors.py -q`

预期：`2 passed`。

- [ ] **步骤 5：Commit**

```bash
git add backend/app/errors.py backend/tests/test_errors.py
git commit -m "feat: 新增错误码体系"
```

---

### 任务 6：坐标换算（geometry）

**文件：**
- 创建：`backend/app/core/__init__.py`
- 创建：`backend/app/core/geometry.py`
- 创建：`backend/tests/test_geometry.py`

- [ ] **步骤 1：编写失败的测试**

创建 `backend/tests/test_geometry.py`：

```python
import pytest

from app.core.geometry import clamp, normalize_to_device
from app.errors import OutOfBounds


def test_half_maps_to_center():
    assert normalize_to_device(0.5, 0.5, 1080, 2340) == (540, 1170)


def test_edges():
    assert normalize_to_device(0.0, 0.0, 1080, 2340) == (0, 0)
    assert normalize_to_device(1.0, 1.0, 1080, 2340) == (1079, 2339)


@pytest.mark.parametrize("x,y", [(-0.01, 0.5), (0.5, 1.01), (1.2, 0.3)])
def test_out_of_bounds_raises(x, y):
    with pytest.raises(OutOfBounds):
        normalize_to_device(x, y, 1080, 2340)


def test_clamp():
    assert clamp(-5, 0, 100) == 0
    assert clamp(105, 0, 100) == 100
    assert clamp(50, 0, 100) == 50
```

- [ ] **步骤 2：运行测试确认失败**

运行：`.venv/bin/python -m pytest tests/test_geometry.py -q`

预期：FAIL，`ModuleNotFoundError: No module named 'app.core'`。

- [ ] **步骤 3：编写实现**

创建 `backend/app/core/__init__.py`（空文件）与 `backend/app/core/geometry.py`：

```python
from __future__ import annotations

import math

from app.errors import OutOfBounds


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def js_round(value: float) -> int:
    """与 JS Math.round 一致：.5 向正无穷方向进位（Python round 是银行家舍入）。"""
    return math.floor(value + 0.5)


def normalize_to_device(x: float, y: float, width: int, height: int) -> tuple[int, int]:
    """归一化坐标（0–1）→ 设备像素坐标。

    越界直接抛 OutOfBounds，不做静默 clamp（规格第 9 节）。
    映射规则：舍入(x * 边长)，再 clamp 到 [0, 边长-1]。
    """
    if width <= 0 or height <= 0:
        raise ValueError(f"设备分辨率非法: {width}x{height}")
    if not (0.0 <= x <= 1.0) or not (0.0 <= y <= 1.0):
        raise OutOfBounds(f"归一化坐标超出 0–1 范围: x={x}, y={y}", detail={"x": x, "y": y})
    px = int(clamp(js_round(x * width), 0, width - 1))
    py = int(clamp(js_round(y * height), 0, height - 1))
    return px, py
```

- [ ] **步骤 4：运行测试确认通过**

运行：`.venv/bin/python -m pytest tests/test_geometry.py -q`

预期：`6 passed`。

- [ ] **步骤 5：Commit**

```bash
git add backend/app/core/__init__.py backend/app/core/geometry.py backend/tests/test_geometry.py
git commit -m "feat: 归一化坐标换算与边界校验"
```

---

### 任务 7：抖动算法（dither）

必须与 [decision.ts](file:///Users/fikard/self_project/capyauto-flow/src/core/decision.ts#L6-L63) 的 `randomGaussian` / `generateHumanClick` / `generateBezierPoints` 行为一致：同样的 RNG 序列应得到同样的整数结果。

**文件：**
- 创建：`backend/app/core/dither.py`
- 创建：`backend/tests/test_dither.py`

- [ ] **步骤 1：编写失败的测试**

创建 `backend/tests/test_dither.py`：

```python
import random
import statistics

from app.core.dither import bezier_points, gaussian_click, random_gaussian


def test_gaussian_zero_stdev_is_deterministic():
    plan = gaussian_click(0.5, 0.5, 1080, 2340, sigma=0.0, press_mean=80, press_stdev=0.0)
    assert (plan.target_x, plan.target_y) == (540, 1170)
    assert (plan.real_x, plan.real_y) == (540, 1170)
    assert plan.press_ms == 80


def test_gaussian_statistics():
    rng = random.Random(42)
    samples = [random_gaussian(100.0, 6.0, rng.random) for _ in range(5000)]
    assert abs(statistics.fmean(samples) - 100.0) < 0.6
    assert abs(statistics.pstdev(samples) - 6.0) < 0.4


def test_click_stays_in_bounds():
    rng = random.Random(7)
    for _ in range(500):
        plan = gaussian_click(0.0, 0.0, 1080, 2340, sigma=30.0, rng=rng.random)
        assert 0 <= plan.real_x <= 1079
        assert 0 <= plan.real_y <= 2339


def test_press_duration_floor():
    rng = random.Random(1)
    for _ in range(200):
        plan = gaussian_click(0.5, 0.5, 1080, 2340, press_mean=40, press_stdev=50, rng=rng.random)
        assert plan.press_ms >= 40


def test_bezier_endpoints_and_length():
    rng = random.Random(3)
    points = bezier_points(100, 200, 900, 1600, steps=10, rng=rng.random)
    assert len(points) == 11
    assert points[0] == (100, 200)
    assert points[-1] == (900, 1600)
    xs = [p[0] for p in points]
    assert all(isinstance(v, int) for v in xs)
```

- [ ] **步骤 2：运行测试确认失败**

运行：`.venv/bin/python -m pytest tests/test_dither.py -q`

预期：FAIL，`ModuleNotFoundError: No module named 'app.core.dither'`。

- [ ] **步骤 3：编写实现**

创建 `backend/app/core/dither.py`：

```python
from __future__ import annotations

import math
import random
import sys
from dataclasses import dataclass
from typing import Callable

from app.core.geometry import clamp, js_round, normalize_to_device

Rng = Callable[[], float]


def random_gaussian(mean: float, stdev: float, rng: Rng = random.random) -> float:
    """Box-Muller 变换，与 TS randomGaussian 逐式对齐。"""
    u1 = rng()
    u2 = rng()
    while u1 <= sys.float_info.epsilon:
        u1 = rng()
    return mean + math.sqrt(-2.0 * math.log(u1)) * math.sin(2.0 * math.pi * u2) * stdev


@dataclass(frozen=True)
class ClickPlan:
    target_x: int
    target_y: int
    real_x: int
    real_y: int
    press_ms: int


def gaussian_click(
    x_norm: float,
    y_norm: float,
    width: int,
    height: int,
    sigma: float = 6.0,
    press_mean: float = 80.0,
    press_stdev: float = 20.0,
    rng: Rng = random.random,
) -> ClickPlan:
    target_x, target_y = normalize_to_device(x_norm, y_norm, width, height)
    real_x = int(clamp(js_round(random_gaussian(target_x, sigma, rng)), 0, width - 1))
    real_y = int(clamp(js_round(random_gaussian(target_y, sigma, rng)), 0, height - 1))
    press_ms = max(40, js_round(random_gaussian(press_mean, press_stdev, rng)))
    return ClickPlan(
        target_x=target_x,
        target_y=target_y,
        real_x=real_x,
        real_y=real_y,
        press_ms=press_ms,
    )


def bezier_points(
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    steps: int = 10,
    offset: float = 40.0,
    rng: Rng = random.random,
) -> list[tuple[int, int]]:
    """二次贝塞尔轨迹，控制点带有机偏移，与 TS generateBezierPoints 对齐。"""
    cx = (x1 + x2) / 2 + (rng() * offset * 2 - offset)
    cy = (y1 + y2) / 2 + (rng() * offset * 2 - offset)
    points: list[tuple[int, int]] = []
    for i in range(steps + 1):
        t = i / steps
        px = js_round((1 - t) * (1 - t) * x1 + 2 * (1 - t) * t * cx + t * t * x2)
        py = js_round((1 - t) * (1 - t) * y1 + 2 * (1 - t) * t * cy + t * t * y2)
        points.append((px, py))
    return points
```

- [ ] **步骤 4：运行测试确认通过**

运行：`.venv/bin/python -m pytest tests/test_dither.py -q`

预期：`5 passed`。

- [ ] **步骤 5：Commit**

```bash
git add backend/app/core/dither.py backend/tests/test_dither.py
git commit -m "feat: 高斯点击与贝塞尔滑动（与前端 TS 实现对齐）"
```

---

### 任务 8：设备抽象与数据类

**文件：**
- 创建：`backend/app/device/__init__.py`
- 创建：`backend/app/device/base.py`
- 创建：`backend/tests/test_mock_device.py`（本任务只写第一个测试）

- [ ] **步骤 1：编写失败的测试**

创建 `backend/tests/test_mock_device.py`：

```python
import asyncio

from app.device.mock_device import MockDevice


def test_mock_session_lifecycle():
    async def scenario():
        device = MockDevice()
        devices = await device.list_devices()
        assert devices[0].serial == "MOCK-0001"
        session = await device.create_session("MOCK-0001", fps=5)
        assert session.width == 1080
        assert session.height == 2400
        assert session.mode == "mock"
        assert device.get_session(session.id).id == session.id
        await device.close_session(session.id)
        try:
            device.get_session(session.id)
        except Exception as exc:
            assert getattr(exc, "code", None) == "SESSION_NOT_FOUND"
        else:
            raise AssertionError("会话应已删除")

    asyncio.run(scenario())
```

- [ ] **步骤 2：运行测试确认失败**

运行：`.venv/bin/python -m pytest tests/test_mock_device.py -q`

预期：FAIL，`ModuleNotFoundError: No module named 'app.device'`。

- [ ] **步骤 3：编写 base.py**

创建 `backend/app/device/__init__.py`（空文件）与 `backend/app/device/base.py`：

```python
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator, Literal


@dataclass
class DeviceInfo:
    serial: str
    state: str
    model: str | None = None
    android: str | None = None
    abi: str | None = None
    wm_size: str | None = None
    width: int | None = None
    height: int | None = None
    transport_id: str | None = None


@dataclass
class MirrorSession:
    id: str
    serial: str
    width: int
    height: int
    fps: int
    degraded: bool = False
    mode: Literal["scrcpy", "screencap", "mock"] = "mock"
    size_mismatch: bool = False


@dataclass
class Frame:
    seq: int
    jpeg: bytes
    width: int
    height: int
    ts: float


@dataclass
class TapResult:
    target_x: int
    target_y: int
    real_x: int
    real_y: int
    press_ms: int
    injected_via: str


@dataclass
class SwipeResult:
    points: list[tuple[int, int]]
    injected_via: str


class DeviceAdapter(ABC):
    name: str = "base"

    @abstractmethod
    async def health(self) -> dict:
        ...

    @abstractmethod
    async def list_devices(self) -> list[DeviceInfo]:
        ...

    @abstractmethod
    async def create_session(self, serial: str, fps: int) -> MirrorSession:
        ...

    @abstractmethod
    async def close_session(self, session_id: str) -> None:
        ...

    @abstractmethod
    def get_session(self, session_id: str) -> MirrorSession:
        ...

    @abstractmethod
    def frames(self, session_id: str) -> AsyncIterator[Frame]:
        ...

    @abstractmethod
    async def tap(
        self,
        session_id: str,
        x: float,
        y: float,
        press_ms: float,
        sigma: float,
        press_stdev: float = 20.0,
    ) -> TapResult:
        ...

    @abstractmethod
    async def swipe(
        self,
        session_id: str,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        duration_ms: int,
    ) -> SwipeResult:
        ...

    @abstractmethod
    async def key(self, session_id: str, key: str) -> None:
        ...

    @abstractmethod
    async def screenshot(self, session_id: str) -> bytes:
        ...
```

- [ ] **步骤 4：编写 MockDevice**

创建 `backend/app/device/mock_device.py`：

```python
from __future__ import annotations

import asyncio
import io
import time

from PIL import Image, ImageDraw

from app.core.dither import bezier_points, gaussian_click
from app.core.geometry import normalize_to_device
from app.device.base import DeviceAdapter, DeviceInfo, Frame, MirrorSession, SwipeResult, TapResult
from app.errors import DeviceNotFound, SessionNotFound

KEY_ALIASES = {"back", "home", "app_switch", "power", "volume_up", "volume_down"}


class MockDevice(DeviceAdapter):
    name = "mock"

    def __init__(self, width: int = 1080, height: int = 2400, jpeg_quality: int = 70) -> None:
        self._width = width
        self._height = height
        self._jpeg_quality = jpeg_quality
        self._sessions: dict[str, MirrorSession] = {}
        self._next_id = 1
        self._seq = 0
        self._last_tap: tuple[int, int] | None = None
        self._keys: list[str] = []

    async def health(self) -> dict:
        return {
            "ok": True,
            "device_backend": self.name,
            "adb_version": None,
            "scrcpy_version": None,
            "ocr_engine": None,
            "hint": "当前为 Mock 后端，不连接真机",
        }

    async def list_devices(self) -> list[DeviceInfo]:
        return [
            DeviceInfo(
                serial="MOCK-0001",
                state="device",
                model="Mock Pixel 8",
                android="14",
                abi="arm64-v8a",
                wm_size=f"Physical size: {self._width}x{self._height}",
                width=self._width,
                height=self._height,
                transport_id="1",
            )
        ]

    async def create_session(self, serial: str, fps: int) -> MirrorSession:
        if serial != "MOCK-0001":
            raise DeviceNotFound(f"未找到设备 {serial}")
        session_id = f"mock-{self._next_id}"
        self._next_id += 1
        session = MirrorSession(
            id=session_id,
            serial=serial,
            width=self._width,
            height=self._height,
            fps=fps,
            mode="mock",
        )
        self._sessions[session_id] = session
        return session

    async def close_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def get_session(self, session_id: str) -> MirrorSession:
        if session_id not in self._sessions:
            raise SessionNotFound(f"会话不存在: {session_id}")
        return self._sessions[session_id]

    async def frames(self, session_id: str):
        session = self.get_session(session_id)
        while session_id in self._sessions:
            self._seq += 1
            yield Frame(
                seq=self._seq,
                jpeg=self._render(self._seq),
                width=session.width,
                height=session.height,
                ts=time.time(),
            )
            await asyncio.sleep(1.0 / max(session.fps, 1))

    async def tap(
        self,
        session_id: str,
        x: float,
        y: float,
        press_ms: float,
        sigma: float,
        press_stdev: float = 20.0,
    ) -> TapResult:
        session = self.get_session(session_id)
        plan = gaussian_click(
            x,
            y,
            session.width,
            session.height,
            sigma=sigma,
            press_mean=press_ms,
            press_stdev=press_stdev,
        )
        self._last_tap = (plan.real_x, plan.real_y)
        return TapResult(
            target_x=plan.target_x,
            target_y=plan.target_y,
            real_x=plan.real_x,
            real_y=plan.real_y,
            press_ms=plan.press_ms,
            injected_via="mock",
        )

    async def swipe(
        self,
        session_id: str,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        duration_ms: int,
    ) -> SwipeResult:
        session = self.get_session(session_id)
        px1, py1 = normalize_to_device(x1, y1, session.width, session.height)
        px2, py2 = normalize_to_device(x2, y2, session.width, session.height)
        return SwipeResult(points=bezier_points(px1, py1, px2, py2), injected_via="mock")

    async def key(self, session_id: str, key: str) -> None:
        self.get_session(session_id)
        if key not in KEY_ALIASES:
            raise ValueError(f"未知按键: {key}")
        self._keys.append(key)

    async def screenshot(self, session_id: str) -> bytes:
        self.get_session(session_id)
        image = Image.open(io.BytesIO(self._render(self._seq or 1)))
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        return buffer.getvalue()

    def _render(self, seq: int) -> bytes:
        width, height = self._width // 4, self._height // 4
        image = Image.new("RGB", (width, height), (15, 20, 26))
        draw = ImageDraw.Draw(image)
        draw.rectangle([6, 6, width - 6, height - 6], outline=(70, 200, 160), width=2)
        draw.text((14, 14), f"MOCK seq={seq}", fill=(200, 230, 220))
        draw.text((14, 34), f"tap={self._last_tap}", fill=(160, 200, 255))
        draw.text((14, 54), f"keys={self._keys[-1] if self._keys else None}", fill=(200, 200, 160))
        if self._last_tap:
            px, py = self._last_tap[0] // 4, self._last_tap[1] // 4
            draw.ellipse([px - 6, py - 6, px + 6, py + 6], outline=(255, 120, 120), width=2)
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", quality=self._jpeg_quality)
        return buffer.getvalue()
```

- [ ] **步骤 5：运行测试确认通过**

运行：`.venv/bin/python -m pytest tests/test_mock_device.py -q`

预期：`1 passed`。

- [ ] **步骤 6：追加 Mock 注入测试**

在 `backend/tests/test_mock_device.py` 末尾追加：

```python
def test_mock_tap_and_key():
    async def scenario():
        device = MockDevice()
        session = await device.create_session("MOCK-0001", fps=5)
        result = await device.tap(session.id, 0.5, 0.5, press_ms=80, sigma=0.0, press_stdev=0.0)
        assert (result.target_x, result.target_y) == (540, 1200)
        assert (result.real_x, result.real_y) == (540, 1200)
        assert result.press_ms == 80
        assert result.injected_via == "mock"
        swipe = await device.swipe(session.id, 0.5, 0.8, 0.5, 0.2, duration_ms=300)
        assert len(swipe.points) == 11
        await device.key(session.id, "back")

    asyncio.run(scenario())
```

- [ ] **步骤 7：运行测试确认通过**

运行：`.venv/bin/python -m pytest tests/test_mock_device.py -q`

预期：`2 passed`。

- [ ] **步骤 8：Commit**

```bash
git add backend/app/device/__init__.py backend/app/device/base.py backend/app/device/mock_device.py backend/tests/test_mock_device.py
git commit -m "feat: DeviceAdapter 抽象与 MockDevice 实现"
```

---
### 任务 9：Mock API（health / devices / session）

**文件：**
- 创建：`backend/app/deps.py`
- 创建：`backend/app/schemas.py`
- 创建：`backend/app/main.py`
- 创建：`backend/app/api/__init__.py`
- 创建：`backend/app/api/health.py`
- 创建：`backend/app/api/devices.py`
- 创建：`backend/tests/conftest.py`
- 创建：`backend/tests/test_api_devices.py`

- [ ] **步骤 1：编写失败的测试**

创建 `backend/tests/test_api_devices.py`：

```python
def test_health_mock(client):
    body = client.get("/api/health").json()
    assert body["ok"] is True
    assert body["device_backend"] == "mock"


def test_list_devices(client):
    body = client.get("/api/devices").json()
    assert body["devices"][0]["serial"] == "MOCK-0001"
    assert body["devices"][0]["state"] == "device"


def test_session_roundtrip(client):
    resp = client.post("/api/session", json={"serial": "MOCK-0001", "fps": 5})
    assert resp.status_code == 200
    body = resp.json()
    assert body["sessionId"].startswith("mock-")
    assert (body["width"], body["height"]) == (1080, 2400)
    assert body["degraded"] is False
    assert client.delete(f"/api/session/{body['sessionId']}").json() == {"ok": True}


def test_session_unknown_device(client):
    resp = client.post("/api/session", json={"serial": "NOPE"})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "DEVICE_NOT_FOUND"
```

- [ ] **步骤 2：运行测试确认失败**

运行：`.venv/bin/python -m pytest tests/test_api_devices.py -q`

预期：FAIL，`ModuleNotFoundError: No module named 'app.main'`。

- [ ] **步骤 3：编写 schemas.py**

创建 `backend/app/schemas.py`：

```python
from __future__ import annotations

from pydantic import BaseModel, Field


class CreateSessionRequest(BaseModel):
    serial: str
    fps: int = Field(default=5, ge=1, le=10)


class TapRequest(BaseModel):
    # 范围不在 pydantic 里校验：越界要返回 OUT_OF_BOUNDS 而不是 422
    sessionId: str
    x: float
    y: float
    pressMs: float = Field(default=80, ge=20, le=600)
    sigma: float = Field(default=6, ge=0, le=40)
    pressStdev: float = Field(default=20, ge=0, le=200)


class SwipeRequest(BaseModel):
    sessionId: str
    x1: float
    y1: float
    x2: float
    y2: float
    durationMs: int = Field(default=300, ge=50, le=3000)


class KeyRequest(BaseModel):
    sessionId: str
    key: str
```

- [ ] **步骤 4：编写 deps.py**

创建 `backend/app/deps.py`：

```python
from __future__ import annotations

from app import config
from app.device.base import DeviceAdapter
from app.device.mock_device import MockDevice

_adapter: DeviceAdapter | None = None


def build_adapter(cfg: config.Settings | None = None) -> DeviceAdapter:
    cfg = cfg or config.settings
    if cfg.device_backend == "mock":
        return MockDevice(jpeg_quality=cfg.jpeg_quality)
    if cfg.device_backend == "adb":
        from app.device.adb import AdbRunner
        from app.device.adb_device import AdbScrcpyDevice

        return AdbScrcpyDevice(
            adb=AdbRunner(cfg.adb_path),
            server_bin=cfg.scrcpy_bin,
            server_jar=cfg.scrcpy_server,
            server_version=cfg.scrcpy_version,
            tcp_port=cfg.scrcpy_tcp_port,
            fps=cfg.mirror_fps,
            bitrate=cfg.scrcpy_bitrate,
            jpeg_quality=cfg.jpeg_quality,
            display_width=cfg.display_width,
            frame_timeout=cfg.frame_timeout,
            allow_fallback=cfg.allow_screencap_fallback,
        )
    raise SystemExit(f"未知 CAPYAUTO_DEVICE_BACKEND={cfg.device_backend}，可选 mock|adb")


def get_adapter() -> DeviceAdapter:
    global _adapter
    if _adapter is None:
        _adapter = build_adapter()
    return _adapter


def reset_adapter() -> None:
    global _adapter
    _adapter = None
```

- [ ] **步骤 5：编写 health 与 devices 路由**

创建 `backend/app/api/__init__.py`（空文件）、`backend/app/api/health.py`：

```python
from fastapi import APIRouter

from app.deps import get_adapter

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
async def health() -> dict:
    return await get_adapter().health()
```

创建 `backend/app/api/devices.py`：

```python
from dataclasses import asdict

from fastapi import APIRouter

from app.deps import get_adapter
from app.schemas import CreateSessionRequest

router = APIRouter(prefix="/api", tags=["devices"])


@router.get("/devices")
async def list_devices() -> dict:
    devices = await get_adapter().list_devices()
    return {"devices": [asdict(device) for device in devices]}


@router.post("/session")
async def create_session(req: CreateSessionRequest) -> dict:
    session = await get_adapter().create_session(req.serial, req.fps)
    return {
        "sessionId": session.id,
        "serial": session.serial,
        "width": session.width,
        "height": session.height,
        "fps": session.fps,
        "degraded": session.degraded,
        "mode": session.mode,
        "sizeMismatch": session.size_mismatch,
    }


@router.delete("/session/{session_id}")
async def close_session(session_id: str) -> dict:
    adapter = get_adapter()
    adapter.get_session(session_id)  # 未知会话抛 SessionNotFound → 404
    await adapter.close_session(session_id)
    return {"ok": True}
```

- [ ] **步骤 6：编写 main.py**

创建 `backend/app/main.py`：

```python
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import config
from app.api import devices, health
from app.errors import ApiError

app = FastAPI(title="CapyAuto Flow Device Bridge", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        f"http://localhost:{config.settings.frontend_port}",
        f"http://127.0.0.1:{config.settings.frontend_port}",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ApiError)
async def handle_api_error(_request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=exc.to_payload())


app.include_router(health.router)
app.include_router(devices.router)
```

- [ ] **步骤 7：编写 conftest.py**

创建 `backend/tests/conftest.py`：

```python
import dataclasses

import pytest
from fastapi.testclient import TestClient

from app import config, deps
from app.main import app


@pytest.fixture(autouse=True)
def mock_backend(monkeypatch):
    cfg = dataclasses.replace(config.settings, device_backend="mock")
    monkeypatch.setattr(config, "settings", cfg)
    deps.reset_adapter()
    yield
    deps.reset_adapter()


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
```

- [ ] **步骤 8：运行测试确认通过**

运行：`.venv/bin/python -m pytest tests/test_api_devices.py -q`

预期：`4 passed`。

- [ ] **步骤 9：手动启动验证**

```bash
cd backend && .venv/bin/python -m app &
sleep 3
curl -s http://127.0.0.1:8084/api/health
curl -s http://127.0.0.1:8084/api/devices
kill %1
```

预期：health 返回 `{"ok":true,"device_backend":"mock",...}`；devices 返回含 `MOCK-0001` 的列表。

- [ ] **步骤 10：Commit**

```bash
git add backend/app/deps.py backend/app/schemas.py backend/app/main.py backend/app/api backend/tests/conftest.py backend/tests/test_api_devices.py
git commit -m "feat: Mock 模式 health/devices/session 接口"
```

---

### 任务 10：WebSocket 镜像与调试页

**文件：**
- 创建：`backend/app/api/mirror.py`
- 创建：`backend/app/static/debug_mirror.html`
- 修改：`backend/app/main.py`（挂载 static 与调试页）
- 创建：`backend/tests/test_ws_mirror.py`

- [ ] **步骤 1：编写失败的测试**

创建 `backend/tests/test_ws_mirror.py`：

```python
import json


def _new_session(client) -> str:
    resp = client.post("/api/session", json={"serial": "MOCK-0001", "fps": 5})
    return resp.json()["sessionId"]


def test_ws_meta_then_jpeg(client):
    session_id = _new_session(client)
    with client.websocket_connect(f"/ws/mirror?sessionId={session_id}") as ws:
        meta = json.loads(ws.receive_text())
        assert meta["type"] == "meta"
        assert meta["width"] == 1080
        assert meta["degraded"] is False
        frame = ws.receive_bytes()
        assert frame[:2] == b"\xff\xd8"
        assert frame[-2:] == b"\xff\xd9"


def test_ws_unknown_session_reports_error(client):
    with client.websocket_connect("/ws/mirror?sessionId=nope") as ws:
        payload = json.loads(ws.receive_text())
        assert payload["type"] == "error"
        assert payload["code"] == "SESSION_NOT_FOUND"
```

- [ ] **步骤 2：运行测试确认失败**

运行：`.venv/bin/python -m pytest tests/test_ws_mirror.py -q`

预期：FAIL，连接被拒绝或 404（路由不存在）。

- [ ] **步骤 3：编写 mirror 路由**

创建 `backend/app/api/mirror.py`：

```python
from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.deps import get_adapter
from app.errors import ApiError, MirrorLost

router = APIRouter(tags=["mirror"])

META_EVERY = 5


@router.websocket("/ws/mirror")
async def mirror(ws: WebSocket, sessionId: str = Query(...)) -> None:
    adapter = get_adapter()
    try:
        session = adapter.get_session(sessionId)
    except ApiError as exc:
        await ws.accept()
        await ws.send_text(
            json.dumps({"type": "error", "code": exc.code, "message": exc.message}, ensure_ascii=False)
        )
        await ws.close(code=4404)
        return

    await ws.accept()

    async def send_meta(seq: int) -> None:
        await ws.send_text(
            json.dumps(
                {
                    "type": "meta",
                    "seq": seq,
                    "ts": time.time(),
                    "width": session.width,
                    "height": session.height,
                    "fps": session.fps,
                    "degraded": session.degraded,
                    "mode": session.mode,
                },
                ensure_ascii=False,
            )
        )

    async def pump_client() -> None:
        try:
            while True:
                message = await ws.receive_text()
                if json.loads(message).get("type") == "ping":
                    await ws.send_text(json.dumps({"type": "pong", "ts": time.time()}))
        except WebSocketDisconnect:
            return

    await send_meta(0)
    pump = asyncio.create_task(pump_client())
    sent = 0
    try:
        async for frame in adapter.frames(sessionId):
            await ws.send_bytes(frame.jpeg)
            sent += 1
            if sent % META_EVERY == 0:
                await send_meta(frame.seq)
    except MirrorLost as exc:
        await ws.send_text(
            json.dumps({"type": "error", "code": "MIRROR_LOST", "message": exc.message}, ensure_ascii=False)
        )
    except WebSocketDisconnect:
        pass
    finally:
        pump.cancel()
        try:
            await ws.close()
        except RuntimeError:
            pass
```

- [ ] **步骤 4：把路由挂到 main.py**

把 [main.py](file:///Users/fikard/self_project/capyauto-flow/backend/app/main.py) 的 import 与 include 段改为：

```python
from app.api import devices, health, mirror

...
app.include_router(health.router)
app.include_router(devices.router)
app.include_router(mirror.router)
```

- [ ] **步骤 5：运行测试确认通过**

运行：`.venv/bin/python -m pytest tests/test_ws_mirror.py -q`

预期：`2 passed`。

- [ ] **步骤 6：编写调试页**

创建 `backend/app/static/debug_mirror.html`：

```html
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>CapyAuto 镜像调试</title>
  <style>
    body { margin: 0; background: #0f141a; color: #cfe3dd; font: 13px/1.5 ui-monospace, monospace; display: flex; gap: 16px; padding: 16px; }
    #stage { position: relative; height: 90vh; }
    #screen { height: 100%; display: block; background: #000; }
    #overlay { position: absolute; inset: 0; cursor: crosshair; }
    #side { min-width: 260px; }
    .dot { position: absolute; width: 10px; height: 10px; border-radius: 50%; transform: translate(-50%, -50%); }
    .intent { border: 1px solid #6ee7b7; }
    .real { background: #f87171; }
    input { width: 70px; background: #1b2530; color: #cfe3dd; border: 1px solid #2f3d4a; }
    button { background: #1b2530; color: #cfe3dd; border: 1px solid #2f3d4a; padding: 4px 10px; cursor: pointer; }
    pre { white-space: pre-wrap; }
  </style>
</head>
<body>
  <div id="stage">
    <img id="screen" alt="mirror" />
    <div id="overlay"></div>
  </div>
  <div id="side">
    <p>会话：<input id="sid" value="" /></p>
    <p><button id="connect">连接</button> <button id="disconnect">断开</button></p>
    <p>sigma <input id="sigma" value="6" /> press <input id="press" value="80" /></p>
    <pre id="log"></pre>
  </div>
  <script>
    const logEl = document.getElementById("log");
    const img = document.getElementById("screen");
    const overlay = document.getElementById("overlay");
    const sidEl = document.getElementById("sid");
    const params = new URLSearchParams(location.search);
    if (params.get("sessionId")) sidEl.value = params.get("sessionId");
    let ws = null;

    function log(line) {
      logEl.textContent = `${new Date().toLocaleTimeString()} ${line}\n` + logEl.textContent;
    }

    function connect() {
      if (ws) return;
      ws = new WebSocket(`ws://${location.host}/ws/mirror?sessionId=${encodeURIComponent(sidEl.value)}`);
      ws.binaryType = "arraybuffer";
      ws.onmessage = (event) => {
        if (typeof event.data === "string") {
          const msg = JSON.parse(event.data);
          if (msg.type === "meta") log(`meta ${msg.width}x${msg.height} fps=${msg.fps} degraded=${msg.degraded}`);
          else log(`error ${msg.code} ${msg.message ?? ""}`);
          return;
        }
        const url = URL.createObjectURL(new Blob([event.data], { type: "image/jpeg" }));
        img.onload = () => URL.revokeObjectURL(url);
        img.src = url;
        fitStage();
      };
      ws.onclose = () => log("ws closed");
      log(`connecting ${sidEl.value}`);
    }

    function disconnect() {
      if (ws) ws.close();
      ws = null;
    }

    function fitStage() {
      document.getElementById("stage").style.width = `${img.clientWidth}px`;
    }

    overlay.addEventListener("click", async (event) => {
      if (!ws) return;
      const rect = img.getBoundingClientRect();
      const x = (event.clientX - rect.left) / rect.width;
      const y = (event.clientY - rect.top) / rect.height;
      const body = {
        sessionId: sidEl.value,
        x, y,
        sigma: Number(document.getElementById("sigma").value),
        pressMs: Number(document.getElementById("press").value),
        pressStdev: 0,
      };
      const resp = await fetch("/api/control/tap", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await resp.json();
      log(JSON.stringify(data));
      if (data.realX === undefined) return;
      mark(rect.width * x, rect.height * y, "intent");
      mark(rect.width * data.realX / data.deviceWidth, rect.height * data.realY / data.deviceHeight, "real");
    });

    function mark(px, py, cls) {
      const dot = document.createElement("div");
      dot.className = `dot ${cls}`;
      dot.style.left = `${px}px`;
      dot.style.top = `${py}px`;
      overlay.appendChild(dot);
      setTimeout(() => dot.remove(), 1500);
    }

    document.getElementById("connect").onclick = connect;
    document.getElementById("disconnect").onclick = disconnect;
    window.addEventListener("resize", fitStage);
  </script>
</body>
</html>
```

- [ ] **步骤 7：在 main.py 挂载静态资源**

在 [main.py](file:///Users/fikard/self_project/capyauto-flow/backend/app/main.py) 顶部 import 区加入：

```python
from pathlib import Path

from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
```

在文件末尾追加：

```python
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/debug/mirror", include_in_schema=False)
async def debug_mirror() -> FileResponse:
    return FileResponse(STATIC_DIR / "debug_mirror.html")
```

- [ ] **步骤 8：验证调试页可访问**

```bash
cd backend && .venv/bin/python -m app &
sleep 3
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8084/debug/mirror
kill %1
```

预期：输出 `200`。

- [ ] **步骤 9：Commit**

```bash
git add backend/app/api/mirror.py backend/app/static backend/app/main.py backend/tests/test_ws_mirror.py
git commit -m "feat: WS 镜像推送与浏览器调试页"
```

---
### 任务 11：AdbRunner（子进程封装与解析）

**文件：**
- 创建：`backend/app/device/adb.py`
- 创建：`backend/tests/test_adb.py`

- [ ] **步骤 1：编写失败的测试**

创建 `backend/tests/test_adb.py`：

```python
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
```

- [ ] **步骤 2：运行测试确认失败**

运行：`.venv/bin/python -m pytest tests/test_adb.py -q`

预期：FAIL，`ModuleNotFoundError: No module named 'app.device.adb'`。

- [ ] **步骤 3：编写实现**

创建 `backend/app/device/adb.py`：

```python
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

from app.device.base import DeviceInfo
from app.errors import AdbError, AdbNotFound, AdbTimeout

ExecFn = Callable[[list[str], float], tuple[int, bytes, bytes]]


def _subprocess_exec(argv: list[str], timeout: float) -> tuple[int, bytes, bytes]:
    proc = subprocess.run(argv, capture_output=True, timeout=timeout)
    return proc.returncode, proc.stdout, proc.stderr


def parse_devices(output: str) -> list[DeviceInfo]:
    devices: list[DeviceInfo] = []
    for raw in output.splitlines():
        line = raw.strip()
        if not line or line.startswith("List of devices") or line.startswith("*"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        extra: dict[str, str] = {}
        for token in parts[2:]:
            if ":" in token:
                key, value = token.split(":", 1)
                extra.setdefault(key, value)
        devices.append(
            DeviceInfo(
                serial=parts[0],
                state=parts[1],
                model=extra.get("model"),
                transport_id=extra.get("transport_id"),
            )
        )
    return devices


def parse_wm_size(output: str) -> tuple[str, int | None, int | None]:
    override: str | None = None
    physical: str | None = None
    for raw in output.splitlines():
        line = raw.strip()
        if line.startswith("Override size:"):
            override = line.split(":", 1)[1].strip()
        elif line.startswith("Physical size:"):
            physical = line.split(":", 1)[1].strip()
    chosen = override or physical
    if not chosen or "x" not in chosen:
        return output.strip(), None, None
    width_text, height_text = chosen.split("x", 1)
    try:
        return output.strip(), int(width_text), int(height_text)
    except ValueError:
        return output.strip(), None, None


class AdbRunner:
    def __init__(self, adb_path: str = "adb", default_timeout: float = 10.0, exec_fn: ExecFn | None = None) -> None:
        self.adb_path = adb_path
        self.default_timeout = default_timeout
        self._exec_fn = exec_fn or _subprocess_exec

    def run(self, *args, serial: str | None = None, timeout: float | None = None, binary: bool = False):
        argv = [self.adb_path]
        if serial:
            argv += ["-s", serial]
        argv += [str(arg) for arg in args]
        effective_timeout = timeout or self.default_timeout
        try:
            code, out, err = self._exec_fn(argv, effective_timeout)
        except FileNotFoundError as exc:
            raise AdbNotFound("未找到 adb，请先执行 brew install scrcpy") from exc
        except subprocess.TimeoutExpired as exc:
            raise AdbTimeout(f"adb 超时（{effective_timeout}s）: {' '.join(argv)}") from exc
        if code != 0:
            raise AdbError(
                f"adb 命令失败（{code}）: {' '.join(argv)}",
                detail={"stderr": err.decode("utf-8", "replace")[:500]},
            )
        return out if binary else out.decode("utf-8", "replace").strip()

    def version(self) -> str:
        lines = str(self.run("version")).splitlines()
        return lines[0] if lines else "adb"

    def devices(self) -> list[DeviceInfo]:
        return parse_devices(str(self.run("devices", "-l")))

    def getprop(self, serial: str, prop: str) -> str:
        return str(self.run("shell", "getprop", prop, serial=serial))

    def wm_size(self, serial: str) -> tuple[str, int | None, int | None]:
        return parse_wm_size(str(self.run("shell", "wm", "size", serial=serial)))

    def push(self, serial: str, local: Path, remote: str) -> None:
        self.run("push", str(local), remote, serial=serial, timeout=60)

    def forward(self, serial: str, local_port: int, remote_spec: str) -> None:
        self.run("forward", f"tcp:{local_port}", remote_spec, serial=serial)

    def forward_remove(self, serial: str, local_port: int) -> None:
        try:
            self.run("forward", "--remove", f"tcp:{local_port}", serial=serial)
        except AdbError:
            pass

    def exec_out(self, serial: str, *args) -> bytes:
        return self.run("exec-out", *args, serial=serial, binary=True, timeout=20)

    def popen_shell(self, serial: str, command: str) -> subprocess.Popen:
        try:
            return subprocess.Popen(
                [self.adb_path, "-s", serial, "shell", command],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise AdbNotFound("未找到 adb，请先执行 brew install scrcpy") from exc
```

- [ ] **步骤 4：运行测试确认通过**

运行：`.venv/bin/python -m pytest tests/test_adb.py -q`

预期：`8 passed`。

- [ ] **步骤 5：Commit**

```bash
git add backend/app/device/adb.py backend/tests/test_adb.py
git commit -m "feat: AdbRunner 子进程封装与 devices/wm size 解析"
```

---

### 任务 12：scrcpy 线格式（meta / 包头 / 触摸 / 按键）

先把协议编码解码做成纯函数并用字节断言锁死，插槽逻辑才敢写。

**文件：**
- 创建：`backend/app/device/scrcpy_session.py`（本任务只放线格式与按键映射）
- 修改：`backend/app/device/base.py`（加入 `KEYCODES` 与 `keycode_for`）
- 修改：`backend/app/device/mock_device.py`（改用 `keycode_for`）
- 创建：`backend/tests/test_scrcpy_wire.py`

- [ ] **步骤 1：编写失败的测试**

创建 `backend/tests/test_scrcpy_wire.py`：

```python
import struct

import pytest

from app.device.base import keycode_for
from app.device.scrcpy_session import (
    ACTION_DOWN,
    ACTION_UP,
    build_key,
    build_touch,
    parse_device_meta,
    parse_packet_header,
)
from app.errors import ScrcpyUnavailable, UnknownKey


def _meta_blob(name: str, codec_id: int, width: int, height: int) -> bytes:
    raw = name.encode("utf-8")
    assert len(raw) <= 64
    return raw.ljust(64, b"\x00") + struct.pack(">III", codec_id, width, height)


def test_parse_device_meta_h264():
    meta = parse_device_meta(_meta_blob("SM-G9730", 0x68323634, 1080, 2340))
    assert meta.device_name == "SM-G9730"
    assert meta.codec == "h264"
    assert (meta.width, meta.height) == (1080, 2340)


def test_parse_device_meta_rejects_unknown_codec():
    with pytest.raises(ScrcpyUnavailable):
        parse_device_meta(_meta_blob("x", 0x12345678, 1080, 2340))


def test_parse_packet_header_flags():
    header = struct.pack(">QI", (1 << 63) | (1 << 62) | 4242, 512)
    pts, is_config, is_key, size = parse_packet_header(header)
    assert (pts, is_config, is_key, size) == (4242, True, True, 512)


def test_build_touch_layout():
    msg = build_touch(ACTION_DOWN, 0, 540, 1200, 1080, 2400)
    assert len(msg) == 32
    msg_type, action, pointer, x, y, width, height, pressure, action_button, buttons = struct.unpack(
        ">BBQiiHHHII", msg
    )
    assert msg_type == 2
    assert action == ACTION_DOWN
    assert (pointer, x, y, width, height) == (0, 540, 1200, 1080, 2400)
    assert pressure == 0xFFFF
    assert (action_button, buttons) == (0, 0)
    assert struct.unpack(">BBQiiHHHII", build_touch(ACTION_UP, 0, 540, 1200, 1080, 2400))[7] == 0


def test_build_key_layout():
    msg = build_key(0, 4)
    assert len(msg) == 14
    assert struct.unpack(">BBIII", msg) == (0, 0, 4, 0, 0)


def test_keycode_mapping():
    assert keycode_for("back") == 4
    assert keycode_for("home") == 3
    assert keycode_for("app_switch") == 187
    with pytest.raises(UnknownKey):
        keycode_for("nope")
```

- [ ] **步骤 2：运行测试确认失败**

运行：`.venv/bin/python -m pytest tests/test_scrcpy_wire.py -q`

预期：FAIL，`ImportError: cannot import name 'keycode_for'`。

- [ ] **步骤 3：在 base.py 加入按键映射**

在 [base.py](file:///Users/fikard/self_project/capyauto-flow/backend/app/device/base.py) 末尾追加（并把顶部 import 改为 `from app.errors import UnknownKey`）：

```python
KEYCODES: dict[str, int] = {
    "back": 4,
    "home": 3,
    "app_switch": 187,
    "power": 26,
    "volume_up": 24,
    "volume_down": 25,
}


def keycode_for(name: str) -> int:
    try:
        return KEYCODES[name]
    except KeyError:
        raise UnknownKey(f"未知按键: {name}，可选 {sorted(KEYCODES)}") from None
```

- [ ] **步骤 4：让 MockDevice 复用该映射**

把 [mock_device.py](file:///Users/fikard/self_project/capyauto-flow/backend/app/device/mock_device.py) 中的：

```python
KEY_ALIASES = {"back", "home", "app_switch", "power", "volume_up", "volume_down"}
```

删除，并把 `key` 方法改为：

```python
    async def key(self, session_id: str, key: str) -> None:
        self.get_session(session_id)
        keycode_for(key)
        self._keys.append(key)
```

同时把该文件的 import 行改为：

```python
from app.device.base import DeviceAdapter, DeviceInfo, Frame, MirrorSession, SwipeResult, TapResult, keycode_for
```

- [ ] **步骤 5：编写线格式实现**

创建 `backend/app/device/scrcpy_session.py`：

```python
from __future__ import annotations

import socket
import struct
from dataclasses import dataclass

from app.errors import ScrcpyUnavailable

DEVICE_NAME_LEN = 64
META_LEN = 76
PACKET_HEADER_LEN = 12
MAX_PACKET_SIZE = 8 * 1024 * 1024

CODEC_IDS = {0x68323634: "h264", 0x68323635: "h265", 0x00617631: "av1"}

ACTION_DOWN, ACTION_UP, ACTION_MOVE = 0, 1, 2
MSG_INJECT_KEYCODE = 0
MSG_INJECT_TOUCH_EVENT = 2


def recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionError(f"socket 提前关闭，仍缺 {remaining} 字节")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


@dataclass(frozen=True)
class VideoMeta:
    device_name: str
    codec: str
    width: int
    height: int


def parse_device_meta(blob: bytes) -> VideoMeta:
    """scrcpy >= 2.0 视频 socket 头：64 字节设备名 + 4 字节 codec + 4+4 宽高。"""
    if len(blob) != META_LEN:
        raise ScrcpyUnavailable(f"视频头长度应为 {META_LEN}，实际 {len(blob)}")
    name = blob[:DEVICE_NAME_LEN].split(b"\x00", 1)[0].decode("utf-8", "replace")
    codec_id, width, height = struct.unpack(">III", blob[DEVICE_NAME_LEN:])
    if codec_id not in CODEC_IDS:
        raise ScrcpyUnavailable(
            f"未知 codec id 0x{codec_id:08x}，需要 scrcpy >= 2.0 且 video_codec=h264"
        )
    if width <= 0 or height <= 0:
        raise ScrcpyUnavailable(f"视频尺寸非法: {width}x{height}")
    return VideoMeta(device_name=name, codec=CODEC_IDS[codec_id], width=width, height=height)


def parse_packet_header(header: bytes) -> tuple[int, bool, bool, int]:
    """12 字节包头：8 字节 pts+flags（bit63=配置帧，bit62=关键帧）+ 4 字节长度。"""
    if len(header) != PACKET_HEADER_LEN:
        raise ValueError(f"包头长度应为 {PACKET_HEADER_LEN}，实际 {len(header)}")
    pts_flags, size = struct.unpack(">QI", header)
    return pts_flags & 0x3FFF_FFFF_FFFF_FFFF, bool(pts_flags >> 63), bool((pts_flags >> 62) & 1), size


def build_touch(
    action: int,
    pointer_id: int,
    x: int,
    y: int,
    width: int,
    height: int,
    pressure: int = 0xFFFF,
    buttons: int = 0,
) -> bytes:
    pressure = 0 if action == ACTION_UP else pressure
    return struct.pack(
        ">BBQiiHHHII", MSG_INJECT_TOUCH_EVENT, action, pointer_id, x, y, width, height, pressure, 0, buttons
    )


def build_key(action: int, keycode: int, repeat: int = 0, meta_state: int = 0) -> bytes:
    return struct.pack(">BBIII", MSG_INJECT_KEYCODE, action, keycode, repeat, meta_state)
```

- [ ] **步骤 6：运行测试确认通过**

运行：`.venv/bin/python -m pytest tests/test_scrcpy_wire.py tests/test_mock_device.py -q`

预期：`8 passed`。

- [ ] **步骤 7：Commit**

```bash
git add backend/app/device/scrcpy_session.py backend/app/device/base.py backend/app/device/mock_device.py backend/tests/test_scrcpy_wire.py
git commit -m "feat: scrcpy 线格式编解码与按键映射"
```

---

### 任务 13：ScrcpySession 视频通道与重连

> **实测修订（审查后落地版本，以此为准；下方代码块仅保留初版草案）**
>
> 1. 常数：新增 `VIDEO_READ_TIMEOUT = 20.0`（静态画面约 10s 才出关键帧，读超时必须大于它并留余量）、`META_READ_TIMEOUT = 5.0`、`CONTROL_READ_TIMEOUT = 5.0`。`_connect(deadline_s, read_timeout)` 握手期用 5s，读到 meta 后 video 提升为 20s。
> 2. 重连计数：`_store` 自增 `_decoded_count`；`_decode_loop` 每轮记录 `decoded_before`，若本轮解出过帧则 `attempt = 0` 再计数，实现真正的「连续 3 次」；放弃分支 `log.exception` + `_close_transport()` + return；`finally` 置 `_stream_alive = False`。
> 3. 只读状态：新增 `stream_alive` 属性（`start()` 成功后 True，线程退出/放弃/stop 后 False），供任务 15 判定 `degraded`；健康判定应为 `stream_alive and control_available`。
> 4. 建连自清理：`_open_transport` 入口检查 `_stop`，主体包 `try/except BaseException: self._close_transport(); raise`，保证 forward 已建、server 已 spawn 后任何失败（含 stop 介入、10s 超时）都回收 server/forward/socket；`_connect` 与重试循环都随 `_stop` 退出。
> 5. 注入互斥：新增独立 `_inject_lock`（与帧锁 `_lock` 分离，无嵌套，不会阻塞解码）；`tap/swipe/key` 整段持锁；`swipe` 用 `release flag + finally` 保证中途失败补发 `ACTION_UP`；`_send` 写失败时关闭并置空 `_control`；所有 `assert` 改为显式 `ScrcpyUnavailable`/`InjectionFailed`。
> 6. 测试：`tests/test_scrcpy_session.py` 最终 21 个用例（socketpair 注入字节/顺序/并发串行化/失败补 UP、PyAV 本地 H.264 按线格式解出 JPEG、重连放弃与归零、stop 中断、建连失败清理），全量 87 passed。

**文件：**
- 修改：`backend/app/device/scrcpy_session.py`（追加会话类）
- 创建：`backend/tests/test_scrcpy_session.py`

- [ ] **步骤 1：编写测试（用本地 fake server 验证首帧与断流重连分支）**

创建 `backend/tests/test_scrcpy_session.py`：

```python
import socket
import struct

import pytest

from app.device.scrcpy_session import META_LEN, PACKET_HEADER_LEN

# 说明：真正的 H.264 解码与注入由真机验收覆盖（任务 15、16）。
# 这里只验证不依赖 ffmpeg 的边界：meta 读取超时、包长度异常、control 消息写入。
from app.device.scrcpy_session import recv_exact
from app.errors import ScrcpyUnavailable


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
        from app.device.scrcpy_session import parse_device_meta

        parse_device_meta(b"\x00" * (META_LEN - 1))


def test_packet_header_size_guard():
    from app.device.scrcpy_session import parse_packet_header

    _, _, _, size = parse_packet_header(struct.pack(">QI", 0, 1024))
    assert size == 1024
    assert PACKET_HEADER_LEN == 12
```

- [ ] **步骤 2：运行测试确认失败**

运行：`.venv/bin/python -m pytest tests/test_scrcpy_session.py -q`

预期：部分通过、`ImportError: cannot import name 'META_LEN'`（若任务 12 已建文件则只剩 import 正常但 `recv_exact` 缺失的用例失败）。任一条 FAIL 都算通过此步。

- [ ] **步骤 3：追加 ScrcpySession 实现**

在 `backend/app/device/scrcpy_session.py` 顶部补充 import 并追加类（文件其余内容保持不变）：

```python
import io
import logging
import random
import subprocess
import threading
import time
from pathlib import Path

import av
from PIL import Image

from app.device.adb import AdbRunner
from app.device.base import Frame
from app.errors import InjectionFailed

log = logging.getLogger("capyauto.scrcpy")


class ScrcpySession:
    """单个设备的 scrcpy 会话：video socket 解码为 JPEG，control socket 注入事件。"""

    def __init__(
        self,
        session_id: str,
        serial: str,
        adb: AdbRunner,
        server_jar: Path,
        server_version: str,
        tcp_port: int,
        fps: int,
        bitrate: int,
        jpeg_quality: int,
        display_width: int,
    ) -> None:
        self.session_id = session_id
        self.serial = serial
        self.meta: VideoMeta | None = None
        self._adb = adb
        self._server_jar = server_jar
        self._server_version = server_version
        self._scid = ""
        self._tcp_port = tcp_port
        self._fps = max(1, fps)
        self._bitrate = bitrate
        self._jpeg_quality = jpeg_quality
        self._display_width = display_width
        self._lock = threading.Lock()
        self._frame: Frame | None = None
        self._seq = 0
        self._stop = threading.Event()
        self._video: socket.socket | None = None
        self._control: socket.socket | None = None
        self._server: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None

    @property
    def control_available(self) -> bool:
        return self._control is not None

    def start(self) -> VideoMeta:
        self._open_transport()
        self._thread = threading.Thread(target=self._decode_loop, name=f"scrcpy-{self.session_id}", daemon=True)
        self._thread.start()
        assert self.meta is not None
        return self.meta

    def _open_transport(self) -> None:
        remote = "/data/local/tmp/scrcpy-server.jar"
        # scrcpy 3.x 的抽象 socket 名带 scid，且 scid 按 16 进制 int32 解析
        self._scid = f"{random.randrange(1, 0x7FFF_FFFF):08x}"
        self._adb.forward(self.serial, self._tcp_port, f"localabstract:scrcpy_{self._scid}")
        self._adb.push(self.serial, self._server_jar, remote)
        command = (
            f"CLASSPATH={remote} app_process / com.genymobile.scrcpy.Server {self._server_version} "
            f"log_level=info tunnel_forward=true audio=false video=true control=true "
            f"scid={self._scid} send_dummy_byte=false "
            f"max_fps={self._fps} video_bit_rate={self._bitrate} max_size=0 cleanup=true"
        )
        self._server = self._adb.popen_shell(self.serial, command)
        # server 必须等 video 与 control 两个 socket 都 accept 后才发 76 字节元数据；
        # adb forward 先于 server 监听时会立刻 EOF，所以整体重试。
        deadline = time.time() + 10.0
        last: Exception | None = None
        while time.time() < deadline:
            try:
                self._video = self._connect(deadline_s=1.0)
                self._control = self._connect(deadline_s=1.0)
                self.meta = parse_device_meta(recv_exact(self._video, META_LEN))
                return
            except (OSError, ConnectionError, ScrcpyUnavailable) as exc:
                last = exc
                for sock in (self._control, self._video):
                    if sock is not None:
                        try:
                            sock.close()
                        except OSError:
                            pass
                self._control = None
                self._video = None
                time.sleep(0.2)
        raise ScrcpyUnavailable(f"scrcpy 会话建立失败: {last}")

    def _connect(self, deadline_s: float = 8.0) -> socket.socket:
        end = time.time() + deadline_s
        last: Exception | None = None
        while time.time() < end:
            try:
                sock = socket.create_connection(("127.0.0.1", self._tcp_port), timeout=3.0)
                sock.settimeout(5.0)
                return sock
            except OSError as exc:
                last = exc
                time.sleep(0.1)
        raise ScrcpyUnavailable(f"连接 scrcpy 端口 {self._tcp_port} 失败: {last}")

    def latest(self) -> Frame | None:
        with self._lock:
            return self._frame

    def _decode_loop(self) -> None:
        attempt = 0
        while not self._stop.is_set():
            try:
                self._decode_once()
                return
            except Exception as exc:  # noqa: BLE001 - 任何异常都进入重连
                if self._stop.is_set():
                    return
                attempt += 1
                if attempt > 3:
                    log.error("scrcpy 连续 3 次重连失败: %s", exc)
                    return
                log.warning("scrcpy 流中断（%s），第 %d 次重连", exc, attempt)
                time.sleep(0.5 * 2 ** (attempt - 1))
                try:
                    self._close_transport()
                    self._open_transport()
                except Exception as restart_exc:  # noqa: BLE001
                    log.error("重启 scrcpy 失败: %s", restart_exc)

    def _decode_once(self) -> None:
        assert self._video is not None and self.meta is not None
        ctx = av.CodecContext.create(self.meta.codec, "r")
        last_emit = 0.0
        while not self._stop.is_set():
            _pts_flags, is_config, _is_key, size = parse_packet_header(
                recv_exact(self._video, PACKET_HEADER_LEN)
            )
            if size <= 0 or size > MAX_PACKET_SIZE:
                raise ConnectionError(f"帧长度异常: {size}")
            payload = recv_exact(self._video, size)
            if is_config:
                # scrcpy 把 SPS/PPS 单独放在 config 包里，必须喂给解码器否则关键帧无法解出
                for packet in ctx.parse(payload):
                    ctx.decode(packet)
                continue
            for packet in ctx.parse(payload):
                for decoded in ctx.decode(packet):
                    now = time.monotonic()
                    if now - last_emit < 1.0 / self._fps:
                        continue
                    last_emit = now
                    self._store(decoded)

    def _store(self, decoded) -> None:
        image = decoded.to_image().convert("RGB")
        if image.width > self._display_width:
            ratio = self._display_width / image.width
            image = image.resize((self._display_width, max(1, int(image.height * ratio))), Image.BILINEAR)
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", quality=self._jpeg_quality)
        with self._lock:
            self._seq += 1
            self._frame = Frame(
                seq=self._seq, jpeg=buffer.getvalue(), width=image.width, height=image.height, ts=time.time()
            )

    def tap(self, x: int, y: int, press_ms: int) -> None:
        assert self.meta is not None
        self._send(build_touch(ACTION_DOWN, 0, x, y, self.meta.width, self.meta.height))
        time.sleep(press_ms / 1000)
        self._send(build_touch(ACTION_UP, 0, x, y, self.meta.width, self.meta.height))

    def swipe(self, points: list[tuple[int, int]], duration_ms: int) -> None:
        assert self.meta is not None
        if not points:
            raise InjectionFailed("滑轨为空")
        step = (duration_ms / 1000) / max(len(points) - 1, 1)
        self._send(build_touch(ACTION_DOWN, 0, points[0][0], points[0][1], self.meta.width, self.meta.height))
        for px, py in points[1:-1]:
            time.sleep(step)
            self._send(build_touch(ACTION_MOVE, 0, px, py, self.meta.width, self.meta.height))
        time.sleep(step)
        last_x, last_y = points[-1]
        self._send(build_touch(ACTION_UP, 0, last_x, last_y, self.meta.width, self.meta.height))

    def key(self, keycode: int) -> None:
        self._send(build_key(0, keycode))
        time.sleep(0.02)
        self._send(build_key(1, keycode))

    def _send(self, payload: bytes) -> None:
        if self._control is None:
            raise InjectionFailed("control socket 不可用")
        try:
            self._control.sendall(payload)
        except OSError as exc:
            raise InjectionFailed(f"control socket 写入失败: {exc}") from exc

    def _close_transport(self) -> None:
        for sock in (self._control, self._video):
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
        self._control = None
        self._video = None
        if self._server is not None:
            self._server.terminate()
            try:
                self._server.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._server.kill()
            self._server = None
        self._adb.forward_remove(self.serial, self._tcp_port)

    def stop(self) -> None:
        self._stop.set()
        self._close_transport()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=3)
```

- [ ] **步骤 4：运行测试确认通过**

运行：`.venv/bin/python -m pytest tests/test_scrcpy_session.py -q`

预期：`21 passed`（初版只有 4 个复用任务 12 的用例；审查要求补足注入序列、PyAV 线格式首帧、重连归零/放弃、stop 中断与建连失败清理，见节首「实测修订」）。全量应为 `87 passed`。

- [ ] **步骤 5：Commit**

```bash
git add backend/app/device/scrcpy_session.py backend/tests/test_scrcpy_session.py
git commit -m "feat: ScrcpySession 视频解码线程、control 注入与重连"
```

实际落地为三个提交（审查修复同轮）：
`f78a79b feat: ScrcpySession 视频解码线程、control 注入与重连`、
`84a75b3 fix: 修复 ScrcpySession 重连计数、读超时与注入竞态`、
`ae71ce7 fix: ScrcpySession 建连失败自清理 server 与 forward`。

---
### 任务 14：screencap 降级通道

**文件：**
- 创建：`backend/app/device/screen.py`
- 创建：`backend/tests/test_screen.py`

- [ ] **步骤 1：编写失败的测试**

创建 `backend/tests/test_screen.py`：

```python
import io
import time

from PIL import Image

from app.device.screen import ScreencapPoller


class FakeAdb:
    def __init__(self) -> None:
        self.calls = 0

    def exec_out(self, serial: str, *args) -> bytes:
        self.calls += 1
        image = Image.new("RGB", (108, 240), (10, 20, 30))
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        return buffer.getvalue()


def test_poller_produces_jpeg_frames():
    adb = FakeAdb()
    poller = ScreencapPoller(adb, "SERIAL", 108, 240, fps=10, jpeg_quality=70, display_width=720)
    poller.start()
    time.sleep(0.35)
    poller.stop()

    frame = poller.latest()
    assert frame is not None
    assert frame.jpeg[:2] == b"\xff\xd8"
    assert frame.width == 108
    assert adb.calls >= 2
```

- [ ] **步骤 2：运行测试确认失败**

运行：`.venv/bin/python -m pytest tests/test_screen.py -q`

预期：FAIL，`ModuleNotFoundError: No module named 'app.device.screen'`。

- [ ] **步骤 3：编写实现**

创建 `backend/app/device/screen.py`：

```python
from __future__ import annotations

import io
import logging
import threading
import time

from PIL import Image

from app.device.adb import AdbRunner
from app.device.base import Frame

log = logging.getLogger("capyauto.screencap")


class ScreencapPoller:
    """scrcpy 不可用时的降级通道：按目标帧率轮询 screencap -p，再编码成 JPEG。"""

    def __init__(
        self,
        adb: AdbRunner,
        serial: str,
        width: int,
        height: int,
        fps: int,
        jpeg_quality: int,
        display_width: int,
    ) -> None:
        self._adb = adb
        self._serial = serial
        self.width = width
        self.height = height
        self._fps = max(1, fps)
        self._jpeg_quality = jpeg_quality
        self._display_width = display_width
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._frame: Frame | None = None
        self._seq = 0
        self._thread: threading.Thread | None = None
        self.last_error: str | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name=f"screencap-{self._serial}", daemon=True)
        self._thread.start()

    def latest(self) -> Frame | None:
        with self._lock:
            return self._frame

    def _loop(self) -> None:
        interval = 1.0 / self._fps
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                png = self._adb.exec_out(self._serial, "screencap", "-p")
                image = Image.open(io.BytesIO(png)).convert("RGB")
                self.width, self.height = image.size
                if image.width > self._display_width:
                    ratio = self._display_width / image.width
                    image = image.resize(
                        (self._display_width, max(1, int(image.height * ratio))), Image.BILINEAR
                    )
                buffer = io.BytesIO()
                image.save(buffer, "JPEG", quality=self._jpeg_quality)
                with self._lock:
                    self._seq += 1
                    self._frame = Frame(
                        seq=self._seq,
                        jpeg=buffer.getvalue(),
                        width=image.width,
                        height=image.height,
                        ts=time.time(),
                    )
                self.last_error = None
            except Exception as exc:  # noqa: BLE001 - 降级通道不因单次失败退出
                self.last_error = str(exc)
                log.warning("screencap 失败: %s", exc)
            elapsed = time.monotonic() - started
            time.sleep(max(0.0, interval - elapsed))

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=3)
```

- [ ] **步骤 4：运行测试确认通过**

运行：`.venv/bin/python -m pytest tests/test_screen.py -q`

预期：`1 passed`。

- [ ] **步骤 5：Commit**

```bash
git add backend/app/device/screen.py backend/tests/test_screen.py
git commit -m "feat: screencap 轮询降级通道"
```

---

### 任务 15：AdbScrcpyDevice 装配与真机镜像验证（P2）

**文件：**
- 创建：`backend/app/device/adb_device.py`
- 创建：`backend/tests/test_adb_device.py`

- [ ] **步骤 1：编写失败的测试**

创建 `backend/tests/test_adb_device.py`：

```python
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
```

- [ ] **步骤 2：运行测试确认失败**

运行：`.venv/bin/python -m pytest tests/test_adb_device.py -q`

预期：FAIL，`ModuleNotFoundError: No module named 'app.device.adb_device'`。

- [ ] **步骤 3：编写实现**

创建 `backend/app/device/adb_device.py`：

```python
from __future__ import annotations

import asyncio
import dataclasses
import logging
import re
import subprocess
import time
from pathlib import Path

from app.core.dither import bezier_points, gaussian_click
from app.core.geometry import normalize_to_device
from app.device.adb import AdbRunner
from app.device.base import (
    DeviceAdapter,
    DeviceInfo,
    Frame,
    MirrorSession,
    SwipeResult,
    TapResult,
    keycode_for,
)
from app.device.scrcpy_session import ScrcpySession
from app.device.screen import ScreencapPoller
from app.errors import (
    ApiError,
    DeviceNotFound,
    DeviceUnauthorized,
    MirrorLost,
    ScrcpyUnavailable,
    SessionNotFound,
)

log = logging.getLogger("capyauto.adb")


def detect_scrcpy_version(scrcpy_bin: str) -> str:
    proc = subprocess.run([scrcpy_bin, "--version"], capture_output=True, timeout=15)
    if proc.returncode != 0:
        raise ScrcpyUnavailable(f"{scrcpy_bin} --version 失败")
    match = re.search(r"scrcpy\s+(\d+\.\d+(?:\.\d+)?)", proc.stdout.decode("utf-8", "replace"))
    if not match:
        raise ScrcpyUnavailable("无法解析 scrcpy 版本号")
    return match.group(1)


class AdbScrcpyDevice(DeviceAdapter):
    name = "adb"

    def __init__(
        self,
        adb: AdbRunner,
        server_bin: str,
        server_jar: Path | None,
        server_version: str | None,
        tcp_port: int,
        fps: int,
        bitrate: int,
        jpeg_quality: int,
        display_width: int,
        frame_timeout: float,
        allow_fallback: bool,
    ) -> None:
        self._adb = adb
        self._server_bin = server_bin
        self._server_jar = server_jar
        self._server_version = server_version
        self._tcp_port = tcp_port
        self._fps = fps
        self._bitrate = bitrate
        self._jpeg_quality = jpeg_quality
        self._display_width = display_width
        self._frame_timeout = frame_timeout
        self._allow_fallback = allow_fallback
        self._sessions: dict[str, MirrorSession] = {}
        self._scrcpy: dict[str, ScrcpySession] = {}
        self._pollers: dict[str, ScreencapPoller] = {}

    # ---------- 基础能力 ----------

    def _version(self) -> str:
        if self._server_version:
            return self._server_version
        return detect_scrcpy_version(self._server_bin)

    def _health_sync(self) -> dict:
        payload: dict = {
            "ok": False,
            "device_backend": self.name,
            "adb_version": None,
            "scrcpy_version": None,
            "ocr_engine": None,
            "hint": None,
        }
        try:
            payload["adb_version"] = self._adb.version()
        except ApiError as exc:
            payload["hint"] = f"{exc.message}；安装：brew install scrcpy"
            return payload
        try:
            payload["scrcpy_version"] = self._version()
        except Exception as exc:  # noqa: BLE001
            payload["hint"] = f"scrcpy 不可用: {exc}"
            return payload
        if self._server_jar is None:
            payload["hint"] = "未找到 scrcpy-server jar，请 brew install scrcpy"
            return payload
        payload["ok"] = True
        return payload

    async def health(self) -> dict:
        return await asyncio.to_thread(self._health_sync)

    def _probe(self, serial: str) -> DeviceInfo:
        match = next((d for d in self._adb.devices() if d.serial == serial), None)
        if match is None:
            raise DeviceNotFound(f"未找到设备 {serial}")
        if match.state == "unauthorized":
            raise DeviceUnauthorized("设备未授权，请在手机上确认 USB 调试授权")
        if match.state != "device":
            raise DeviceNotFound(f"设备 {serial} 状态为 {match.state}")
        wm_raw, width, height = self._adb.wm_size(serial)
        return dataclasses.replace(
            match,
            model=self._adb.getprop(serial, "ro.product.model"),
            abi=self._adb.getprop(serial, "ro.product.cpu.abi"),
            android=self._adb.getprop(serial, "ro.build.version.sdk"),
            wm_size=wm_raw,
            width=width,
            height=height,
        )

    def _list_sync(self) -> list[DeviceInfo]:
        infos: list[DeviceInfo] = []
        for info in self._adb.devices():
            if info.state != "device":
                infos.append(info)
                continue
            try:
                infos.append(self._probe(info.serial))
            except ApiError:
                infos.append(info)
        return infos

    async def list_devices(self) -> list[DeviceInfo]:
        return await asyncio.to_thread(self._list_sync)

    # ---------- 会话 ----------

    def _create_sync(self, serial: str, fps: int) -> MirrorSession:
        info = self._probe(serial)
        session_id = f"s{len(self._sessions) + 1}"
        fallback_width = info.width or 1080
        fallback_height = info.height or 2340

        if self._server_jar is not None:
            transport = ScrcpySession(
                session_id=session_id,
                serial=serial,
                adb=self._adb,
                server_jar=self._server_jar,
                server_version=self._version(),
                tcp_port=self._tcp_port,
                fps=fps,
                bitrate=self._bitrate,
                jpeg_quality=self._jpeg_quality,
                display_width=self._display_width,
            )
            try:
                meta = transport.start()
            except Exception as exc:  # noqa: BLE001
                transport.stop()
                if not self._allow_fallback:
                    raise ScrcpyUnavailable(f"scrcpy 启动失败: {exc}") from exc
                log.warning("scrcpy 启动失败，降级 screencap: %s", exc)
            else:
                session = MirrorSession(
                    id=session_id,
                    serial=serial,
                    width=meta.width,
                    height=meta.height,
                    fps=fps,
                    mode="scrcpy",
                    size_mismatch=bool(
                        info.width and (info.width, info.height) != (meta.width, meta.height)
                    ),
                )
                self._sessions[session_id] = session
                self._scrcpy[session_id] = transport
                return session

        poller = ScreencapPoller(
            self._adb, serial, fallback_width, fallback_height, fps, self._jpeg_quality, self._display_width
        )
        poller.start()
        session = MirrorSession(
            id=session_id,
            serial=serial,
            width=fallback_width,
            height=fallback_height,
            fps=fps,
            degraded=True,
            mode="screencap",
        )
        self._sessions[session_id] = session
        self._pollers[session_id] = poller
        return session

    async def create_session(self, serial: str, fps: int) -> MirrorSession:
        return await asyncio.to_thread(self._create_sync, serial, fps)

    async def close_session(self, session_id: str) -> None:
        await asyncio.to_thread(self._close_sync, session_id)

    def _close_sync(self, session_id: str) -> None:
        transport = self._scrcpy.pop(session_id, None)
        if transport is not None:
            transport.stop()
        poller = self._pollers.pop(session_id, None)
        if poller is not None:
            poller.stop()
        self._sessions.pop(session_id, None)

    def get_session(self, session_id: str) -> MirrorSession:
        if session_id not in self._sessions:
            raise SessionNotFound(f"会话不存在: {session_id}")
        return self._sessions[session_id]

    async def frames(self, session_id: str):
        session = self.get_session(session_id)
        transport = self._scrcpy.get(session_id)
        poller = self._pollers.get(session_id)
        last_seq = -1
        deadline = time.monotonic() + self._frame_timeout
        tick = min(1.0 / max(session.fps, 1), 0.25) / 4
        while True:
            frame: Frame | None = None
            if transport is not None:
                frame = transport.latest()
            elif poller is not None:
                frame = poller.latest()
            if frame is not None and frame.seq != last_seq:
                last_seq = frame.seq
                deadline = time.monotonic() + self._frame_timeout
                yield frame
            elif time.monotonic() > deadline:
                raise MirrorLost(f"{self._frame_timeout}s 内没有新帧（mode={session.mode}）")
            await asyncio.sleep(tick)

    # ---------- 注入 ----------

    def _tap_sync(
        self, session_id: str, x: float, y: float, press_ms: float, sigma: float, press_stdev: float
    ) -> TapResult:
        session = self.get_session(session_id)
        plan = gaussian_click(
            x,
            y,
            session.width,
            session.height,
            sigma=sigma,
            press_mean=press_ms,
            press_stdev=press_stdev,
        )
        transport = self._scrcpy.get(session_id)
        if transport is not None and transport.control_available:
            transport.tap(plan.real_x, plan.real_y, plan.press_ms)
            via = "scrcpy"
        else:
            self._adb.run(
                "shell",
                "input",
                "swipe",
                plan.real_x,
                plan.real_y,
                plan.real_x,
                plan.real_y,
                plan.press_ms,
                serial=session.serial,
            )
            via = "input"
        return TapResult(
            target_x=plan.target_x,
            target_y=plan.target_y,
            real_x=plan.real_x,
            real_y=plan.real_y,
            press_ms=plan.press_ms,
            injected_via=via,
        )

    async def tap(
        self,
        session_id: str,
        x: float,
        y: float,
        press_ms: float,
        sigma: float,
        press_stdev: float = 20.0,
    ) -> TapResult:
        return await asyncio.to_thread(self._tap_sync, session_id, x, y, press_ms, sigma, press_stdev)

    def _swipe_sync(
        self, session_id: str, x1: float, y1: float, x2: float, y2: float, duration_ms: int
    ) -> SwipeResult:
        session = self.get_session(session_id)
        px1, py1 = normalize_to_device(x1, y1, session.width, session.height)
        px2, py2 = normalize_to_device(x2, y2, session.width, session.height)
        points = bezier_points(px1, py1, px2, py2)
        transport = self._scrcpy.get(session_id)
        if transport is not None and transport.control_available:
            transport.swipe(points, duration_ms)
            via = "scrcpy"
        else:
            self._adb.run(
                "shell",
                "input",
                "swipe",
                px1,
                py1,
                px2,
                py2,
                duration_ms,
                serial=session.serial,
            )
            via = "input"
        return SwipeResult(points=points, injected_via=via)

    async def swipe(
        self,
        session_id: str,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        duration_ms: int,
    ) -> SwipeResult:
        return await asyncio.to_thread(self._swipe_sync, session_id, x1, y1, x2, y2, duration_ms)

    def _key_sync(self, session_id: str, key: str) -> None:
        session = self.get_session(session_id)
        keycode = keycode_for(key)
        transport = self._scrcpy.get(session_id)
        if transport is not None and transport.control_available:
            transport.key(keycode)
        else:
            self._adb.run("shell", "input", "keyevent", keycode, serial=session.serial)

    async def key(self, session_id: str, key: str) -> None:
        await asyncio.to_thread(self._key_sync, session_id, key)

    async def screenshot(self, session_id: str) -> bytes:
        session = self.get_session(session_id)
        return await asyncio.to_thread(self._adb.exec_out, session.serial, "screencap", "-p")
```

- [ ] **步骤 4：运行测试确认通过**

运行：`.venv/bin/python -m pytest tests/test_adb_device.py -q`

预期：`3 passed`。

- [ ] **步骤 5：跑全量单测**

运行：`.venv/bin/python -m pytest -q`

预期：全部通过（`25 passed` 左右，数量随任务累计变化，关键是 0 failed）。

- [ ] **步骤 6：真机镜像验证（P2 完成判据）**

```bash
cd backend && CAPYAUTO_DEVICE_BACKEND=adb .venv/bin/python -m app
```

另开终端：

```bash
SID=$(curl -s -X POST http://127.0.0.1:8084/api/session \
  -H 'Content-Type: application/json' \
  -d "{\"serial\":\"$(adb devices | awk 'NR==2{print $1}')\",\"fps\":5}" | python3 -c 'import json,sys;print(json.load(sys.stdin)["sessionId"])')
echo "$SID"
open "http://127.0.0.1:8084/debug/mirror?sessionId=$SID"
```

预期：

- 调试页出现手机实时画面，日志每 5 帧打印一次 `meta ... degraded=false`。
- 帧率 ≈ 5 fps，连续观察 10 分钟不断流。
- 拔掉数据线 5 秒后插回：日志出现 `scrcpy 流中断（...），第 1 次重连`，随后画面恢复。
- 若设备无法启动 scrcpy（例如端口被占用），接口返回 `degraded=true`、`mode=screencap`，调试页仍出画面（1 fps 左右）。

- [ ] **步骤 7：Commit**

```bash
git add backend/app/device/adb_device.py backend/tests/test_adb_device.py
git commit -m "feat: AdbScrcpyDevice 会话装配、镜像推流与降级"
```

---

### 任务 16：控制注入 API 与真机验证（P3）

**文件：**
- 创建：`backend/app/api/control.py`
- 修改：`backend/app/main.py`（注册 control 路由）
- 创建：`backend/tests/test_api_control.py`

- [ ] **步骤 1：编写失败的测试**

创建 `backend/tests/test_api_control.py`：

```python
def _session(client) -> str:
    return client.post("/api/session", json={"serial": "MOCK-0001", "fps": 5}).json()["sessionId"]


def test_tap_returns_target_and_real(client):
    session_id = _session(client)
    body = client.post(
        "/api/control/tap",
        json={"sessionId": session_id, "x": 0.5, "y": 0.5, "sigma": 0, "pressMs": 80, "pressStdev": 0},
    ).json()
    assert (body["targetX"], body["targetY"]) == (540, 1200)
    assert (body["realX"], body["realY"]) == (540, 1200)
    assert body["pressMs"] == 80
    assert body["injectedVia"] == "mock"
    assert (body["deviceWidth"], body["deviceHeight"]) == (1080, 2400)


def test_tap_out_of_bounds(client):
    session_id = _session(client)
    resp = client.post("/api/control/tap", json={"sessionId": session_id, "x": 1.4, "y": 0.5})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "OUT_OF_BOUNDS"


def test_tap_unknown_session(client):
    resp = client.post("/api/control/tap", json={"sessionId": "nope", "x": 0.5, "y": 0.5})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "SESSION_NOT_FOUND"


def test_swipe_returns_points(client):
    session_id = _session(client)
    body = client.post(
        "/api/control/swipe",
        json={"sessionId": session_id, "x1": 0.5, "y1": 0.8, "x2": 0.5, "y2": 0.2, "durationMs": 300},
    ).json()
    assert len(body["points"]) == 11
    assert body["points"][0] == [540, 1920]
    assert body["injectedVia"] == "mock"


def test_key_unknown(client):
    session_id = _session(client)
    resp = client.post("/api/control/key", json={"sessionId": session_id, "key": "nope"})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "UNKNOWN_KEY"


def test_key_back_ok(client):
    session_id = _session(client)
    assert client.post("/api/control/key", json={"sessionId": session_id, "key": "back"}).json() == {"ok": True}
```

- [ ] **步骤 2：运行测试确认失败**

运行：`.venv/bin/python -m pytest tests/test_api_control.py -q`

预期：FAIL，全部 404（路由不存在）。

- [ ] **步骤 3：编写 control 路由**

创建 `backend/app/api/control.py`：

```python
from __future__ import annotations

from fastapi import APIRouter

from app.deps import get_adapter
from app.schemas import KeyRequest, SwipeRequest, TapRequest

router = APIRouter(prefix="/api/control", tags=["control"])


@router.post("/tap")
async def tap(req: TapRequest) -> dict:
    adapter = get_adapter()
    session = adapter.get_session(req.sessionId)
    result = await adapter.tap(
        req.sessionId, req.x, req.y, req.pressMs, req.sigma, req.pressStdev
    )
    return {
        "targetX": result.target_x,
        "targetY": result.target_y,
        "realX": result.real_x,
        "realY": result.real_y,
        "pressMs": result.press_ms,
        "injectedVia": result.injected_via,
        "deviceWidth": session.width,
        "deviceHeight": session.height,
    }


@router.post("/swipe")
async def swipe(req: SwipeRequest) -> dict:
    result = await get_adapter().swipe(
        req.sessionId, req.x1, req.y1, req.x2, req.y2, req.durationMs
    )
    return {
        "points": [list(point) for point in result.points],
        "injectedVia": result.injected_via,
    }


@router.post("/key")
async def key(req: KeyRequest) -> dict:
    await get_adapter().key(req.sessionId, req.key)
    return {"ok": True}
```

- [ ] **步骤 4：注册路由**

把 [main.py](file:///Users/fikard/self_project/capyauto-flow/backend/app/main.py) 的 import 改为：

```python
from app.api import control, devices, health, mirror
```

并在 include 段追加：

```python
app.include_router(control.router)
```

- [ ] **步骤 5：运行测试确认通过**

运行：`.venv/bin/python -m pytest tests/test_api_control.py -q`

预期：`6 passed`。

- [ ] **步骤 6：真机注入验证（P3 完成判据）**

先打开系统触摸坐标显示：

```bash
adb shell settings put system pointer_location 1
cd backend && CAPYAUTO_DEVICE_BACKEND=adb .venv/bin/python -m app
```

另开终端（`SID` 用任务 15 步骤 6 的方式创建）：

```bash
curl -s -X POST http://127.0.0.1:8084/api/control/tap \
  -H 'Content-Type: application/json' \
  -d "{\"sessionId\":\"$SID\",\"x\":0.5,\"y\":0.5,\"sigma\":0,\"pressMs\":80,\"pressStdev\":0}"
```

预期：

- 返回 `realX/realY` 为屏幕中心坐标（如 1080x2340 设备为 `540,1170`），`injectedVia` 为 `scrcpy`。
- 手机上屏幕顶部坐标条显示的落点与返回值一致（偏差 ≤ 2px）。
- 把 `sigma` 设为 6 连点 10 次，落点在中心附近散布，全部落在 0–边长 范围内。
- 越界：`{"x":1.5,"y":0.5}` 返回 HTTP 400 与 `OUT_OF_BOUNDS`。

按压时长校验（脚本测量 5 次的注入耗时）：

```bash
cd backend && .venv/bin/python - "$SID" <<'PY'
import json, sys, time, urllib.request

session_id = sys.argv[1]
body = json.dumps({"sessionId": session_id, "x": 0.5, "y": 0.5, "sigma": 0, "pressMs": 80, "pressStdev": 0}).encode()
for i in range(5):
    request = urllib.request.Request(
        "http://127.0.0.1:8084/api/control/tap", data=body, headers={"Content-Type": "application/json"}
    )
    started = time.perf_counter()
    payload = json.load(urllib.request.urlopen(request))
    elapsed = (time.perf_counter() - started) * 1000
    print(f"pressMs={payload['pressMs']} roundtrip={elapsed:.1f}ms delta={elapsed - payload['pressMs']:.1f}ms")
PY
```

预期：每行 `delta` 在 `-20 ~ +80ms` 区间（注入 80ms + 网络与函数调用开销）；若 `injectedVia` 为 `input`，说明 control socket 未建立，需检查 scrcpy 启动日志。

滑动与按键：

```bash
curl -s -X POST http://127.0.0.1:8084/api/control/swipe \
  -H 'Content-Type: application/json' \
  -d "{\"sessionId\":\"$SID\",\"x1\":0.5,\"y1\":0.8,\"x2\":0.5,\"y2\":0.2,\"durationMs\":300}"
curl -s -X POST http://127.0.0.1:8084/api/control/key \
  -H 'Content-Type: application/json' -d "{\"sessionId\":\"$SID\",\"key\":\"home\"}"
```

预期：手机执行一次上滑、然后回到桌面。

最后关闭坐标显示：

```bash
adb shell settings put system pointer_location 0
```

- [ ] **步骤 7：Commit**

```bash
git add backend/app/api/control.py backend/app/main.py backend/tests/test_api_control.py
git commit -m "feat: tap/swipe/key 注入接口与归一化坐标协议"
```

---
## 4. P0 结论记录（执行任务 2、3 后回填）

P0 只回答一件事：**这台手机能不能用「自写轻客户端 + PyAV 解码 + scrcpy control socket 注入」跑通**。

默认结论是 **C2（自写轻客户端）**，理由：

- 与现有 FastAPI/Python 技术栈同构，不需要为镜像再引入 Node 进程。
- `scripts/scrcpy_probe.py` 已验证线格式（76 字节 meta、12 字节包头、32 字节 touch、14 字节 key）。
- 失败时仍有 `ScreencapPoller` 降级通道，不会阻塞 P1 之后的任务。

执行任务 3 后，把探针输出填进下表（值来自 `python scripts/scrcpy_probe.py` 的 JSON）：

| 字段 | 实测值 | 说明 |
|---|---|---|
| `scrcpy_version` | `3.3.1` | 与 `scrcpy --version` 一致，作为 `Server` 参数 |
| `server_jar` | `/usr/local/share/scrcpy/scrcpy-server`（90,788 B） | 路径由 `_detect_scrcpy_server()` 自动发现 |
| `model` / `android_sdk` / `abi` | `ALP-AN00` / `34` / `arm64-v8a` | 来自 `adb devices -l` 与 `getprop` |
| `wm_size` / `width` / `height` | `1200x2652` / `1200` / `2648` | 视频高度比物理高度少 4px，`size_mismatch=true`，以视频尺寸为准 |
| `frames` | `45`（首轮）/ `21`（修复后） | 静态画面下编码器不产帧，10s 内帧数会波动 |
| `first_packet_s` | `0.13` | 判定 ≤ 5 |
| `mean_interval_ms` | `309.3` | 判定 ≤ 400；静态画面偏低帧率属正常 |
| `inject_ms` | `84.5` / `87.2` | 目标 80ms，落在 0.8×~3× 区间 |
| `gate` | `PASS` | 连续 3 次 PASS，失败路径退出码 1 |

结论：**P0 结论 C2 通过**。同时实测出三处与直觉不同、已回写到任务 12/13 的协议细节：

- 抽象 socket 名必须带 `scid`：`localabstract:scrcpy_<scid>`，且 scid 按 16 进制 int32 解析（`deadbeef` 会越界）。
- server 必须等 video 与 control 两个 socket 都 accept 后才发 76 字节元数据，因此要先连 control 再读 meta。
- 必须传 `send_dummy_byte=false`，否则元数据前会多一个字节；`12` 字节包头是 `pts(8)+size(4)`，config 位为 `1<<63`。

结论判定：

- `gate: PASS` → 记录「P0 结论：C2 通过」，继续任务 4 起实现（本次已记录）。
- `frames`/`first_packet_s` 不达标但 control 注入可用 → 记录「视频解码不达标，走 screencap 降级」，任务 14/15 已覆盖该路径。
- control 注入不可用但视频可用 → 记录「control socket 不可用，注入降级 `adb shell input`」，任务 15 已实现该分支。
- 两者都不可用 → 记录原因并停在 P0，不要继续 P1；此时需要更换 scrcpy 版本或改用 AutoX.js 端侧方案（属于 Plan 2 之外的新决策）。

---

## 5. Plan 2（P4–P7）范围说明

本计划只覆盖 P0–P3。后续计划（`2026-11-11-real-device-bridge-p4-p7.md`）覆盖：

| 阶段 | 内容 | 主要文件 |
|---|---|---|
| P4 | 应用与账号控制：`/api/app/start`、`/api/app/stop`、`/api/app/current`、`/api/app/users`、`/api/app/switch-user`、`/api/network/airplane` | `backend/app/api/app_control.py`、`backend/app/api/network.py`、`backend/app/device/packages.py` |
| P5 | 真机 OCR 闭环：`/api/vision/ocr`，返回文本、置信度、归一化 bounds；无结果返回空数组 | `backend/app/vision/ocr.py`、`backend/app/api/vision.py` |
| P6 | 前端整合：仿真/真机模式切换、`DeviceBar`、`DeviceDrawer`、错误态与降级标注 | `src/components/DeviceBar.tsx`、`src/components/DeviceDrawer.tsx`、`src/hooks/useDeviceBridge.ts`、`src/api/deviceClient.ts` |
| P7 | 验收脚本：`python -m app.verify` 覆盖 V1–V10，产出 `reports/verify-*.json/md` 与取证截图 | `backend/app/verify.py`、`backend/app/verify_checks.py` |

Plan 2 的入口条件：本计划的 P0 结论已记录、P1–P3 全部单测通过、任务 15/16 的真机步骤已人工确认。

契约以规格文件第 6、8 节为准，Plan 2 不得修改本计划已落地的 `/api/health`、`/api/devices`、`/api/session`、`/api/control/*`、`/ws/mirror` 的字段名。

---

## 6. 自检结论

### 6.1 规格覆盖度

| 规格项 | 本计划任务 |
|---|---|
| V1 adb 可用且设备在线 | 任务 2（环境验证）、任务 11（`AdbRunner.devices`） |
| V2 设备信息完整 | 任务 11（`getprop`、`wm_size`）、任务 15（`_probe`） |
| V3 会话与画面 | 任务 13（解码线程）、任务 15（会话装配和 `frames` 超时） |
| V4 截图通道 | 任务 14（`ScreencapPoller`）、任务 15（`screenshot`） |
| V5 点击生效 | 任务 16（`/api/control/tap` + 真机步骤 6） |
| V6 按压时长 | 任务 16（按压耗时脚本，`injectedVia` 区分 scrcpy/input） |
| V7–V10 | Plan 2（见第 5 节） |
| 错误码体系 | 任务 5，任务 9 的 API 层统一 handler |
| 端口与 devgate | 任务 1 |
| Mock 无设备可跑 | 任务 8、任务 9、任务 10 |
| 降级路径 | 任务 14、任务 15（`allow_fallback`） |

### 6.2 占位符扫描

已扫描 `TODO`、`待定`、`后续实现`、`补充细节`、`类似任务`、`PART<n>` 标记：计划正文无占位符。第 4 节的「待回填」是执行后必须记录的实测值，不是未完成的实现步骤。

### 6.3 类型与命名一致性

已逐项核对：

- `DeviceAdapter` 的 `frames` 是同步方法返回 `AsyncIterator[Frame]`，`MockDevice` 与 `AdbScrcpyDevice` 都用 `async def` + `yield` 实现，WS 层用 `async for` 消费，签名一致。
- `Frame`、`MirrorSession`、`TapResult`、`SwipeResult` 字段在任务 8 定义，任务 9/10/15/16 只读取不新增。
- `TapRequest.pressMs/sigma/pressStdev` 与 `adapter.tap(...)`、`gaussian_click(...)` 的参数名一一对应。
- 按键映射只在任务 12 的 `base.py` 定义一次；任务 8 的 `KEY_ALIASES` 在任务 12 被显式删除，`mock_device.py` 改为调用 `keycode_for`。
- `config.Settings` 的 10 个字段与任务 9 `build_adapter` 的构造参数完全对应。
- `normalize_to_device` 越界抛 `OutOfBounds`，API 层据此返回 400；不做静默 clamp（与规格第 9 节一致）。
- `ScrcpySession` 不再接收未使用的 `frame_timeout`，帧超时只由 `AdbScrcpyDevice.frames` 负责。

### 6.4 已知风险与验证归属

| 风险 | 处理 |
|---|---|
| scrcpy server 参数随版本变化 | 任务 2 锁定版本号，任务 3 探针先跑通 |
| PyAV 解码器不接受 config 包 | 任务 13 已把 SPS/PPS 喂给 `ctx.parse/decode`，真机验收确认首帧 |
| 设备分辨率与视频流不一致 | `MirrorSession.size_mismatch` 暴露，前端在 Plan 2 标注 |
| `adb shell input` 无法模拟长按 | 用 `input swipe x y x y pressMs`，任务 15 已采用 |
| 端口 27183 被占用 | `CAPYAUTO_SCRCPY_TCP_PORT` 可覆盖，错误走 `ScrcpyUnavailable` |

### 6.5 执行前置清单

- [ ] `brew install scrcpy` 完成，`scrcpy --version` 可执行
- [ ] 手机已开启 USB 调试并授权，`adb devices -l` 显示 `device`
- [ ] `/Users/fikard/.local/bin/python3.12` 存在
- [ ] `devgate register` 与 `devgate env --write` 已执行，`~/.config/trading-ports.env` 含 `CAPYAUTO_BACKEND_PORT=8084`、`CAPYAUTO_FRONTEND_PORT=5178`
- [ ] 已记录真实游戏包名与主 Activity（P4 需要，不阻塞本计划）

