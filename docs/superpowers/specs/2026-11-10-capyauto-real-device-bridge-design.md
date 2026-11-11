# CapyAuto Flow 真机桥接中控台 — 设计规格

- 日期：2026-11-10
- 状态：待评审
- 范围：把现有纯前端仿真中控台，扩展为可驱动真实安卓设备的「仿真 / 真机」双模式控制台
- 目标设备：用户自有安卓真机（真实游戏，包名待用户提供）
- 实施技术：scrcpy 画面与输入通道 + FastAPI 后端 + 现有 React 前端

## 1. 背景

现有工程是纯前端演示：

- `src/App.tsx` 用 `useState` 管理 FSM、账号矩阵、日志、配置，刷新即丢。
- `src/components/PhoneSimulator.tsx` 用定时器模拟流水线，点击只是生成高斯坐标并写日志。
- `src/data/scriptFiles.ts` 内置一套 AutoX.js 工程字符串，可打包导出，但未经真机验证。

所有状态机和指标都是模拟值，没有任何设备通信。本设计要在不改动现有 7 个页签信息架构的前提下，接上真实设备。

## 2. 目标与非目标

### 2.1 第一版目标

1. 前端可在「仿真 / 真机」之间切换，真机模式下手机壳显示实时设备画面。
2. 点击、滑动、返回/主页/多任务按键注入真实设备，并沿用现有高斯抖动与按压时长参数。
3. 应用启停、Android 用户列表探测与分身切换、飞行模式换 IP。
4. 真机截图 → OCR → 技能三选一决策 → 自动点击，形成一次完整业务闭环。
5. 提供脚本化验收（自动 PASS/FAIL/SKIP 报告 + 取证截图）与界面人工演示两条验收路径。

### 2.2 非目标（明确不做）

- 不做多设备并发控制，第一版单设备。
- 不实现 AutoX.js 端侧执行后端，只预留适配接口。
- 不把 FSM 与账号调度下沉到后端。
- 不迁移 `config.json` 中的明文账号口令字段，也不做账号密码托管。
- 不接入云真机、不做 WebRTC。
- 不调整现有 7 个页签的视觉风格与布局。
- 不做游戏风控绕过承诺；注入能力只用于自有设备上的自有账号运营。

## 3. 关键决策

| 决策 | 结论 | 理由 |
|---|---|---|
| 画面与输入通道 | scrcpy | 帧率高、输入事件时序可控、不启用无障碍服务；调试期体验最好 |
| 后端运行时 | Python 3.12 + FastAPI | 与 OCR 同进程，避免跨语言传图；符合现有技术栈 |
| OCR 引擎 | 首选 `rapidocr-onnxruntime`，备选 PaddleOCR | Apple Silicon 上 onnxruntime 轮子成熟，PaddlePaddle 本地安装风险高；两者均为 PP-OCR 模型，输出同构 |
| 坐标协议 | 前端只发归一化坐标（0–1） | 缩放换算与抖动都在后端完成，避免两端各算一次 |
| 自动流水线位置 | 保留在前端 | 复用现有 FSM 与 `matchBestSkill`，避免 Python/TS 双份实现 |
| 端侧执行后端 | 只留 `DeviceAdapter` 接口 | 将来接 AutoX.js 时只新增一个适配器与端侧 Agent |
| 多账号隔离 | 探测 + 降级 | 不同厂商分身 user id 不同，探测失败时返回不支持而非报错 |

### 3.1 三种执行后端的关系

```
DeviceAdapter（唯一能力边界）
  ├── AdbScrcpyDevice   第一版实现：PC 侧 adb + scrcpy
  ├── MockDevice        无设备时驱动前端与单测
  └── AutoXBridgeDevice 预留：端侧 Agent 经 WS 上报画面、接收指令
```

前端的 FSM、技能优先级、页面结构、参数面板与后端实现无关，因此替换后端不需要改 UI。

第一版业务配置（技能优先级、抖动参数、包名、账号矩阵）仍由前端持有，后端只接收请求里传来的参数，不读取业务配置。等 AutoX 端侧后端落地时，再把同一份配置导出为 `config.json` 供端侧脚本读取，届时前端与脚本共用同一份数据来源。这样第一版不需要在 Python 里维护一份重复配置。

## 4. 架构

### 4.1 进程与端口

| 进程 | 端口 | 说明 |
|---|---|---|
| Vite 前端 | `CAPYAUTO_FRONTEND_PORT`，默认 5178 | 现有 `dev` 脚本写死 3000，与 travel_design 后端冲突，需改 |
| FastAPI 后端 | `CAPYAUTO_BACKEND_PORT`，默认 8084 | 设备会话、scrcpy 生命周期、OCR、验收 |
| 外部二进制 | — | `adb`、`scrcpy-server.jar`（随 scrcpy 发行包） |

按全局端口规范，两个端口需同时登记到 `~/.config/trading-ports.env` 与 `~/.config/trading-ports-check.sh`；代码中一律通过环境变量读取并带默认值。

### 4.2 后端模块

```
backend/
├── app/
│   ├── main.py                  FastAPI 入口、CORS、异常映射
│   ├── config.py                环境变量、端口、路径、开关
│   ├── api/
│   │   ├── health.py            /api/health
│   │   ├── devices.py           /api/devices, /api/session
│   │   ├── control.py           /api/control/*
│   │   ├── apps.py              /api/app/*, /api/app/users
│   │   ├── network.py           /api/network/airplane
│   │   ├── vision.py            /api/vision/ocr
│   │   ├── verify.py            /api/verify/run
│   │   └── mirror.py            /ws/mirror
│   ├── device/
│   │   ├── base.py              DeviceAdapter 协议 + 数据类
│   │   ├── adb.py               AdbRunner：subprocess 封装、超时、错误码
│   │   ├── adb_device.py        AdbScrcpyDevice
│   │   ├── mock_device.py       MockDevice
│   │   ├── scrcpy_session.py    server 推送、双 socket、解码、重连
│   │   └── screen.py            screencap 降级通道
│   ├── core/
│   │   ├── dither.py            Box-Muller、高斯点击、贝塞尔滑动
│   │   └── geometry.py          归一化坐标 → 设备坐标、边界校验
│   └── vision/
│       └── ocr.py               OCR 引擎单例与结果归一化
├── tests/
└── pyproject.toml
```

### 4.3 前端模块

```
src/
├── services/deviceClient.ts     REST + WS 封装、重连、错误归一化
├── components/DeviceMirror.tsx  画面渲染、坐标映射、点击回传
├── components/DeviceBar.tsx     连接状态、序列号、分辨率、帧率、错误提示
├── components/DeviceDrawer.tsx  真机控制（启停、切用户、OCR、验收）
├── hooks/useDeviceSession.ts    会话生命周期
└── App.tsx                      新增全局 mode: 'sim' | 'real'
```

`PhoneSimulator` 在 `real` 模式下把屏幕内容替换为 `DeviceMirror`，其余 7 个页签、状态机、参数面板全部复用。

## 5. 接口契约

### 5.1 REST

| 方法 | 路径 | 请求 | 响应要点 |
|---|---|---|---|
| GET | `/api/health` | — | `adb_version`、`scrcpy_version`、`ocr_engine`、`ok` |
| GET | `/api/devices` | — | `serial`、`model`、`android`、`abi`、`state`、`wm_size` |
| POST | `/api/session` | `{serial}` | `sessionId`、`width`、`height`、`fps`、`degraded` |
| DELETE | `/api/session/{id}` | — | `ok` |
| POST | `/api/control/tap` | `{sessionId,x,y,pressMs,sigma}` | `realX`、`realY`、`pressMs`、`injectedVia` |
| POST | `/api/control/swipe` | `{sessionId,x1,y1,x2,y2,durationMs}` | `points`、`injectedVia` |
| POST | `/api/control/key` | `{sessionId,key}` | `ok` |
| POST | `/api/app/launch` | `{sessionId,package,user?}` | `ok`、`usedUser` |
| POST | `/api/app/stop` | `{sessionId,package}` | `ok` |
| GET | `/api/app/users` | `sessionId` | `[{id,name,current}]`、`switchSupported`、`reason` |
| POST | `/api/network/airplane` | `{sessionId,enable}` | `ok`、`appliedVia` |
| POST | `/api/vision/ocr` | `{sessionId,region?}` | `tookMs`、`items[{text,confidence,bounds}]`、`debugPng?` |
| POST | `/api/verify/run` | `{sessionId}` | `jobId`；随后 `GET /api/verify/{jobId}` 轮询 |

`x/y` 均为 0–1 归一化坐标。`sigma`、`pressMs` 以设备像素与毫秒为单位。

### 5.2 WebSocket

`/ws/mirror?sessionId=xxx`

- 服务端 → 客户端：二进制帧（JPEG）与文本元消息交替。
- 文本消息：`{type:'meta'|'error', seq, ts, width, height, code?, message?}`。
- 客户端 → 服务端：仅心跳 `{type:'ping'}`。
- 断流后由服务端自动重连；连续 3 次失败推送 `{type:'error',code:'MIRROR_LOST'}` 并关闭。

## 6. 数据流

### 6.1 建立会话

1. `GET /api/devices`：`adb devices -l` → 过滤 `state=device`。
2. 探测 `ro.product.cpu.abi`、`ro.build.version.sdk`、`wm size`、`pm list users`。
3. 按 ABI 推送对应 `scrcpy-server.jar` 到 `/data/local/tmp/`。
4. 启动 server 进程，建立 video 与 control 两条 localabstract socket。
5. 读取首帧，返回真实视频宽高（与 `wm size` 交叉校验，不一致时以视频为准并在 `DeviceBar` 标注）。

### 6.2 镜像

video socket → Annex-B H.264 → PyAV 解码 → 缩放至显示尺寸 → JPEG(quality 70) → WS。

- 目标 5 fps（可配置 1–10），单帧编码耗时超阈值时自动降帧，不做无上限追帧。
- 只保留最新帧，不做发送队列堆积，避免延迟累积。

### 6.3 点击注入

前端 `DeviceMirror` 把点击位置换算成归一化坐标 → `POST /api/control/tap` → 后端：

1. 归一化坐标 × 设备分辨率 = 目标点。
2. `dither.gaussian_click` 生成真实落点与按压时长，边界 clamp。
3. 通过 control socket 注入 DOWN → 保持 `pressMs` → UP。
4. control socket 不可用时降级 `adb shell input swipe x y x y <pressMs>`。
5. 返回真实落点，前端在镜像上叠加「意图点 / 实际落点」并显示 Δx/Δy。

### 6.4 OCR 与业务闭环

1. `POST /api/vision/ocr`：按需 `exec-out screencap -p` 抓无损 PNG（不复用视频帧，避免压缩影响识别）。
2. RapidOCR 推理，返回 `items`。
3. 前端把 `items.map(i => ({text}))` 交给现有 `matchBestSkill`，得到命中的卡牌索引。
4. 用该候选的 `bounds` 中心作为点击目标，走 6.3 注入。
5. 未识别到任何文本时**不点击**，只上报 `OCR_EMPTY`，避免盲点导致误操作。

### 6.5 应用与账号控制

- 启停：`am start -n` / `am force-stop`。
- 切用户：先 `pm list users`，再用 `pm list packages --user N` 校验包已安装；不满足则返回 `switchSupported:false` 与原因，前端置灰。
- 飞行模式：Android 11+ 用 `cmd connectivity airplane-mode enable|disable`；低版本回退 `settings put global airplane_mode_on` + 广播。生效校验读回 `settings get global airplane_mode_on`。

## 7. 阶段路径

每个阶段都有明确的完成标准，未达标不进入下一阶段。

| 阶段 | 内容 | 完成标准 |
|---|---|---|
| P0 技术闸门 | 装 `adb`（`brew install scrcpy` 会带 platform-tools）；真机连接；验证 scrcpy 客户端路径 | 连续 10 秒不断流画面 + 一次 80ms 按压注入成功；给出 C1（改造 ws-scrcpy）或 C2（自写轻客户端）结论 |
| P1 后端骨架 | FastAPI + `DeviceAdapter` + `MockDevice` + 端口规范落地 | `uvicorn` 可起；Mock 下 `/api/health`、`/api/devices`、`/api/session`、`/ws/mirror` 全通；pytest 通过 |
| P2 镜像接入 | `AdbScrcpyDevice` 视频通道 + 降级 screencap 通道 | 真机 5 fps 稳定 10 分钟；拔线 5 秒后插回能自动恢复；scrcpy 失败时自动降级且 `degraded=true` |
| P3 输入注入 | tap / swipe / key，坐标换算与抖动 | 点击落点误差 < 2px；按压时长误差 < 20ms；越界返回 `OUT_OF_BOUNDS`；前端点击位置与设备一致 |
| P4 应用与账号 | 启停、用户探测、切分身、飞行模式 | 启停后 `dumpsys activity` 状态变化可验证；不支持切分身的机型返回 SKIP 原因；飞行模式开关读回一致 |
| P5 OCR 闭环 | RapidOCR + 技能卡识别 + 决策点击 | 真实技能三选一界面识别 3 张卡，文本正确 ≥ 2/3；单次 OCR 小于可配置阈值（`CAPYAUTO_OCR_MAX_MS`，默认 5000ms）；闭环点击成功进入战斗 |
| P6 前端整合 | 仿真/真机切换、设备栏、控制抽屉、错误态 | 7 个页签在真机模式无报错；断开设备时 UI 有明确提示且不白屏 |
| P7 验收 | 验收脚本 + 报告 + 人工演示 | `npm run verify` 全部 PASS 或 SKIP 有理由；生成报告与取证截图；界面演示通过 |

**P4–P7 状态：已通过（2026-11-12，ALP-AN00 / Android 14 / `ANASUT3C20010476`）。** 验收报告 `backend/reports/verify-20261112-001139235686.json`（V1–V7、V10 PASS，V8 SKIP，V9 PASS）。

> OCR 性能说明：原「单次 OCR < 800ms」按 Apple Silicon 预估。当前 Intel i7-8750H 上 RapidOCR（PP-OCRv4 mobile，CPU 推理）实测 2.2–4.7s，det/rec 推理本身即超过 800ms，无法通过调参达标；因此阈值改为可配置项（默认 5000ms），并做了关方向分类、限制推理线程数的无损提速（优化前 6.5–7.4s）。Apple Silicon 环境可通过 `CAPYAUTO_OCR_MAX_MS=800` 恢复原标准。

P0 是唯一带技术不确定性的阶段。若 C1 与 C2 都不通，立即启用 `screen.py` 的 screencap 轮询降级路线，保证 P1 之后的阶段不被阻塞。

## 8. ADB 验证方案

### 8.1 自动化验收

`npm run verify` 只是入口别名，实际执行 `python -m app.verify`。验收脚本独立运行，不依赖浏览器，也不依赖前端进程，便于在 CI 或纯终端环境复跑。按顺序执行：

| 编号 | 检查项 | 判定方式 |
|---|---|---|
| V1 | adb 可用且设备在线 | `adb version` + `adb devices` 中存在 `state=device` |
| V2 | 设备信息完整 | 分辨率、ABI、Android 版本、`wm size` 均非空 |
| V3 | 会话与画面 | 30 秒内收到 ≥ 5 帧，帧间隔 P95 < 400ms |
| V4 | 截图通道 | `screencap` 返回 PNG，尺寸等于设备分辨率 |
| V5 | 点击生效 | 点击目标前后 `dumpsys activity activities` 的前台 Activity 变化 |
| V6 | 按压时长 | 注入耗时 ≈ `pressMs` + 固定开销，误差 ±50ms；`input swipe` 兜底可用 |
| V7 | 应用启停 | 启动后进程存在，强杀后进程消失 |
| V8 | 用户探测与切换 | 能列出 user；切换不可用时记 SKIP 并写明原因 |
| V9 | 飞行模式 | 开启后读回 `airplane_mode_on=1`，关闭后为 0 |
| V10 | OCR | 目标界面返回 ≥ 1 条文本，最高置信度 > 0.6 |

输出：

- `reports/verify-<timestamp>.json`：逐项 `PASS/FAIL/SKIP`、耗时、原始输出摘要。
- `reports/verify-<timestamp>.md`：人读摘要。
- `reports/frames/<check>-<timestamp>.png`：取证截图。

判定规则：任一 `FAIL` 则整体失败；`SKIP` 必须带原因，不允许静默跳过。

### 8.2 界面人工验收

- `DeviceBar` 显示 `ONLINE`、序列号、分辨率、实时帧率。
- 镜像上点击后显示意图点与实际落点，Δx/Δy 与后端返回值一致。
- 控制抽屉里逐项触发：启停应用、列用户、飞行模式、OCR、运行验收。
- 断开连接后 UI 显示明确错误，不出现空白或卡死。

## 9. 错误处理

| 场景 | 处理 |
|---|---|
| `adb` 未安装 | `/api/health` 返回 `ok:false` 与安装指引；前端顶部提示 |
| 设备未授权 | 错误码 `DEVICE_UNAUTHORIZED`，提示在手机上确认调试授权 |
| 多台设备 | `/api/devices` 返回列表，前端下拉选择 |
| scrcpy server 启动失败 | 自动降级 screencap 轮询，`degraded=true`，UI 标注 |
| 视频断流 | 重连 3 次（指数退避），仍失败推送 `MIRROR_LOST` |
| 坐标越界 | 400 `OUT_OF_BOUNDS`，不做 clamp 静默修正 |
| 切用户不支持 | 200 + `switchSupported:false` + `reason`，前端置灰 |
| 飞行模式命令失败 | 按 Android 版本回退，仍失败记 SKIP |
| OCR 无结果 | 返回空数组，前端显示「未识别」，不触发点击 |
| 后端崩溃/端口占用 | 启动自检端口，冲突时明确报错并退出 |

## 10. 测试策略

- **单元测试（pytest）**：`AdbRunner` 用 fake 输出测解析与超时；`geometry` 测归一化换算与边界；`dither` 用 5000 次采样断言均值与标准差；`ocr` 用固定图片测结果归一化。
- **接口测试**：`MockDevice` 驱动全部 REST 与 WS，断言状态码与字段形状。
- **契约测试**：TS 与 Python 两份抖动实现用同一组参数做统计断言，避免两端手感漂移；`matchBestSkill` 只在 TS 存在，Python 不复制。
- **真机验收**：第 8 节脚本，作为回归入口。
- **前端**：保留 `src/core/decision.test.ts`；新增 `deviceClient` 的坐标与错误归一化测试。

## 11. 风险与未决事项

| 风险 | 影响 | 应对 |
|---|---|---|
| 自写 scrcpy 客户端工作量 | 阻塞 P2 | P0 闸门先验证；C1 不通转 C2；两者都不通走 screencap 降级 |
| 游戏检测 adb 注入 | 业务闭环可能失败 | 先小步验证点击是否生效；不做绕过承诺 |
| 厂商分身 user id 差异 | 切分身不可用 | 探测 + 降级，不硬编码 999 |
| 刘海/挖孔屏坐标偏移 | 点击偏位 | 以视频帧尺寸为准，与 `wm size` 交叉校验 |
| Apple Silicon 安装 PaddlePaddle 困难 | OCR 不可用 | 首选 RapidOCR(onnxruntime) |
| 无线调试 IP 变化 | 连接中断 | 支持 USB 优先，无线作为备选并记住最近 serial |

待用户提供（不阻塞 P0/P1/P2/P3）：

- 真实游戏包名与主 Activity 名称。
- 设备型号、Android 版本、分辨率。
- 是否接受关闭屏幕运行（`--turn-screen-off`）以降低发热。

## 12. 明确不做的设计

- 不在 Python 里重写 FSM 与技能决策。
- 不为 AutoX 端侧后端写实现代码，只保留接口与配置共享。
- 不做多设备并发、任务队列、数据库持久化；状态全部在内存。
- 不在第一版引入 WebRTC、H.264 直通浏览器（WebCodecs）等优化。
