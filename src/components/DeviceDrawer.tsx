import React from 'react';
import { Play, ScanText, ShieldCheck, Square, Users, Wifi, WifiOff } from 'lucide-react';
import type { OcrPayload, UsersPayload } from '../types/device';

interface DeviceDrawerProps {
  packageName: string;
  busy: boolean;
  users: UsersPayload | null;
  ocr: OcrPayload | null;
  onLaunch: () => void;
  onStop: () => void;
  onLoadUsers: () => void;
  onSwitchUser: (userId: number) => void;
  onAirplane: (enable: boolean) => void;
  onOcr: () => void;
  onVerify: () => void;
  verifyResult: string | null;
}

const CARD = 'p-4 bg-slate-900 rounded-xl border border-slate-800 space-y-3';
const CARD_TITLE = 'flex items-center gap-2 text-xs font-bold text-slate-100';
const ACTION =
  'px-2.5 py-1.5 rounded-md text-[11px] font-semibold transition-colors cursor-pointer border flex items-center gap-1.5 disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:border-slate-700';

export const DeviceDrawer: React.FC<DeviceDrawerProps> = ({
  packageName,
  busy,
  users,
  ocr,
  onLaunch,
  onStop,
  onLoadUsers,
  onSwitchUser,
  onAirplane,
  onOcr,
  onVerify,
  verifyResult,
}) => {
  const switchDisabled = busy || !users || users.switchSupported === false;

  return (
    <div className="grid gap-3 sm:grid-cols-2 content-start">
      {/* 应用 */}
      <section className={CARD}>
        <div className="flex items-center justify-between gap-2">
          <h3 className={CARD_TITLE}>
            <Play className="w-3.5 h-3.5 text-amber-400" />
            <span>应用</span>
          </h3>
          <span className="text-[10px] font-mono text-slate-500">改机 / 启动</span>
        </div>
        <p className="text-[10px] font-mono text-slate-400 truncate" title={packageName}>
          {packageName}
        </p>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={onLaunch}
            disabled={busy}
            className={`${ACTION} bg-amber-500 text-slate-950 border-amber-500 hover:bg-amber-400 disabled:hover:bg-amber-500`}
          >
            <Play className="w-3 h-3 fill-current" />
            <span>启动游戏</span>
          </button>
          <button
            type="button"
            onClick={onStop}
            disabled={busy}
            className={`${ACTION} bg-slate-950 text-slate-300 border-slate-700 hover:border-rose-500/60 hover:text-rose-300`}
          >
            <Square className="w-3 h-3" />
            <span>停止游戏</span>
          </button>
        </div>
        <div className="pt-2 border-t border-slate-800/80 space-y-1.5">
          <button
            type="button"
            onClick={onVerify}
            disabled={busy}
            className={`${ACTION} bg-slate-950 text-slate-300 border-slate-700 hover:border-amber-500/60 hover:text-amber-400`}
          >
            <ShieldCheck className="w-3 h-3" />
            <span>校验环境</span>
          </button>
          {verifyResult ? (
            <p className="text-[10px] font-mono text-slate-400 break-all">{verifyResult}</p>
          ) : (
            <p className="text-[10px] text-slate-500">请在终端执行 npm run verify</p>
          )}
        </div>
      </section>

      {/* 账号 */}
      <section className={CARD}>
        <div className="flex items-center justify-between gap-2">
          <h3 className={CARD_TITLE}>
            <Users className="w-3.5 h-3.5 text-amber-400" />
            <span>账号</span>
          </h3>
          <button
            type="button"
            onClick={onLoadUsers}
            disabled={busy}
            className={`${ACTION} bg-slate-950 text-slate-300 border-slate-700 hover:border-amber-500/60 hover:text-amber-400`}
          >
            加载用户
          </button>
        </div>

        {!users ? (
          <p className="text-[11px] text-slate-500">尚未加载用户列表</p>
        ) : (
          <>
            <ul className="space-y-1">
              {users.users.map((user) => (
                <li
                  key={user.id}
                  className={`flex items-center justify-between gap-2 px-2 py-1.5 rounded-lg border text-[11px] ${
                    user.current
                      ? 'bg-amber-500/10 border-amber-500/40 text-amber-300'
                      : 'bg-slate-950/60 border-slate-800 text-slate-300'
                  }`}
                >
                  <span className="flex items-center gap-2 min-w-0">
                    <span className="font-mono text-[10px] text-slate-500 shrink-0">
                      #{user.id}
                    </span>
                    <span className="truncate">{user.name}</span>
                  </span>
                  {user.current ? (
                    <span className="text-[10px] font-mono shrink-0">当前</span>
                  ) : (
                    <button
                      type="button"
                      onClick={() => onSwitchUser(user.id)}
                      disabled={switchDisabled}
                      className={`${ACTION} bg-slate-950 text-slate-300 border-slate-700 hover:border-amber-500/60 hover:text-amber-400 shrink-0`}
                    >
                      切换
                    </button>
                  )}
                </li>
              ))}
            </ul>

            {users.switchSupported === false && (
              <p className="text-[10px] text-amber-400/90 break-all">
                切换不可用：{users.reason ?? '当前设备不支持多用户切换'}
              </p>
            )}
          </>
        )}
      </section>

      {/* 网络 */}
      <section className={CARD}>
        <div className="flex items-center justify-between gap-2">
          <h3 className={CARD_TITLE}>
            <Wifi className="w-3.5 h-3.5 text-amber-400" />
            <span>网络</span>
          </h3>
          <span className="text-[10px] font-mono text-slate-500">IP 重置</span>
        </div>
        <p className="text-[11px] text-slate-500">飞行模式可触发重拨，获取新的蜂窝出口 IP。</p>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => onAirplane(true)}
            disabled={busy}
            className={`${ACTION} bg-slate-950 text-slate-300 border-slate-700 hover:border-amber-500/60 hover:text-amber-400`}
          >
            <WifiOff className="w-3 h-3" />
            <span>开启飞行模式</span>
          </button>
          <button
            type="button"
            onClick={() => onAirplane(false)}
            disabled={busy}
            className={`${ACTION} bg-slate-950 text-slate-300 border-slate-700 hover:border-emerald-500/60 hover:text-emerald-400`}
          >
            <Wifi className="w-3 h-3" />
            <span>关闭飞行模式</span>
          </button>
        </div>
      </section>

      {/* 视觉 */}
      <section className={CARD}>
        <div className="flex items-center justify-between gap-2">
          <h3 className={CARD_TITLE}>
            <ScanText className="w-3.5 h-3.5 text-amber-400" />
            <span>视觉</span>
          </h3>
          <button
            type="button"
            onClick={onOcr}
            disabled={busy}
            className={`${ACTION} bg-slate-950 text-slate-300 border-slate-700 hover:border-amber-500/60 hover:text-amber-400`}
          >
            执行 OCR
          </button>
        </div>

        {!ocr ? (
          <p className="text-[11px] text-slate-500">尚未执行 OCR</p>
        ) : (
          <div className="space-y-1.5">
            <p className="text-[10px] font-mono text-slate-400">
              耗时 {ocr.tookMs} ms · 识别 {ocr.items.length} 条
            </p>
            {ocr.items.length === 0 ? (
              <p className="text-[11px] text-slate-500">未识别到文本（不会自动点击）</p>
            ) : (
              <ul className="space-y-1 max-h-40 overflow-y-auto">
                {ocr.items.map((item, index) => (
                  <li
                    key={`${item.text}_${index}`}
                    className="flex items-center justify-between gap-2 px-2 py-1 rounded bg-slate-950/60 border border-slate-800 text-[11px] text-slate-300"
                  >
                    <span className="truncate">{item.text}</span>
                    <span className="font-mono text-[10px] text-emerald-400 shrink-0">
                      {item.confidence.toFixed(2)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </section>
    </div>
  );
};
