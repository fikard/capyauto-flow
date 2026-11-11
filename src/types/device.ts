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
