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
