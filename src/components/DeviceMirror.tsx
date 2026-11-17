import React, { useEffect, useRef, useState } from 'react';
import { AlertTriangle, RefreshCw, Video } from 'lucide-react';
import { buildMirrorUrl, isTapInside, toNormalized } from '../api/deviceClient';
import {
  metaSizeMismatch,
  parseMirrorText,
  reconnectDelay,
  type MirrorMeta,
} from '../core/mirrorStream';
import type { SessionPayload, TapPayload } from '../types/device';

interface DeviceMirrorProps {
  session: SessionPayload | null;
  lastTap: TapPayload | null;
  onTap: (x: number, y: number) => void;
  error: string | null;
}

const MAX_DISPLAY_WIDTH = 360;

type StreamStatus = 'idle' | 'connecting' | 'live' | 'reconnecting' | 'closed' | 'error';

const STATUS_LABEL: Record<StreamStatus, string> = {
  idle: '未连接',
  connecting: '连接中',
  live: '实时',
  reconnecting: '重连中',
  closed: '已断开',
  error: '异常',
};

export const DeviceMirror: React.FC<DeviceMirrorProps> = ({
  session,
  lastTap,
  onTap,
  error,
}) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const hasFrameRef = useRef(false);
  const [status, setStatus] = useState<StreamStatus>('idle');
  const [streamError, setStreamError] = useState<string | null>(null);
  const [disconnected, setDisconnected] = useState(false);
  const [hasFrame, setHasFrame] = useState(false);
  const [meta, setMeta] = useState<MirrorMeta | null>(null);
  const [retryCount, setRetryCount] = useState(0);
  const [reconnectToken, setReconnectToken] = useState(0);
  const lastSessionRef = useRef<string | null>(null);

  const sessionId = session?.sessionId ?? null;
  const deviceWidth = session?.width ?? 0;
  const deviceHeight = session?.height ?? 0;

  useEffect(() => {
    // 只有切换会话才清空画面；自动/手动重连保留最后一帧，避免闪黑
    if (lastSessionRef.current !== sessionId) {
      lastSessionRef.current = sessionId;
      hasFrameRef.current = false;
      setHasFrame(false);
      setMeta(null);
      setRetryCount(0);
    }

    if (!sessionId || !deviceWidth || !deviceHeight) {
      setStatus('idle');
      setStreamError(null);
      setDisconnected(false);
      return;
    }

    let cancelled = false;
    let socket: WebSocket | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let heartbeat: ReturnType<typeof setInterval> | null = null;
    let attempt = 0;

    setStreamError(null);
    setDisconnected(false);

    function scheduleReconnect() {
      if (cancelled || retryTimer) return;
      const delay = reconnectDelay(attempt);
      attempt += 1;
      setRetryCount(attempt);
      setStatus('reconnecting');
      retryTimer = setTimeout(() => {
        retryTimer = null;
        openSocket();
      }, delay);
    }

    function openSocket() {
      if (cancelled) return;
      if (heartbeat) {
        clearInterval(heartbeat);
        heartbeat = null;
      }
      setStatus(attempt === 0 ? 'connecting' : 'reconnecting');
      const ws = new WebSocket(buildMirrorUrl(sessionId as string));
      socket = ws;
      ws.binaryType = 'blob';

      ws.onopen = () => {
        if (cancelled) return;
        setStatus('live');
        setStreamError(null);
        setDisconnected(false);
      };

      ws.onmessage = (event: MessageEvent) => {
        if (cancelled) return;

        if (typeof event.data === 'string') {
          const frame = parseMirrorText(event.data);
          if (frame.kind === 'meta') {
            // meta 是后端每 5 帧推一次的链路心跳：seq / 分辨率 / fps / 降级状态都在这里消费
            attempt = 0;
            setRetryCount((prev) => (prev === 0 ? prev : 0));
            setMeta(frame.meta);
            return;
          }
          if (frame.kind === 'error') {
            setStreamError(frame.error.message ?? frame.error.code ?? '镜像流返回错误');
            setDisconnected(true);
            setStatus('error');
            // 主动关闭，交给 onclose 统一走退避重连
            ws.close();
          }
          return;
        }

        const blob = event.data instanceof Blob ? event.data : null;
        if (!blob) return;

        createImageBitmap(blob)
          .then((bitmap) => {
            // 帧可能在 close 前入队：连接已关闭时丢弃迟到帧，不得覆盖断流状态
            if (cancelled || ws.readyState !== WebSocket.OPEN) {
              bitmap.close();
              return;
            }
            const canvas = canvasRef.current;
            const ctx = canvas?.getContext('2d');
            if (canvas && ctx) {
              ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
              if (!hasFrameRef.current) {
                hasFrameRef.current = true;
                setHasFrame(true);
              }
              // 收到新帧 = 链路是活的，清零退避并清除瞬时错误
              attempt = 0;
              setRetryCount((prev) => (prev === 0 ? prev : 0));
              setStatus((prev) => (prev === 'live' ? prev : 'live'));
              setStreamError((prev) => (prev ? null : prev));
              setDisconnected((prev) => (prev ? false : prev));
            }
            bitmap.close();
          })
          .catch(() => {
            if (!cancelled) setStreamError('镜像帧解码失败');
          });
      };

      ws.onerror = () => {
        if (cancelled) return;
        setStreamError('镜像流连接异常');
        setStatus('error');
      };

      ws.onclose = () => {
        if (cancelled) return;
        setStatus('closed');
        setDisconnected(true);
        scheduleReconnect();
      };

      // 后端 pump_client 会回 pong；定期发 ping 防止中间代理掐掉空闲连接
      heartbeat = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          try {
            ws.send(JSON.stringify({ type: 'ping' }));
          } catch {
            // 发送失败由 onclose 接管
          }
        }
      }, 15000);
    }

    openSocket();

    return () => {
      cancelled = true;
      if (retryTimer) clearTimeout(retryTimer);
      if (heartbeat) clearInterval(heartbeat);
      if (socket) {
        socket.onclose = null;
        try {
          socket.close();
        } catch {
          // 已处于 CLOSING/CLOSED 时忽略
        }
      }
    };
  }, [sessionId, deviceWidth, deviceHeight, reconnectToken]);

  const handleCanvasClick = (event: React.MouseEvent<HTMLCanvasElement>) => {
    if (!session) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return;

    const offsetX = event.clientX - rect.left;
    const offsetY = event.clientY - rect.top;
    const { x, y } = toNormalized(offsetX, offsetY, rect.width, rect.height);
    if (!isTapInside(x, y)) return;
    onTap(x, y);
  };

  const tapGeometry =
    lastTap && lastTap.deviceWidth > 0 && lastTap.deviceHeight > 0
      ? {
          targetLeft: (lastTap.targetX / lastTap.deviceWidth) * 100,
          targetTop: (lastTap.targetY / lastTap.deviceHeight) * 100,
          realLeft: (lastTap.realX / lastTap.deviceWidth) * 100,
          realTop: (lastTap.realY / lastTap.deviceHeight) * 100,
          dx: Math.round(lastTap.realX - lastTap.targetX),
          dy: Math.round(lastTap.realY - lastTap.targetY),
        }
      : null;

  return (
    <div className="p-4 bg-slate-900 rounded-xl border border-slate-800">
      <div className="flex items-center justify-between pb-3 mb-3 border-b border-slate-800 gap-2">
        <div className="flex items-center gap-2">
          <Video className="w-4 h-4 text-amber-400" />
          <h3 className="text-sm font-bold text-slate-100">真机镜像</h3>
        </div>
        <div className="flex items-center gap-2">
          <span
            className={`px-2 py-0.5 rounded border text-[10px] font-mono tracking-wider ${
              status === 'live'
                ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
                : status === 'error'
                  ? 'bg-rose-500/10 text-rose-400 border-rose-500/30'
                  : status === 'reconnecting'
                    ? 'bg-amber-500/10 text-amber-400 border-amber-500/30'
                    : 'bg-slate-950 text-slate-400 border-slate-800'
            }`}
          >
            {STATUS_LABEL[status]}{status === 'reconnecting' && retryCount > 0 ? ` #${retryCount}` : ''}
          </span>
          <button
            type="button"
            onClick={() => setReconnectToken((token) => token + 1)}
            disabled={!session}
            title="跳过退避，立即重建镜像连接"
            className="flex items-center gap-1 px-2 py-0.5 rounded border border-slate-700 text-[10px] font-mono text-slate-300 hover:border-amber-500/60 hover:text-amber-400 cursor-pointer disabled:opacity-40"
          >
            <RefreshCw className="w-3 h-3" />
            <span>立即重连</span>
          </button>
        </div>
      </div>

      {session ? (
        <div
          className="relative mx-auto w-full rounded-lg overflow-hidden border border-slate-800 bg-slate-950"
          style={{ maxWidth: `${MAX_DISPLAY_WIDTH}px` }}
        >
          <canvas
            ref={canvasRef}
            width={deviceWidth}
            height={deviceHeight}
            onClick={handleCanvasClick}
            className="block w-full h-auto cursor-crosshair touch-none"
          />

          {tapGeometry && (
            <>
              <span
                aria-hidden="true"
                title={`意图点 (${lastTap?.targetX}, ${lastTap?.targetY})`}
                className="absolute w-3 h-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-amber-300 bg-amber-500/30"
                style={{ left: `${tapGeometry.targetLeft}%`, top: `${tapGeometry.targetTop}%` }}
              />
              <span
                aria-hidden="true"
                title={`落点 (${lastTap?.realX}, ${lastTap?.realY})`}
                className="absolute w-3 h-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-emerald-300 bg-emerald-500/40"
                style={{ left: `${tapGeometry.realLeft}%`, top: `${tapGeometry.realTop}%` }}
              />
              <span className="absolute bottom-1.5 left-1.5 px-1.5 py-0.5 rounded bg-slate-950/80 border border-slate-700 text-[10px] font-mono text-slate-300">
                Δx {tapGeometry.dx >= 0 ? '+' : ''}
                {tapGeometry.dx} / Δy {tapGeometry.dy >= 0 ? '+' : ''}
                {tapGeometry.dy}
              </span>
            </>
          )}

          {/* 非阻塞提示：bridge 全局错误与瞬时解码失败，均不拦截画布点击 */}
          {(error || (!disconnected && streamError)) && (
            <div className="pointer-events-none absolute inset-x-0 top-0 flex flex-col gap-1 p-1">
              {error && (
                <span className="flex items-start gap-1 px-2 py-1 rounded bg-rose-950/85 border border-rose-800/60 text-[10px] font-mono text-rose-300 break-all">
                  <AlertTriangle className="w-3 h-3 shrink-0 mt-px" />
                  <span>{error}</span>
                </span>
              )}
              {!disconnected && streamError && (
                <span className="px-2 py-1 rounded bg-amber-500/10 border border-amber-500/30 text-[10px] font-mono text-amber-400 break-all">
                  {streamError}
                </span>
              )}
            </div>
          )}

          {disconnected && !hasFrame && (
            <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-2 bg-slate-950/80 p-4 text-center">
              <AlertTriangle className="w-5 h-5 text-rose-400" />
              <span className="text-[11px] font-mono text-amber-400">镜像断流 · 自动重连中（第 {retryCount} 次，点「立即重连」可跳过退避）</span>
              {streamError && (
                <span className="text-[10px] font-mono text-rose-300 break-all">{streamError}</span>
              )}
            </div>
          )}

          {disconnected && hasFrame && (
            <div className="pointer-events-none absolute inset-x-0 bottom-0 flex flex-col items-center gap-0.5 py-1.5 bg-slate-950/85 border-t border-slate-800">
              <span className="text-[11px] font-mono text-amber-400">镜像断流 · 自动重连中（第 {retryCount} 次，点「立即重连」可跳过退避）</span>
              {streamError && (
                <span className="px-2 text-center text-[10px] font-mono text-rose-300 break-all">
                  {streamError}
                </span>
              )}
            </div>
          )}

          {!disconnected && !hasFrame && (
            <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-slate-950/80 text-[11px] font-mono text-slate-400">
              正在连接镜像流…
            </div>
          )}
        </div>
      ) : (
        <div
          className="mx-auto w-full h-40 rounded-lg border border-dashed border-slate-800 bg-slate-950 flex items-center justify-center px-4 text-center"
          style={{ maxWidth: `${MAX_DISPLAY_WIDTH}px` }}
        >
          <span className="text-[11px] font-mono text-slate-500">尚未连接设备，请在顶栏切到「真机」并建立会话</span>
        </div>
      )}

      <div className="mt-3 space-y-0.5 text-[10px] font-mono text-slate-500">
        <div className="flex items-center justify-between gap-2">
          <span>点击画布注入真机触摸</span>
          {session && (
            <span>
              {deviceWidth}×{deviceHeight} · {session.fps} fps · {session.mode}
            </span>
          )}
        </div>
        {meta && (
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className={meta.degraded ? 'text-amber-400' : 'text-slate-500'}>
              meta seq {meta.seq} · {meta.width}×{meta.height} · {meta.fps} fps · {meta.mode}
              {meta.degraded ? ' · 已降级' : ''}
            </span>
            <span>
              meta 距今 {Math.max(0, Math.round(Date.now() - meta.ts * 1000))}ms
              {retryCount > 0 ? ` · 重连 ${retryCount} 次` : ''}
            </span>
          </div>
        )}
        {meta && metaSizeMismatch(meta, deviceWidth, deviceHeight) && (
          <p className="text-amber-400">画布尺寸与设备分辨率不一致，点击落点可能有偏差，建议重建会话</p>
        )}
      </div>
    </div>
  );
};
