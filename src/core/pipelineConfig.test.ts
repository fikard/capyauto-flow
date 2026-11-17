import assert from 'node:assert/strict';
import test from 'node:test';
import {
  CONFIG_STORAGE_KEY,
  DEFAULT_ACCOUNT_QUEUE,
  DEFAULT_PIPELINE_CONFIG,
  isValidOcrRegion,
  loadPipelineConfig,
  parseAccountQueue,
  sanitizeConfig,
  savePipelineConfig,
  toAutomationConfig,
} from './pipelineConfig';

function mockStorage(seed?: string) {
  const store = new Map<string, string>();
  if (seed !== undefined) store.set(CONFIG_STORAGE_KEY, seed);
  return {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => { store.set(key, value); },
    removeItem: (key: string) => { store.delete(key); },
    clear: () => store.clear(),
    key: (i: number) => [...store.keys()][i] ?? null,
    get length() { return store.size; },
  } as Storage;
}

test('默认配置覆盖仿真域与真机自动化域，账号队列独立拷贝', () => {
  const config = sanitizeConfig(null);
  assert.equal(config.speed, 0.5);
  assert.equal(config.maxRuns, 0);
  assert.equal(config.serverDryRun, true);
  assert.equal(config.ocrRegion, null);
  assert.deepEqual(config.accountQueue, DEFAULT_ACCOUNT_QUEUE);
  assert.notStrictEqual(config.accountQueue, DEFAULT_ACCOUNT_QUEUE);
  assert.equal(config.gaussianStdev, 6);
});

test('脏数据按后端 pydantic 范围钳制，非法类型回退默认值', () => {
  const config = sanitizeConfig({
    speed: 99,
    towerFloors: -3,
    maxStageFails: 'abc',
    travelStamina: 5000,
    maxRuns: 42,
    pressDurationMean: 1,
    stageMode: 'unknown',
    serverDryRun: 'false',
    allowGemTalentBreakthrough: 1,
    skillPriorityList: [' a ', '', 7, 'b'],
  });
  assert.equal(config.speed, 3);
  assert.equal(config.towerFloors, 0);
  assert.equal(config.maxStageFails, 2);
  assert.equal(config.travelStamina, 1000);
  assert.equal(config.maxRuns, 10);
  assert.equal(config.pressDurationMean, 20);
  assert.equal(config.stageMode, 'full');
  assert.equal(config.serverDryRun, true);
  assert.equal(config.allowGemTalentBreakthrough, false);
  assert.deepEqual(config.skillPriorityList, ['a', 'b']);
});

test('非对象输入与未知键不会污染配置', () => {
  assert.equal(sanitizeConfig('broken').speed, DEFAULT_PIPELINE_CONFIG.speed);
  assert.equal(sanitizeConfig(undefined).towerFloors, DEFAULT_PIPELINE_CONFIG.towerFloors);
  const config = sanitizeConfig({ injected: 'evil', speed: 1 });
  assert.equal('injected' in config, false);
  assert.equal(config.speed, 1);
});

test('OCR 区域必须满足 0<=left<right<=1 且 0<=top<bottom<=1', () => {
  assert.equal(isValidOcrRegion([0, 0, 1, 1]), true);
  assert.equal(isValidOcrRegion([0.2, 0.3, 0.8, 0.9]), true);
  assert.equal(isValidOcrRegion([0.8, 0, 0.2, 1]), false);
  assert.equal(isValidOcrRegion([0, 0.9, 1, 0.1]), false);
  assert.equal(isValidOcrRegion([0, 0, 1.5, 1]), false);
  assert.equal(isValidOcrRegion(null), false);
  assert.deepEqual(sanitizeConfig({ ocrRegion: [0.1, 0.2, 0.9, 0.8] }).ocrRegion, [0.1, 0.2, 0.9, 0.8]);
  assert.equal(sanitizeConfig({ ocrRegion: [1, 1, 0, 0] }).ocrRegion, null);
  assert.equal(sanitizeConfig({ ocrRegion: 'full' }).ocrRegion, null);
});

test('load/save 往返保留用户配置，坏 JSON 回退默认值', () => {
  const storage = mockStorage();
  const config = { ...DEFAULT_PIPELINE_CONFIG, serverTo: '闲云野鹤9区', maxRuns: 3, speed: 0.3 };
  assert.equal(savePipelineConfig(config, storage), true);
  const loaded = loadPipelineConfig(storage);
  assert.equal(loaded.serverTo, '闲云野鹤9区');
  assert.equal(loaded.maxRuns, 3);
  assert.equal(loaded.speed, 0.3);

  const broken = mockStorage('{ not json');
  assert.equal(loadPipelineConfig(broken).speed, DEFAULT_PIPELINE_CONFIG.speed);
});

test('storage 不可用时降级为默认配置，不抛异常', () => {
  assert.equal(savePipelineConfig(DEFAULT_PIPELINE_CONFIG, null), false);
  assert.equal(loadPipelineConfig(null).speed, DEFAULT_PIPELINE_CONFIG.speed);
});

test('账号队列文本解析支持逗号/顿号/箭头/空白分隔并限量', () => {
  assert.deepEqual(parseAccountQueue('风贰,风零，风壹 风陆→风叁'), ['风贰', '风零', '风壹', '风陆', '风叁']);
  assert.deepEqual(parseAccountQueue('  '), []);
  assert.equal(parseAccountQueue(Array.from({ length: 40 }, (_, i) => `号${i}`).join(',')).length, 20);
});

test('toAutomationConfig 只带自动化字段，不含仿真参数', () => {
  const automation = toAutomationConfig({ ...DEFAULT_PIPELINE_CONFIG, maxRuns: 2, gaussianStdev: 12 });
  assert.equal(automation.maxRuns, 2);
  assert.equal('gaussianStdev' in automation, false);
  assert.equal('skillPriorityList' in automation, false);
  assert.equal('serverTo' in automation, true);
  assert.equal('allowGemTalentBreakthrough' in automation, true);
  assert.equal('ocrRegion' in automation, true);
});
