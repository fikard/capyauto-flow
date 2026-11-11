import React, { useEffect, useRef, useState } from 'react';
import { AlertTriangle, Video } from 'lucide-react';
import { buildMirrorUrl, isTapInside, toNormalized } from '../api/deviceClient';
import type { SessionPayload, TapPayload } from '../types/device';

interface DeviceMirrorProps {
  session: SessionPayload | null;
  lastTap: TapPayload | null;
  onTap: (x: number, y: number) => void;
  error: string | null;
}

const MAX_DISPLAY_WIDTH = 360;

type StreamStatus = 'idle' | 'connecting' | 'live' | 'closed' | 'error';

const STATUS_LABEL: Record<StreamStatus, string> = {
  idle: '未连接',
  connecting: '连接中',
  live: '实时',
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

  const sessionId = session?.sessionId ?? null;
  const deviceWidth = session?.width ?? 0;
  const deviceHeight = session?.height ?? 0;

  useEffect(() => {
    hasFrameRef.current = false;
    setHasFrame(false);
    setDisconnected(false);

    if (!sessionId || !deviceWidth || !deviceHeight) {
      setStatus('idle');
      setStreamError(null);
      return;
    }

    let cancelled = false;
    setStatus('connecting');
    setStreamError(null);
    setDisconnected(false);

    const ws = new WebSocket(buildMirrorUrl(sessionId));
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
        try {
          const payload = JSON.parse(event.data) as {
            type?: string;
            message?: string;
            code?: string;
          };
          if (payload?.type === 'error') {
            // 断流错误帧：保留原始信息作为副标题，但「连接已断开」提示必须出现
            setStreamError(payload.message ?? payload.code ?? '镜像流返回错误');
            setDisconnected(true);
            setStatus('error');
          }
        } catch {
          // 非 JSON 文本帧忽略
        }
        return;
      }

      const blob = event.data instanceof Blob ? event.data : null;
      if (!blob) return;

      createImageBitmap(blob)
        .then((bitmap) => {
          // 帧可能在 close 前入队：连接已关闭时丢弃迟到帧，不得覆盖 onclose 的断流状态
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
            // 收到新帧 = 连接恢复，清除瞬时错误状态，避免永久锁死交互
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
      // 保留最后一帧，仅提示重连
      if (!cancelled) {
        setStatus((prev) => (prev === 'error' ? 'error' : 'closed'));
        setDisconnected(true);
      }
    };

    return () => {
      cancelled = true;
      ws.close();
    };
  }, [sessionId, deviceWidth, deviceHeight]);

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
        <span
          className={`px-2 py-0.5 rounded border text-[10px] font-mono tracking-wider ${
            status === 'live'
              ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
              : status === 'error'
                ? 'bg-rose-500/10 text-rose-400 border-rose-500/30'
                : 'bg-slate-950 text-slate-400 border-slate-800'
          }`}
        >
          {STATUS_LABEL[status]}
        </span>
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
              <span className="text-[11px] font-mono text-amber-400">连接已断开，点击刷新重连</span>
              {streamError && (
                <span className="text-[10px] font-mono text-rose-300 break-all">{streamError}</span>
              )}
            </div>
          )}

          {disconnected && hasFrame && (
            <div className="pointer-events-none absolute inset-x-0 bottom-0 flex flex-col items-center gap-0.5 py-1.5 bg-slate-950/85 border-t border-slate-800">
              <span className="text-[11px] font-mono text-amber-400">连接已断开，点击刷新重连</span>
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
          <span className="text-[11px] font-mono text-slate-500">尚未连接设备，点击刷新重连</span>
        </div>
      )}

      <div className="mt-3 flex items-center justify-between text-[10px] font-mono text-slate-500 gap-2">
        <span>点击画布注入真机触摸</span>
        {session && (
          <span>
            {deviceWidth}×{deviceHeight} · {session.fps} fps · {session.mode}
          </span>
        )}
      </div>
    </div>
  );
};
