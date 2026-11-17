"use strict";

// AutoX 端侧配置的唯一入口。
//
// 优先级（高 → 低）：
//   1. 全局注入 CAPYAUTO_CONFIG（对象）/ CAPYAUTO_BACKEND_URL / CAPYAUTO_ACCOUNT / CAPYAUTO_DRY_RUN
//   2. 同目录可选的 config.local.json（由 scripts/gen-autox-config.sh 从 devgate 生成，不入库）
//   3. config.json（可入库的默认值，不含任何机器相关 IP / 端口）
//
// 真机要换后端地址时不要改代码：生成 config.local.json，或在启动脚本里注入全局变量。
// 配置缺失 / 非法一律显式报错，绝不悄悄回退到某个写死的 IP。

const FORBIDDEN_ACCOUNT = "你瞅啥呢";
const TRAVEL_COST = 100;

const DEFAULT_CONFIG = {
  account: "风贰",
  backendUrl: "",
  dryRun: true,
  ocr: { pollIntervalMs: 800 },
  loop: { maxTierSteps: 4, settlementPolls: 60, maxStaminaPolls: 3 },
  stamina: { minRequired: TRAVEL_COST },
  multiplierPlus: {
    // 仅作为 OCR 识别不到「+」按钮时的兜底，位置来自配置而非代码常量。
    normalized: [0.725, 0.835],
    ocrAnchors: ["+", "＋", "加"],
    requireOcrAnchor: false,
  },
};

// 不依赖 URL 全局对象：AutoX.js 的 Rhino 运行时不保证有 WHATWG URL。
const BACKEND_URL_PATTERN = /^(https?):\/\/(\[[0-9a-fA-F:]+\]|[A-Za-z0-9._-]+)(?::(\d{1,5}))?\/?$/i;

function normalizeBackendUrl(raw) {
  const value = typeof raw === "string" ? raw.trim() : "";
  const match = BACKEND_URL_PATTERN.exec(value);
  if (!match) throw new Error(`backendUrl 无效：${raw || "(空)"}，需形如 http://<主机>:<端口>`);
  const port = match[3] === undefined ? null : Number(match[3]);
  if (port !== null && (!Number.isInteger(port) || port < 1 || port > 65535)) {
    throw new Error(`backendUrl 无效：端口 ${match[3]} 超出 1~65535`);
  }
  return value.replace(/\/+$/, "");
}

function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function mergeConfig(base, override) {
  if (!isPlainObject(base)) throw new Error("配置 base 必须是对象");
  if (!isPlainObject(override)) throw new Error("配置 override 必须是对象");
  const result = {};
  for (const key of Object.keys(base)) {
    if (base[key] !== undefined) result[key] = base[key];
  }
  for (const key of Object.keys(override)) {
    const value = override[key];
    if (value === undefined) continue;
    result[key] = isPlainObject(value) && isPlainObject(result[key])
      ? mergeConfig(result[key], value)
      : value;
  }
  return result;
}

function assertPositive(value, label, min = 1) {
  if (!Number.isFinite(value) || value < min) throw new Error(`配置 ${label} 必须是 >= ${min} 的数字`);
}

function resolveConfig({ base = {}, local = null, env = {} } = {}) {
  const layers = [DEFAULT_CONFIG, base, local || {}];
  const singles = {};
  if (env.CAPYAUTO_BACKEND_URL !== undefined) singles.backendUrl = env.CAPYAUTO_BACKEND_URL;
  if (env.CAPYAUTO_ACCOUNT !== undefined) singles.account = env.CAPYAUTO_ACCOUNT;
  if (env.CAPYAUTO_DRY_RUN !== undefined) singles.dryRun = env.CAPYAUTO_DRY_RUN;
  layers.push(singles);
  if (env.CAPYAUTO_CONFIG !== undefined) {
    if (!isPlainObject(env.CAPYAUTO_CONFIG)) throw new Error("配置 CAPYAUTO_CONFIG 必须是对象");
    layers.push(env.CAPYAUTO_CONFIG);
  }
  let merged = {};
  for (const layer of layers) merged = mergeConfig(merged, layer || {});

  merged.backendUrl = normalizeBackendUrl(merged.backendUrl);
  if (typeof merged.account !== "string" || !merged.account.trim()) {
    throw new Error("配置 account 不能为空");
  }
  merged.account = merged.account.trim();
  if (merged.account === FORBIDDEN_ACCOUNT) throw new Error(`配置拒绝操作主账号「${FORBIDDEN_ACCOUNT}」`);
  if (typeof merged.dryRun !== "boolean") throw new Error("配置 dryRun 必须是布尔值（默认 true）");

  const normalized = merged.multiplierPlus && merged.multiplierPlus.normalized;
  if (
    !Array.isArray(normalized) ||
    normalized.length !== 2 ||
    !normalized.every((n) => Number.isFinite(n) && n >= 0 && n <= 1)
  ) {
    throw new Error("配置 multiplierPlus.normalized 必须是两个 0~1 的归一化坐标");
  }
  const anchors = merged.multiplierPlus.ocrAnchors;
  if (!Array.isArray(anchors) || anchors.length === 0 || !anchors.every((s) => typeof s === "string")) {
    throw new Error("配置 multiplierPlus.ocrAnchors 必须是非空字符串数组");
  }
  if (typeof merged.multiplierPlus.requireOcrAnchor !== "boolean") {
    throw new Error("配置 multiplierPlus.requireOcrAnchor 必须是布尔值");
  }
  assertPositive(merged.stamina.minRequired, "stamina.minRequired", TRAVEL_COST);
  assertPositive(merged.loop.maxStaminaPolls, "loop.maxStaminaPolls");
  assertPositive(merged.loop.maxTierSteps, "loop.maxTierSteps");
  assertPositive(merged.loop.settlementPolls, "loop.settlementPolls");
  assertPositive(merged.ocr.pollIntervalMs, "ocr.pollIntervalMs");
  return merged;
}

function loadConfig(globals) {
  const files = globals && globals.files;
  if (!files || typeof files.read !== "function" || typeof files.join !== "function") {
    throw new Error("配置读取失败：缺少 files.read / files.join 能力");
  }
  const dir = globals.dirname || ".";
  const pathOf = (name) => files.join(dir, name);
  const readJson = (name) => {
    const path = pathOf(name);
    let raw;
    try {
      raw = files.read(path);
    } catch (error) {
      throw new Error(`配置读取失败：${path}`);
    }
    try {
      const parsed = JSON.parse(raw);
      if (!isPlainObject(parsed)) throw new Error("not an object");
      return parsed;
    } catch (error) {
      throw new Error(`配置解析失败：${path}（不是合法 JSON 对象）`);
    }
  };

  const base = readJson("config.json");
  let local = null;
  const localPath = pathOf("config.local.json");
  const exists = typeof files.exists === "function" ? files.exists(localPath) : true;
  if (exists) {
    try {
      local = readJson("config.local.json");
    } catch (error) {
      if (/解析失败/.test(error.message)) throw error;
      local = null;
    }
  }

  const env = {
    CAPYAUTO_BACKEND_URL: globals.CAPYAUTO_BACKEND_URL,
    CAPYAUTO_ACCOUNT: globals.CAPYAUTO_ACCOUNT,
    CAPYAUTO_DRY_RUN: globals.CAPYAUTO_DRY_RUN,
    CAPYAUTO_CONFIG: globals.CAPYAUTO_CONFIG,
  };
  return resolveConfig({ base, local, env });
}

module.exports = {
  DEFAULT_CONFIG,
  TRAVEL_COST,
  normalizeBackendUrl,
  mergeConfig,
  resolveConfig,
  loadConfig,
};
