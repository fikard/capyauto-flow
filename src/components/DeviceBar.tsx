import React from 'react';
import { AlertTriangle, Monitor, RefreshCw, Smartphone, Wifi, WifiOff } from 'lucide-react';
import type {
  BridgeMode,
  DeviceInfoPayload,
  HealthPayload,
  SessionPayload,
} from '../types/device';

interface DeviceBarProps {
  mode: BridgeMode;
  onModeChange: (mode: BridgeMode) => void;
  health: HealthPayload | null;
  device: DeviceInfoPayload | null;
  session: SessionPayload | null;
  error: string | null;
  onRefresh: () => void;
}

export const DeviceBar: React.FC<DeviceBarProps> = ({
  mode,
  onModeChange,
  health,
  device,
  session,
  error,
  onRefresh,
}) => {
  const online = Boolean(health?.ok && session);
  const serial = session?.serial ?? device?.serial ?? '未连接设备';

  return (
    <div className="p-3 bg-slate-900 rounded-xl border border-slate-800 space-y-2">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <div className="flex p-0.5 bg-slate-950 rounded-lg border border-slate-800">
            <button
              type="button"
              onClick={() => onModeChange('sim')}
              className={`px-3 py-1.5 text-xs rounded-md font-semibold transition-colors cursor-pointer whitespace-nowrap flex items-center gap-1.5 ${
                mode === 'sim'
                  ? 'bg-slate-700 text-slate-100'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Monitor className="w-3.5 h-3.5" />
              <span>仿真</span>
            </button>
            <button
              type="button"
              onClick={() => onModeChange('real')}
              className={`px-3 py-1.5 text-xs rounded-md font-semibold transition-colors cursor-pointer whitespace-nowrap flex items-center gap-1.5 ${
                mode === 'real'
                  ? 'bg-amber-500 text-slate-950 font-bold'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Smartphone className="w-3.5 h-3.5" />
              <span>真机</span>
            </button>
          </div>

          <span
            className={`inline-flex items-center gap-1 px-2 py-0.5 rounded border text-[10px] font-mono font-bold tracking-wider ${
              online
                ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
                : 'bg-slate-800/60 text-slate-400 border-slate-700'
            }`}
          >
            {online ? <Wifi className="w-3 h-3" /> : <WifiOff className="w-3 h-3" />}
            <span>{online ? 'ONLINE' : 'OFFLINE'}</span>
          </span>
        </div>

        <div className="flex flex-wrap items-center gap-2 text-[11px] font-mono text-slate-400">
          <span className="px-2 py-0.5 rounded bg-slate-950 border border-slate-800 text-slate-300 max-w-[220px] truncate">
            {serial}
          </span>

          {session ? (
            <>
              <span className="px-2 py-0.5 rounded bg-slate-950 border border-slate-800">
                {session.width}×{session.height}
              </span>
              <span className="px-2 py-0.5 rounded bg-slate-950 border border-slate-800">
                {session.fps} fps
              </span>
              <span className="px-2 py-0.5 rounded bg-slate-950 border border-slate-800 text-amber-400">
                {session.mode}
              </span>
              {session.degraded && (
                <span className="px-2 py-0.5 rounded bg-amber-500/10 border border-amber-500/30 text-amber-400">
                  降级
                </span>
              )}
              {session.sizeMismatch && (
                <span className="px-2 py-0.5 rounded bg-rose-500/10 border border-rose-500/30 text-rose-400">
                  尺寸不一致
                </span>
              )}
            </>
          ) : (
            <span className="px-2 py-0.5 rounded bg-slate-950 border border-slate-800 text-slate-500">
              无活动会话
            </span>
          )}

          <button
            type="button"
            onClick={onRefresh}
            className="px-2.5 py-1 rounded-md bg-slate-950 border border-slate-700 text-slate-300 hover:border-amber-500/60 hover:text-amber-400 transition-colors cursor-pointer flex items-center gap-1.5 font-mono"
          >
            <RefreshCw className="w-3 h-3" />
            <span>刷新设备</span>
          </button>
        </div>
      </div>

      {error && (
        <div
          role="alert"
          className="flex items-start gap-2 px-3 py-2 rounded-lg bg-rose-950/40 border border-rose-800/60 text-[11px] text-rose-300 font-mono break-all"
        >
          <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}
    </div>
  );
};
