export type BridgeMode = 'sim' | 'real';

export interface HealthPayload {
  ok: boolean;
  device_backend: string;
  adb_version: string | null;
  scrcpy_version: string | null;
  ocr_engine: string | null;
  hint: string | null;
}

export interface DeviceInfoPayload {
  serial: string;
  state: string;
  model: string | null;
  android: string | null;
  abi: string | null;
  wm_size: string | null;
  width: number | null;
  height: number | null;
  transport_id: string | null;
}

export interface SessionPayload {
  sessionId: string;
  serial: string;
  width: number;
  height: number;
  fps: number;
  degraded: boolean;
  mode: 'scrcpy' | 'screencap' | 'mock';
  sizeMismatch: boolean;
}

export interface TapPayload {
  targetX: number;
  targetY: number;
  realX: number;
  realY: number;
  pressMs: number;
  injectedVia: string;
  deviceWidth: number;
  deviceHeight: number;
}

export interface OcrItemPayload {
  text: string;
  confidence: number;
  bounds: { left: number; top: number; right: number; bottom: number };
  /** 知识库标注：秘宝 kind（核心/守护/图腾） */
  kind?: string | null;
  /** 知识库标注：品质（神话/传说/史诗/稀有/超越/至宝/不朽/绝世） */
  rarity?: string | null;
  /** 知识库标注：主词条英文字段键，指向 ocr_attr_index.json */
  lexiconRef?: string | null;
}

export interface OcrPayload {
  tookMs: number;
  engine: string | null;
  items: OcrItemPayload[];
}

export interface UsersPayload {
  users: { id: number; name: string; current: boolean }[];
  switchSupported: boolean;
  reason: string | null;
}

export interface AutomationLogPayload {
  ts: number;
  level: 'info' | 'warn' | 'error';
  message: string;
}

export type AutomationTask =
  | 'growth'
  | 'daily'
  | 'guild'
  | 'ship'
  | 'bootstrap'
  | 'server_sweep'
  | 'account_sweep'
  | 'all';

export interface AutomationPayload {
  status: 'idle' | 'running' | 'completed' | 'stopped' | 'error';
  task: AutomationTask | null;
  sessionId: string | null;
  startedAt: number | null;
  endedAt: number | null;
  error: string | null;
  progress: {
    stageRuns: number;
    towerFloors: number;
    dailySteps: number;
    guildSteps: number;
    shipSteps: number;
    guildRaids?: number;
    dungeonSweeps?: number;
    phase?: string;
    stageFails?: number;
    stageFailStreak?: number;
    dungeonsDone?: number;
    travelSpent?: number;
    // AutoX 端侧开始游历前 OCR 确认的体力证据
    staminaBefore?: number;
    upgradeSteps?: number;
    accountsCreated?: number;
    serversDone?: number;
    power?: number;
    stamina?: number;
  };
  logs: AutomationLogPayload[];
}

export interface CurrentAppPayload {
  package: string;
  activity: string | null;
  running: boolean;
  pid: number | null;
}

export interface VerifyCheckPayload {
  checkId: string;
  status: 'PASS' | 'FAIL' | 'SKIP';
  detail: string;
  elapsedMs: number;
}

export interface VerifyPayload {
  serial: string;
  started: string;
  deviceOnline: boolean;
  summary: { passed: number; failed: number; skipped: number; ok: boolean };
  checks: VerifyCheckPayload[];
  hint: string | null;
}

export type SwipeDirection = 'up' | 'down' | 'left' | 'right';

export interface AccountWorkRecord {
  label: string;
  done: boolean;
  count: number;
  doneAt: number | null;
}

export interface AccountRunRecord {
  runId: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'stopped';
  currentPhase: string;
  error: string;
  startedAt: number;
  updatedAt: number;
  progress: AutomationPayload['progress'];
}

export interface AccountRecord {
  name: string;
  power: number;
  stamina: number;
  updatedAt: number | null;
  lastRun: AccountRunRecord | null;
  works: Record<'daily' | 'guild' | 'ship' | 'stage', AccountWorkRecord>;
}
