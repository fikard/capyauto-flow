/**
 * /ws/mirror 文本帧协议（后端 backend/app/api/mirror.py）：
 *   {"type":"meta", seq, ts, width, height, fps, degraded, mode}  每 5 帧一次 + 连接首帧
 *   {"type":"error", code, message}                             会话失效 / MIRROR_LOST
 *   {"type":"pong", ts}                                         心跳响应
 * 二进制帧是 JPEG，由 DeviceMirror 直接解码。
 */
export interface MirrorMeta {
  type: 'meta';
  seq: number;
  ts: number;
  width: number;
  height: number;
  fps: number;
  degraded: boolean;
  mode: string;
}

export interface MirrorErrorFrame {
  type: 'error';
  code?: string;
  message?: string;
}

export type MirrorTextFrame =
  | { kind: 'meta'; meta: MirrorMeta }
  | { kind: 'error'; error: MirrorErrorFrame }
  | { kind: 'pong' }
  | { kind: 'unknown' };

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object';
}

/** 把任意文本帧解析成判别联合；坏 JSON / 未知 type 一律返回 unknown，不抛异常 */
export function parseMirrorText(data: string): MirrorTextFrame {
  let parsed: unknown;
  try {
    parsed = JSON.parse(data);
  } catch {
    return { kind: 'unknown' };
  }
  if (!isRecord(parsed)) return { kind: 'unknown' };
  if (parsed.type === 'meta') {
    const { seq, ts, width, height, fps, degraded, mode } = parsed;
    return {
      kind: 'meta',
      meta: {
        type: 'meta',
        seq: typeof seq === 'number' ? seq : 0,
        ts: typeof ts === 'number' ? ts : 0,
        width: typeof width === 'number' ? width : 0,
        height: typeof height === 'number' ? height : 0,
        fps: typeof fps === 'number' ? fps : 0,
        degraded: degraded === true,
        mode: typeof mode === 'string' ? mode : 'unknown',
      },
    };
  }
  if (parsed.type === 'error') {
    return {
      kind: 'error',
      error: {
        type: 'error',
        code: typeof parsed.code === 'string' ? parsed.code : undefined,
        message: typeof parsed.message === 'string' ? parsed.message : undefined,
      },
    };
  }
  if (parsed.type === 'pong') return { kind: 'pong' };
  return { kind: 'unknown' };
}

export const RECONNECT_BASE_MS = 1000;
export const RECONNECT_MAX_MS = 8000;

/** 指数退避：1s → 2s → 4s → 8s → 8s…；attempt 从 0 开始 */
export function reconnectDelay(attempt: number): number {
  const safe = Number.isFinite(attempt) && attempt >= 0 ? Math.floor(attempt) : 0;
  return Math.min(RECONNECT_MAX_MS, RECONNECT_BASE_MS * 2 ** safe);
}

/** 依据 meta 与 session 判断画布尺寸是否要跟着设备分辨率变化 */
export function metaSizeMismatch(meta: MirrorMeta, width: number, height: number): boolean {
  return meta.width > 0 && meta.height > 0 && (meta.width !== width || meta.height !== height);
}
