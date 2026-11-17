import type {
  AccountRecord,
  AutomationPayload,
  AutomationTask,
  DeviceInfoPayload,
  HealthPayload,
  OcrPayload,
  SessionPayload,
  TapPayload,
  UsersPayload,
  VerifyPayload,
} from '../types/device';
import type { OcrRegion } from '../types/pipeline';

const env = (import.meta as unknown as { env?: Record<string, string | undefined> }).env;
export const BACKEND_URL = env?.VITE_BACKEND_URL ?? 'http://127.0.0.1:8084';

export class DeviceApiError extends Error {
  status: number;
  code: string;

  constructor(code: string, message: string, status = 0) {
    super(message);
    this.name = 'DeviceApiError';
    this.code = code;
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BACKEND_URL}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...init,
    });
  } catch {
    throw new DeviceApiError('BACKEND_UNREACHABLE', `无法连接后端 ${BACKEND_URL}，请确认服务已启动`);
  }
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = payload?.error ?? {};
    throw new DeviceApiError(error.code ?? 'HTTP_ERROR', error.message ?? `请求失败（${response.status}）`, response.status);
  }
  return payload as T;
}

export function buildMirrorUrl(sessionId: string, base = BACKEND_URL): string {
  const wsBase = base.replace(/^http/, 'ws');
  return `${wsBase}/ws/mirror?sessionId=${encodeURIComponent(sessionId)}`;
}

export function toNormalized(offsetX: number, offsetY: number, width: number, height: number) {
  const clamp = (value: number) => Math.min(1, Math.max(0, value));
  return { x: clamp(offsetX / width), y: clamp(offsetY / height) };
}

export function isTapInside(x: number, y: number): boolean {
  return Number.isFinite(x) && Number.isFinite(y) && x >= 0 && x <= 1 && y >= 0 && y <= 1;
}

export const deviceClient = {
  health: () => request<HealthPayload>('/api/health'),
  listDevices: () => request<{ devices: DeviceInfoPayload[] }>('/api/devices'),
  createSession: (serial: string, fps = 5) =>
    request<SessionPayload>('/api/session', {
      method: 'POST',
      body: JSON.stringify({ serial, fps }),
    }),
  closeSession: (sessionId: string) =>
    request<{ ok: boolean }>(`/api/session/${encodeURIComponent(sessionId)}`, { method: 'DELETE' }),
  tap: (
    sessionId: string,
    x: number,
    y: number,
    pressMs = 80,
    sigma = 6,
    pressStdev = 20
  ) =>
    request<TapPayload>('/api/control/tap', {
      method: 'POST',
      body: JSON.stringify({ sessionId, x, y, pressMs, sigma, pressStdev }),
    }),
  swipe: (sessionId: string, x1: number, y1: number, x2: number, y2: number, durationMs = 300) =>
    request<{ points: [number, number][]; injectedVia: string }>('/api/control/swipe', {
      method: 'POST',
      body: JSON.stringify({ sessionId, x1, y1, x2, y2, durationMs }),
    }),
  key: (sessionId: string, key: string) =>
    request<{ ok: boolean }>('/api/control/key', {
      method: 'POST',
      body: JSON.stringify({ sessionId, key }),
    }),
  launchApp: (sessionId: string, packageName: string, user?: number) =>
    request<{
      ok: boolean;
      usedUser: number | null;
      package: string;
      activity: string | null;
      running: boolean;
      pid: number | null;
    }>(
      '/api/app/launch',
      { method: 'POST', body: JSON.stringify({ sessionId, package: packageName, user }) }
    ),
  stopApp: (sessionId: string, packageName: string) =>
    request<{ ok: boolean }>('/api/app/stop', {
      method: 'POST',
      body: JSON.stringify({ sessionId, package: packageName }),
    }),
  currentApp: (sessionId: string) =>
    request<{ package: string; activity: string | null; running: boolean; pid: number | null }>(
      `/api/app/current?sessionId=${encodeURIComponent(sessionId)}`
    ),
  listUsers: (sessionId: string) =>
    request<UsersPayload>(`/api/app/users?sessionId=${encodeURIComponent(sessionId)}`),
  switchUser: (sessionId: string, userId: number) =>
    request<{ ok: boolean; userId: number; switchSupported: boolean; reason: string | null }>(
      '/api/app/switch-user',
      { method: 'POST', body: JSON.stringify({ sessionId, userId }) }
    ),
  airplane: (sessionId: string, enable: boolean) =>
    request<{ ok: boolean; airplaneModeOn: boolean; appliedVia: string }>('/api/network/airplane', {
      method: 'POST',
      body: JSON.stringify({ sessionId, enable }),
    }),
  ocr: (sessionId: string, region: OcrRegion | null = null) =>
    request<OcrPayload>('/api/vision/ocr', {
      method: 'POST',
      body: JSON.stringify({ sessionId, region: region ?? undefined }),
    }),
  automationStatus: () => request<AutomationPayload>('/api/automation/status'),
  automationStart: (
    sessionId: string,
    task: AutomationTask,
    maxRuns = 0,
    skillPriorityList: string[] = [],
    speed = 1.0,
    towerFloors = 2,
    {
      maxStageFails,
      travelStamina,
      allowGemTalentBreakthrough,
      stageMode,
      fastStageCheckEvery,
      account,
      accounts,
      serverFrom,
      serverTo,
      serverDryRun,
    }: {
      maxStageFails?: number;
      travelStamina?: number;
      allowGemTalentBreakthrough?: boolean;
      stageMode?: 'full' | 'lean';
      fastStageCheckEvery?: number;
      account?: string;
      accounts?: string[];
      serverFrom?: string;
      serverTo?: string;
      serverDryRun?: boolean;
    } = {}
  ) =>
    request<AutomationPayload>('/api/automation/start', {
      method: 'POST',
      body: JSON.stringify({
        sessionId,
        task,
        maxRuns,
        skillPriorityList,
        speed,
        towerFloors,
        maxStageFails,
        travelStamina,
        allowGemTalentBreakthrough,
        stageMode,
        fastStageCheckEvery,
        account,
        accounts,
        serverFrom,
        serverTo,
        serverDryRun,
      }),
    }),
  automationStop: () => request<AutomationPayload>('/api/automation/stop', { method: 'POST' }),
  accounts: () => request<{ accounts: AccountRecord[] }>('/api/accounts'),
  verifyRun: (skip: string[] = [], serial = '') =>
    request<VerifyPayload>('/api/verify/run', {
      method: 'POST',
      body: JSON.stringify({ serial, skip }),
    }),
};
