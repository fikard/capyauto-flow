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
  const [hasFrame, setHasFrame] = useState(false);

  const sessionId = session?.sessionId ?? null;
  const deviceWidth = session?.width ?? 0;
  const deviceHeight = session?.height ?? 0;

  useEffect(() => {
    hasFrameRef.current = false;
    setHasFrame(false);

    if (!sessionId || !deviceWidth || !deviceHeight) {
      setStatus('idle');
      setStreamError(null);
      return;
    }

    let cancelled = false;
    setStatus('connecting');
    setStreamError(null);

    const ws = new WebSocket(buildMirrorUrl(sessionId));
    ws.binaryType = 'blob';

    ws.onopen = () => {
      if (!cancelled) setStatus('live');
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
            setStreamError(payload.message ?? payload.code ?? '镜像流返回错误');
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
          if (cancelled) {
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
      if (!cancelled) setStatus((prev) => (prev === 'error' ? 'error' : 'closed'));
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

  const overlayMessage = streamError ?? error;
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

          {overlayMessage && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-slate-950/80 p-4 text-center">
              <AlertTriangle className="w-5 h-5 text-rose-400" />
              <span className="text-[11px] text-rose-300 font-mono break-all">{overlayMessage}</span>
            </div>
          )}

          {!overlayMessage && !hasFrame && (
            <div className="absolute inset-0 flex items-center justify-center bg-slate-950/80 text-[11px] font-mono text-slate-400">
              {status === 'closed' ? '连接已断开，点击刷新重连' : '正在连接镜像流…'}
            </div>
          )}

          {!overlayMessage && hasFrame && status === 'closed' && (
            <div className="absolute inset-x-0 bottom-0 py-1.5 text-center bg-slate-950/85 border-t border-slate-800 text-[11px] font-mono text-amber-400">
              连接已断开，点击刷新重连
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
