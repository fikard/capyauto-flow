const test = require("node:test");
const assert = require("node:assert/strict");

const {
  TRAVEL_COST,
  buildReport,
  centerOf,
  createState,
  decide,
  parseStamina,
} = require("./logic.js");

function item(text, bounds = { left: 100, top: 200, right: 300, bottom: 400 }) {
  return { text, bounds };
}

// 真实屏幕上的体力形如「125/200」，与后端 SERVER_STAMINA_PATTERN 对齐
function tierScreen(tier = "20倍奖励", extra = []) {
  return [item(tier), item("开始游历"), item("125/200"), ...extra];
}

function stateAt(phase, overrides = {}) {
  return {
    ...createState({
      account: "风贰",
      dryRun: false,
      loop: { maxTierSteps: 4, settlementPolls: 2 },
    }),
    phase,
    ...overrides,
  };
}

test("默认使用风贰并拒绝主账号", () => {
  const state = createState();
  assert.equal(state.account, "风贰");
  assert.equal(state.dryRun, true);
  assert.throws(() => createState({ account: "你瞅啥呢" }), /拒绝操作主账号/);
});

test("确认20倍奖励前禁止开始，只在游历倍率上下文点击加档", () => {
  const decision = decide(stateAt("tier"), tierScreen("10倍奖励"));
  assert.equal(decision.action, "click");
  assert.equal(decision.target, "multiplier_plus");
  assert.deepEqual(decision.normalized, [0.725, 0.835]);

  const unknownTier = decide(stateAt("tier"), [item("开始游历"), item("125/200")]);
  assert.equal(unknownTier.action, "failed");
  assert.equal(unknownTier.point, undefined);
});

test("确认20倍奖励后只允许一次开始且固定消耗100", () => {
  const screen = tierScreen();
  const decision = decide(stateAt("tier"), screen);
  assert.equal(TRAVEL_COST, 100);
  assert.equal(decision.action, "click");
  assert.equal(decision.target, "travel_start");
  assert.deepEqual(decision.point, { x: 200, y: 300 });
  assert.equal(decision.nextState.started, true);
  assert.equal(decision.nextState.travelSpent, 100);

  const repeated = decide(decision.nextState, screen);
  assert.notEqual(repeated.target, "travel_start");
  assert.equal(repeated.action, "failed");
});

test("充值、材料购买、广告、宝石和钻石立即阻断", () => {
  for (const danger of ["充值", "材料购买", "广告", "宝石", "钻石"]) {
    const decision = decide(stateAt("tier"), tierScreen("20倍奖励", [item(danger)]));
    assert.equal(decision.action, "failed", danger);
    assert.equal(decision.point, undefined, danger);
  }
});

test("主城购买时间文案不误阻断，精确购买按钮仍阻断", () => {
  const main = decide(stateAt("account"), [item("风贰"), item("购买时间：19:22")]);
  assert.equal(main.action, "advance");

  const purchase = decide(stateAt("account"), [item("风贰"), item("购买")]);
  assert.equal(purchase.action, "failed");
  assert.equal(purchase.point, undefined);
});

test("开始后结算不明禁止自动重试", () => {
  const started = stateAt("settlement", { started: true, travelSpent: 100 });
  const waiting = decide(started, []);
  assert.equal(waiting.action, "wait");
  assert.equal(waiting.point, undefined);

  const unclear = decide(waiting.nextState, []);
  assert.equal(unclear.action, "failed");
  assert.match(unclear.error, /结算不明，禁止自动重试/);
  assert.equal(unclear.point, undefined);
});

test("dry-run 零点击但推进状态机，能一路验到 20 倍与结算", () => {
  const cases = [
    ["entry", [item("游历")], "tier"],
    ["tier", tierScreen(), "settlement"],
    ["settlement", [item("游历结束"), item("返回")], "done", { started: true }],
  ];
  for (const [phase, screen, nextPhase, overrides] of cases) {
    const decision = decide(stateAt(phase, { dryRun: true, ...overrides }), screen);
    assert.equal(decision.action, "advance", phase);
    assert.equal(decision.dryRun, true, phase);
    assert.equal(decision.target, undefined, phase);
    assert.equal(decision.point, undefined, phase);
    assert.equal(decision.normalized, undefined, phase);
    assert.equal(decision.nextState.phase, nextPhase, phase);
    assert.equal(decision.nextState.travelSpent, 0, phase);
  }
});

test("危险词在 dry-run 中仍阻断", () => {
  const decision = decide(stateAt("entry", { dryRun: true }), [item("游历"), item("充值")]);
  assert.equal(decision.action, "failed");
});

test("点击坐标取 OCR bounds 中心", () => {
  assert.deepEqual(centerOf(item("游历")), { x: 200, y: 300 });
  assert.deepEqual(centerOf({ bounds: [10, 20, 30, 40] }), { x: 20, y: 30 });
});

test("未知页面立即停止", () => {
  const decision = decide(stateAt("entry"), [item("神秘页面")]);
  assert.equal(decision.action, "failed");
  assert.match(decision.error, /未知页面/);
});

test("回报字段完整并共用 travel/done 阶段", () => {
  const state = stateAt("done", { travelSpent: 100 });
  assert.deepEqual(buildReport("autox-test-1", state, "completed", null), {
    runId: "autox-test-1",
    account: "风贰",
    status: "completed",
    currentPhase: "done",
    travelSpent: 100,
    error: "",
  });
  assert.equal(buildReport("autox-test-2", stateAt("tier"), "running", null).currentPhase, "travel");
});

test("buildReport 可附带体力证据，默认载荷保持向后兼容", () => {
  const state = stateAt("done", { travelSpent: 100, staminaBefore: 125 });
  assert.deepEqual(buildReport("autox-test-3", state, "completed", null), {
    runId: "autox-test-3",
    account: "风贰",
    status: "completed",
    currentPhase: "done",
    travelSpent: 100,
    error: "",
  });
  const withEvidence = buildReport("autox-test-4", state, "completed", null, {
    staminaBefore: 125,
    source: "autox",
  });
  assert.equal(withEvidence.staminaBefore, 125);
  assert.equal(withEvidence.source, "autox");
});

test("parseStamina 与后端 SERVER_STAMINA_PATTERN 对齐", () => {
  assert.equal(parseStamina([item("125/200")]), 125);
  assert.equal(parseStamina([item("体力 125 / 200")]), 125);
  assert.equal(parseStamina([item("100/100"), item("20倍奖励")]), 100);
  assert.equal(parseStamina([item("125/19")]), null, "上限 <20 视为 OCR 噪声");
  assert.equal(parseStamina([item("20倍奖励"), item("开始游历")]), null);
  assert.equal(parseStamina([]), null);
});

test("未确认当前体力时有限等待，超限即禁止开始游历", () => {
  const screen = [item("20倍奖励"), item("开始游历")];
  const first = decide(stateAt("tier"), screen);
  assert.equal(first.action, "wait");
  assert.equal(first.nextState.staminaPolls, 1);
  assert.equal(first.nextState.phase, "tier");
  assert.equal(first.nextState.travelSpent, 0);

  const second = decide(first.nextState, screen);
  assert.equal(second.action, "wait");
  const third = decide(second.nextState, screen);
  assert.equal(third.action, "failed");
  assert.match(third.error, /未确认当前体力/);
  assert.equal(third.point, undefined);
  assert.equal(third.nextState.travelSpent, 0);
});

test("体力低于 100 立即禁止开始，不记消耗", () => {
  const decision = decide(stateAt("tier"), tierScreen("20倍奖励").map((i) =>
    i.text === "125/200" ? item("95/200") : i
  ));
  assert.equal(decision.action, "failed");
  assert.match(decision.error, /体力 95/);
  assert.equal(decision.target, undefined);
  assert.equal(decision.nextState.travelSpent, 0);
});

test("确认体力后记录开始前后证据", () => {
  const decision = decide(stateAt("tier"), tierScreen());
  assert.equal(decision.action, "click");
  assert.equal(decision.nextState.staminaBefore, 125);
  assert.equal(decision.nextState.travelSpent, 100);
});

test("倍率 + 按钮优先用 OCR bounds 定位，坐标不再是唯一来源", () => {
  const plus = item("+", { left: 700, top: 1600, right: 760, bottom: 1660 });
  const decision = decide(stateAt("tier"), tierScreen("10倍奖励", [plus]));
  assert.equal(decision.action, "click");
  assert.equal(decision.target, "multiplier_plus");
  assert.deepEqual(decision.point, { x: 730, y: 1630 });
  assert.equal(decision.normalized, undefined);
  assert.equal(decision.anchorVia, "ocr");
});

test("强制 OCR 锚点时，识别不到 + 按钮就拒绝盲点固定坐标", () => {
  const state = stateAt("tier", {
    multiplierPlus: { normalized: [0.725, 0.835], ocrAnchors: ["+", "＋"], requireOcrAnchor: true },
  });
  const decision = decide(state, tierScreen("10倍奖励"));
  assert.equal(decision.action, "failed");
  assert.match(decision.error, /未定位到倍率/);
  assert.equal(decision.normalized, undefined);
});

test("倍率按钮坐标可由配置改写，不在代码里写死", () => {
  const state = stateAt("tier", {
    multiplierPlus: { normalized: [0.6, 0.7], ocrAnchors: ["+"], requireOcrAnchor: false },
  });
  const decision = decide(state, tierScreen("10倍奖励"));
  assert.deepEqual(decision.normalized, [0.6, 0.7]);
  assert.equal(decision.anchorVia, "config");
});

test("加档次数上限与体力门槛同时生效", () => {
  const state = stateAt("tier", { tierSteps: 4 });
  const decision = decide(state, tierScreen("10倍奖励"));
  assert.equal(decision.action, "failed");
  assert.match(decision.error, /未确认20倍奖励/);
});
