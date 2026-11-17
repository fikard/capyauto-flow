import type { AutomationConfig, OcrRegion, PipelineConfig } from '../types/pipeline';

/** localStorage 键带版本：结构变更时升级版本号即可让旧配置自然失效 */
export const CONFIG_STORAGE_KEY = 'capyauto.pipeline.config.v1';

export const DEFAULT_ACCOUNT_QUEUE = ['风贰', '风零', '风壹', '风陆', '风叁', '风伍', '风肆'];

/**
 * 唯一默认配置源。仿真域与真机域共用，避免两套 state 各写一份默认值。
 * 数值范围与 backend/app/schemas.py 的 pydantic 校验保持一致。
 */
export const DEFAULT_PIPELINE_CONFIG: PipelineConfig = {
  // 仿真域
  skillPriorityList: [],
  gaussianStdev: 6,
  pressDurationMean: 80,
  pressDurationStdev: 20,
  reactionMinDelay: 400,
  reactionMaxDelay: 850,
  enableAirplaneModeIpReset: true,
  enableScreenDarkening: true,
  enableWatchdogThread: true,
  autoSweepDaily: true,
  maxDailyBoatTickets: 5,
  maxDefeatRetries: 2,
  // 真机自动化域
  speed: 0.5,
  towerFloors: 2,
  maxStageFails: 2,
  travelStamina: 100,
  stageMode: 'full',
  fastStageCheckEvery: 8,
  account: '',
  accountQueue: [...DEFAULT_ACCOUNT_QUEUE],
  serverFrom: '',
  serverTo: '',
  serverDryRun: true,
  allowGemTalentBreakthrough: false,
  maxRuns: 0,
  ocrRegion: null,
};

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

function num(value: unknown, fallback: number, min: number, max: number): number {
  const parsed = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return clamp(parsed, min, max);
}

function flag(value: unknown, fallback: boolean): boolean {
  return typeof value === 'boolean' ? value : fallback;
}

function text(value: unknown, fallback: string, maxLength: number): string {
  return typeof value === 'string' ? value.slice(0, maxLength) : fallback;
}

function textList(value: unknown, fallback: string[], maxLength: number): string[] {
  if (!Array.isArray(value)) return [...fallback];
  const cleaned = value
    .filter((item): item is string => typeof item === 'string')
    .map((item) => item.trim().slice(0, 40))
    .filter(Boolean);
  return cleaned.slice(0, maxLength);
}

/** 后端 OcrRequest 要求 0<=left<right<=1、0<=top<bottom<=1；不合法一律退化为全屏 */
export function isValidOcrRegion(value: OcrRegion | null): boolean {
  if (!value) return false;
  const [left, top, right, bottom] = value;
  return (
    value.length === 4 &&
    value.every((n) => Number.isFinite(n)) &&
    0 <= left && left < right && right <= 1 &&
    0 <= top && top < bottom && bottom <= 1
  );
}

function region(value: unknown): OcrRegion | null {
  if (!Array.isArray(value) || value.length !== 4) return null;
  const parsed = value.map((item) => Number(item)) as OcrRegion;
  return isValidOcrRegion(parsed) ? parsed : null;
}

/**
 * 把任意来源（localStorage / 旧版本 / 手工改坏）的值清洗成合法配置。
 * 只读取已知键，未知键丢弃；保证写入后端的请求体不会因脏数据触发 422。
 */
export function sanitizeConfig(raw: unknown): PipelineConfig {
  const base = DEFAULT_PIPELINE_CONFIG;
  const src = raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : {};
  const stageMode = src.stageMode === 'lean' ? 'lean' : 'full';
  return {
    skillPriorityList: textList(src.skillPriorityList, base.skillPriorityList, 50),
    gaussianStdev: num(src.gaussianStdev, base.gaussianStdev, 0, 40),
    pressDurationMean: num(src.pressDurationMean, base.pressDurationMean, 20, 600),
    pressDurationStdev: num(src.pressDurationStdev, base.pressDurationStdev, 0, 200),
    reactionMinDelay: num(src.reactionMinDelay, base.reactionMinDelay, 0, 10000),
    reactionMaxDelay: num(src.reactionMaxDelay, base.reactionMaxDelay, 0, 10000),
    enableAirplaneModeIpReset: flag(src.enableAirplaneModeIpReset, base.enableAirplaneModeIpReset),
    enableScreenDarkening: flag(src.enableScreenDarkening, base.enableScreenDarkening),
    enableWatchdogThread: flag(src.enableWatchdogThread, base.enableWatchdogThread),
    autoSweepDaily: flag(src.autoSweepDaily, base.autoSweepDaily),
    maxDailyBoatTickets: num(src.maxDailyBoatTickets, base.maxDailyBoatTickets, 0, 999),
    maxDefeatRetries: num(src.maxDefeatRetries, base.maxDefeatRetries, 0, 20),
    speed: num(src.speed, base.speed, 0.1, 3),
    towerFloors: num(src.towerFloors, base.towerFloors, 0, 20),
    maxStageFails: num(src.maxStageFails, base.maxStageFails, 1, 5),
    travelStamina: num(src.travelStamina, base.travelStamina, 0, 1000),
    stageMode,
    fastStageCheckEvery: num(src.fastStageCheckEvery, base.fastStageCheckEvery, 1, 50),
    account: text(src.account, base.account, 40),
    accountQueue: textList(src.accountQueue, base.accountQueue, 20),
    serverFrom: text(src.serverFrom, base.serverFrom, 40),
    serverTo: text(src.serverTo, base.serverTo, 40),
    serverDryRun: flag(src.serverDryRun, base.serverDryRun),
    allowGemTalentBreakthrough: flag(src.allowGemTalentBreakthrough, base.allowGemTalentBreakthrough),
    maxRuns: num(src.maxRuns, base.maxRuns, 0, 10),
    ocrRegion: region(src.ocrRegion),
  };
}

function getStorage(storage?: Storage | null): Storage | null {
  if (storage !== undefined) return storage;
  try {
    return typeof localStorage === 'undefined' ? null : localStorage;
  } catch {
    // 隐私模式 / 禁用 storage 时降级为内存态
    return null;
  }
}

export function loadPipelineConfig(storage?: Storage | null): PipelineConfig {
  const target = getStorage(storage);
  if (!target) return sanitizeConfig(null);
  try {
    const raw = target.getItem(CONFIG_STORAGE_KEY);
    if (!raw) return sanitizeConfig(null);
    return sanitizeConfig(JSON.parse(raw));
  } catch {
    // 解析失败按默认值处理，不让坏数据把界面卡死
    return sanitizeConfig(null);
  }
}

export function savePipelineConfig(config: PipelineConfig, storage?: Storage | null): boolean {
  const target = getStorage(storage);
  if (!target) return false;
  try {
    target.setItem(CONFIG_STORAGE_KEY, JSON.stringify(sanitizeConfig(config)));
    return true;
  } catch {
    return false;
  }
}

/** 账号队列文本框 ↔ string[] 的解析，供配置界面使用 */
export function parseAccountQueue(input: string): string[] {
  return input
    .split(/[,，\s→]+/)
    .map((item) => item.trim())
    .filter(Boolean)
    .slice(0, 20);
}

/** 仅取自动化字段，传给 DeviceDrawer / useDeviceBridge，避免把仿真参数混进请求体 */
export function toAutomationConfig(config: PipelineConfig): AutomationConfig {
  const {
    speed, towerFloors, maxStageFails, travelStamina, stageMode, fastStageCheckEvery,
    account, accountQueue, serverFrom, serverTo, serverDryRun,
    allowGemTalentBreakthrough, maxRuns, ocrRegion,
  } = config;
  return {
    speed, towerFloors, maxStageFails, travelStamina, stageMode, fastStageCheckEvery,
    account, accountQueue, serverFrom, serverTo, serverDryRun,
    allowGemTalentBreakthrough, maxRuns, ocrRegion,
  };
}
