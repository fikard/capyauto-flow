"use strict";

// AutoX.js 端侧单账号游历闭环。
//
// 真机上直接运行本文件即自动执行；测试通过 CAPYAUTO_AUTOX_NO_AUTORUN=true
// 关闭自动执行，再显式调用 run(注入的全局对象) 覆盖整条主循环。
// 所有 AutoX 全局能力都从 globals 读取，纯决策逻辑在 logic.js，配置在 config.js。

const { CLICK_WHITELIST, buildReport, createState, decide } = require("./logic.js");
const { loadConfig } = require("./config.js");

function collectGlobals() {
  const g = {
    files: typeof files !== "undefined" ? files : undefined,
    auto: typeof auto !== "undefined" ? auto : undefined,
    images: typeof images !== "undefined" ? images : undefined,
    requestScreenCapture: typeof requestScreenCapture !== "undefined" ? requestScreenCapture : undefined,
    click: typeof click !== "undefined" ? click : undefined,
    http: typeof http !== "undefined" ? http : undefined,
    events: typeof events !== "undefined" ? events : undefined,
    sleep: typeof sleep !== "undefined" ? sleep : undefined,
    device: typeof device !== "undefined" ? device : undefined,
    detect: typeof detect !== "undefined" ? detect : undefined,
    $ocr: typeof $ocr !== "undefined" ? $ocr : undefined,
    gmlkit: typeof gmlkit !== "undefined" ? gmlkit : undefined,
    console: typeof console !== "undefined" ? console : undefined,
    dirname: typeof __dirname !== "undefined" ? __dirname : undefined,
  };
  if (typeof CAPYAUTO_BACKEND_URL !== "undefined") g.CAPYAUTO_BACKEND_URL = CAPYAUTO_BACKEND_URL;
  if (typeof CAPYAUTO_ACCOUNT !== "undefined") g.CAPYAUTO_ACCOUNT = CAPYAUTO_ACCOUNT;
  if (typeof CAPYAUTO_DRY_RUN !== "undefined") g.CAPYAUTO_DRY_RUN = CAPYAUTO_DRY_RUN;
  if (typeof CAPYAUTO_CONFIG !== "undefined") g.CAPYAUTO_CONFIG = CAPYAUTO_CONFIG;
  return g;
}

function detector(globals) {
  if (typeof globals.detect === "function") return (image) => globals.detect(image);
  if (globals.$ocr && typeof globals.$ocr.detect === "function") {
    return (image) => globals.$ocr.detect(image);
  }
  if (globals.gmlkit && typeof globals.gmlkit.detect === "function") {
    return (image) => globals.gmlkit.detect(image);
  }
  throw new Error("OCR 能力不可用：需要 detect、$ocr.detect 或 gmlkit.detect");
}

function preflight(globals) {
  if (!globals.auto || typeof globals.auto.waitFor !== "function") throw new Error("无障碍能力不可用");
  globals.auto.waitFor();
  if (!globals.auto.service) throw new Error("无障碍服务未启用");
  if (!globals.images || typeof globals.images.captureScreen !== "function") throw new Error("截屏能力不可用");
  if (typeof globals.requestScreenCapture !== "function" || !globals.requestScreenCapture(false)) {
    throw new Error("截屏权限未授予");
  }
  if (typeof globals.click !== "function") throw new Error("点击能力不可用");
  if (!globals.http || typeof globals.http.postJson !== "function") throw new Error("网络回报能力不可用");
  return detector(globals);
}

function installEmergencyStop(globals, onStop) {
  if (!globals.events || typeof globals.events.onKeyDown !== "function") throw new Error("音量键监听不可用");
  globals.events.observeKey();
  globals.events.setKeyInterceptionEnabled("volume_down", true);
  globals.events.onKeyDown("volume_down", (event) => {
    onStop();
    if (event && typeof event.consume === "function") event.consume();
  });
}

function readScreen(globals, detectImage) {
  let image = null;
  try {
    image = globals.images.captureScreen();
    if (!image) throw new Error("截屏为空");
    const items = detectImage(image);
    if (!Array.isArray(items)) throw new Error("OCR 返回格式未知");
    return items;
  } finally {
    if (image && typeof image.recycle === "function") image.recycle();
  }
}

// 倍率按钮优先用 OCR 的 bounds 中心；只有配置允许兜底时才用归一化坐标。
function clickDecision(globals, config, stateBefore, decision) {
  if (config.dryRun) throw new Error("点击被 dry-run 阻止");
  if (CLICK_WHITELIST.indexOf(decision.target) < 0) throw new Error("点击目标不在游历白名单");
  let ok;
  if (decision.target === "multiplier_plus") {
    if (stateBefore.phase !== "tier") throw new Error("缺少游历倍率上下文");
    let x;
    let y;
    if (decision.point) {
      x = decision.point.x;
      y = decision.point.y;
    } else if (decision.normalized) {
      if (!globals.device) throw new Error("无法获取屏幕尺寸");
      x = globals.device.width * decision.normalized[0];
      y = globals.device.height * decision.normalized[1];
    } else {
      throw new Error("倍率按钮缺少 OCR / 配置定位信息");
    }
    ok = globals.click(x, y);
  } else {
    if (!decision.point) throw new Error("点击目标缺少 OCR bounds 中心");
    ok = globals.click(decision.point.x, decision.point.y);
  }
  if (ok === false) throw new Error(`点击失败：${decision.target}`);
}

function run(globals) {
  const g = globals || collectGlobals();
  const logger = g.console || { warn() {}, error() {}, log() {} };
  const runId = `autox-${Date.now()}-${Math.floor(Math.random() * 1000000)}`;

  let config;
  try {
    config = loadConfig(g);
  } catch (error) {
    logger.error(`[${runId}] 配置加载失败：${error && error.message ? error.message : error}`);
    throw error;
  }

  let state = createState(config);
  let stopped = false;

  function report(status, error) {
    const extra = {};
    // dry-run 只识别不消耗，不上报「消耗前体力」以免被误读为真实扣减
    if (!config.dryRun && state.staminaBefore != null) extra.staminaBefore = state.staminaBefore;
    const payload = buildReport(runId, state, status, error, extra);
    const url = `${config.backendUrl}/api/accounts/report`;
    try {
      const response = g.http.postJson(url, payload);
      const code = response && response.statusCode;
      if (code < 200 || code >= 300) logger.error(`[${runId}] 回报失败 HTTP ${code}: ${url}`);
    } catch (error) {
      logger.error(`[${runId}] 网络回报失败: ${url}; ${error && error.message ? error.message : error}`);
    }
  }

  function pause() {
    if (typeof g.sleep === "function") g.sleep(config.ocr.pollIntervalMs);
  }

  report("running", null);
  let finalStatus = "failed";
  let finalError = "流程未完成";
  try {
    installEmergencyStop(g, () => {
      stopped = true;
      logger.warn(`[${runId}] 音量下急停`);
    });
    const detectImage = preflight(g);
    while (true) {
      if (stopped) {
        finalStatus = "stopped";
        finalError = null;
        break;
      }
      const decision = decide(state, readScreen(g, detectImage));
      if (decision.action === "failed") {
        state = decision.nextState;
        finalStatus = "failed";
        finalError = decision.error;
        break;
      }
      if (decision.action === "complete") {
        state = decision.nextState;
        finalStatus = "completed";
        finalError = null;
        break;
      }
      if (decision.action === "click") {
        if (stopped) {
          finalStatus = "stopped";
          finalError = null;
          break;
        }
        // 先推进状态：开始点击即使返回异常，也绝不会再次开始。
        const previousState = state;
        state = decision.nextState;
        try {
          clickDecision(g, config, previousState, decision);
        } catch (error) {
          state = decision.target === "travel_start" ? state : previousState;
          throw error;
        }
        if (decision.target === "travel_start") report("running", null);
      } else {
        state = decision.nextState;
      }
      pause();
    }
  } catch (error) {
    finalStatus = stopped ? "stopped" : "failed";
    finalError = stopped ? null : String(error && error.message ? error.message : error);
    logger.error(`[${runId}] ${finalStatus}: ${finalError || "音量下急停"}`);
  } finally {
    report(finalStatus, finalError);
    if (g.events && typeof g.events.setKeyInterceptionEnabled === "function") {
      g.events.setKeyInterceptionEnabled("volume_down", false);
    }
  }
  return { runId, status: finalStatus, error: finalError };
}

const noAutorun =
  (typeof globalThis !== "undefined" && globalThis.CAPYAUTO_AUTOX_NO_AUTORUN === true) ||
  (typeof CAPYAUTO_AUTOX_NO_AUTORUN !== "undefined" && CAPYAUTO_AUTOX_NO_AUTORUN === true);
if (!noAutorun) run(collectGlobals());

module.exports = { run, collectGlobals };
