export type FsmState =
  | 'IDLE'
  | 'MAIN_CITY'
  | 'BATTLE_RUNNING'
  | 'SKILL_CHOICE'
  | 'BATTLE_VICTORY'
  | 'BATTLE_DEFEAT'
  | 'GUILD_PANEL'
  | 'POPUP_INTERRUPT'
  | 'ACCOUNT_SWITCHING';

export type AccountType = 'clone_user_0' | 'clone_user_999' | 'phone_auth' | 'guest';

export interface AccountItem {
  id: string;
  name: string;
  type: AccountType;
  userId?: number;
  phone?: string;
  doneToday: boolean;
  stamina: number;
  maxStamina: number;
  boatTicketsDonated: number;
  goldDonatedTimes: number;
  currentStage: string;
  lastRunTime?: string;
  ipResetCount: number;
  enabled: boolean;
}

export interface SkillCandidate {
  id: string;
  name: string;
  category: 'survival' | 'offense' | 'elemental' | 'utility';
  desc: string;
  bounds: {
    left: number;
    top: number;
    right: number;
    bottom: number;
  };
  matchedPriorityRank?: number; // 0 is highest
  confidence: number;
}

export interface TouchEventRecord {
  id: string;
  timestamp: string;
  targetX: number;
  targetY: number;
  realX: number;
  realY: number;
  pressTime: number;
  stdev: number;
  label: string;
}

export interface LogMessage {
  id: string;
  timestamp: string;
  level: 'INFO' | 'WARN' | 'ERROR' | 'FSM' | 'OCR' | 'TOUCH' | 'GUARD';
  tag: string;
  message: string;
}

/** 归一化 OCR 区域：[left, top, right, bottom]，取值 0–1，null 表示全屏 */
export type OcrRegion = [number, number, number, number];

/**
 * 真机自动化参数。字段与 backend/app/schemas.py::AutomationStartRequest 对齐，
 * 由界面统一维护并持久化，不再散落在 useDeviceBridge 的局部 state 里。
 */
export interface AutomationConfig {
  /** 速度倍数：<1 加速（0.5 = 两倍速），1.0 正常 */
  speed: number;
  towerFloors: number;
  maxStageFails: number;
  travelStamina: number;
  stageMode: 'full' | 'lean';
  fastStageCheckEvery: number;
  /** 本次运行归属账号，留空由主城画面识别 */
  account: string;
  /** 账号队列（account_sweep 按顺序执行） */
  accountQueue: string[];
  serverFrom: string;
  serverTo: string;
  serverDryRun: boolean;
  allowGemTalentBreakthrough: boolean;
  /** 最大循环数，0 = 不限 */
  maxRuns: number;
  ocrRegion: OcrRegion | null;
}

export interface PipelineConfig extends AutomationConfig {
  skillPriorityList: string[];
  gaussianStdev: number;
  pressDurationMean: number;
  pressDurationStdev: number;
  reactionMinDelay: number;
  reactionMaxDelay: number;
  enableAirplaneModeIpReset: boolean;
  enableScreenDarkening: boolean;
  enableWatchdogThread: boolean;
  autoSweepDaily: boolean;
  maxDailyBoatTickets: number;
  maxDefeatRetries: number;
}
