# CapyAuto Flow 实现方案与功能状态

> 整理时间：2026-11-15
> 依据：全库代码通读，`docs/superpowers/specs|plans`，`.trae/documents/`，`.superpowers/sdd/progress.md`，`backend/reports/` 验收报告，以及本轮实跑的静态四连。
> 定位：这不是设计期项目，是「功能代码已成型、真机桥接已验收、批量账号业务验收未做」的双轨收口期工程。

---

## 1. 结论先行

- 后端是**真实可跑通的 FastAPI 真机桥接服务**（自写 scrcpy 客户端 + PyAV 解码 + control socket 注入 + RapidOCR），不是演示壳；V1–V10 真机验收报告在 `backend/reports/verify-20261112-001139235686.json`。
- 但**默认配置是 mock 设备**（`backend/app/config.py:74`），开箱跑的是假帧，OCR 识别不到游戏文案，自动化必然失败。真跑必须 `CAPYAUTO_DEVICE_BACKEND=adb` + 真机 + RapidOCR。
- 前端「仿真」分支是**硬编码演示壳**；`@google/genai` 是零引用的 AI Studio 模板残留，项目零云端调用。
- **真机桥接已验收（2026-11-15 23:28）**：设备 `ANASUT3C20010476` 在线，V1–V10 CLI **9 PASS / 1 SKIP / 0 FAIL（exit 0）**，web 端 REST 触发路径 **8 PASS / 2 SKIP / 0 FAIL**；浏览器真机模式的会话、镜像帧、启动/急停链路全部实测通过。详见 §9。
- 真机侧暴露并已修复一个**关键启动缺陷**：游戏必须经「冲鸭变速器」的桌面快捷方式「冒险者日记」启动，直启 `com.hb.cncapy.and` 会绕开变速器沙箱。已按 TDD 落地 `LauncherSpec` + 桌面图标定位 + 宿主停止，见 §2.4 / §7.4。
- 2026-11-15 四批改动：前两批把 **P1 全部收口**；第三批推进 **P2 可静态验证部分**；第四批修好真机启动链路并完成 V1–V10 与 web 端到真机验收。详见 §7。
- **仍未变的结论**：P0 里涉及账号业务的四步（风贰单账号、七账号队列、AutoX dry-run、一次实机 100 体力游历）仍需游戏停在主城、账号确认后上机执行；在此之前不能宣称端到端交付。P2 六项后置真机能力、`AutoXBridgeDevice` 与 P3 仍未做。

---

## 2. 实现方案

### 2.1 分层与数据流

| 层 | 组成 | 职责 |
|---|---|---|
| 接入层 | `src/` React 19 SPA（7 页签、无路由、纯 `useState`）、`autox/` 端侧脚本、`app/verify.py` CLI、`app/static/debug_mirror.html` | 展示与操作入口 |
| 服务层 | `backend/app/main.py` + `api/` 9+1 个 router | 20 REST + 1 WS，统一 `ApiError`、CORS 白名单、pydantic 校验 |
| 能力层 | `automation/engine.py`（2388 行）、`device/`（base + mock + adb + scrcpy_session）、`vision/ocr.py`、`accounts.py` | 业务状态机、设备抽象、OCR、账号状态 |
| 数据层 | `backend/.data/accounts.json`、`stage_script.json`、`capy-knowledge/` 3 个词典、`backend/reports/` | 状态、回放锚点、OCR 标注、验收报告 |

通信：前端 `src/api/deviceClient.ts` 直连 `VITE_BACKEND_URL`（默认 `127.0.0.1:8084`），`/ws/mirror` 走原生 WebSocket 收 JPEG 帧；`vite.config.ts` 未配 proxy，靠后端 CORS 白名单。

### 2.2 双轨设计

- **ADB / scrcpy 轨**：PC 侧截图 → RapidOCR → 归一化坐标 → scrcpy control socket 或 adb 注入。能力完整，8 个自动化任务、七账号队列、lean 录制回放都在这条轨。
- **AutoX.js 端侧轨**：`autox/main.js`（可注入 runtime）+ `logic.js`（纯决策）+ `config.js`（分层配置），手机本地 OCR 决策，只做「单账号核验角色名 → 体力 OCR 门槛 → 20 倍档 → 一次 100 体力游历 → 结算」最小闭环；通过 `POST /api/accounts/report` 单向回报。
- 端侧后端地址**不写死**：`config.json`（入库默认值，`backendUrl` 为空）← `config.local.json`（`scripts/gen-autox-config.sh` 从 devgate 端口 + 本机 LAN IP 生成，不入库）← 全局注入 `CAPYAUTO_BACKEND_URL` / `CAPYAUTO_CONFIG`；缺配置显式报错，不静默回退到某个 IP。
- 两轨**共用 `accounts.json` 的 `lastRun` 状态视图**（含端侧上报的 `staminaBefore` 证据），但执行能力不对等（见 §4）。

### 2.3 关键设计取舍

- `DeviceAdapter` 抽象 `mock | adb`，scrcpy 失败自动降级 `screencap` 1fps 并置 `degraded=true`。
- 决策基于 OCR 文案匹配而非固定坐标脚本；坐标全部 0–1 归一化；高斯抖动 + 贝塞尔轨迹模拟人工。
- 风控用白名单 + 危险词 + 主账号排除，不承诺绕过游戏检测；端侧默认 `dryRun=true`、音量下急停。
- 多设备并发、数据库、WebRTC、账号密码托管均为规格① §2.2 / §12 明确非目标。
- 端口走 devgate（`scripts/web.sh`），不硬编码；唯一事实源 `~/.config/devgate/registry.yaml`。

### 2.4 真机启动链路（2026-11-15 实测确认）

游戏并非独立运行，而是托管在「冲鸭变速器」`com.joke.chongya` 的沙箱里：

| 事实 | 实测证据 |
|---|---|
| 桌面「冒险者日记」是变速器发布的 pinned shortcut `cy_com.hb.cncapy.and` | `adb shell dumpsys shortcut` |
| 前台 Activity 是 `com.joke.chongya/top.bienvenido.mundo.manifest.MundoActivity$Companion$STUB1`，游戏与宿主共享 uid | `dumpsys activity activities` / `ps -A` |
| 直启 `am start com.hb.cncapy.and` 会拉起 `PLMainActivity` 原生包，**绕开变速器** | 首次 API 实测前台为原生包、宿主进程为空 |
| 沙箱 `SandboxStartAdvActivity` **not exported**，shell `am start` 抛 `SecurityException` | 直接命令复现失败 |
| `am force-stop com.hb.cncapy.and` 对插件进程无效，必须 force-stop 宿主 `com.joke.chongya` | 强杀实验，宿主停后 game/host pid 同时消失 |

因此实现走 **HOME 键回桌面 → uiautomator 按文字标签定位图标（最多翻 4 页）→ 点击 → 轮询校验前台属于宿主沙箱**；误点「YOYO 建议」等原生入口时显式报 `AdbError`，不把原生直启误判为成功。配置化为 `LauncherSpec`（`CAPYAUTO_LAUNCH_MODE=auto|package|launcher`、`CAPYAUTO_LAUNCHER_HOST_PACKAGE`、`CAPYAUTO_LAUNCHER_ICON_LABEL`、`CAPYAUTO_LAUNCHER_ICON_POINT`、`CAPYAUTO_LAUNCHER_WAIT_S`），`auto` 只在宿主确实安装时改走桌面图标。

---

## 3. 已实现功能

| 模块 | 内容 | 主要文件 / 证据 |
|---|---|---|
| 真机桥接底座 | adb/scrcpy 视频流、控制注入、screencap 降级、断流重连、应用启停、用户切换、飞行模式 | `backend/app/device/*`；2026-11-15 真机 V1–V10 9 PASS / 1 SKIP |
| 变速器沙箱启动 | HOME 回桌面 → 按文字标签翻页定位「冒险者日记」→ 点击 → 校验前台属于宿主沙箱；误点原生包显式报错；停止时回退强杀宿主 | `backend/app/device/packages.py`、`config.py`、`deps.py`、`verify.py`；`tests/test_launcher.py` 29 用例 |
| 后端服务 | 20 REST（含本轮新增 `/api/verify/run`）+ `/ws/mirror`、统一错误、CORS | `backend/app/main.py`、`api/*` |
| 自动化引擎 | 8 任务（growth / daily / guild / ship / bootstrap / account_sweep / server_sweep / all），起号阶段机、局内 OCR 事件、lean 回放、分类等待、七账号队列 | `backend/app/automation/engine.py` |
| 视觉与风控 | RapidOCR + 知识库 `kind/rarity/lexiconRef` 标注、危险词与主账号拦截、白名单点击、音量下急停 | `vision/ocr.py`、`capy-knowledge/`、`autox/logic.js` |
| 账号状态 | `works` + `lastRun`、原子写、`/api/accounts/report` 端侧上报、前端展示 | `backend/app/accounts.py`、`api/accounts.py` |
| 前端中控台 | 7 页签、仿真/真机切换、WS 画面点击注入、设备抽屉、代码仓库 ZIP 导出、日志/风控页 | `src/components/*` |
| 真机控制 | tap（含高斯/按压参数透传）、swipe、key、currentApp、区域 OCR、应用/用户/网络/自动化操作 | `src/hooks/useDeviceBridge.ts`、`DeviceDrawer.tsx` |
| 统一配置与持久化 | 仿真参数 + 真机自动化参数合并为唯一 `PipelineConfig`，localStorage 自动存取、脏数据清洗与范围钳制、界面可恢复默认 | `src/core/pipelineConfig.ts`、`hooks/usePipelineConfig.ts` |
| 双轨账号视图 | 真机页签只读 `/api/accounts`（`works`/`lastRun`/战力/体力）；仿真演示数据隔离并显式标注；账号队列可编辑、可用真机账号一键填充 | `src/components/AccountMatrix.tsx`、`data/demoAccounts.ts` |
| 镜像链路 | 消费 WS meta（seq/分辨率/fps/降级）、15s ping 心跳、1→2→4→8s 指数退避自动重连、手动跳过退避、尺寸不一致提示 | `src/core/mirrorStream.ts`、`components/DeviceMirror.tsx` |
| 环境校验 | `npm run verify` CLI（V1–V10，产出 JSON + Markdown 报告）+ 界面触发的 `/api/verify/run` | `app/verify.py`、`api/verify_run.py` |
| AutoX 最小闭环 | 单账号一次游历、`dryRun` 全链路零点击识别、三级 OCR 兜底、权限预检、急停、状态回报；体力 OCR 门槛、倍率按钮 OCR 定位、分层配置、`main.js` 注入式单测 | `autox/main.js`、`logic.js`、`config.js`、`config.json` |
| 端侧配置 | `backendUrl` 分层覆盖与 URL 校验；`scripts/gen-autox-config.sh` 从 devgate 端口 + 本机 LAN IP 生成 `config.local.json` | `scripts/gen-autox-config.sh`、`.gitignore` |
| 工程配套 | devgate 启停、`backend/tests/` 360 用例、前端 27 用例、端侧 42 用例 | `scripts/web.sh`、`tests/`、`autox/*.test.js` |

---

## 4. 待实现 / 未完成

### 4.1 阻塞项（P0）

- `.trae/...md:71-77` 五步验证中，**静态四连已完成、真机桥接 V1–V10 已完成**（§9）；剩余四步涉及账号业务，尚未执行：风贰单账号、七账号队列（风贰不重复）、AutoX dry-run、风贰一次实机 100 体力游历、最终汇总。前置条件是游戏停在主城、账号为风贰、绝不触碰主账号「你瞅啥呢」。
- `autox/config.json` 仍 `dryRun: true`（有意保留）；`backendUrl` 已改为空，**上机前必须先跑** `bash scripts/gen-autox-config.sh` 生成 `autox/config.local.json`，或注入 `CAPYAUTO_BACKEND_URL`，否则脚本会显式报配置错误而不是连到旧 IP。
- 规格② `:556/:560/:563/:570` 反复记录「单次 bootstrap 端到端验收尚未成立」，当前证据是多次续跑 + 手动干预的组合。

### 4.2 前端与集成（第二批已消除的项见 §7.2）

- **第二批已消除**：双状态割裂、配置无持久化、`allowGemTalentBreakthrough` / `serverTo` / `maxRuns` / `ocr.region` 无入口、WS meta 被忽略且断流不重连、顶栏「启动全自动流水线」在真机模式只写日志不调后端。
- **占位残留**：`scriptFiles.ts` 的凭证重登录「(略)」、`config.json` 前端回写注释与实现不符、知识库动态对齐注释与实现不符、第 4 个风控开关只读、自动流水线仿真分支缺 `BATTLE_DEFEAT` / `ACCOUNT_SWITCHING`、「战败自动熔断」未闭环。
- **演示态边界**：仿真账号（`DEMO_ACCOUNTS`）、新增演示账号、日志流**仍为会话内状态**，刷新回到初值；这是有意保留的演示语义，不是设备事实源。持久化只覆盖用户配置。
- **模板残留**：`package.json` 的 `name: react-example`、`README.md` 为 AI Studio 模板、`GEMINI_API_KEY` / `@google/genai` / `express` / `motion` 零引用、示例明文口令、包名 `com.game.capy` 与 `com.hb.cncapy.and` 不一致。
- **未加 npm 脚本**：`npm run test:frontend` 未落地 —— 改 `package.json` 会被环境版本检查拦截（要求把零引用的 `express` 升到 `^5.2.0`），属无关改动，故测试命令以显式 `tsx --test <4 个文件>` 执行，见 §6。

### 4.3 后端与引擎

- `/api/verify/run` **本轮已补**；仍缺：`AutoXBridgeDevice`、`state.json` 断点续跑、`targetChapter` 参数、内置 2 倍速。
- 引擎半实现：建角不输角色名、新手引导为盲点（80 步上限）、提升链只 3 步、公会只免费捐献、`serverDryRun` 默认只枚举。
- `progress.md:79` 的 minor backlog：`pidof` 无 `ps/dumpsys` 回退；`:47` 另列 14 项（截图尺寸、贝塞尔越界、422 响应不统一、lifespan 清理等）。

### 4.4 AutoX 轨与数据

- **本轮已消除**：无体力 OCR、加档按钮坐标写死在代码里、`main.js` 无法单测、`backendUrl` 写死 IP、`dryRun` 在第一个点击就结束（导致根本验不到 20 倍与结算）。详见 §7.3。
- **仍未做**：`.trae/...md:60` 后置六项（多账号切换、完整 bootstrap、推关、公会、副本、端侧 WS 镜像）、`AutoXBridgeDevice`；结算后**未核验体力差 = 100**，目前只在开始前确认体力并把 `staminaBefore` 上报为证据；`currentPhase` 仍只有 `travel/done` 两种粗粒度值。
- **未验证的假设**：体力文案 `125/200` 与倍率「+」按钮的 OCR 可识别性均来自后端 `SERVER_STAMINA_PATTERN` 与代码注释，**尚未在真机 AutoX OCR 上实测**；真机若识别不到，应调 `ocrAnchors` / `maxStaminaPolls` 或开启 `requireOcrAnchor` 前的锚点确认，而不是放宽体力门槛。
- 前端 `src/data/scriptFiles.ts` 导出的 `config.json` 是**另一套旧 AutoX 模板**（账号矩阵/技能优先级），与 `autox/config.json` 无关，仍属 §4.2 的模板残留。
- `capy-knowledge/` 12 个文件仅 3 个被 `vision/ocr.py` 消费；`ocr_primary_lexicon.json`（416 键）、`ocr_trigger_lexicon.json`（1606 条）等 9 个未接入；`capy-db-raw/` 15 个全无引用且被 gitignore，其中 `counts` 是 404 HTML 残留。
- 规格① §12 写「不在 Python 里重写 FSM / 状态全在内存」，实际 FSM、账号调度、JSON 落盘已下沉后端——**规格与实现已偏离，文档未同步**。

---

## 5. 规划（P0 → P3）

| 阶段 | 内容 | 完成判据 | 状态 |
|---|---|---|---|
| **P0** | 静态四连 → 风贰单账号 → 七账号队列（风贰不重复）→ AutoX dry-run → 风贰一次实机 100 体力游历 → 汇总 | 每账号三方对账 `/api/accounts` + `/api/automation/status` + 主城 OCR；AutoX 用独立 `autox-` runId，不冒充完整 bootstrap | **部分完成**：静态四连 + 真机 V1–V10 桥接验收 + web→真机链路已通过（§9）；账号业务四步待上机 |
| **P1** | 统一两套账号/配置状态；配置持久化；swipe / key / currentApp UI；仿真参数透传；WS meta 消费与自动重连；`/api/verify/run` REST | 前端不再有写死假账号冒充真机状态；刷新不丢配置；界面可直接触发验收 | **已完成**：两批代码（§7）+ 浏览器真机复核（ONLINE / WS meta / 尺寸不一致提示 / 启停按钮） |
| **P2** | AutoX 六项后置能力 + 体力 OCR + 倍率按钮 OCR 定位 + `backendUrl` 配置化 + `AutoXBridgeDevice` + `main.js` 单测 | 端侧能跑完整 bootstrap，不依赖硬编码 IP / 坐标 | **可静态验证部分已完成**（§7.3）；六项后置真机能力 + `AutoXBridgeDevice` 待办，坐标签名与体力文案待真机 OCR 实测 |
| **P3** | 建角录屏、新手引导、完整提升链、2 倍速、断点续跑、`targetChapter`；规格② §9 的 11 项待实测；知识库词典接入；模板清理、坐标外置、鉴权、文档同步 | 单次 bootstrap 端到端验收成立；规格与代码一致 | 待办 |

依据：`.trae/...md:71-77`（P0）、`progress.md:79` + 本轮代码审查（P1）、`.trae/...md:60`（P2）、规格② §9 与 §10（P3）。

---

## 6. 验证基线（2026-11-15 第四批真机验收后复跑）

| 检查 | 命令 | 结果 |
|---|---|---|
| 类型检查 | `npm run lint` | 通过 |
| 生产构建 | `npm run build` | 通过，488.97 kB JS / 60.40 kB CSS |
| 后端测试 | `cd backend && env -u PYTHONPATH -u PYTHONHOME -u PYTHONSTARTUP .venv/bin/python -m pytest -q` | **360 passed**（exit 0，含 `test_launcher.py` 29 项） |
| 前端单测 | `./node_modules/.bin/tsx --test src/api/deviceClient.test.ts src/core/decision.test.ts src/core/pipelineConfig.test.ts src/core/mirrorStream.test.ts` | **27 passed** |
| 端侧单测 | `node --test autox/config.test.js autox/logic.test.js autox/main.test.js` | **42 passed** |
| 真机 V1–V10 | `cd backend && env -u PYTHONPATH -u PYTHONHOME -u PYTHONSTARTUP .venv/bin/python -m app.verify --out reports` | **9 PASS / 1 SKIP / 0 FAIL，exit 0**；`reports/verify-20261115-232831537807.{json,md}` |
| web 端验收 | `POST /api/verify/run` | **8 PASS / 2 SKIP / 0 FAIL，`ok=true`** |
| 端侧配置生成 | `bash scripts/gen-autox-config.sh --output /tmp/capyauto-autox-config.json` | 通过，端口取自 devgate（8084），IP 取自本机 LAN |

> ⚠️ 环境坑：在 agent 默认环境直接跑 pytest 会报 16 个 `FileExistsError: /private/var/.../pytest-of-root`，根因是 WorkBuddy shim 的 `sitecustomize.py` 拦截 `mkdir`，**不是项目代码问题**。需显式清变量：
> `env -u PYTHONPATH -u PYTHONHOME -u PYTHONSTARTUP .venv/bin/python -m pytest -q`
> CI / 自动化脚本里必须照此处理。另：本机 `pytest -q` 不打印 `N passed` 汇总行，且 `| tail` 会吞掉退出码；确认全绿须单独取 `exit=0` 并数进度点（本轮 360 个）。
> 本地端口探测一律 `curl --noproxy '*'`；`scripts/web.sh start --backend` 用 nohup 起的进程会在工具会话结束时被回收，需改用受管后台任务直接跑 `.venv/bin/python -m app` 才能跨调用存活。

---

## 7. 四批实现进度（2026-11-15）

### 7.1 第一批：验收 REST 与真机控制闭环

按 TDD 执行：先写 `test_api_verify_run.py` 并确认红灯（模块不存在），再实现，5 个测试转绿；前端改动后重跑静态四连全绿。

| 文件 | 变更 |
|---|---|
| `backend/tests/test_api_verify_run.py` | **新增** 5 个测试：无设备结构化结果、skip 生效、非法检查项 422、serial 透传、并发 409 |
| `backend/app/schemas.py` | 新增 `VERIFY_CHECK_IDS` 与 `VerifyRunRequest`（skip 校验并归一化大小写） |
| `backend/app/api/verify_run.py` | **新增** `POST /api/verify/run`：复用 `verify.run_checks`，独立线程避免阻塞事件循环，`_RUN_LOCK` 防并发操作同一设备，返回 `deviceOnline/summary/checks/hint` |
| `backend/app/main.py` | 挂载 `verify_run.router` |
| `src/types/device.ts` | 新增 `CurrentAppPayload` / `VerifyCheckPayload` / `VerifyPayload` / `SwipeDirection` |
| `src/api/deviceClient.ts` | 新增 `verifyRun()`；`tap()` 增加 `pressStdev` 透传 |
| `src/api/deviceClient.test.ts` | **新增** 2 个测试：verifyRun 请求体、tap 参数透传 |
| `src/hooks/useDeviceBridge.ts` | 新增 `swipe` / `pressKey` / `refreshCurrentApp` / `runVerify` 及对应 state；`tap` 支持按压与抖动参数；会话切换清理 `currentApp`；验收用独立 `verifyBusy` 避免长时间锁死其它按钮 |
| `src/components/DeviceDrawer.tsx` | 「校验环境」从恒 `null` 改为展示 V1–V10 逐项 PASS/FAIL/SKIP + 摘要 + 离线提示；新增「真机控制」卡片（四向滑动、back/home/app_switch、查询当前应用） |
| `src/App.tsx` | 消除三处占位：`onVerify`、`verifyResult`、`onRecordTouch`；真机点击透传仿真域的 `pressDurationMean / gaussianStdev / pressDurationStdev` |

**消除的缺口**：`/api/verify/run` 未实现（`progress.md:79`）、「校验环境」按钮只写日志、`swipe`/`key`/`currentApp` 三个定义了从不调用的接口、`onRecordTouch` 空函数、仿真配置对真机无效。

**本批未做**：P0 真机验收（需 Master 上机）、P1 剩余状态统一与参数入口（已由 §7.2 完成）、P2/P3 全部。

### 7.2 第二批：P1 收口（配置 / 账号 / 参数 / 镜像链路）

以「先抽纯函数 + 单测，再接 UI」推进，核心逻辑（配置清洗、帧解析、退避）都有独立 `node:test` 覆盖。

| 文件 | 变更 |
|---|---|
| `src/types/pipeline.ts` | 新增 `OcrRegion`、`AutomationConfig`；`PipelineConfig` 扩展全部真机自动化字段 |
| `src/core/pipelineConfig.ts` | **新增** 唯一默认配置源、脏数据清洗与后端 pydantic 对齐的范围钳制、localStorage 读写降级、队列文本解析、`toAutomationConfig` |
| `src/core/pipelineConfig.test.ts` | **新增** 8 个用例：默认值 / 脏数据 / 未知键 / region 合法性 / 存取往返 / storage 不可用 / 队列解析 / 字段隔离 |
| `src/hooks/usePipelineConfig.ts` | **新增** 全应用唯一配置状态源，变更即持久化，提供 `setConfig` / `patchAutomation` / `resetConfig` |
| `src/data/demoAccounts.ts` | **新增** 写死演示账号从 `App.tsx` 隔离，注释明确「不是设备事实源」 |
| `src/core/mirrorStream.ts` + `.test.ts` | **新增** WS 文本帧解析（meta / error / pong）、1→2→4→8s 指数退避、尺寸不一致检测，5 个用例 |
| `src/components/DeviceMirror.tsx` | 消费 meta（seq / 分辨率 / fps / 降级）、15s ping 心跳、断流自动重连、手动跳过退避、断流文案与链路信息 |
| `src/components/AccountMatrix.tsx` | 新增 `RealAccountMatrix`（只读 `/api/accounts` 的 `works`/`lastRun`/战力/体力 + 刷新）；仿真表格加演示徽标与「切到真机」入口 |
| `src/components/DeviceDrawer.tsx` | 配置改 patch 更新；新增 `maxRuns` / `serverTo` / 允许宝石突破 / 账号队列编辑与一键填充 / OCR 区域 / 恢复默认；队列与区域用草稿态避免中间值被清洗掉 |
| `src/api/deviceClient.ts` + `.test.ts` | `ocr()` 支持归一化 region；新增 2 个用例覆盖 region 与全参数 `automationStart` 请求体 |
| `src/hooks/useDeviceBridge.ts` | 移除第二份 `automationConfig`；`startAutomation(task, config)` 全参数透传；`runOcr(region)`；新增 `refreshAccounts()` |
| `src/App.tsx` | 接入唯一配置源；账号页按仿真/真机分流；顶栏「启动/急停」在真机模式真正调后端并跟随 `automation/status`；DeviceDrawer 新入口全部接线 |

**消除的缺口**：双状态割裂、配置无持久化、`allowGemTalentBreakthrough` / `serverTo` / `maxRuns` / `ocr.region` 无界面入口、WS meta 被忽略、断流无自动重连、真机模式顶栏按钮只写日志不调后端、「点击刷新重连」文案无对应按钮。

**本批未做**：P0 真机验收、P2 端侧能力（已由 §7.3 推进可静态验证部分）、P3 全部。

### 7.3 第三批：P2 端侧配置化 / 体力门槛 / 可注入单测

按 TDD 执行：先写 `config.test.js`、`main.test.js` 与扩充 `logic.test.js`（红灯 11 项 + 后端 2 项），再实现，端侧 42 项与后端 2 项转绿。

| 文件 | 变更 |
|---|---|
| `autox/config.js` + `config.test.js` | **新增** 分层配置：`normalizeBackendUrl`（正则实现，不依赖 AutoX Rhino 未必有的 WHATWG `URL`）、`mergeConfig`、`resolveConfig`（覆盖优先级 + 非法值显式拒绝）、`loadConfig`（读 `config.json` 与可选 `config.local.json`）；10 个用例 |
| `autox/config.json` | `backendUrl` 从写死 `http://192.168.0.113:8084` 改为空；新增 `stamina.minRequired`、`loop.maxStaminaPolls`、`multiplierPlus`（兜底归一化坐标 / OCR 锚点 / 强制锚点开关） |
| `scripts/gen-autox-config.sh` | **新增** 从 `devgate port capyauto-flow backend` + 本机 LAN IP 生成 `autox/config.local.json`，支持 `--ip / --port / --dry-run / --output`；探测不到 IP 直接报错，不猜 |
| `.gitignore` | 追加 `autox/config.local.json`（含机器相关 IP，不入库） |
| `autox/logic.js` | 新增 `parseStamina`（对齐后端 `SERVER_STAMINA_PATTERN`）；`tier` 阶段体力门槛（未确认 → 有限等待 → 失败；低于 100 → 失败）；倍率按钮优先 OCR `+` 锚点、兜底坐标来自配置、可强制禁用盲点；`buildReport` 支持证据字段；**`dryRun` 改为零点击推进完整状态机** |
| `autox/main.js` | 重构为 `run(globals)` 可注入 runtime（真机默认仍自动执行），配置加载失败显式报错；`multiplier_plus` 点击支持 OCR 像素坐标；实机回报附 `staminaBefore` |
| `autox/main.test.js` | **新增** 12 个用例：dry-run 全链路、实机三次白名单点击、OCR 定位加档、体力未确认/不足、危险词、权限/无障碍预检、音量下急停、URL 两种来源、缺配置 |
| `autox/logic.test.js` | 扩充到 20 个用例（体力解析、锚点定位、配置坐标、`buildReport` 证据、dryRun 新语义） |
| `backend/app/schemas.py` + `api/accounts.py` | `AccountRunReport` 新增可选 `staminaBefore`（`ge=0`），写入 `lastRun.progress`；`tests/test_accounts.py` 新增 2 个用例（写入 + 负数值 422） |
| `src/types/device.ts` + `components/AccountMatrix.tsx` | 真机账号页展示「游历 X 体力 · 起始体力 Y」，让端侧证据在共享账号视图里可见 |

**消除的缺口**：`backendUrl` 写死 IP/端口、端侧无体力 OCR（与 `.trae:27-28` 不符）、加档按钮坐标写死在代码、`main.js` 无法单测、`dryRun` 在第一个点击就结束（根本验不到 20 倍与结算）、端侧体力证据未进入共享账号视图。

**行为变更（上机前必读）**：
1. `dryRun` 不再返回 `completed` 于第一个点击，而是零点击走完 `account → entry → tier → settlement → done`，因此现在能真正验证角色名、20 倍档、体力与结算文案；仍保证零点击、`travelSpent=0`。
2. `autox/config.json` 不再自带后端地址。上机前先跑 `bash scripts/gen-autox-config.sh`（或注入 `CAPYAUTO_BACKEND_URL`），否则脚本显式抛「配置加载失败」而不是连到旧 IP。
3. 体力未确认或不足 100 时**绝不点击开始游历**；`maxStaminaPolls` 默认 3 次 OCR 重试后停止。

**仍未做**：P2 六项后置真机能力与 `AutoXBridgeDevice`、结算后体力差 = 100 的核验、P3 引擎/规格收口、模板残留清理（`express` / `@google/genai` / `scriptFiles.ts` 旧模板）、仿真分支 `BATTLE_DEFEAT` / `ACCOUNT_SWITCHING` 与战败熔断闭环。

### 7.4 第四批：真机启动链路修复与 V1–V10 / web 端到真机验收

按 TDD 执行：先写 `tests/test_launcher.py`（26 项红灯：模块不存在 / 函数未定义），实现后 29 项转绿；后端全量 360 项 exit 0。

| 文件 | 变更 |
|---|---|
| `backend/tests/test_launcher.py` | **新增** 29 个用例：UI 标签解析（文字优先 / 面积优先 / 忽略空 text）、翻页、HOME 键、宿主安装探测与 auto 决策、点击坐标、沙箱复用、误点原生包报错、超时错误、停止宿主回退、`LauncherSpec` 配置解析 |
| `backend/app/config.py` | 新增 `_env_launch_mode` / `_env_point` 与 5 个 `launcher_*` 字段（`CAPYAUTO_LAUNCH_MODE` / `CAPYAUTO_LAUNCHER_HOST_PACKAGE` / `..._ICON_LABEL` / `..._ICON_POINT` / `..._WAIT_S`），取值带范围/枚举校验 |
| `backend/app/device/packages.py` | **新增** `LauncherSpec`、`parse_launcher_bounds(require_text=)`、`is_host_installed`、`should_use_launcher`、`dump_ui_xml`、`launch_via_launcher`（HOME 键 + 最多 4 页滑动 + 轮询等待 + 前台沙箱校验）；`launch_app` 加 `launcher` 参数；`stop_app` 加宿主强杀回退 |
| `backend/app/device/adb_device.py` | 构造时注入 `LauncherSpec` 与 `host_package`，`launch_app` / `stop_app` 透传 |
| `backend/app/deps.py` | 新增 `build_launcher_spec(settings)`，唯一装配点 |
| `backend/app/verify.py` | `VerifyContext` 注入 `LauncherSpec`；CLI 新增 `--launch-mode auto\|package\|launcher`；`run_checks` 增加可选 `launcher` 参数 |

**真机调试的两轮修正**（缺一不可）：

1. 首版用 `am start -a MAIN -c HOME` 回桌面，在 HONOR 上会重开桌面并落到另一页，`uiautomator` 匹配到 `text=""` 的「YOYO 建议」小图标（bounds `[99,1184][303,1388]`），点它**直启了游戏原生包**（前台 `PLMainActivity`、宿主进程为空）。真正带文字标签的 shortcut 在 `[882,1540][1164,1870]`。
2. 改为 `input keyevent 3` 回桌面、最多翻 4 页、**只认 `text=` 标签节点**、同页多命中时按节点面积取最大；启动后必须校验前台 `package == host_package`，若发现游戏以原生包起来且宿主进程不存在，直接抛 `AdbError` 而不算成功。

**真机实测结果**见 §9：CLI 9 PASS / 1 SKIP、REST 8 PASS / 2 SKIP、`/api/app/launch` 返回沙箱 STUB1、`/api/app/stop` 使 game/host pid 同时消失、浏览器真机模式 ONLINE + WS 帧 + 顶栏启动/急停闭环。

---

## 8. 边界与风险

- **不编数据**：`/api/verify/run` 在无设备时如实返回 V1 FAIL + 其余 SKIP 与 `deviceOnline=false` 提示，不用假 PASS 充数；真机账号页后端无记录时显示「暂无账号记录」，不拿演示数据补位。
- **配置边界**：持久化只发生在浏览器 localStorage，是「界面默认值」而非服务端配置；后端仍读自身默认值，任务参数由每次请求体带入。换浏览器 / 清缓存会回到 `DEFAULT_PIPELINE_CONFIG`。
- **自动重连风险**：镜像断流会无限退避重连（上限 8s），会话失效时每次重连都会拿到 4404 错误帧；这是为了让 scrcpy 偶发断流自愈，但设备主动断开后应手动切回仿真或断开会话，避免空转。
- **分支状态**：`.superpowers/sdd/progress.md:80` 定稿 `Branch state: 保留不合入（用户决定）`；`.trae/...md:69` 约定「不创建 git commit、不做无关重构」。四批均沿用：未提交、未改分支、未动引擎业务逻辑；`autox/` 是第三批按 §5 的 P2 规划主动改造的范围，第四批改的是设备启动层。
- **启动链路强约束**：`auto` 模式依赖「宿主包已安装」+「桌面存在带文字标签的快捷方式」。桌面改名、换页、换启动器、游戏脱离变速器独立安装都会导致启动失败并显式报错，这是安全方向，不要为了跑通而降级到直启原生包 —— 那会绕开倍速环境，运行态不等价。`--launch-mode package` 只用于对照实验。
- **急停是协作式的**：`POST /api/automation/stop` 只置停止标志，等当前 OCR / 点击动作结束后才收敛；真机实测 `daily` 约 8s、`all` 约 15s 才从 `running` 变 `stopped`。期间日志为「收到停止指令，等待当前动作结束」，前端按钮保持「急停流水线」，**不是卡死**。若需强制中断需在引擎层加取消点，当前未做。
- **安全**：后端仅靠 localhost CORS 白名单，无鉴权；`src/data/scriptFiles.ts` 导出的 `config.json` 含明文示例账号口令；真机上跑前需确认不会误触主账号「你瞅啥呢」与任何付费/广告入口。
- **规格与实现偏离**：规格① §12 的非目标条款已失效，下一次改规格时应同步修订，否则后续评审会按错误前提判断。
- **端侧配置边界**：`autox/config.local.json` 由脚本生成、不入库，含当前 LAN IP；换网络或换端口必须重跑脚本。后端需监听 `0.0.0.0` 而非仅 `127.0.0.1`，手机才能访问。缺配置时脚本失败是**有意设计**，不是 bug。
- **体力 / 锚点未经真机 OCR 实测**：`125/200` 文案与「+」按钮锚点来自 ADB 轨的 `SERVER_STAMINA_PATTERN` 与既有坐标注释，AutoX 端 OCR 引擎不同，识别结果可能不一致。当前策略是「识别不到就停」（安全方向），真机验收时应先 dry-run 观察识别结果，再调整 `ocrAnchors` / `maxStaminaPolls`，**不要放宽体力门槛**。`requireOcrAnchor` 默认 `false`，意味着仍可能使用配置里的兜底坐标 `[0.725, 0.835]`（只是不再写死在代码中）；要彻底禁用盲点需显式设为 `true`。
- **证据边界**：`staminaBefore` 只在非 `dryRun` 上报，是「点击开始前 OCR 读到的体力」，**不是**结算后核验的体力差；`.trae:74` 要求的「每次游历体力差为 100」端侧尚未闭环。

---

## 9. 真机验证执行记录（2026-11-15 22:19–23:35）

**结论：真机 `ANASUT3C20010476` 已接入，V1–V10 桥接验收 9 PASS / 1 SKIP / 0 FAIL，web 端到真机的会话、镜像、启动游戏、自动化启动/急停链路全部实测通过。核心阻塞「游戏必须经冲鸭变速器桌面快捷方式启动」已定位并按 TDD 修复。仍未完成的是涉及账号业务的四步 P0 验收（需游戏停主城 + 账号确认）。**

### 9.1 设备与环境

| 项 | 实测 | 判定 |
|---|---|---|
| 设备 | `ANASUT3C20010476`，HONOR ALP-AN00 / Android 14 / 1200×2652 / arm64-v8a | **在线** |
| adb / scrcpy / OCR | 1.0.41 / 3.3.1 / rapidocr-onnxruntime | 依赖齐全 |
| 后端 | `CAPYAUTO_DEVICE_BACKEND=adb`，:8084，`/api/health` → `device_backend=adb` | 已就绪 |
| 前端 | :5178 HTTP 200，`VITE_BACKEND_URL` 默认 `127.0.0.1:8084`，CORS 放行 | 已就绪 |
| 启动配置 | `launch_mode=auto`，宿主 `com.joke.chongya`，图标标签「冒险者日记」 | 已生效 |

> 22:19 曾因设备未连接得到 `V1 FAIL / V2–V10 SKIP`（报告 `verify-20261115-221931696645.*`），那是离线如实结果，保留在 §9.6 作为对照。

### 9.2 启动链路问题定位（Master 反馈）

Master 反馈「直接通过冒险者日记的 app 启动不对，实际要通过冲鸭变速器启动，即桌面的冒险者日记」。adb 实测结论见 §2.4：桌面图标是 `com.joke.chongya` 发布的 pinned shortcut `cy_com.hb.cncapy.and`，游戏跑在其沙箱 `MundoActivity$Companion$STUB1` 内；直启游戏包会绕开变速器，沙箱 Activity 又 `not exported` 导致 shell 无法 `am start` 复现，停止也必须强杀宿主。

首次按「桌面图标」实现后 API 仍直启原生包，二次定位根因：`am start -c HOME` 在 HONOR 上落到桌面另一页，匹配到 `text=""` 的「YOYO 建议」小图标 `[99,1184][303,1388]`，真正带标签的 shortcut 在 `[882,1540][1164,1870]`。修复后（HOME 键 + 翻页 + 只认 `text=` 标签 + 前台沙箱校验）`POST /api/app/launch` 返回：

```
{"package":"com.hb.cncapy.and","activity":"top.bienvenido.mundo.manifest.MundoActivity$Companion$STUB1","running":true,"pid":24034,"ok":true}
```

同时 `pidof com.hb.cncapy.and=24034`、`pidof com.joke.chongya=23978`、前台 `com.joke.chongya/...STUB1`；`POST /api/app/stop` 后两个 pid 均为空 —— **宿主停止生效**。

### 9.3 V1–V10 真机验收结果

| 路径 | 命令 | 结果 |
|---|---|---|
| CLI | `cd backend && env -u PYTHONPATH -u PYTHONHOME -u PYTHONSTARTUP .venv/bin/python -m app.verify --out reports` | **9 PASS / 1 SKIP / 0 FAIL，exit 0**；`reports/verify-20261115-232831537807.{json,md}` |
| Web 端「校验环境」 | `POST /api/verify/run` | HTTP 200，**8 PASS / 2 SKIP / 0 FAIL**，`deviceOnline=true`、`ok=true` |

CLI 逐项：V1 adb 在线 / V2 1200×2652 Android 34 / V3 40 帧 P95=213ms / V4 PNG 尺寸一致 / V5 点击后前台变化（`HWSettings → BluetoothSettingsActivity`）/ V6 scrcpy 注入 105ms（阈值 ±50ms）/ **V7 启动 pid=24034 → 强杀宿主后进程消失** / V8 SKIP（设备仅一个用户，不支持应用分身）/ V9 飞行模式开读回 True、关读回 False / V10 OCR 2 条、最高 `HABB` 0.99、ocrMs=1502（阈值 5000ms）。

REST 路径差异：V5 SKIP（当时前台停在设置页，点击后未变化），其余一致；V7 pid=27796（第二轮确实经桌面快捷方式重新拉起）。**两轮均无 FAIL、无假 PASS，V8 SKIP 是设备能力如实判定**。

### 9.4 web 端到真机的全自动流水线链路

**API 层（真机 adb 模式，会话 `s2`）**

| 步骤 | 实测 |
|---|---|
| `POST /api/session` | HTTP 200，`s2`，576×1280 @ 5fps |
| `/ws/mirror` | 收到 5 帧 JPEG（528410 字节）+ meta `{"type":"meta","seq":0,"width":576,"height":1280,"fps":5,"degraded":false,"mode":"scrcpy"}` |
| `GET /api/app/current` | 桌面 `com.hihonor.android.launcher/.unihome.UniHomeLauncher` |
| `POST /api/automation/start {task:daily,maxRuns:1}` | `status=running` |
| `POST /api/automation/stop` | 日志「收到停止指令，等待当前动作结束」，8s 后 `stopped`；日志如实写「未能确认冒险页 / 本次没有可领取的内容，不计入完成」 |
| `POST /api/app/launch` | 沙箱 `...STUB1`，game pid 1940 + host pid 1873 |
| `POST /api/app/stop` | 两个 pid 均变 `none` |

**浏览器层（本机 Chrome headless + CDP 实际点击，非 mock）**

- 切「真机」后顶栏显示 `ONLINE / ANASUT3C20010476 / 576×1280 / 5 fps / scrcpy`，镜像 `canvas 576x1280` 建立，WS meta 驱动出「尺寸不一致」提示（物理 1200×2652 vs 缩放流 576×1280）；设备抽屉真机控制按钮齐全（启动/停止游戏、校验环境、四向滑动、按键、OCR、成长、日常）。
- 点顶栏「启动全自动流水线」→ `/api/automation/status` 变 `running, task=all`，按钮变「急停流水线」；点「急停流水线」→ 约 15s 后收敛 `stopped`。
- `airplane_mode_on` 前后均为 `0`（未被自动化改动）；`backend/.data/accounts.json` 时间戳保持 18:18，**未写脏账号数据**。

> 为避免误触账号，浏览器与 API 两次自动化都先把游戏 force-stop，画面为桌面/设置页，引擎在 OCR 阶段如实失败。这是**链路验证**，不是「游戏主城里的完整业务验收」。

### 9.5 仍需上机执行的四步（Master 操作）

1. 让游戏经桌面「冒险者日记」进入**主城**，确认账号为风贰；**绝不触碰主账号「你瞅啥呢」**、不点任何付费/广告入口。
2. 风贰单账号全流程，核对 `/api/accounts` + `/api/automation/status` + 主城 OCR 三方一致。
3. 七账号队列（风贰不重复），逐账号核对上方三方证据。
4. 端侧 AutoX：先 `bash scripts/gen-autox-config.sh` 生成 `autox/config.local.json` → dry-run 观察体力与「+」锚点识别 → 用独立 `autox-` runId 做一次实机 100 体力游历，并核验结算后体力差 = 100。
5. 最终汇总。若 V1–V10 需复跑：`cd backend && env -u PYTHONPATH -u PYTHONHOME -u PYTHONSTARTUP .venv/bin/python -m app.verify --out reports`；后端 :8084 需保持 `CAPYAUTO_DEVICE_BACKEND=adb` 运行（受管后台任务方式，见 §6 环境坑）。

### 9.6 历史离线记录（22:19，设备未连接时的如实结果，保留对照）

- CLI → exit 1，`V1 FAIL`（`adb devices 中没有 state=device 的设备`），`V2–V10 SKIP`；报告 `verify-20261115-221931696645.{json,md}`。
- `POST /api/verify/run` → HTTP 200，`deviceOnline=false`、`{passed:0, failed:1, skipped:9, ok:false}` + `hint: 请连接真机后重新校验`。
- 设备缺失时控制链路如实拒绝：`/api/devices` → `[]`、`status` → `idle`、建会话 → 404 `DEVICE_NOT_FOUND`、启动 → 404 `SESSION_NOT_FOUND`、急停幂等。
- 当时曾在隔离 `:8085` mock 后端验证 `start → running → stop → stopped` 闭环（用 `CAPYAUTO_ACCOUNTS=/tmp/...` 隔离账号文件），**该结果不是真机验收**，现已由 §9.4 的真机链路取代。

## 10. 2026-11-16 真机复验：包名显示与全自动流水线动作

Master 反馈两处不符：Web「启动游戏」仍显示 `com.hb.cncapy.and`；点全自动流水线后没有推关、公会捐献/讨伐、副本挑战或扫荡。**四个根因，已全部定位，其中三个已修并上机复验。**

| # | 根因 | 处理 |
|---|---|---|
| 1 | Web 应用区那行是前端静态常量 `DEFAULT_PACKAGE`，不是真机状态；且 `POST /api/app/launch` 的 `package` 字段直接回显请求包名（游戏包），`activity` 却是宿主 STUB1，自相矛盾 | `adb_device.py::_launch_sync` 在 launcher 生效时改回真实前台（宿主包 + STUB1 + host pid）；`useDeviceBridge.launchGame` 启动后直接把 launch 响应写入 `currentApp`；抽屉应用区改显示「启动宿主 / 被托管游戏包 / 真实前台」三行 |
| 2 | `all` 原本只有 日常/公会收集/船/growth，**没有**公会捐献、讨伐、副本挑战/扫荡；且公会入口写死文字「公会」，真机主城是纯图标无文字 → 公会阶段 100% 静默跳过 | `engine._run_all` 逐阶段隔离执行 7 段：日常 → 公会收集 → 免费捐献 → 公会讨伐 → 船 → 副本挑战/扫荡 → 成长；新增 `_guild_raid()`、`guildRaids`/`dungeonSweeps` 进度；`TASK_GUILD` 单任务也补图标路径；阶段写入 `progress.phase` 并出汇总日志；开头保留主账号「你瞅啥呢」护栏 |
| 3 | `_back_to_adventure` 在「家园」等子页面先点左下角箭头，那里其实是「编辑」按钮，切进编辑态后 6 次兜底全失效 → 后续入口和阶段被整片跳过 | 实测截图确认右上角 X（0.932, 0.132）才是关闭位；新增 `SUBPAGE_CLOSE_WORDS`，命中子页面标题时优先点 X，不再误触左下；`test_back_to_adventure_closes_home_page_with_top_right_x` 覆盖 |
| 4 | 上一次急停停在推关局内时，所有子页面都回不了主城；旧实现只留下一堆静默跳过 | `_run_all` 开头检测 `_in_run()` 并打明确 warn；完整「局内自愈」仍待做（见下） |

**上机证据（真机 `ANASUT3C20010476`，`CAPYAUTO_DEVICE_BACKEND=adb`）**

- `POST /api/app/launch` → `{"package":"com.joke.chongya","activity":"...MundoActivity$Companion$STUB1","running":true,"pid":22180,"ok":true}`；`GET /api/app/current` 完全一致。Web 显示的旧包名已消除。
- `task=all` 启动日志明确列出阶段清单；真机 phase 依次 `daily → guild`，daily 实际点击 5 次「挂机奖励」，修复 #3 后能从「家园」继续走到「特权卡」「活动」（修复前是整片跳过）。
- 单独 `task=growth`、`travelStamina=0` 复验推关：phase `travel → stage`，日志出现「第 1 轮推关：点击「开始」」「选择技能：「经验」」，证明推关动作真实发生。
- 静态回归：`npm run lint` / `npm run build`（489.97 kB）/ 前端 27 / AutoX 42 / 后端全量 pytest **0 失败**。

**仍需校准（不编造、如实标注）**

1. 公会捐献/讨伐、副本挑战/扫荡的**真机 UI 文字锚点尚未逐页核对**：真机公会信息页实测文字是「公会信息 / 捐献 / 公会管理」，代码用「公会大厅」确认，认不出时明确 warn 跳过而不是盲点。需按各子页实拍 OCR 补齐锚点表。
2. 局内残留（急停停在「选择技能」）目前只告警，未自动打完这一局；建议后续把 `_run_all` 开头的 warn 升级为「先 `_play_run` 结算再继续」。
3. OCR 约 3s/帧，`daily` 单阶段实测约 3.5 分钟，全流程偏慢；赶时间可用 `travelStamina=0` 或单任务分段验证，或后续上 lean 回放模式。
4. 后端 :8084 用受管后台任务运行；若会话回收退出，用 `cd backend && env -u PYTHONPATH -u PYTHONHOME -u PYTHONSTARTUP CAPYAUTO_DEVICE_BACKEND=adb .venv/bin/python -m app` 重启。**不要**用 `scripts/web.sh start --backend`（nohup 会被工具会话回收，端口静默消失且日志无 shutdown 记录）。

## 11. 2026-11-16 二次复验：天赋误报、挖宝卡住、局内自愈、精简提速

Master 反馈「成长任务天赋提升失败」「挖宝卡住」。定位到五个独立问题，均已修并有回归测试锁定。

| # | 根因 | 处理 |
|---|---|---|
| 1 | 天赋材料不足时游戏弹「道具获取 / 前往 / 30元」，旧代码只看文本变化就记一次提升 → **虚报成功**，后续盲点还有付费风险 | 新增材料弹窗识别：同时命中获取引导词与货币/价格才算；只点底部 X 关闭；升级成功必须比对「等级 N」数字真实增长。`test_has_material_dialog_and_close_only_taps_x` 等锁定 |
| 2 | 挖宝翻牌页识别后无限循环，翻完仍不退出 | `DIG_HINT`（「翻出三个相同卡牌」）才进翻牌分支，`DIG_MAX_ROUNDS` 限制轮数；「挖宝」入口按钮不再被误认成翻牌页 |
| 3 | 技能弹窗确认按钮找不到：真机底部实际是「领悟 / 下一天」，旧代码找「选择技能」标题 | 新增 `_confirm_button()` + `SKILL_CONFIRM_WORDS = ("领悟","下一天","继续","确定")`。更关键是**卡住真因**：`action is not None and stuck < 3` —— 选卡期间屏幕签名连续相同累积 `stuck`，出弹窗后即使出现「下一天」也不点，又因 `action is not None` 走不到 in_run 兜底，只能空转到放弃。修：技能等有效操作后 `stuck=0`，并允许新 action 文本直接点击 |
| 4 | 急停停在推关局内后，后续任务静默跳过、页面回不了主城 | `_recover_if_stuck()` 最多杀进程重启一次；二次仍卡置 `_fatal_stuck`，`_stage`/`_growth`/`_run` 检查后转 error 并明确告警，不再假装成功 |
| 5 | 精简（lean）模式没有实际提速 | lean 参数放实例属性，默认与全量一致；只在 `start(stage_mode="lean")` 时压缩：点击间隔 55%、选项补点 0.06–0.14s、jitter 0.008、精简模式多一次续跑。**`check_every` 不覆盖用户显式值**，直接调 `_replay_stage` 的单测不被 lean 参数污染 |

**上机证据（真机 `ANASUT3C20010476`）**

- `growth`（`travelStamina=0`, `maxRuns=1`）：**没有再出现「天赋XX提升一次」误报**；天赋页残留材料弹窗被识别并关闭。暴露遗留问题：从天赋页调 `_ensure_adventure` 返回冒险页失败（见下）。
- 从第 2 天局内启动推关：日志连续出现「检测到进行中的一局，先完成当前关卡 → 点击下一天 → 点击战斗 → 选择技能：反击光枪 → 点击下一天 → 点击战斗 → 选择技能：剑雨 → 点击下一天」，**推关卡住问题根治**（旧实现选完技能即停）。240s 观察窗内持续推进，由 Master 主动急停；急停正常收敛到 `stopped`。
- 静态回归全绿：`npm run lint`、`npm run build`、前端 27、AutoX 42、后端 pytest **391 passed**。
- 期间两次后台后端 exit 143 均为主动 kill 旧进程以加载修复，属预期 SIGTERM，不是崩溃。

**仍需确认（如实标注，未上机项不写明验证通过）**

1. 天赋页没有可识别的返回锚点：底部导航被滚出可视区，`_ensure_adventure` 从天赋页返回冒险页失败 → 该场景下提升阶段会跳过。需补天赋页专用返回坐标/文字。
2. 挖宝上限、杀进程自愈、lean 提速只完成单元测试 + 静态回归，**尚未在真机逐项触发验证**；lean 的实际提速比例需 A/B 上机确认。
3. 真机屏幕出现「试用已结束，变速已暂停」——冲鸭变速器试用到期，游戏无加速，OCR 单帧约 3s，全流程偏慢；不影响动作正确性。
4. §10 遗留的公会捐献/讨伐、副本挑战/扫荡文字锚点逐页校准仍未做。

## 12. 2026-11-16 六项日常专项（Master 新增需求）

Master 要求日常任务新增 6 个入口的免费领取/强化/挖矿动作。全部在真机逐页采集 OCR 锚点后 TDD 实现，挂到 `TASK_DAILY` 与 `_run_all` 的 daily 阶段，单项异常隔离，进度与汇总日志独立计数。

| # | 需求 | 真机锚点与实现 | 进度字段 |
|---|---|---|---|
| 1 | 商城→底部冒险者补给箱→免费领取 | 商城长列表下滑 6 次找「冒险者补给箱」(≈0.263,0.548)；「免费」按钮 (≈0.286,0.748)。**倒计时文本「06:07:12后免费」本身含「免费」，必须先排除，否则误点**（单测抓到的真实 bug）；无文字按钮时点补给箱卡片下方坐标兜底 | `supplyClaims` |
| 2 | 商城→礼包商城→免费礼包 | 「礼包商城」(≈0.621,0.876)，「免费礼包(0/1)」+「免费」(≈0.790,0.378)；显示「已领取」跳过 | `giftClaims` |
| 3 | 装备→可强化装备→一键强化 | **真机无「一键强化」文案**，最近等价动作是工坊「一键合成」(≈0.886,0.364)；装备详情仅「升阶/合成提升等级」。按真实存在的一键合成实现，日志注明「真机等价一键强化」 | `enhanceSteps` |
| 4 | 冒险→左侧特权卡→领取全部 | 「特权卡」(≈0.079,0.251)，底部「领取全部」(≈0.501,0.958) | `privilegeClaims` |
| 5 | 三横→邮件一键领取 / 好友→游戏好友→一键领取赠送 | 三横 (≈0.081,0.159)；「邮件」→「一键领取」(≈0.676,0.735)；「好友」→「游戏好友」→「一键领取赠送」(≈0.501,0.728) | `mailClaims` / `friendClaims` |
| 6 | 活动→挑战→哥布林矿工→逐个挖掘 | 5×6 网格 30 格 `(0.19..0.79, 0.36..0.71)`，镐头 `N/60` 正则解析；命中「无法挖掘/镐头不足/明日再来」或无镐头停止；`GOBLIN_MAX_TAPS=80` 保护上限；**「自动挖矿」是付费功能，绝不点** | `goblinDigs` |

**关键工程修复（真机暴露、单测未覆盖）**

- `_daily_specials` 调度表最初直接放方法引用，`work()` 调用漏传 `session_id`，六项全报 `missing 1 required positional argument`。改为 lambda 绑定参数（与 `_run_all` 一致），并补回归测试验证确实透传。
- 首轮真机 **4/6 成功**（装备强化、特权卡、邮件、好友、哥布林矿工；哥布林挖满 30 格）；补给箱/礼包商城报「未找到底部商城入口」——**底部商城 tab 是纯图标、OCR 读不到「商城」文字**，而这两项缺坐标兜底（装备/特权卡已有）。新增 `_tap_nav_shop()`：OCR 命中则点，否则点已验证的图标坐标 `(0.100,0.941)`。
- 补给箱倒计时误判：`claim` 判定排除含「后免费」的项，避免把倒计时文本当领取按钮误点。

**真机复验（账号「风零」，`ANASUT3C20010476`）**

- 补测轮 6/6 全部触发成功：日志依次出现「补给箱：点击免费 / 商城入口无文字锚点用图标坐标兜底 → 免费礼包：点击免费 / 装备强化：工坊点击一键合成 / 特权卡：领取全部 / 邮件：一键领取 / 好友：一键领取赠送」；计数 `supplyClaims=1 giftClaims=1 enhanceSteps=1 privilegeClaims=1 mailClaims=1 friendClaims=1`，哥布林矿工继续挖掘中。
- 静态回归全绿：lint / build / 前端 27 / AutoX 42 / 后端 pytest **405 passed**（新增 `test_daily_specials.py` 14 项）。
- 期间多次 exit 143 均为主动 kill 旧后端加载修复，预期 SIGTERM。

**如实标注的遗留**

- 装备「一键强化」是映射工坊「一键合成」的等价实现，非字面同名按钮；若 Master 认领另有独立强化入口需再校准。
- 补给箱/免费礼包当前账号多为「倒计时中/已领取」，验证的是「正确识别并可点击」路径；真实扣奖励的领取结果依赖游戏侧状态。
- 哥布林矿工「自动挖矿」为付费功能，本实现只做逐个手动点击，挖满或镐头耗尽即停。

## 13. 2026-11-17 每日重置 API + 全账号流水线三问题分析

### 13.1 每日 8 点重置任务状态（已实现）

游戏每日 8 点重置日常，账号完成标记需同步归零。

- 后端新增 `accounts.reset_account_works(names=None, at=None)`：清空各账号 `works`（daily/guild/ship/stage 完成记录），写 `worksResetAt` 时间戳；**保留**账号身份、`power`/`stamina` 指标与 `lastRun` 历史。`names=None` 表示全部，传入名单只重置命中项，未知名字忽略。
- REST 新增 `POST /api/accounts/reset`，请求体 `{"names": [...] | null}`。
- 测试 `test_account_reset.py` 5 项全绿（全量/subset/未知名/时间戳/API 端点）；后端全量 **410 passed**。
- automation 已建：`CapyAuto 每日 8 点重置账号任务状态`，`FREQ=DAILY;BYHOUR=8;BYMINUTE=0`，ACTIVE，首次 2026-11-18 08:00（北京时间）。prompt 内含：先探活/必要时受管后台启动后端 → 调 reset → 核对 `/api/accounts` 全部 done=false → 输出结论；明确所有 curl 带 `--noproxy '*'`（本机 HTTP 代理坑）。
- **未即时重启后端加载 reset API**：全账号流水线正在同一后端进程中运行，重启会丢失流水线状态；待流水线跑完后重启加载。定时任务首次触发在次日，时间充裕。

### 13.2 全账号流水线三问题根因（代码级，结论待流水线跑完补）

Master 观察到三问题，本轮全账号流水线日志已全部复现。代码级根因如下（优化方案待真机取证后定稿）：

1. **公会升级 toast 误判未加入公会**：`_guild`/`_guild_raid` 用 `screen.find_exact(GUILD_HALL)` 精确匹配「公会大厅」确认进入；真机公会信息页实际是「公会信息/捐献/公会管理」，且进入瞬间若弹「公会升级」toast 会遮挡标题 → `hall is None` → 误报「未确认公会地图，跳过公会（可能未加入公会）」。日志中该 warn 在多个账号反复出现。

2. **游历点「挂机奖励」后未点「领取」**：「挂机奖励」在 `DAILY_CONFIG.collect_words`，由 `_collect_entries` 点击（日志 `游历：点击「挂机奖励」`）。点击后进入结算页需要二次点「领取」，但 `_collect_entries` 的循环用 `signature == last_signature` 提前 break——结算页动画帧未变化时即退出，漏掉后续领取。属状态机缺一步，非文案缺失。

3. **活动-副本未正确进入并完成挑战/扫荡**：日志模式「进入副本 → 界面长时间无响应，放弃当前关卡 → 挑战失败，改为扫荡 → 无扫荡入口，跳过」。根因是结构性错配：`_dungeons` 复用了**为推关设计**的 `_play_run()`（找下一天/战斗/选技能/结算），副本战斗界面按钮不同 → idle 6 轮放弃；失败后 `_sweep_dungeon` 重新开 activity tab 时可能仍在副本残留页，扫荡按钮 OCR 不识别。副本需独立的战斗/扫荡状态机与真机锚点取证，不能套推关循环。

> 三问题的修复需占用真机取证（公会 toast 表现、挂机奖励结算页按钮、副本战斗/扫荡页文案与坐标），当前真机被全账号流水线占用，**不做无取证的猜测性修改**。待流水线跑完输出完整结论后，再按证据逐项修。

## 14. 2026-11-17 流水线中断修复与全账号重跑

### 14.1 上一轮失败结论（已确认）
- 首次重跑在 **风零**（队列第 1 个账号）耗时约 57 分钟后报 `error`：`起号结束前未能回到冒险页，账号不记为完成`；其余 6 号 `lastRun` 仍是 `pending`，即**一个账号失败导致整队没有继续**。
- 真机取证：游戏停在「传说技能」事件转盘的 **转盘中…** 按钮，既不出结果也不出「返回」，按系统返回键无效；这是加速器下动画卡死，不是 OCR 漏识别。旧代码只能空转到单局超时，收尾 `_back_to_adventure` 再次失败 → 整号判失败。

### 14.2 本轮代码修复
1. **硬卡死即时自愈**：新增 `WHEEL_SPIN_HINT="转盘中"`，单局循环 8 轮仍无结果即置 `_hard_stuck` 并跳过普通「连续两局」阈值；抽出 `_restart_game()`，`_recover_if_stuck(force=True)` 与 `_back_to_adventure()` 共用「杀进程一次 → 经桌面 shortcut 重启 → 回冒险页」链路；重启仍失败置 `_fatal_stuck` 停止。真机 OCR 实测读不到「转盘中」小字，因此 `_wheel_stuck()` 补上下文兜底：只见到「传说技能」且没有「开始/继续/返回」即判卡住；重启额度按账号重置，避免第一号用掉后后续账号无法自愈。
2. **单号失败不阻断全队**：`_account_sweep` 捕获单号异常后写 `failed` 并继续下一个账号，只有写盘 `OSError` 或 `_fatal_stuck` 才中断；末尾汇总失败账号。
3. **重启残留清理**：`_ensure_adventure` 识别「您有未完成的冒险」并点「取消」，避免半局状态污染后续阶段。
4. **公会 toast 误判**：新增 `_enter_guild_hall()`，多锚点确认 `公会信息/公会管理/公会成员/捐献/讨伐`，遇 `公会升级/升级成功/公会等级` toast 时等待而非判未入会。
5. **游历挂机奖励二次领取**：`_collect_entries` 点「挂机奖励」后再轮询最多 5 次 `一键领取/立即领取/领取全部/领取`，不再因 OCR 签名相同提前 break。
6. **副本独立状态机（真机取证）**：活动页底部 `竞技/挑战/副本` tab；副本详情有 `扫荡上一难度` 与 `挑战`；点「挑战」后是 **约 4 秒自动战斗**，直接出 `胜利 + 确定`，不是推关的「下一天/选技能」循环。新增 `_play_dungeon_run()` 等结算页点确定；`_sweep_dungeon()` 复用当前详情弹窗，确认后才计数。
7. **启动期弹窗链**：公告 → 钥匙特惠 → 限定秘藏箱 → 锦鲤大奖 → 冠军公会 → 宠物特惠礼包，逐个用已验证的 X 位置关闭；`_back_to_adventure` 的弹窗关键字与关闭位置列表扩充（含 0.939），但绝不点 `购买 XX 元 / 立即前往`。

### 14.3 回归与重跑
- 后端全量 **417 passed**（新增 `tests/test_pipeline_fixes.py` 8 项 + 更新旧断言）；前端 `tsc --noEmit` / `npm run build` 通过；AutoX `node --test` **42 passed**。
- 后端已用 `CAPYAUTO_DEVICE_BACKEND=adb` 重启加载新代码，`/api/devices` 返回真机 `ANASUT3C20010476`。
- 全账号 `works` 已通过 `POST /api/accounts/reset` 清零（8 个账号，含主账号），再按 `风零→风壹→风贰→风叁→风肆→风伍→风陆` 启动 `account_sweep + bootstrap` 全流程，监控日志 `/tmp/capy_sweep_final.log`。
