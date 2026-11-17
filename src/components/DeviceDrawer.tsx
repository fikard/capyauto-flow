import React, { useState } from 'react';
import {
  Bot,
  Play,
  RefreshCw,
  ScanText,
  ShieldCheck,
  Smartphone,
  Square,
  Users,
  Wifi,
  WifiOff,
} from 'lucide-react';
import type {
  AccountRecord,
  AutomationPayload,
  AutomationTask,
  CurrentAppPayload,
  OcrPayload,
  SwipeDirection,
  UsersPayload,
  VerifyPayload,
} from '../types/device';
import type { AutomationConfig, OcrRegion } from '../types/pipeline';
import { isValidOcrRegion, parseAccountQueue } from '../core/pipelineConfig';

interface DeviceDrawerProps {
  packageName: string;
  /** 变速器宿主包：桌面「冒险者日记」快捷方式拉起的是它的沙箱 Activity */
  launcherHost: string;
  launcherIconLabel: string;
  busy: boolean;
  users: UsersPayload | null;
  ocr: OcrPayload | null;
  automation: AutomationPayload | null;
  accounts: AccountRecord[];
  automationConfig: AutomationConfig;
  setAutomationConfig: (patch: Partial<AutomationConfig>) => void;
  onLaunch: () => void;
  onStop: () => void;
  onLoadUsers: () => void;
  onSwitchUser: (userId: number) => void;
  onAirplane: (enable: boolean) => void;
  onOcr: (region: OcrRegion | null) => void;
  onVerify: () => void;
  /** 用 /api/accounts 的真实账号名覆盖队列 */
  onFillAccountQueue: () => void;
  /** 恢复默认配置（同时清空 localStorage 中的自定义值） */
  onResetConfig: () => void;
  onSwipe: (direction: SwipeDirection) => void;
  onKey: (key: string) => void;
  onCurrentApp: () => void;
  currentAppInfo: CurrentAppPayload | null;
  verifyBusy: boolean;
  onAutomationStart: (task: AutomationTask) => void;
  onAutomationStop: () => void;
  verifyResult: VerifyPayload | null;
}

const CARD = 'p-4 bg-slate-900 rounded-xl border border-slate-800 space-y-3';
const CARD_TITLE = 'flex items-center gap-2 text-xs font-bold text-slate-100';
const ACTION =
  'px-2.5 py-1.5 rounded-md text-[11px] font-semibold transition-colors cursor-pointer border flex items-center gap-1.5 disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:border-slate-700';
const SWIPE_LABELS: Record<SwipeDirection, string> = {
  up: '上滑',
  down: '下滑',
  left: '左滑',
  right: '右滑',
};
const SECONDARY = `${ACTION} bg-slate-950 text-slate-300 border-slate-700 hover:border-amber-500/60 hover:text-amber-400`;

export const DeviceDrawer: React.FC<DeviceDrawerProps> = ({
  packageName,
  launcherHost,
  launcherIconLabel,
  busy,
  users,
  ocr,
  automation,
  accounts,
  automationConfig,
  setAutomationConfig,
  onLaunch,
  onStop,
  onLoadUsers,
  onSwitchUser,
  onAirplane,
  onOcr,
  onVerify,
  onFillAccountQueue,
  onResetConfig,
  onSwipe,
  onKey,
  onCurrentApp,
  currentAppInfo,
  verifyBusy,
  onAutomationStart,
  onAutomationStop,
  verifyResult,
}) => {
  const switchDisabled = busy || !users || users.switchSupported === false;
  const autoRunning = automation?.status === 'running';
  const autoLogs = automation?.logs.slice(-6) ?? [];
  // 队列输入框用草稿态，避免逐字解析时把用户刚输入的分隔符吞掉
  const [queueDraft, setQueueDraft] = useState<string | null>(null);
  const queueText = queueDraft ?? automationConfig.accountQueue.join(', ');
  const commitQueue = () => {
    if (queueDraft !== null) setAutomationConfig({ accountQueue: parseAccountQueue(queueDraft) });
    setQueueDraft(null);
  };
  // OCR 区域同样用草稿态：逐个数字编辑时中间值可能暂时不合法，不能立刻写回配置
  const [regionDraft, setRegionDraft] = useState<string[] | null>(null);
  const [regionError, setRegionError] = useState<string | null>(null);
  const commitRegion = () => {
    if (regionDraft !== null) {
      const parsed = regionDraft.map((item) => Number(item)) as OcrRegion;
      if (isValidOcrRegion(parsed)) {
        setAutomationConfig({ ocrRegion: parsed });
        setRegionError(null);
      } else {
        setRegionError('区域不合法：需满足 0≤L<R≤1、0≤T<B≤1，已保留上次有效值');
      }
      setRegionDraft(null);
    }
  };

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
        <p className="text-[10px] font-mono text-emerald-300/90 truncate" title={`启动宿主 ${launcherHost}`}>
          启动宿主：{launcherHost} · 桌面「{launcherIconLabel}」
        </p>
        <p className="text-[10px] font-mono text-slate-500 truncate" title={packageName}>
          被托管游戏包：{packageName}（不可直启）
        </p>
        {currentAppInfo ? (
          <p className="text-[10px] font-mono text-slate-300 break-all">
            前台：{currentAppInfo.package || '(无)'} · {currentAppInfo.activity ?? '-'} · running={String(currentAppInfo.running)} · pid={currentAppInfo.pid ?? '-'}
          </p>
        ) : (
          <p className="text-[10px] text-slate-500">点「启动游戏」后自动回读真实前台</p>
        )}
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
            disabled={busy || verifyBusy}
            className={`${ACTION} bg-slate-950 text-slate-300 border-slate-700 hover:border-amber-500/60 hover:text-amber-400`}
          >
            <ShieldCheck className="w-3 h-3" />
            <span>{verifyBusy ? '校验中…' : '校验环境'}</span>
          </button>
          {verifyBusy ? (
            <p className="text-[10px] text-amber-400">正在执行 V1–V10 真机验收，可能持续数十秒…</p>
          ) : !verifyResult ? (
            <p className="text-[10px] text-slate-500">点击执行 V1–V10 真机验收（也可在终端执行 npm run verify）</p>
          ) : (
            <div className="space-y-1.5">
              <p
                className={`text-[10px] font-mono ${
                  verifyResult.summary.ok ? 'text-emerald-400' : 'text-rose-400'
                }`}
              >
                {verifyResult.deviceOnline ? '设备在线' : '设备离线'} · PASS {verifyResult.summary.passed} / FAIL{' '}
                {verifyResult.summary.failed} / SKIP {verifyResult.summary.skipped}
              </p>
              {verifyResult.hint && (
                <p className="text-[10px] text-amber-400">{verifyResult.hint}</p>
              )}
              <ul className="space-y-0.5 max-h-36 overflow-y-auto">
                {verifyResult.checks.map((check) => (
                  <li key={check.checkId} className="text-[10px] font-mono leading-snug">
                    <span
                      className={
                        check.status === 'PASS'
                          ? 'text-emerald-400'
                          : check.status === 'FAIL'
                            ? 'text-rose-400'
                            : 'text-slate-500'
                      }
                    >
                      {check.checkId} {check.status}
                    </span>
                    <span className="text-slate-400 break-all"> · {check.detail}</span>
                  </li>
                ))}
              </ul>
            </div>
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

      {/* 真机控制 */}
      <section className={CARD}>
        <div className="flex items-center justify-between gap-2">
          <h3 className={CARD_TITLE}>
            <Smartphone className="w-3.5 h-3.5 text-amber-400" />
            <span>真机控制</span>
          </h3>
          <span className="text-[10px] font-mono text-slate-500">滑动 / 按键 / 前台</span>
        </div>
        <div className="flex flex-wrap gap-2">
          {(['up', 'down', 'left', 'right'] as const).map((direction) => (
            <button
              key={direction}
              type="button"
              onClick={() => onSwipe(direction)}
              disabled={busy}
              className={SECONDARY}
            >
              {SWIPE_LABELS[direction]}
            </button>
          ))}
          {(['back', 'home', 'app_switch'] as const).map((key) => (
            <button
              key={key}
              type="button"
              onClick={() => onKey(key)}
              disabled={busy}
              className={SECONDARY}
            >
              {key === 'back' ? '返回键' : key === 'home' ? 'Home 键' : '多任务'}
            </button>
          ))}
          <button
            type="button"
            onClick={onCurrentApp}
            disabled={busy}
            className={SECONDARY}
          >
            <RefreshCw className="w-3 h-3" />
            <span>查询当前应用</span>
          </button>
        </div>
        {currentAppInfo ? (
          <p className="text-[10px] font-mono text-slate-400 break-all">
            {currentAppInfo.package || '(无)'} · {currentAppInfo.activity ?? '-'} · running={' '}
            {String(currentAppInfo.running)} · pid={currentAppInfo.pid ?? '-'}
          </p>
        ) : (
          <p className="text-[10px] text-slate-500">滑动坐标使用 0–1 归一化，按键名走后端 KEYCODES 白名单</p>
        )}
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
            onClick={() => onOcr(automationConfig.ocrRegion)}
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
                    <span className="truncate flex items-center gap-1.5 min-w-0">
                      {item.text}
                      {item.rarity && (
                        <span className="text-[9px] font-bold px-1 py-0.5 rounded shrink-0 bg-amber-500/20 text-amber-300 border border-amber-500/30">
                          {item.rarity}
                        </span>
                      )}
                      {item.kind && (
                        <span className="text-[9px] px-1 py-0.5 rounded shrink-0 bg-sky-500/20 text-sky-300 border border-sky-500/30">
                          {item.kind}
                        </span>
                      )}
                      {item.lexiconRef && (
                        <span className="text-[9px] font-mono text-slate-500 shrink-0" title={item.lexiconRef}>
                          {item.lexiconRef}
                        </span>
                      )}
                    </span>
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

      {/* 自动化 */}
      <section className={`${CARD} sm:col-span-2`}>
        <div className="flex items-center justify-between gap-2">
          <h3 className={CARD_TITLE}>
            <Bot className="w-3.5 h-3.5 text-amber-400" />
            <span>自动化</span>
          </h3>
          <span
            className={`text-[10px] font-mono px-1.5 py-0.5 rounded border ${
              autoRunning
                ? 'bg-emerald-500/15 border-emerald-500/40 text-emerald-300'
                : automation?.status === 'error'
                  ? 'bg-rose-500/15 border-rose-500/40 text-rose-300'
                  : 'bg-slate-950 border-slate-800 text-slate-500'
            }`}
          >
            {automation?.status ?? 'idle'}
          </span>
        </div>

        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => onAutomationStart('growth')}
            disabled={busy || autoRunning}
            className={`${ACTION} bg-amber-500 text-slate-950 border-amber-500 hover:bg-amber-400 disabled:hover:bg-amber-500`}
          >
            成长
          </button>
          <button
            type="button"
            onClick={() => onAutomationStart('daily')}
            disabled={busy || autoRunning}
            className={`${ACTION} bg-slate-950 text-slate-300 border-slate-700 hover:border-sky-500/60 hover:text-sky-300`}
          >
            日常
          </button>
          <button
            type="button"
            onClick={() => onAutomationStart('guild')}
            disabled={busy || autoRunning}
            className={`${ACTION} bg-slate-950 text-slate-300 border-slate-700 hover:border-emerald-500/60 hover:text-emerald-300`}
          >
            公会
          </button>
          <button
            type="button"
            onClick={() => onAutomationStart('ship')}
            disabled={busy || autoRunning}
            className={`${ACTION} bg-slate-950 text-slate-300 border-slate-700 hover:border-violet-500/60 hover:text-violet-300`}
          >
            船
          </button>
          <button
            type="button"
            onClick={() => onAutomationStart('bootstrap')}
            disabled={busy || autoRunning}
            className={`${ACTION} bg-emerald-500 text-slate-950 border-emerald-500 hover:bg-emerald-400 disabled:hover:bg-emerald-500`}
          >
            起号
          </button>
          <button
            type="button"
            onClick={() => onAutomationStart('account_sweep')}
            disabled={busy || autoRunning || automationConfig.accountQueue.length === 0}
            className={`${ACTION} bg-cyan-500 text-slate-950 border-cyan-500 hover:bg-cyan-400 disabled:hover:bg-cyan-500`}
          >
            依次执行七账号
          </button>
          <button
            type="button"
            onClick={() => onAutomationStart('server_sweep')}
            disabled={busy || autoRunning || !automationConfig.serverFrom}
            className={`${ACTION} bg-slate-950 text-slate-300 border-slate-700 hover:border-cyan-500/60 hover:text-cyan-300`}
          >
            区服遍历
          </button>
          <button
            type="button"
            title="日常 → 公会捐献/讨伐 → 船 → 副本挑战/扫荡 → 游历 → 推关 → 爬塔 → 提升"
            onClick={() => onAutomationStart('all')}
            disabled={busy || autoRunning}
            className={`${ACTION} bg-sky-500 text-slate-950 border-sky-500 hover:bg-sky-400 disabled:hover:bg-sky-500`}
          >
            全自动流水线
          </button>
          <button
            type="button"
            onClick={onAutomationStop}
            disabled={!autoRunning}
            className={`${ACTION} bg-slate-950 text-slate-300 border-slate-700 hover:border-rose-500/60 hover:text-rose-300`}
          >
            停止
          </button>
        </div>

        <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[11px] text-slate-400">
          <label className="flex items-center gap-1.5">
            <span>速度</span>
            <select
              value={automationConfig.speed}
              onChange={(e) => setAutomationConfig({ speed: Number(e.target.value) })}
              disabled={autoRunning}
              className="bg-slate-950 border border-slate-700 rounded px-1.5 py-0.5 text-[11px] text-slate-200 disabled:opacity-40"
            >
              <option value={0.3}>极速 x3.3</option>
              <option value={0.5}>快速 x2.0</option>
              <option value={1.0}>正常 x1.0</option>
            </select>
          </label>
          <label className="flex items-center gap-1.5">
            <span title="0 = 不限">最大循环数</span>
            <input
              type="number"
              min={0}
              max={10}
              value={automationConfig.maxRuns}
              onChange={(e) =>
                setAutomationConfig({ maxRuns: Math.max(0, Math.min(10, Number(e.target.value) || 0)) })
              }
              disabled={autoRunning}
              className="w-12 bg-slate-950 border border-slate-700 rounded px-1.5 py-0.5 text-[11px] text-slate-200 text-center disabled:opacity-40"
            />
          </label>
          <label className="flex items-center gap-1.5">
            <span>爬塔层数</span>
            <input
              type="number"
              min={0}
              max={20}
              value={automationConfig.towerFloors}
              onChange={(e) =>
                setAutomationConfig({ towerFloors: Math.max(0, Math.min(20, Number(e.target.value) || 0)) })
              }
              disabled={autoRunning}
              className="w-14 bg-slate-950 border border-slate-700 rounded px-1.5 py-0.5 text-[11px] text-slate-200 text-center disabled:opacity-40"
            />
          </label>
          <label className="flex items-center gap-1.5">
            <span>失败上限</span>
            <input
              type="number"
              min={1}
              max={5}
              value={automationConfig.maxStageFails}
              onChange={(e) =>
                setAutomationConfig({ maxStageFails: Math.max(1, Math.min(5, Number(e.target.value) || 1)) })
              }
              disabled={autoRunning}
              className="w-12 bg-slate-950 border border-slate-700 rounded px-1.5 py-0.5 text-[11px] text-slate-200 text-center disabled:opacity-40"
            />
          </label>
          <label className="flex items-center gap-1.5">
            <span>游历停止阈值</span>
            <input
              type="number"
              min={0}
              max={1000}
              value={automationConfig.travelStamina}
              onChange={(e) =>
                setAutomationConfig({ travelStamina: Math.max(0, Math.min(1000, Number(e.target.value) || 0)) })
              }
              disabled={autoRunning}
              className="w-14 bg-slate-950 border border-slate-700 rounded px-1.5 py-0.5 text-[11px] text-slate-200 text-center disabled:opacity-40"
            />
          </label>
          <label className="flex items-center gap-1.5">
            <span>推关模式</span>
            <select
              value={automationConfig.stageMode}
              onChange={(e) => setAutomationConfig({ stageMode: e.target.value === 'lean' ? 'lean' : 'full' })}
              disabled={autoRunning}
              className="bg-slate-950 border border-slate-700 rounded px-1.5 py-0.5 text-[11px] text-slate-200 disabled:opacity-40"
            >
              <option value="full">全量（逐帧识别）</option>
              <option value="lean">精简（定时回放）</option>
            </select>
          </label>
          <label className="flex items-center gap-1.5">
            <span>校验间隔</span>
            <input
              type="number"
              min={1}
              max={50}
              value={automationConfig.fastStageCheckEvery}
              onChange={(e) =>
                setAutomationConfig({ fastStageCheckEvery: Math.max(1, Math.min(50, Number(e.target.value) || 8)) })
              }
              disabled={autoRunning || automationConfig.stageMode !== 'lean'}
              className="w-12 bg-slate-950 border border-slate-700 rounded px-1.5 py-0.5 text-[11px] text-slate-200 text-center disabled:opacity-40"
            />
          </label>
          <label className="flex items-center gap-1.5">
            <span>账号</span>
            <input
              type="text"
              value={automationConfig.account}
              placeholder="留空自动识别"
              onChange={(e) => setAutomationConfig({ account: e.target.value })}
              disabled={autoRunning}
              className="w-24 bg-slate-950 border border-slate-700 rounded px-1.5 py-0.5 text-[11px] text-slate-200 disabled:opacity-40"
            />
          </label>
          <label className="flex items-center gap-1.5">
            <span>起始区服</span>
            <input
              type="text"
              value={automationConfig.serverFrom}
              placeholder="闲云野鹤1区"
              onChange={(e) => setAutomationConfig({ serverFrom: e.target.value })}
              disabled={autoRunning}
              className="w-28 bg-slate-950 border border-slate-700 rounded px-1.5 py-0.5 text-[11px] text-slate-200 disabled:opacity-40"
            />
          </label>
          <label className="flex items-center gap-1.5">
            <span>结束区服</span>
            <input
              type="text"
              value={automationConfig.serverTo}
              placeholder="留空 = 最新区"
              onChange={(e) => setAutomationConfig({ serverTo: e.target.value })}
              disabled={autoRunning}
              className="w-28 bg-slate-950 border border-slate-700 rounded px-1.5 py-0.5 text-[11px] text-slate-200 disabled:opacity-40"
            />
          </label>
          <label className="flex items-center gap-1.5">
            <input
              type="checkbox"
              checked={automationConfig.serverDryRun}
              onChange={(e) => setAutomationConfig({ serverDryRun: e.target.checked })}
              disabled={autoRunning}
              className="accent-cyan-500"
            />
            <span>只枚举不切换</span>
          </label>
          <label className="flex items-center gap-1.5">
            <input
              type="checkbox"
              checked={automationConfig.allowGemTalentBreakthrough}
              onChange={(e) => setAutomationConfig({ allowGemTalentBreakthrough: e.target.checked })}
              disabled={autoRunning}
              className="accent-amber-500"
            />
            <span title="允许天赋整十突破消耗宝石">允许宝石突破</span>
          </label>
          <span className="text-[10px] text-slate-500">快速模式技能默认选第一张</span>
        </div>

        {/* 账号队列：可编辑，并可用 /api/accounts 的真实账号名一键填充 */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between gap-2">
            <p className="text-[10px] font-bold text-slate-300">账号队列 · account_sweep 顺序</p>
            <div className="flex items-center gap-1.5">
              <button
                type="button"
                onClick={() => { onFillAccountQueue(); setQueueDraft(null); }}
                disabled={accounts.length === 0}
                className={SECONDARY}
              >
                用真机账号填充
              </button>
              <button
                type="button"
                onClick={onResetConfig}
                className={SECONDARY}
              >
                恢复默认配置
              </button>
            </div>
          </div>
          <input
            type="text"
            value={queueText}
            onChange={(e) => setQueueDraft(e.target.value)}
            onBlur={commitQueue}
            onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur(); }}
            placeholder="逗号分隔，例：风贰, 风零, 风壹"
            className="w-full bg-slate-950 border border-slate-700 rounded px-2 py-1 text-[11px] font-mono text-slate-200"
          />
          <p className="text-[10px] text-slate-500 break-all">
            当前顺序：{automationConfig.accountQueue.join(' → ') || '（空）'} · 共 {automationConfig.accountQueue.length} 个
          </p>
        </div>

        {/* OCR 区域：归一化坐标，null = 全屏 */}
        <div className="space-y-1.5">
          <label className="flex items-center gap-1.5 text-[11px] text-slate-400">
            <input
              type="checkbox"
              checked={automationConfig.ocrRegion !== null}
              onChange={(e) => {
                setAutomationConfig({ ocrRegion: e.target.checked ? ([0, 0, 1, 1] as OcrRegion) : null });
                setRegionDraft(null);
                setRegionError(null);
              }}
              className="accent-cyan-500"
            />
            <span>限定 OCR 区域（归一化 0–1，留空为全屏）</span>
          </label>
          {automationConfig.ocrRegion !== null && (
            <div className="flex flex-wrap items-center gap-1.5 text-[10px] font-mono text-slate-400">
              {(['L', 'T', 'R', 'B'] as const).map((label, index) => (
                <label key={label} className="flex items-center gap-1">
                  <span>{label}</span>
                  <input
                    type="number"
                    min={0}
                    max={1}
                    step={0.05}
                    value={regionDraft?.[index] ?? String(automationConfig.ocrRegion?.[index] ?? 0)}
                    onChange={(e) => {
                      const base = (automationConfig.ocrRegion ?? [0, 0, 1, 1]).map(String);
                      base[index] = e.target.value;
                      setRegionDraft(base);
                    }}
                    onBlur={commitRegion}
                    onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur(); }}
                    className="w-16 bg-slate-950 border border-slate-700 rounded px-1 py-0.5 text-[11px] text-slate-200 text-center"
                  />
                </label>
              ))}
              <span className="text-slate-500">失焦或回车后生效</span>
            </div>
          )}
          {regionError && <p className="text-[10px] text-rose-400">{regionError}</p>}
        </div>

        <p className="text-[10px] text-slate-500">
          每次游历固定 100 体力（20倍奖励），停止阈值不改变单次消耗 · 配置自动保存到本地
        </p>

        {!automation ? (
          <p className="text-[11px] text-slate-500">尚未启动自动化任务</p>
        ) : (
          <div className="space-y-1.5">
            <p className="text-[10px] font-mono text-slate-400">
              推关 {automation.progress.stageRuns ?? 0} 轮 · 爬塔 {automation.progress.towerFloors ?? 0} 层 · 日常 {automation.progress.dailySteps ?? 0} 步 · 公会 {automation.progress.guildSteps ?? 0} · 船 {automation.progress.shipSteps ?? 0} · 讨伐 {automation.progress.guildRaids ?? 0} · 扫荡 {automation.progress.dungeonSweeps ?? 0}
            </p>
            <p className="text-[10px] font-mono text-emerald-400/80">
              阶段 {automation.progress.phase || 'idle'} · 战力 {automation.progress.power ?? 0} · 体力 {automation.progress.stamina ?? 0} · 副本 {automation.progress.dungeonsDone ?? 0} · 游历 {automation.progress.travelSpent ?? 0} 体力 · 提升 {automation.progress.upgradeSteps ?? 0} 步 · 失败 {automation.progress.stageFails ?? 0} 次
            </p>
            {automation.error && (
              <p className="text-[10px] text-rose-400 break-all">{automation.error}</p>
            )}
            {autoLogs.length > 0 && (
              <ul className="space-y-1 max-h-32 overflow-y-auto">
                {autoLogs.map((log, index) => (
                  <li
                    key={`${log.ts}_${index}`}
                    className={`text-[10px] font-mono leading-snug ${
                      log.level === 'error'
                        ? 'text-rose-400'
                        : log.level === 'warn'
                          ? 'text-amber-400'
                          : 'text-slate-400'
                    }`}
                  >
                    {log.message}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        <div className="space-y-1.5">
          <p className="text-[10px] font-bold text-slate-300">账号集合 · 完成情况</p>
          {accounts.length === 0 ? (
            <p className="text-[10px] text-slate-500">暂无账号记录，任务完成后自动写入</p>
          ) : (
            <ul className="space-y-1 max-h-48 overflow-y-auto">
              {accounts.map((account) => (
                <li key={account.name} className="text-[10px] font-mono text-slate-400">
                  <span className="text-slate-200">{account.name}</span>
                  <span className="text-slate-500"> · 战力 {account.power || '-'}</span>
                  <span className="ml-1.5 space-x-1">
                    {(['daily', 'guild', 'ship', 'stage'] as const).map((key) => {
                      const work = account.works[key];
                      return (
                        <span
                          key={key}
                          className={work.done ? 'text-emerald-400' : 'text-slate-600'}
                        >
                          {work.label}
                          {work.done ? '✓' : '✗'}
                        </span>
                      );
                    })}
                  </span>
                  {account.lastRun && (
                    <span
                      className={`block ${
                        account.lastRun.status === 'completed'
                          ? 'text-emerald-400'
                          : account.lastRun.status === 'failed'
                            ? 'text-rose-400'
                            : account.lastRun.status === 'running'
                              ? 'text-amber-400'
                              : 'text-slate-500'
                      }`}
                    >
                      {account.lastRun.status} · {account.lastRun.currentPhase || '-'} · 推关 {account.lastRun.progress.stageRuns ?? 0} 轮 · 游历 {account.lastRun.progress.travelSpent ?? 0} 体力
                      {account.lastRun.error && <span className="text-rose-400"> · {account.lastRun.error}</span>}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>
    </div>
  );
};
