const test = require("node:test");
const assert = require("node:assert/strict");

const {
  DEFAULT_CONFIG,
  normalizeBackendUrl,
  mergeConfig,
  resolveConfig,
  loadConfig,
} = require("./config.js");

function fakeFiles({ base, local, localExists = true } = {}) {
  return {
    join: (dir, name) => `${dir}/${name}`,
    exists: (path) => (path.endsWith("config.local.json") ? localExists : true),
    read: (path) => {
      if (path.endsWith("config.local.json")) return JSON.stringify(local);
      return JSON.stringify(base);
    },
  };
}

function globals(overrides = {}) {
  return { dirname: "/fake/autox", ...overrides };
}

test("默认配置不含任何硬编码 IP 或端口", () => {
  assert.equal(DEFAULT_CONFIG.backendUrl, "");
  assert.equal(DEFAULT_CONFIG.account, "风贰");
  assert.equal(DEFAULT_CONFIG.dryRun, true);
  assert.deepEqual(DEFAULT_CONFIG.multiplierPlus.normalized, [0.725, 0.835]);
  assert.equal(DEFAULT_CONFIG.multiplierPlus.requireOcrAnchor, false);
  assert.equal(DEFAULT_CONFIG.stamina.minRequired, 100);
});

test("backendUrl 归一化：合法地址、去尾斜杠、拒绝非法格式", () => {
  assert.equal(normalizeBackendUrl("http://192.168.0.113:8084"), "http://192.168.0.113:8084");
  assert.equal(normalizeBackendUrl("https://backend.capyauto-flow.test/"), "https://backend.capyauto-flow.test");
  assert.equal(normalizeBackendUrl("http://localhost:5178"), "http://localhost:5178");
  assert.equal(normalizeBackendUrl("http://[::1]:8084"), "http://[::1]:8084");

  for (const invalid of [
    "",
    "192.168.0.113:8084",
    "ftp://192.168.0.113:8084",
    "http://192.168.0.113:8084/api",
    "http://192.168.0.113:8084?x=1",
    "http://192.168.0.113:0",
    "http://192.168.0.113:70000",
    "http://",
  ]) {
    assert.throws(() => normalizeBackendUrl(invalid), /backendUrl 无效/, invalid);
  }
  assert.equal(normalizeBackendUrl("http://192.168.0.113:80/"), "http://192.168.0.113:80");
});

test("mergeConfig 深合并普通对象、替换数组、忽略 undefined", () => {
  const merged = mergeConfig(
    { ocr: { pollIntervalMs: 800, retries: 2 }, accounts: ["a"], dryRun: true },
    { ocr: { pollIntervalMs: 300 }, accounts: ["b", "c"], dryRun: false, extra: undefined }
  );
  assert.deepEqual(merged, {
    ocr: { pollIntervalMs: 300, retries: 2 },
    accounts: ["b", "c"],
    dryRun: false,
  });
  assert.throws(() => mergeConfig({}, null), /必须是对象/);
});

test("resolveConfig 优先级：全局注入 > local > base", () => {
  const base = { account: "风贰", dryRun: true };
  const local = { backendUrl: "http://10.0.0.2:9000", dryRun: false };
  const env = { CAPYAUTO_BACKEND_URL: "http://10.0.0.3:9001" };
  const config = resolveConfig({ base, local, env });
  assert.equal(config.backendUrl, "http://10.0.0.3:9001");
  assert.equal(config.dryRun, false);
  assert.equal(config.account, "风贰");

  const objectOverride = resolveConfig({
    base,
    local,
    env: { CAPYAUTO_CONFIG: { backendUrl: "http://10.0.0.4:9002", account: "风零" } },
  });
  assert.equal(objectOverride.backendUrl, "http://10.0.0.4:9002");
  assert.equal(objectOverride.account, "风零");
});

test("resolveConfig 缺 backendUrl 时明确拒绝，不回退到写死 IP", () => {
  assert.throws(() => resolveConfig({ base: {} }), /backendUrl/);
  assert.throws(
    () => resolveConfig({ base: {}, env: { CAPYAUTO_BACKEND_URL: "not-a-url" } }),
    /backendUrl 无效/
  );
});

test("resolveConfig 拒绝主账号与非法数值，不做静默钳制", () => {
  assert.throws(() => resolveConfig({ base: { account: "你瞅啥呢" }, env: { CAPYAUTO_BACKEND_URL: "http://x:8084" } }), /主账号/);
  for (const bad of [
    { multiplierPlus: { normalized: [1.2, 0.5] } },
    { multiplierPlus: { normalized: [0.5] } },
    { stamina: { minRequired: -1 } },
    { stamina: { minRequired: 99 } },
    { loop: { maxStaminaPolls: 0 } },
    { ocr: { pollIntervalMs: 0 } },
  ]) {
    assert.throws(
      () => resolveConfig({ base: bad, env: { CAPYAUTO_BACKEND_URL: "http://x:8084" } }),
      /配置/,
      JSON.stringify(bad)
    );
  }
});

test("resolveConfig 保持 dryRun 默认安全且只接受布尔", () => {
  const config = resolveConfig({ base: {}, env: { CAPYAUTO_BACKEND_URL: "http://x:8084" } });
  assert.equal(config.dryRun, true);
  assert.throws(
    () => resolveConfig({ base: { dryRun: "false" }, env: { CAPYAUTO_BACKEND_URL: "http://x:8084" } }),
    /dryRun/
  );
});

test("loadConfig 读取 config.json + config.local.json 并应用全局覆盖", () => {
  const files = fakeFiles({
    base: { account: "风贰", dryRun: true, ocr: { pollIntervalMs: 800 } },
    local: { backendUrl: "http://192.168.0.113:8084", dryRun: false },
  });
  const config = loadConfig(globals({ files, CAPYAUTO_BACKEND_URL: "http://10.0.0.9:7777/" }));
  assert.equal(config.backendUrl, "http://10.0.0.9:7777");
  assert.equal(config.dryRun, false);
  assert.equal(config.ocr.pollIntervalMs, 800);

  const noOverride = loadConfig(globals({ files }));
  assert.equal(noOverride.backendUrl, "http://192.168.0.113:8084");
});

test("loadConfig 无本地覆盖文件时仍可用，但缺 URL 必须报错", () => {
  const files = fakeFiles({ base: {}, local: {}, localExists: false });
  assert.throws(() => loadConfig(globals({ files })), /backendUrl/);
  const ok = loadConfig(globals({ files, CAPYAUTO_BACKEND_URL: "http://127.0.0.1:8084" }));
  assert.equal(ok.backendUrl, "http://127.0.0.1:8084");
});

test("loadConfig 遇到损坏的本地配置必须报错，不静默降级", () => {
  const files = {
    join: (dir, name) => `${dir}/${name}`,
    exists: () => true,
    read: (path) => (path.endsWith("config.local.json") ? "{not json" : JSON.stringify({})),
  };
  assert.throws(() => loadConfig(globals({ files, CAPYAUTO_BACKEND_URL: "http://x:8084" })), /解析失败/);
});
