"use strict";

const TRAVEL_COST = 100;
const DEFAULT_ACCOUNT = "风贰";
const FORBIDDEN_ACCOUNT = "你瞅啥呢";
const DANGER_WORDS = ["充值", "材料购买", "广告", "宝石", "钻石"];
const TIERS = ["1倍奖励", "3倍奖励", "5倍奖励", "10倍奖励", "20倍奖励"];
const SETTLEMENT_WAIT_WORDS = ["游历中", "幸运转盘", "幸运宝藏", "点击关闭"];
const CLICK_WHITELIST = ["travel_entry", "multiplier_plus", "travel_start", "settlement_back"];
// 与后端 engine.py 的 SERVER_STAMINA_PATTERN 完全一致：分母 <20 视为 OCR 噪声
const STAMINA_PATTERN = /(\d{1,5})\s*\/\s*(\d{1,5})/;
const DEFAULT_MULTIPLIER_PLUS = {
  normalized: [0.725, 0.835],
  ocrAnchors: ["+", "＋", "加"],
  requireOcrAnchor: false,
};

function createState(config = {}) {
  const account = config.account || DEFAULT_ACCOUNT;
  if (account === FORBIDDEN_ACCOUNT) throw new Error("拒绝操作主账号");
  const loop = config.loop || {};
  const stamina = config.stamina || {};
  return {
    account,
    dryRun: config.dryRun !== false,
    phase: "account",
    started: false,
    travelSpent: 0,
    tierSteps: 0,
    settlementPolls: 0,
    staminaBefore: null,
    staminaPolls: 0,
    minStamina: stamina.minRequired == null ? TRAVEL_COST : stamina.minRequired,
    maxStaminaPolls: loop.maxStaminaPolls == null ? 3 : loop.maxStaminaPolls,
    maxTierSteps: loop.maxTierSteps == null ? 4 : loop.maxTierSteps,
    maxSettlementPolls: loop.settlementPolls == null ? 60 : loop.settlementPolls,
    multiplierPlus: config.multiplierPlus || DEFAULT_MULTIPLIER_PLUS,
    error: null,
  };
}

function text(item) {
  return String((item && item.text) || "").replace(/\s+/g, "");
}

function find(items, word, exact = true) {
  return items.find((item) => exact ? text(item) === word : text(item).includes(word));
}

function centerOf(item) {
  const bounds = item && item.bounds;
  if (Array.isArray(bounds) && bounds.length === 4) {
    return { x: (bounds[0] + bounds[2]) / 2, y: (bounds[1] + bounds[3]) / 2 };
  }
  if (bounds && ["left", "top", "right", "bottom"].every((key) => Number.isFinite(bounds[key]))) {
    return { x: (bounds.left + bounds.right) / 2, y: (bounds.top + bounds.bottom) / 2 };
  }
  if (bounds && typeof bounds.centerX === "function" && typeof bounds.centerY === "function") {
    return { x: bounds.centerX(), y: bounds.centerY() };
  }
  throw new Error("OCR 项缺少有效 bounds");
}

// 体力形如「125/200」：只返回分子，未识别或与后端规则不符时返回 null。
function parseStamina(items) {
  for (const item of items) {
    const match = STAMINA_PATTERN.exec(text(item));
    if (match && Number(match[2]) >= 20) return Number(match[1]);
  }
  return null;
}

function plusAnchor(items, state) {
  const anchors = (state.multiplierPlus && state.multiplierPlus.ocrAnchors) || [];
  const hit = items.find((item) => anchors.indexOf(text(item)) >= 0);
  return hit ? centerOf(hit) : null;
}

function failed(state, error) {
  return { action: "failed", status: "failed", error, nextState: { ...state, error } };
}

function decide(state, items) {
  const allText = items.map(text).join("|");
  if (allText.includes(FORBIDDEN_ACCOUNT)) return failed(state, "识别到主账号，拒绝操作");
  const danger = DANGER_WORDS.find((word) => allText.includes(word)) || (find(items, "购买") ? "购买" : undefined);
  if (danger) return failed(state, `识别到危险内容：${danger}`);

  let decision;
  if (state.phase === "account") {
    decision = find(items, state.account, false)
      ? { action: "advance", nextState: { ...state, phase: "entry" } }
      : failed(state, "未知页面：未核验配置角色名");
  } else if (state.phase === "entry") {
    const entry = find(items, "游历");
    decision = entry
      ? { action: "click", target: "travel_entry", point: centerOf(entry), nextState: { ...state, phase: "tier" } }
      : failed(state, "未知页面：未识别游历入口");
  } else if (state.phase === "tier") {
    // 未确认体力绝不点击「开始游历」：允许有限次 OCR 重试，超限即停。
    const stamina = parseStamina(items);
    if (stamina === null) {
      decision = state.staminaPolls + 1 >= state.maxStaminaPolls
        ? failed(state, "未确认当前体力，禁止开始游历")
        : { action: "wait", nextState: { ...state, staminaPolls: state.staminaPolls + 1 } };
    } else if (stamina < state.minStamina) {
      decision = failed(state, `当前体力 ${stamina} < ${state.minStamina}，禁止开始游历`);
    } else {
      const tier = TIERS.find((word) => find(items, word));
      const start = find(items, "开始游历");
      if (!tier || !start) {
        decision = failed(state, "未知页面：未确认游历倍率上下文");
      } else if (tier === "20倍奖励") {
        decision = {
          action: "click",
          target: "travel_start",
          point: centerOf(start),
          nextState: {
            ...state,
            phase: "settlement",
            started: true,
            travelSpent: TRAVEL_COST,
            staminaBefore: stamina,
            settlementPolls: 0,
          },
        };
      } else if (state.tierSteps >= state.maxTierSteps) {
        decision = failed(state, "未确认20倍奖励，禁止开始");
      } else {
        const anchor = plusAnchor(items, state);
        if (!anchor && state.multiplierPlus.requireOcrAnchor) {
          decision = failed(state, "未定位到倍率 + 按钮，禁止盲点固定坐标");
        } else {
          decision = {
            action: "click",
            target: "multiplier_plus",
            ...(anchor
              ? { point: anchor, anchorVia: "ocr" }
              : { normalized: state.multiplierPlus.normalized.slice(), anchorVia: "config" }),
            nextState: { ...state, tierSteps: state.tierSteps + 1, staminaBefore: stamina },
          };
        }
      }
    }
  } else if (state.phase === "settlement") {
    if (!state.started) {
      decision = failed(state, "未开始游历，禁止进入结算");
    } else {
      const settled = find(items, "游历结束", false) || find(items, "游历完成", false);
      const back = find(items, "返回");
      if (settled && back) {
        decision = {
          action: "click",
          target: "settlement_back",
          point: centerOf(back),
          nextState: { ...state, phase: "done" },
        };
      } else {
        const known = items.length === 0 || settled || SETTLEMENT_WAIT_WORDS.some((word) => find(items, word, false));
        if (!known || state.settlementPolls + 1 >= state.maxSettlementPolls) {
          decision = failed(state, "结算不明，禁止自动重试");
        } else {
          decision = {
            action: "wait",
            nextState: { ...state, settlementPolls: state.settlementPolls + 1 },
          };
        }
      }
    }
  } else if (state.phase === "done") {
    decision = { action: "complete", status: "completed", nextState: state };
  } else {
    decision = failed(state, "未知页面或阶段");
  }

  // dry-run 不再在第一个点击就结束：零点击但推进状态机，才能真的验到 20 倍与结算。
  if (state.dryRun && decision.action === "click") {
    return {
      action: "advance",
      dryRun: true,
      nextState: { ...decision.nextState, travelSpent: 0 },
    };
  }
  return decision;
}

function buildReport(runId, state, status, error, extra = {}) {
  return {
    runId,
    account: state.account,
    status,
    currentPhase: status === "completed" ? "done" : "travel",
    travelSpent: state.travelSpent,
    error: error || "",
    ...extra,
  };
}

module.exports = {
  TRAVEL_COST,
  CLICK_WHITELIST,
  buildReport,
  centerOf,
  createState,
  decide,
  parseStamina,
};
