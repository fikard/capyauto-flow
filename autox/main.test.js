const test = require("node:test");
const assert = require("node:assert/strict");

// main.js 加载时默认会在真机上自动执行；测试里显式关闭自动执行，
// 然后通过 run(globals) 注入一套假的 AutoX 全局来跑完整主循环。
globalThis.CAPYAUTO_AUTOX_NO_AUTORUN = true;
const { run } = require("./main.js");

function item(text, bounds = { left: 100, top: 200, right: 300, bottom: 400 }) {
  return { text, bounds };
}

const TIER_OK = () => [item("20倍奖励"), item("开始游历"), item("125/200")];
const SETTLED = () => [item("游历结束"), item("返回")];
const FULL_SCREENS = () => [[item("风贰")], [item("游历")], TIER_OK(), SETTLED(), SETTLED()];

function makeGlobals({
  screens = FULL_SCREENS(),
  dryRun = true,
  base = {},
  local = null,
  env = {},
  requestScreenCapture = () => true,
  autoService = true,
  stopAfterScreen = null,
} = {}) {
  const reports = [];
  const clicks = [];
  const logs = [];
  let keyHandler = null;
  let screenIndex = 0;

  const consoleStub = {
    warn: (...args) => logs.push(["warn", ...args]),
    error: (...args) => logs.push(["error", ...args]),
    log: (...args) => logs.push(["log", ...args]),
  };

  const files = {
    join: (dir, name) => `${dir}/${name}`,
    exists: (path) => (path.endsWith("config.local.json") ? local !== null : true),
    read: (path) => {
      if (path.endsWith("config.local.json")) return JSON.stringify(local);
      return JSON.stringify({
        account: "风贰",
        backendUrl: "http://192.168.0.113:8084",
        dryRun,
        ocr: { pollIntervalMs: 1 },
        loop: { maxTierSteps: 4, settlementPolls: 2, maxStaminaPolls: 3 },
        ...base,
      });
    },
  };

  const globals = {
    dirname: "/fake/autox",
    console: consoleStub,
    files,
    auto: { waitFor() {}, service: autoService },
    images: { captureScreen: () => ({ recycle() {} }) },
    requestScreenCapture,
    click: (x, y) => {
      clicks.push([x, y]);
      return true;
    },
    http: {
      postJson: (url, payload) => {
        reports.push({ url, payload });
        return { statusCode: 200 };
      },
    },
    events: {
      observeKey() {},
      setKeyInterceptionEnabled() {},
      onKeyDown: (name, cb) => {
        assert.equal(name, "volume_down");
        keyHandler = cb;
      },
    },
    sleep: () => {},
    device: { width: 1000, height: 2000 },
    detect: () => {
      const frame = screens[Math.min(screenIndex, screens.length - 1)];
      screenIndex += 1;
      if (stopAfterScreen !== null && screenIndex === stopAfterScreen && keyHandler) {
        keyHandler({ consume() {} });
      }
      return frame;
    },
    ...env,
  };

  return { globals, reports, clicks, logs, screenCount: () => screenIndex };
}

test("dry-run 走完整识别链路：零点击、零消耗、回报 completed", () => {
  const { globals, reports, clicks, screenCount } = makeGlobals();
  const result = run(globals);

  assert.equal(result.status, "completed");
  assert.equal(clicks.length, 0);
  assert.ok(screenCount() >= 4, "dry-run 必须验到 20 倍与结算，不能在第一个点击就结束");
  assert.equal(reports.length, 2);
  assert.equal(reports[0].payload.status, "running");
  assert.equal(reports[1].payload.status, "completed");
  assert.equal(reports[1].payload.travelSpent, 0);
  assert.match(reports[0].payload.runId, /^autox-/);
  assert.equal(reports[0].url, "http://192.168.0.113:8084/api/accounts/report");
});

test("实机流程：三次白名单点击、固定 100 体力、回报带体力证据", () => {
  const { globals, reports, clicks } = makeGlobals({ dryRun: false });
  const result = run(globals);

  assert.equal(result.status, "completed");
  assert.equal(clicks.length, 3);
  assert.deepEqual(clicks[0], [200, 300]);
  assert.equal(reports.length, 3, "开始游历前后各一次 running，结束时一次 completed");
  assert.equal(reports[1].payload.status, "running");
  const last = reports[2].payload;
  assert.equal(last.status, "completed");
  assert.equal(last.travelSpent, 100);
  assert.equal(last.staminaBefore, 125);
  assert.equal(last.currentPhase, "done");
});

test("倍率 + 按钮由 OCR 定位时点击 bounds 中心，不用固定坐标", () => {
  const plus = item("+", { left: 700, top: 1600, right: 760, bottom: 1660 });
  const screens = [
    [item("风贰")],
    [item("游历")],
    [item("10倍奖励"), item("开始游历"), item("125/200"), plus],
    TIER_OK(),
    SETTLED(),
    SETTLED(),
  ];
  const { globals, clicks } = makeGlobals({ screens, dryRun: false });
  const result = run(globals);

  assert.equal(result.status, "completed");
  assert.deepEqual(clicks[1], [730, 1630]);
  assert.equal(clicks.length, 4);
});

test("未确认体力时禁止开始，回报 failed 且零消耗", () => {
  const screens = [
    [item("风贰")],
    [item("游历")],
    [item("20倍奖励"), item("开始游历")],
  ];
  const { globals, reports, clicks } = makeGlobals({ screens, dryRun: false });
  const result = run(globals);

  assert.equal(result.status, "failed");
  assert.match(result.error, /未确认当前体力/);
  assert.equal(clicks.length, 1, "只允许点到游历入口");
  assert.equal(reports.at(-1).payload.travelSpent, 0);
  assert.match(reports.at(-1).payload.error, /未确认当前体力/);
});

test("体力不足 100 时禁止开始", () => {
  const screens = [
    [item("风贰")],
    [item("游历")],
    [item("20倍奖励"), item("开始游历"), item("95/200")],
  ];
  const { globals, reports } = makeGlobals({ screens, dryRun: false });
  const result = run(globals);

  assert.equal(result.status, "failed");
  assert.match(result.error, /体力 95/);
  assert.equal(reports.at(-1).payload.travelSpent, 0);
});

test("危险词立即阻断，失败回报不含点击证据", () => {
  const screens = [
    [item("风贰")],
    [item("游历")],
    [...TIER_OK(), item("充值")],
  ];
  const { globals, reports, clicks } = makeGlobals({ screens, dryRun: false });
  const result = run(globals);

  assert.equal(result.status, "failed");
  assert.match(result.error, /危险内容/);
  assert.equal(clicks.length, 1);
  assert.equal(reports.at(-1).payload.status, "failed");
});

test("权限预检失败如实回报，不冒充成功", () => {
  const { globals, reports, clicks } = makeGlobals({
    requestScreenCapture: () => false,
    dryRun: false,
  });
  const result = run(globals);

  assert.equal(result.status, "failed");
  assert.match(result.error, /截屏权限/);
  assert.equal(clicks.length, 0);
  assert.equal(reports.at(-1).payload.status, "failed");
});

test("无障碍服务未启用时阻断", () => {
  const { globals, reports } = makeGlobals({ autoService: false });
  const result = run(globals);
  assert.equal(result.status, "failed");
  assert.match(result.error, /无障碍服务/);
  assert.equal(reports.at(-1).payload.status, "failed");
});

test("音量下急停：回报 stopped 且不再继续点击", () => {
  const { globals, reports, clicks } = makeGlobals({ dryRun: false, stopAfterScreen: 1 });
  const result = run(globals);

  assert.equal(result.status, "stopped");
  assert.equal(result.error, null);
  assert.equal(clicks.length, 0);
  assert.equal(reports.at(-1).payload.status, "stopped");
});

test("回报地址来自全局注入，覆盖配置文件里的地址", () => {
  const { globals, reports } = makeGlobals({
    env: { CAPYAUTO_BACKEND_URL: "http://10.0.0.9:7777/" },
  });
  run(globals);
  assert.equal(reports[0].url, "http://10.0.0.9:7777/api/accounts/report");
});

test("回报地址也可来自 config.local.json（不写死在代码里）", () => {
  const { globals, reports } = makeGlobals({
    local: { backendUrl: "http://192.168.1.77:9001" },
  });
  run(globals);
  assert.equal(reports[0].url, "http://192.168.1.77:9001/api/accounts/report");
});

test("缺 backendUrl 时直接失败且明确报错，不静默连到写死 IP", () => {
  const { globals, reports, logs } = makeGlobals({
    local: null,
    base: { backendUrl: "" },
  });
  assert.throws(() => run(globals), /backendUrl/);
  assert.equal(reports.length, 0);
  assert.ok(logs.some((entry) => String(entry[1]).includes("配置")), "应打印配置错误");
});
