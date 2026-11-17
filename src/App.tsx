import React, { useEffect, useState } from 'react';
import {
  FsmState,
  AccountItem,
  LogMessage,
  TouchEventRecord,
} from './types/pipeline';
import { PhoneSimulator } from './components/PhoneSimulator';
import { FsmVisualizer } from './components/FsmVisualizer';
import { AccountMatrix, RealAccountMatrix } from './components/AccountMatrix';
import { CodeRepository } from './components/CodeRepository';
import { SkillPriorityStudio } from './components/SkillPriorityStudio';
import { AntiBanTelemetry } from './components/AntiBanTelemetry';
import { FloatingLogger } from './components/FloatingLogger';
import { DeploymentGuide } from './components/DeploymentGuide';
import { DeviceBar } from './components/DeviceBar';
import { DeviceMirror } from './components/DeviceMirror';
import { DeviceDrawer } from './components/DeviceDrawer';
import { useDeviceBridge } from './hooks/useDeviceBridge';
import { usePipelineConfig } from './hooks/usePipelineConfig';
import { DEMO_ACCOUNTS } from './data/demoAccounts';
import {
  Cpu,
  Layers,
  Users,
  Code2,
  ListOrdered,
  ShieldCheck,
  Terminal,
  Play,
  Pause,
  RotateCcw,
  BookOpen,
} from 'lucide-react';

export default function App() {
  const [activeTab, setActiveTab] = useState<
    'simulator' | 'accounts' | 'code' | 'skills' | 'risk' | 'logs' | 'deploy'
  >('simulator');

  const bridge = useDeviceBridge();

  const [fsmState, setFsmState] = useState<FsmState>('MAIN_CITY');
  const [isAutoRunning, setIsAutoRunning] = useState<boolean>(false);
  const [isResettingIp, setIsResettingIp] = useState<boolean>(false);
  const [interceptedCount, setInterceptedCount] = useState<number>(3);

  // 全应用唯一配置源：仿真参数 + 真机自动化参数，自动持久化到 localStorage
  const { config, setConfig, patchAutomation, resetConfig } = usePipelineConfig();

  // 仿真域演示账号（明确隔离在 data/demoAccounts.ts，不作为设备事实源）
  // 真机模式的账号一律读 bridge.accounts（/api/accounts），见下方 accounts 页签分支
  const [accounts, setAccounts] = useState<AccountItem[]>(() => DEMO_ACCOUNTS.map((item) => ({ ...item })));

  const [activeAccountId, setActiveAccountId] = useState<string>('main_01');

  // Logs stream
  const [logs, setLogs] = useState<LogMessage[]>([
    {
      id: 'log_01',
      timestamp: '12:40:02',
      level: 'INFO',
      tag: 'INIT',
      message: 'CapyScript 宿主无障碍服务与媒体投影截屏权限已授权',
    },
    {
      id: 'log_02',
      timestamp: '12:40:05',
      level: 'GUARD',
      tag: 'THREAD',
      message: '守护子线程 (Watchdog Daemon) 已就绪，正在以 2000ms 周期监听阻断弹窗',
    },
    {
      id: 'log_03',
      timestamp: '12:41:10',
      level: 'FSM',
      tag: 'STATE',
      message: '有限状态机初始化完成，进入 [MAIN_CITY] 主城待命状态',
    },
    {
      id: 'log_04',
      timestamp: '12:42:15',
      level: 'OCR',
      tag: 'MODEL',
      message: 'PaddleOCR-NCNN 本地离线推理引擎载入完成 (耗时 24ms, 零云端调用)',
    },
  ]);

  const addLog = (
    level: LogMessage['level'],
    tag: string,
    message: string
  ) => {
    const newLog: LogMessage = {
      id: `log_${Date.now()}_${Math.random()}`,
      timestamp: new Date().toLocaleTimeString(),
      level,
      tag,
      message,
    };
    setLogs((prev) => [newLog, ...prev.slice(0, 150)]);

    if (level === 'GUARD' && tag === 'RESOLVED') {
      setInterceptedCount((prev) => prev + 1);
    }
  };

  const activeAccount = accounts.find((a) => a.id === activeAccountId) || accounts[0];

  const handleSimulateIpReset = () => {
    setIsResettingIp(true);
    addLog('INFO', 'NETWORK', '触发蜂窝移动网络飞行模式重置 (airplane_mode_on 1)...');
    setTimeout(() => {
      addLog('INFO', 'NETWORK', '恢复网络接入 (airplane_mode_on 0)，基站已分配新动态 IP');
      setIsResettingIp(false);
      setAccounts((prev) =>
        prev.map((a) =>
          a.id === activeAccountId ? { ...a, ipResetCount: a.ipResetCount + 1 } : a
        )
      );
    }, 4500);
  };

  // 真机模式下按钮状态跟随后端 automation/status，避免任务自然结束后仍显示「急停」
  useEffect(() => {
    if (bridge.mode !== 'real' || !bridge.automation) return;
    const running = bridge.automation.status === 'running';
    setIsAutoRunning((prev) => (prev === running ? prev : running));
  }, [bridge.mode, bridge.automation?.status]);

  const handleToggleAutoRun = async () => {
    const nextState = !isAutoRunning;
    if (bridge.mode === 'real') {
      if (nextState) {
        addLog('FSM', 'START', '真机模式：启动 all 自动化任务（参数取自中控台配置）');
        const result = await bridge.startAutomation('all', config);
        if (!result) {
          addLog('WARN', 'AUTO', '任务未启动：请确认设备会话已连接且后端就绪');
          return;
        }
        setIsAutoRunning(true);
        addLog('INFO', 'AUTO', `任务已启动：${result.task ?? 'all'} · status=${result.status}`);
      } else {
        const result = await bridge.stopAutomation();
        setIsAutoRunning(false);
        addLog('WARN', 'STOP', result ? `真机急停完成：status=${result.status}` : '急停请求失败，请检查后端');
      }
      return;
    }
    setIsAutoRunning(nextState);
    if (nextState) {
      addLog('FSM', 'START', `启动全自动流水线！正在调度账号 [${activeAccount.id}]（仿真演示）`);
      if (fsmState === 'IDLE') {
        setFsmState('MAIN_CITY');
      }
    } else {
      addLog('WARN', 'STOP', '人工急停中断自动化流水线（仿真演示）');
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      {/* Top Bar Contract: [Brand title] - [Nav links] - [1 primary action] */}
      <header className="flex items-center justify-between gap-8 px-6 py-3.5 border-b border-slate-800/80 bg-slate-950 sticky top-0 z-50">
        {/* Zone 1: Brand Wordmark */}
        <div className="flex items-center gap-2 whitespace-nowrap shrink-0">
          <div className="w-8 h-8 rounded-lg bg-amber-500/10 border border-amber-500/30 flex items-center justify-center text-amber-400 font-bold text-base">
            🦫
          </div>
          <span className="text-base font-bold tracking-tight text-slate-100">
            CapyAuto Flow
          </span>
        </div>

        {/* Zone 2: Navigation Links (Single-Line, whitespace-nowrap) */}
        <nav className="hidden lg:flex items-center gap-6 text-xs font-medium text-slate-400">
          <button
            type="button"
            onClick={() => setActiveTab('simulator')}
            className={`transition-colors whitespace-nowrap shrink-0 cursor-pointer ${
              activeTab === 'simulator' ? 'text-amber-400 font-bold' : 'hover:text-slate-200'
            }`}
          >
            实机仿真与状态机
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('accounts')}
            className={`transition-colors whitespace-nowrap shrink-0 cursor-pointer ${
              activeTab === 'accounts' ? 'text-amber-400 font-bold' : 'hover:text-slate-200'
            }`}
          >
            多账号隔离调度
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('skills')}
            className={`transition-colors whitespace-nowrap shrink-0 cursor-pointer ${
              activeTab === 'skills' ? 'text-amber-400 font-bold' : 'hover:text-slate-200'
            }`}
          >
            视觉决策与技能队列
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('code')}
            className={`transition-colors whitespace-nowrap shrink-0 cursor-pointer ${
              activeTab === 'code' ? 'text-amber-400 font-bold' : 'hover:text-slate-200'
            }`}
          >
            工程代码与导出
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('risk')}
            className={`transition-colors whitespace-nowrap shrink-0 cursor-pointer ${
              activeTab === 'risk' ? 'text-amber-400 font-bold' : 'hover:text-slate-200'
            }`}
          >
            风控防封与保活
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('deploy')}
            className={`transition-colors whitespace-nowrap shrink-0 cursor-pointer ${
              activeTab === 'deploy' ? 'text-amber-400 font-bold' : 'hover:text-slate-200'
            }`}
          >
            真机部署手册
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('logs')}
            className={`transition-colors whitespace-nowrap shrink-0 cursor-pointer ${
              activeTab === 'logs' ? 'text-amber-400 font-bold' : 'hover:text-slate-200'
            }`}
          >
            控制台日志
          </button>
        </nav>

        {/* Zone 3: 1 Primary Action */}
        <div className="flex items-center gap-3 shrink-0">
          <button
            type="button"
            onClick={handleToggleAutoRun}
            className={`px-4 py-2 text-xs font-bold rounded-lg transition-colors whitespace-nowrap shrink-0 flex items-center gap-1.5 cursor-pointer shadow-sm ${
              isAutoRunning
                ? 'bg-rose-600 hover:bg-rose-500 text-white'
                : 'bg-amber-500 hover:bg-amber-400 text-slate-950'
            }`}
          >
            {isAutoRunning ? (
              <>
                <Pause className="w-3.5 h-3.5" />
                <span>急停流水线</span>
              </>
            ) : (
              <>
                <Play className="w-3.5 h-3.5 fill-current" />
                <span>启动全自动流水线</span>
              </>
            )}
          </button>
        </div>
      </header>

      {/* Main Workspace Viewport */}
      <main className="flex-1 max-w-7xl w-full mx-auto p-4 sm:p-6 space-y-6">
        {/* Breadcrumb & Sub-nav Bar */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-4 border-b border-slate-800/80 gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-xs text-slate-400 font-mono overflow-x-auto whitespace-nowrap py-0.5">
              <span>Android 工程中控</span>
              <span aria-hidden="true">/</span>
              <span>AutoX.js v6.x</span>
              <span aria-hidden="true">/</span>
              <span className="text-amber-400 font-semibold truncate">
                {activeTab === 'simulator' && '实机仿真与有限状态机拓扑'}
                {activeTab === 'accounts' && '多账号隔离与分身生命周期管理'}
                {activeTab === 'skills' && 'PaddleOCR 离线视觉决策与高斯落点'}
                {activeTab === 'code' && 'AutoX.js 模块化工程代码仓库'}
                {activeTab === 'risk' && '风控防封鲁棒性与硬件降温'}
                {activeTab === 'deploy' && 'Android 实体手机部署向导'}
                {activeTab === 'logs' && '实时运行管道日志流'}
              </span>
            </div>
            <h1 className="text-lg sm:text-xl font-bold text-slate-100 tracking-tight mt-1">
              单台安卓设备工程化全自动流水线
            </h1>
          </div>

          {/* Quick tab switcher on smaller screens */}
          <div className="flex lg:hidden overflow-x-auto gap-1 p-1 bg-slate-900 rounded-lg border border-slate-800 shrink-0">
            <button
              type="button"
              onClick={() => setActiveTab('simulator')}
              className={`px-2.5 py-1 text-xs rounded font-medium whitespace-nowrap cursor-pointer ${
                activeTab === 'simulator' ? 'bg-amber-500 text-slate-950 font-bold' : 'text-slate-400'
              }`}
            >
              实机仿真
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('accounts')}
              className={`px-2.5 py-1 text-xs rounded font-medium whitespace-nowrap cursor-pointer ${
                activeTab === 'accounts' ? 'bg-amber-500 text-slate-950 font-bold' : 'text-slate-400'
              }`}
            >
              多账号
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('skills')}
              className={`px-2.5 py-1 text-xs rounded font-medium whitespace-nowrap cursor-pointer ${
                activeTab === 'skills' ? 'bg-amber-500 text-slate-950 font-bold' : 'text-slate-400'
              }`}
            >
              视觉决策
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('code')}
              className={`px-2.5 py-1 text-xs rounded font-medium whitespace-nowrap cursor-pointer ${
                activeTab === 'code' ? 'bg-amber-500 text-slate-950 font-bold' : 'text-slate-400'
              }`}
            >
              代码工程
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('risk')}
              className={`px-2.5 py-1 text-xs rounded font-medium whitespace-nowrap cursor-pointer ${
                activeTab === 'risk' ? 'bg-amber-500 text-slate-950 font-bold' : 'text-slate-400'
              }`}
            >
              防封保活
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('deploy')}
              className={`px-2.5 py-1 text-xs rounded font-medium whitespace-nowrap cursor-pointer ${
                activeTab === 'deploy' ? 'bg-amber-500 text-slate-950 font-bold' : 'text-slate-400'
              }`}
            >
              部署手册
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('logs')}
              className={`px-2.5 py-1 text-xs rounded font-medium whitespace-nowrap cursor-pointer ${
                activeTab === 'logs' ? 'bg-amber-500 text-slate-950 font-bold' : 'text-slate-400'
              }`}
            >
              控制台日志
            </button>
          </div>
        </div>

        {/* 真机设备栏：模式切换 / 会话状态 / 错误提示 */}
        <div>
          <DeviceBar
            mode={bridge.mode}
            onModeChange={bridge.switchMode}
            health={bridge.health}
            device={bridge.device}
            session={bridge.session}
            error={bridge.error}
            onRefresh={() => bridge.connect()}
          />
        </div>

        {/* Tab 1: Simulator & FSM View */}
        {activeTab === 'simulator' && (
          <div className="space-y-6">
            <FsmVisualizer
              currentState={fsmState}
              onStateSelect={(state) => {
                setFsmState(state);
                addLog('FSM', 'MANUAL', `手动切换状态至 [${state}]`);
              }}
            />

            {bridge.mode === 'real' ? (
              <div className="grid gap-4 lg:grid-cols-[minmax(0,360px)_1fr]">
                <DeviceMirror
                  session={bridge.session}
                  lastTap={bridge.lastTap}
                  error={bridge.error}
                  onTap={async (x, y) => {
                    const result = await bridge.tap(
                      x,
                      y,
                      config.pressDurationMean,
                      config.gaussianStdev,
                      config.pressDurationStdev
                    );
                    if (result) addLog('TOUCH', 'REAL', `真机点击 (${result.realX}, ${result.realY}) via ${result.injectedVia}`);
                  }}
                />
                <DeviceDrawer
                  packageName={bridge.defaultPackage}
                  launcherHost={bridge.launcherHostPackage}
                  launcherIconLabel={bridge.launcherIconLabel}
                  busy={bridge.busy}
                  users={bridge.users}
                  ocr={bridge.ocr}
                  automation={bridge.automation}
                  accounts={bridge.accounts}
                  automationConfig={config}
                  setAutomationConfig={patchAutomation}
                  onFillAccountQueue={async () => {
                    const list = await bridge.refreshAccounts();
                    if (list.length === 0) {
                      addLog('WARN', 'ACCOUNT', '真机账号为空，未能填充队列（先跑一次任务或确认后端就绪）');
                      return;
                    }
                    patchAutomation({ accountQueue: list.map((row) => row.name) });
                    addLog('INFO', 'ACCOUNT', `已用 /api/accounts 的 ${list.length} 个账号覆盖队列`);
                  }}
                  onResetConfig={() => {
                    resetConfig();
                    addLog('INFO', 'CONFIG', '配置已恢复默认值并写回本地存储');
                  }}
                  onLaunch={() => bridge.launchGame()}
                  onStop={() => bridge.stopGame()}
                  onLoadUsers={() => bridge.loadUsers()}
                  onSwitchUser={(id) => bridge.switchUser(id)}
                  onAirplane={(enable) => bridge.toggleAirplane(enable)}
                  onOcr={(region) => {
                    addLog('INFO', 'OCR', region ? `区域 OCR [${region.join(', ')}]` : '全屏 OCR');
                    void bridge.runOcr(region);
                  }}
                  onAutomationStart={(task) => {
                    addLog('INFO', 'AUTO', `启动自动化任务：${task}（maxRuns=${config.maxRuns}, serverTo=${config.serverTo || '最新区'}）`);
                    void bridge.startAutomation(task, config);
                  }}
                  onAutomationStop={() => bridge.stopAutomation()}
                  onVerify={() => {
                    addLog('INFO', 'VERIFY', '触发 V1–V10 真机验收');
                    void bridge.runVerify().then((result) => {
                      if (result) {
                        addLog(
                          'INFO',
                          'VERIFY',
                          `验收完成：PASS ${result.summary.passed} / FAIL ${result.summary.failed} / SKIP ${result.summary.skipped}`
                        );
                      }
                    });
                  }}
                  onSwipe={(direction) => {
                    addLog('TOUCH', 'SWIPE', `真机滑动：${direction}`);
                    void bridge.swipe(direction);
                  }}
                  onKey={(key) => {
                    addLog('TOUCH', 'KEY', `真机按键：${key}`);
                    void bridge.pressKey(key);
                  }}
                  onCurrentApp={() => { void bridge.refreshCurrentApp(); }}
                  currentAppInfo={bridge.currentApp}
                  verifyBusy={bridge.verifyBusy}
                  verifyResult={bridge.verifyResult}
                />
              </div>
            ) : (
              <PhoneSimulator
                fsmState={fsmState}
                onFsmChange={setFsmState}
                activeAccount={activeAccount}
                config={config}
                onLog={addLog}
                onRecordTouch={(record: TouchEventRecord) => {
                  const dx = record.realX - record.targetX;
                  const dy = record.realY - record.targetY;
                  addLog(
                    'TOUCH',
                    'SAMPLE',
                    `归档触控样本 ${record.id.slice(-4)}：偏差 Δ${dx.toFixed(1)}/${dy.toFixed(1)}px · 按压 ${record.pressTime.toFixed(0)}ms · σ=${record.stdev}`
                  );
                }}
                isAutoRunning={isAutoRunning}
                onToggleAutoRun={handleToggleAutoRun}
              />
            )}
          </div>
        )}

        {/* Tab 2: Accounts Management Matrix */}
        {activeTab === 'accounts' && (
          bridge.mode === 'real' ? (
            <RealAccountMatrix
              accounts={bridge.accounts}
              busy={bridge.busy}
              onRefresh={() => { void bridge.refreshAccounts(); }}
            />
          ) : (
            <AccountMatrix
              accounts={accounts}
              activeAccountId={activeAccountId}
              demo
              onSwitchToReal={() => { void bridge.switchMode('real'); }}
              onSelectAccount={(acc) => {
                setActiveAccountId(acc.id);
                addLog('INFO', 'DISPATCH', `将仿真调度账号切换至 [${acc.id}] (${acc.name})`);
              }}
              onToggleAccountDone={(id) => {
                setAccounts((prev) =>
                  prev.map((a) => (a.id === id ? { ...a, doneToday: !a.doneToday } : a))
                );
                addLog('INFO', 'ACCOUNT', `更新演示账号 [${id}] 今日完成标记`);
              }}
              onAddAccount={(newAcc) => {
                const item: AccountItem = {
                  ...newAcc,
                  id: `alt_${Date.now().toString().slice(-4)}`,
                  boatTicketsDonated: 0,
                  goldDonatedTimes: 0,
                  currentStage: '第 1 章 · 启程初原',
                  ipResetCount: 0,
                };
                setAccounts((prev) => [...prev, item]);
                addLog('INFO', 'ACCOUNT', `新增演示小号 [${item.id}] 进入仿真调度池`);
              }}
              onResetAllDaily={() => {
                setAccounts((prev) => prev.map((a) => ({ ...a, doneToday: false })));
                addLog('INFO', 'ACCOUNT', '已重置仿真账号的今日已完成标记');
              }}
              onSimulateIpReset={handleSimulateIpReset}
              isResettingIp={isResettingIp}
            />
          )
        )}

        {/* Tab 3: Visual Decision & Skill Priority Studio */}
        {activeTab === 'skills' && (
          <SkillPriorityStudio
            config={config}
            onUpdateConfig={setConfig}
          />
        )}

        {/* Tab 4: Code Repository & ZIP Exporter */}
        {activeTab === 'code' && <CodeRepository />}

        {/* Tab 5: Anti-Ban, IP hopping & Telemetry */}
        {activeTab === 'risk' && (
          <AntiBanTelemetry
            config={config}
            onUpdateConfig={setConfig}
            interceptedCount={interceptedCount}
          />
        )}

        {/* Tab 6: Android Deployment Guide */}
        {activeTab === 'deploy' && <DeploymentGuide />}

        {/* Tab 7: Real-Time Floating Logger Stream */}
        {activeTab === 'logs' && (
          <FloatingLogger logs={logs} onClearLogs={() => setLogs([])} />
        )}
      </main>

      {/* Clean Footer (No fake engines, clean links & summary) */}
      <footer className="border-t border-slate-800/80 bg-slate-950 py-4 px-6 text-xs text-slate-500 mt-auto">
        <div className="max-w-7xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-slate-400">CapyAuto Flow 工程化流水线</span>
            <span>·</span>
            <span>基于 AutoX.js 与 PaddleOCR-NCNN 离线推理架构</span>
          </div>

          <div className="flex items-center gap-4 text-[11px] font-mono">
            <span>无障碍 (Accessibility) 就绪</span>
            <span>·</span>
            <span>高斯拟人点击 (σ={config.gaussianStdev}px)</span>
            <span>·</span>
            <span>守护线程看门狗</span>
          </div>
        </div>
      </footer>
    </div>
  );
}
