import React, { useState, useEffect } from 'react';
import {
  FsmState,
  SkillCandidate,
  TouchEventRecord,
  AccountItem,
  PipelineConfig,
} from '../types/pipeline';
import {
  generateHumanClick,
  matchBestSkill,
} from '../core/decision';
import {
  Shield,
  Swords,
  Coins,
  Ship,
  Sparkles,
  AlertTriangle,
  RotateCcw,
  Zap,
  Target,
  Eye,
  Activity,
  Play,
  Pause,
  RefreshCw,
  X,
  Volume2,
  BatteryCharging,
  Wifi,
} from 'lucide-react';

interface PhoneSimulatorProps {
  fsmState: FsmState;
  onFsmChange: (newState: FsmState) => void;
  activeAccount: AccountItem;
  config: PipelineConfig;
  onLog: (level: 'INFO' | 'WARN' | 'ERROR' | 'FSM' | 'OCR' | 'TOUCH' | 'GUARD', tag: string, msg: string) => void;
  onRecordTouch: (record: TouchEventRecord) => void;
  isAutoRunning: boolean;
  onToggleAutoRun: () => void;
}

export const PhoneSimulator: React.FC<PhoneSimulatorProps> = ({
  fsmState,
  onFsmChange,
  activeAccount,
  config,
  onLog,
  onRecordTouch,
  isAutoRunning,
  onToggleAutoRun,
}) => {
  const [showOcrBoxes, setShowOcrBoxes] = useState(true);
  const [showTouchPoints, setShowTouchPoints] = useState(true);
  const [isDarkScreen, setIsDarkScreen] = useState(false);
  const [lastTouchPoint, setLastTouchPoint] = useState<{ x: number; y: number; realX: number; realY: number } | null>(null);
  const [battleHp, setBattleHp] = useState(100);
  const [battleExp, setBattleExp] = useState(45);
  const [touchTrail, setTouchTrail] = useState<{ realX: number; realY: number; id: string }[]>([]);

  // Sample skill cards for the 3-choice modal
  const skillCards: SkillCandidate[] = [
    {
      id: 'c1',
      name: '冰刺·寒冰穿刺',
      category: 'elemental',
      desc: '向前发射3枚冰刺，造成减速与冰冻效果',
      confidence: 0.96,
      bounds: { left: 24, top: 260, right: 110, bottom: 420 },
    },
    {
      id: 'c2',
      name: '越战越硬·护盾',
      category: 'survival',
      desc: '受到攻击时获得最大生命值 8% 的减伤护盾',
      confidence: 0.98,
      bounds: { left: 126, top: 260, right: 212, bottom: 420 },
    },
    {
      id: 'c3',
      name: '连击强化·迅捷',
      category: 'offense',
      desc: '普通攻击额外触发 1 次连击判定',
      confidence: 0.94,
      bounds: { left: 228, top: 260, right: 314, bottom: 420 },
    },
  ];

  // Calculate OCR match result
  const decisionResult = matchBestSkill(
    skillCards.map((c) => ({ text: c.name, id: c.id })),
    config.skillPriorityList
  );

  // Trigger humanized click
  const executeSimulatedClick = (targetX: number, targetY: number, label: string) => {
    const { realX, realY, pressTime } = generateHumanClick(
      targetX,
      targetY,
      config.gaussianStdev,
      config.pressDurationMean,
      config.pressDurationStdev
    );

    const record: TouchEventRecord = {
      id: `touch_${Date.now()}`,
      timestamp: new Date().toLocaleTimeString(),
      targetX,
      targetY,
      realX,
      realY,
      pressTime,
      stdev: config.gaussianStdev,
      label,
    };

    setLastTouchPoint({ x: targetX, y: targetY, realX, realY });
    setTouchTrail((prev) => [...prev.slice(-12), { realX, realY, id: record.id }]);
    onRecordTouch(record);
    onLog('TOUCH', 'GAUSS', `拟人点击 [${label}]: 目标(${targetX},${targetY}) -> 物理落点(${realX},${realY}) 按压${pressTime}ms`);
  };

  // Auto pipeline step runner
  useEffect(() => {
    if (!isAutoRunning) return;

    const timer = setTimeout(() => {
      switch (fsmState) {
        case 'IDLE':
        case 'MAIN_CITY':
          onLog('FSM', 'STEP', `账号 [${activeAccount.id}] 从主城进入主线关卡推关`);
          executeSimulatedClick(170, 520, '主线挑战按钮');
          onFsmChange('BATTLE_RUNNING');
          setBattleHp(100);
          setBattleExp(40);
          break;

        case 'BATTLE_RUNNING':
          // Battle progresses, either upgrade or win
          if (battleExp < 90) {
            setBattleExp((prev) => prev + 30);
            setBattleHp((prev) => Math.max(30, prev - 15));
            onLog('INFO', 'COMBAT', `局内战斗中... 击败第 2 波怪物，经验积累 ${battleExp}%`);
          } else {
            onLog('FSM', 'EVENT', '经验值达到 100%，触发技能三选一升级事件！');
            onFsmChange('SKILL_CHOICE');
          }
          break;

        case 'SKILL_CHOICE':
          // Pick best skill via OCR
          const chosenCard = skillCards[decisionResult.matchedIndex];
          onLog('OCR', 'DECISION', `PaddleOCR 检出 3 个候选技能，命中最高优: [${chosenCard.name}] (优先级Rank: ${decisionResult.highestRank})`);
          
          const centerX = (chosenCard.bounds.left + chosenCard.bounds.right) / 2;
          const centerY = (chosenCard.bounds.top + chosenCard.bounds.bottom) / 2;
          executeSimulatedClick(centerX, centerY, `技能选择: ${chosenCard.name}`);
          
          setTimeout(() => {
            onFsmChange('BATTLE_VICTORY');
            onLog('FSM', 'STATE', '战斗胜利！获取关卡掉落物与公会船票');
          }, 800);
          break;

        case 'BATTLE_VICTORY':
          executeSimulatedClick(170, 530, '胜利结算/下一关');
          onLog('FSM', 'STEP', '推关胜利，准备前往公会提交小号日常航海船票');
          onFsmChange('GUILD_PANEL');
          break;

        case 'GUILD_PANEL':
          executeSimulatedClick(170, 480, '公会船票一键捐献');
          onLog('INFO', 'GUILD', `账号 [${activeAccount.id}] 成功捐献 3 次金币，提交公会船票 x1`);
          setTimeout(() => {
            onFsmChange('MAIN_CITY');
            onLog('FSM', 'DONE', `当前账号 [${activeAccount.id}] 流水线完成！准备切号`);
          }, 1200);
          break;

        case 'POPUP_INTERRUPT':
          // Handled by Watchdog daemon
          break;

        default:
          break;
      }
    }, 2200);

    return () => clearTimeout(timer);
  }, [fsmState, isAutoRunning, battleExp, activeAccount.id]);

  // Watchdog daemon effect for popup interrupts
  useEffect(() => {
    if (fsmState === 'POPUP_INTERRUPT' && config.enableWatchdogThread) {
      onLog('GUARD', 'WATCHDOG', '守护子线程检测到非法遮罩弹窗【限时首充礼包】，正在寻找关闭按键...');
      const dismissTimer = setTimeout(() => {
        executeSimulatedClick(295, 235, '守护线程自动点击关闭[X]');
        onLog('GUARD', 'RESOLVED', '阻断弹窗已消除，主任务流恢复继续执行！');
        onFsmChange('MAIN_CITY');
      }, 1600);
      return () => clearTimeout(dismissTimer);
    }
  }, [fsmState, config.enableWatchdogThread]);

  return (
    <div className="flex flex-col xl:flex-row items-center xl:items-start justify-center gap-6">
      {/* Phone Mockup Frame */}
      <div className="relative">
        {/* Device Outer Frame */}
        <div className="w-[340px] h-[680px] bg-slate-900 border-[8px] border-slate-800 rounded-[44px] shadow-2xl relative overflow-hidden flex flex-col select-none ring-1 ring-slate-700/50">
          {/* Top Speaker / Dynamic Island */}
          <div className="absolute top-2 left-1/2 -translate-x-1/2 w-28 h-5 bg-black rounded-full z-40 flex items-center justify-between px-3">
            <div className="w-2.5 h-2.5 rounded-full bg-slate-900 border border-slate-800"></div>
            <div className="w-2 h-2 rounded-full bg-emerald-500/80"></div>
          </div>

          {/* Status Bar */}
          <div className="h-8 bg-slate-950/80 backdrop-blur-sm flex items-center justify-between px-6 pt-1 text-[11px] text-slate-300 font-mono z-30 shrink-0">
            <span>12:45</span>
            <div className="flex items-center gap-1.5 text-slate-300">
              <span className="text-[9px] text-emerald-400 font-sans font-bold">5G</span>
              <Wifi className="w-3 h-3 text-slate-300" />
              <BatteryCharging className="w-3.5 h-3.5 text-emerald-400" />
              <span className="tabular-nums">84%</span>
            </div>
          </div>

          {/* Screen Display Container */}
          <div className={`relative flex-1 bg-slate-950 overflow-hidden flex flex-col transition-opacity duration-300 ${isDarkScreen ? 'opacity-15' : 'opacity-100'}`}>
            
            {/* Screen Content by FSM State */}
            {fsmState === 'MAIN_CITY' && (
              <div className="flex-1 flex flex-col justify-between p-4 bg-gradient-to-b from-indigo-950/60 via-slate-950 to-slate-900">
                {/* Header Profile */}
                <div className="flex items-center justify-between bg-slate-900/80 p-2.5 rounded-xl border border-slate-800">
                  <div className="flex items-center gap-2.5">
                    <div className="w-9 h-9 rounded-lg bg-amber-500/20 border border-amber-500/40 flex items-center justify-center text-amber-300 font-bold text-sm">
                      🦫
                    </div>
                    <div>
                      <div className="text-xs font-semibold text-slate-100">卡皮巴拉勇者</div>
                      <div className="text-[10px] text-slate-400">Lv.42 · 战力 184,200</div>
                    </div>
                  </div>
                  <div className="flex items-center gap-1 text-[10px] text-amber-400 font-mono bg-amber-950/40 px-2 py-0.5 rounded border border-amber-900/60">
                    <Coins className="w-3 h-3" />
                    <span>248.5K</span>
                  </div>
                </div>

                {/* Stage Info Badge */}
                <div className="text-center my-3 bg-slate-900/60 py-2 px-3 rounded-lg border border-slate-800/80">
                  <div className="text-[10px] text-amber-400 font-medium">当前关卡</div>
                  <div className="text-sm font-bold text-slate-100">第 32 章 · 沼泽巨石阵 (45/50)</div>
                  <div className="w-full bg-slate-800 h-1.5 rounded-full mt-2 overflow-hidden">
                    <div className="bg-amber-500 h-full w-[90%]"></div>
                  </div>
                </div>

                {/* Character Center Canvas */}
                <div className="flex-1 flex flex-col items-center justify-center relative">
                  <div className="w-28 h-28 rounded-full bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center animate-pulse">
                    <span className="text-5xl select-none">🦫</span>
                  </div>
                  <div className="text-[10px] text-slate-400 mt-2 font-mono">
                    账号: {activeAccount.name} ({activeAccount.type})
                  </div>
                </div>

                {/* Main Action Hub */}
                <div className="space-y-2 mt-auto">
                  <div className="grid grid-cols-2 gap-2">
                    <button
                      type="button"
                      onClick={() => {
                        executeSimulatedClick(85, 450, '20倍游历收菜');
                        onLog('INFO', 'HARVEST', '执行 20 倍挂机体力游历，收益金币 +34,000');
                      }}
                      className="py-2.5 px-2 bg-indigo-950/80 hover:bg-indigo-900/80 border border-indigo-700/40 rounded-lg text-indigo-200 text-xs font-medium flex items-center justify-center gap-1.5 transition-colors cursor-pointer"
                    >
                      <Sparkles className="w-3.5 h-3.5 text-indigo-400" />
                      <span>20倍游历收菜</span>
                    </button>

                    <button
                      type="button"
                      onClick={() => {
                        executeSimulatedClick(255, 450, '公会入口');
                        onFsmChange('GUILD_PANEL');
                        onLog('FSM', 'STATE', '进入公会大厅模块');
                      }}
                      className="py-2.5 px-2 bg-amber-950/80 hover:bg-amber-900/80 border border-amber-700/40 rounded-lg text-amber-200 text-xs font-medium flex items-center justify-center gap-1.5 transition-colors cursor-pointer"
                    >
                      <Ship className="w-3.5 h-3.5 text-amber-400" />
                      <span>公会航海大厅</span>
                    </button>
                  </div>

                  <button
                    type="button"
                    onClick={() => {
                      executeSimulatedClick(170, 520, '出战推关');
                      onFsmChange('BATTLE_RUNNING');
                      onLog('FSM', 'STATE', '启动自动推关主线流程');
                    }}
                    className="w-full py-3 bg-gradient-to-r from-amber-600 to-amber-500 hover:from-amber-500 hover:to-amber-400 text-slate-950 font-bold text-sm rounded-xl shadow-lg shadow-amber-500/20 flex items-center justify-center gap-2 transition-all cursor-pointer active:scale-98"
                  >
                    <Swords className="w-4 h-4 text-slate-950" />
                    <span>挑战关卡 BOSS</span>
                  </button>
                </div>
              </div>
            )}

            {/* BATTLE_RUNNING State */}
            {fsmState === 'BATTLE_RUNNING' && (
              <div className="flex-1 flex flex-col justify-between p-4 bg-gradient-to-b from-slate-950 via-slate-900 to-slate-950">
                {/* Battle Top HUD */}
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between text-[11px] text-slate-300">
                    <span className="font-semibold text-amber-400">WAVE 3 / 5</span>
                    <span className="font-mono text-slate-400">00:42</span>
                  </div>
                  {/* Monster HP */}
                  <div className="w-full bg-slate-800 h-2 rounded-full overflow-hidden">
                    <div className="bg-rose-500 h-full w-[65%] transition-all duration-300"></div>
                  </div>
                  {/* EXP Bar */}
                  <div className="flex items-center justify-between text-[9px] text-indigo-300">
                    <span>经验值 (EXP)</span>
                    <span className="font-mono">{battleExp}%</span>
                  </div>
                  <div className="w-full bg-slate-800 h-1.5 rounded-full overflow-hidden">
                    <div
                      className="bg-indigo-500 h-full transition-all duration-300"
                      style={{ width: `${battleExp}%` }}
                    ></div>
                  </div>
                </div>

                {/* Battle Arena */}
                <div className="flex-1 flex flex-col items-center justify-center relative">
                  {/* Incoming Monsters */}
                  <div className="flex items-center gap-6 mb-6">
                    <div className="text-3xl animate-bounce">👾</div>
                    <div className="text-2xl animate-pulse">🦇</div>
                    <div className="text-3xl animate-bounce">🧟</div>
                  </div>

                  {/* Projectiles */}
                  <div className="absolute w-1.5 h-6 bg-cyan-400 rounded-full animate-ping top-1/2 left-1/2 -translate-x-1/2"></div>

                  {/* Capybara Hero */}
                  <div className="relative">
                    <div className="w-16 h-16 rounded-2xl bg-amber-500/20 border border-amber-500/40 flex items-center justify-center text-3xl">
                      🦫
                    </div>
                    {/* Hero HP */}
                    <div className="absolute -bottom-3 left-0 right-0 h-1.5 bg-slate-800 rounded-full overflow-hidden">
                      <div
                        className="bg-emerald-500 h-full transition-all duration-300"
                        style={{ width: `${battleHp}%` }}
                      ></div>
                    </div>
                  </div>
                </div>

                {/* Bottom Combat State */}
                <div className="bg-slate-900/80 p-2.5 rounded-xl border border-slate-800 flex items-center justify-between">
                  <div className="text-[10px] text-slate-400 flex items-center gap-1.5">
                    <Activity className="w-3.5 h-3.5 text-emerald-400" />
                    <span>AutoX.js 战斗监听器轮询中 (1000ms)</span>
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      onLog('FSM', 'MANUAL', '手动触发技能升级');
                      onFsmChange('SKILL_CHOICE');
                    }}
                    className="text-[10px] text-indigo-400 hover:text-indigo-300 underline font-medium cursor-pointer"
                  >
                    立刻升级
                  </button>
                </div>
              </div>
            )}

            {/* SKILL_CHOICE State (Roguelike 3-Choice Modal with OCR Overlay) */}
            {fsmState === 'SKILL_CHOICE' && (
              <div className="flex-1 flex flex-col justify-between p-3 bg-slate-950/95 backdrop-blur-md relative">
                {/* Modal Title */}
                <div className="text-center pt-2">
                  <div className="text-[10px] text-amber-400 font-semibold tracking-wider">ROGUELIKE UPGRADE</div>
                  <h3 className="text-base font-bold text-slate-100">请选择局内战技 (三选一)</h3>
                  <p className="text-[10px] text-slate-400 mt-0.5">离线 OCR 扫描卡面特征并执行加权决策</p>
                </div>

                {/* 3 Skill Cards with simulated OCR bounds */}
                <div className="grid grid-cols-3 gap-2 my-auto">
                  {skillCards.map((card, idx) => {
                    const isSelected = decisionResult.matchedIndex === idx;
                    return (
                      <div
                        key={card.id}
                        onClick={() => {
                          const cx = (card.bounds.left + card.bounds.right) / 2;
                          const cy = (card.bounds.top + card.bounds.bottom) / 2;
                          executeSimulatedClick(cx, cy, `技能: ${card.name}`);
                          onLog('OCR', 'USER_TAP', `手动选定技能: [${card.name}]`);
                          onFsmChange('BATTLE_RUNNING');
                        }}
                        className={`relative p-2 rounded-xl flex flex-col justify-between cursor-pointer transition-all border ${
                          isSelected
                            ? 'bg-amber-950/50 border-amber-500 shadow-md shadow-amber-500/20 ring-1 ring-amber-500/50'
                            : 'bg-slate-900/80 border-slate-800 hover:border-slate-700'
                        }`}
                      >
                        {/* Selected Tag */}
                        {isSelected && (
                          <div className="absolute -top-2.5 left-1/2 -translate-x-1/2 bg-amber-500 text-slate-950 text-[9px] font-bold px-1.5 py-0.2 rounded-full whitespace-nowrap shadow">
                            首选推荐 #{decisionResult.highestRank + 1}
                          </div>
                        )}

                        {/* OCR Bounding Box visualization */}
                        {showOcrBoxes && (
                          <div
                            className={`absolute inset-0.5 border border-dashed rounded-lg pointer-events-none ${
                              isSelected ? 'border-amber-400 bg-amber-500/5' : 'border-emerald-500/60 bg-emerald-500/5'
                            }`}
                          >
                            <span className="absolute top-0.5 right-1 text-[7px] font-mono text-emerald-400">
                              {(card.confidence * 100).toFixed(0)}%
                            </span>
                          </div>
                        )}

                        <div className="w-8 h-8 rounded-lg bg-slate-800 flex items-center justify-center mx-auto mb-1.5">
                          {idx === 0 ? '❄️' : idx === 1 ? '🛡️' : '⚡'}
                        </div>

                        <div className="text-center">
                          <div className="text-[11px] font-bold text-slate-100 line-clamp-1">{card.name}</div>
                          <div className="text-[9px] text-slate-400 mt-1 line-clamp-3 leading-tight">{card.desc}</div>
                        </div>

                        <div className="mt-2 text-center">
                          <span
                            className={`text-[8px] font-mono px-1 py-0.5 rounded ${
                              isSelected ? 'bg-amber-500/20 text-amber-300' : 'bg-slate-800 text-slate-400'
                            }`}
                          >
                            {isSelected ? 'PRIORITY WIN' : 'RANK ' + (idx + 3)}
                          </span>
                        </div>
                      </div>
                    );
                  })}
                </div>

                {/* Bottom OCR Decision Telemetry */}
                <div className="bg-slate-900/90 p-2.5 rounded-xl border border-slate-800 text-[10px] space-y-1">
                  <div className="flex items-center justify-between text-slate-300">
                    <span className="text-amber-400 font-semibold">PaddleOCR-NCNN 推理结果</span>
                    <span className="font-mono text-slate-400">耗时 32ms</span>
                  </div>
                  <div className="text-slate-400 flex items-center gap-1">
                    <span>最高命中期:</span>
                    <span className="text-slate-100 font-bold">{skillCards[decisionResult.matchedIndex].name}</span>
                  </div>
                </div>
              </div>
            )}

            {/* BATTLE_VICTORY State */}
            {fsmState === 'BATTLE_VICTORY' && (
              <div className="flex-1 flex flex-col justify-between p-4 bg-gradient-to-b from-amber-950/60 via-slate-950 to-slate-900">
                <div className="text-center pt-8">
                  <div className="text-4xl mb-2">🏆</div>
                  <h3 className="text-xl font-bold text-amber-400">通关胜利！VICTORY</h3>
                  <p className="text-xs text-slate-400 mt-1">第 32 章 · 沼泽巨石阵 已成功击破</p>
                </div>

                {/* Loot Items */}
                <div className="bg-slate-900/80 p-3 rounded-xl border border-slate-800 space-y-2">
                  <div className="text-xs font-semibold text-slate-300">本局掉落汇总</div>
                  <div className="grid grid-cols-3 gap-2 text-center text-[10px]">
                    <div className="bg-slate-950 p-2 rounded-lg border border-slate-800">
                      <Coins className="w-4 h-4 text-amber-400 mx-auto mb-1" />
                      <div className="font-mono text-slate-200">+12,500</div>
                    </div>
                    <div className="bg-slate-950 p-2 rounded-lg border border-slate-800">
                      <Ship className="w-4 h-4 text-cyan-400 mx-auto mb-1" />
                      <div className="font-mono text-slate-200">公会船票 x1</div>
                    </div>
                    <div className="bg-slate-950 p-2 rounded-lg border border-slate-800">
                      <Shield className="w-4 h-4 text-emerald-400 mx-auto mb-1" />
                      <div className="font-mono text-slate-200">坚硬重甲 x1</div>
                    </div>
                  </div>
                </div>

                <button
                  type="button"
                  onClick={() => {
                    executeSimulatedClick(170, 520, '胜利领取奖励');
                    onFsmChange('GUILD_PANEL');
                    onLog('FSM', 'STATE', '通关完毕，切换至公会模块');
                  }}
                  className="w-full py-3 bg-amber-500 hover:bg-amber-400 text-slate-950 font-bold text-xs rounded-xl shadow cursor-pointer"
                >
                  领取奖励并前往公会
                </button>
              </div>
            )}

            {/* BATTLE_DEFEAT State */}
            {fsmState === 'BATTLE_DEFEAT' && (
              <div className="flex-1 flex flex-col justify-between p-4 bg-gradient-to-b from-rose-950/60 via-slate-950 to-slate-900">
                <div className="text-center pt-8">
                  <div className="text-4xl mb-2">💀</div>
                  <h3 className="text-xl font-bold text-rose-400">战败 DEFEAT</h3>
                  <p className="text-xs text-slate-400 mt-1">小号当前战力达到瓶颈，退回主城强化</p>
                </div>

                <div className="space-y-2">
                  <button
                    type="button"
                    onClick={() => {
                      executeSimulatedClick(170, 480, '返回主城强化');
                      onFsmChange('MAIN_CITY');
                      onLog('FSM', 'STATE', '战败退回主城，执行属性提升');
                    }}
                    className="w-full py-3 bg-slate-800 hover:bg-slate-700 text-slate-100 font-bold text-xs rounded-xl border border-slate-700 cursor-pointer"
                  >
                    返回主城强化战力
                  </button>

                  <button
                    type="button"
                    onClick={() => {
                      executeSimulatedClick(170, 530, '再次挑战');
                      onFsmChange('BATTLE_RUNNING');
                      setBattleHp(100);
                      setBattleExp(20);
                      onLog('FSM', 'STATE', '重新尝试挑战该关卡');
                    }}
                    className="w-full py-2.5 bg-rose-600/80 hover:bg-rose-600 text-rose-100 font-semibold text-xs rounded-xl cursor-pointer"
                  >
                    再次挑战 (剩余重试: 1)
                  </button>
                </div>
              </div>
            )}

            {/* GUILD_PANEL State */}
            {fsmState === 'GUILD_PANEL' && (
              <div className="flex-1 flex flex-col justify-between p-4 bg-gradient-to-b from-cyan-950/60 via-slate-950 to-slate-900">
                <div className="flex items-center justify-between pb-2 border-b border-slate-800">
                  <div className="flex items-center gap-2">
                    <Ship className="w-5 h-5 text-cyan-400" />
                    <div>
                      <h4 className="text-xs font-bold text-slate-100">卡皮巴拉公会·航海大厅</h4>
                      <div className="text-[10px] text-slate-400">公会等级: Lv.8 · 排名: 14</div>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => onFsmChange('MAIN_CITY')}
                    className="text-xs text-slate-400 hover:text-slate-200 cursor-pointer"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>

                <div className="space-y-3 my-auto">
                  {/* Gold Donation */}
                  <div className="bg-slate-900/80 p-3 rounded-xl border border-slate-800 flex items-center justify-between">
                    <div>
                      <div className="text-xs font-bold text-slate-100">金币日常建设 (3次)</div>
                      <div className="text-[10px] text-slate-400">今日已捐赠 3/3 次 (+300贡献)</div>
                    </div>
                    <button
                      type="button"
                      onClick={() => {
                        executeSimulatedClick(260, 220, '金币捐献');
                        onLog('INFO', 'GUILD', '完成公会金币 3 连捐！');
                      }}
                      className="py-1.5 px-3 bg-amber-500/20 text-amber-300 border border-amber-500/40 rounded-lg text-xs font-medium cursor-pointer"
                    >
                      已拉满
                    </button>
                  </div>

                  {/* Boat Tickets Contribution */}
                  <div className="bg-slate-900/80 p-3 rounded-xl border border-slate-800 flex items-center justify-between">
                    <div>
                      <div className="text-xs font-bold text-slate-100">远洋航海船票贡献</div>
                      <div className="text-[10px] text-cyan-400">当前持有船票: 2 张</div>
                    </div>
                    <button
                      type="button"
                      onClick={() => {
                        executeSimulatedClick(260, 280, '提交船票');
                        onLog('INFO', 'GUILD', '小号成功提交船票 x2 反哺公会航海宝箱！');
                      }}
                      className="py-1.5 px-3 bg-cyan-600 hover:bg-cyan-500 text-white rounded-lg text-xs font-medium cursor-pointer"
                    >
                      一键提交
                    </button>
                  </div>
                </div>

                <button
                  type="button"
                  onClick={() => {
                    executeSimulatedClick(170, 520, '返回主城');
                    onFsmChange('MAIN_CITY');
                  }}
                  className="w-full py-2.5 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold rounded-xl cursor-pointer"
                >
                  返回主城
                </button>
              </div>
            )}

            {/* POPUP_INTERRUPT State (Watchdog Thread Test) */}
            {fsmState === 'POPUP_INTERRUPT' && (
              <div className="absolute inset-0 bg-black/80 backdrop-blur-sm z-50 flex flex-col items-center justify-center p-6 text-center">
                <div className="w-full bg-slate-900 border border-amber-500/60 rounded-2xl p-4 shadow-2xl relative animate-in fade-in zoom-in-95">
                  {/* Close button X */}
                  <button
                    type="button"
                    onClick={() => {
                      executeSimulatedClick(295, 235, '手动消除弹窗[X]');
                      onFsmChange('MAIN_CITY');
                    }}
                    className="absolute -top-3 -right-3 w-7 h-7 rounded-full bg-rose-600 hover:bg-rose-500 text-white flex items-center justify-center cursor-pointer shadow-lg"
                  >
                    <X className="w-4 h-4" />
                  </button>

                  <div className="text-3xl mb-2">🎁</div>
                  <h4 className="text-sm font-bold text-amber-400">【限时特惠】至尊首充大礼包</h4>
                  <p className="text-[10px] text-slate-300 mt-1">
                    充值 ¥648 赠送传说品质水豚铠甲与 10,000 钻石！
                  </p>

                  <div className="mt-4 space-y-2">
                    <button
                      type="button"
                      className="w-full py-2 bg-gradient-to-r from-amber-500 to-amber-400 text-slate-950 font-bold text-xs rounded-lg"
                    >
                      ¥648 立即充值 (诱导充值)
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        executeSimulatedClick(170, 360, '残忍拒绝按钮');
                        onFsmChange('MAIN_CITY');
                      }}
                      className="text-[10px] text-slate-400 hover:text-slate-200 underline cursor-pointer"
                    >
                      残忍拒绝 / 暂不升级
                    </button>
                  </div>

                  <div className="mt-3 pt-2 border-t border-slate-800 text-[9px] text-emerald-400 flex items-center justify-center gap-1">
                    <Activity className="w-3 h-3 animate-spin" />
                    <span>后台守护线程 (Thread) 正在自动检索关闭键...</span>
                  </div>
                </div>
              </div>
            )}

            {/* ACCOUNT_SWITCHING State */}
            {fsmState === 'ACCOUNT_SWITCHING' && (
              <div className="flex-1 flex flex-col items-center justify-center p-6 bg-slate-950 text-center">
                <RefreshCw className="w-8 h-8 text-amber-400 animate-spin mb-3" />
                <h4 className="text-xs font-bold text-slate-100">正在隔离切换账号分身</h4>
                <div className="text-[10px] font-mono text-slate-400 mt-2 bg-slate-900 p-2 rounded-lg border border-slate-800 w-full text-left">
                  <div>$ am force-stop com.game.capy</div>
                  <div>$ am start --user 999 ...</div>
                  <div className="text-emerald-400">$ 蜂窝网络飞行模式 IP 重置完成</div>
                </div>
                <button
                  type="button"
                  onClick={() => onFsmChange('MAIN_CITY')}
                  className="mt-4 px-4 py-1.5 bg-amber-500 text-slate-950 text-xs font-bold rounded-lg cursor-pointer"
                >
                  完成切换
                </button>
              </div>
            )}

            {/* Touch Point Gaussian Trail Overlay */}
            {showTouchPoints && lastTouchPoint && (
              <div
                className="absolute pointer-events-none z-50 transform -translate-x-1/2 -translate-y-1/2"
                style={{ left: `${lastTouchPoint.realX}px`, top: `${lastTouchPoint.realY}px` }}
              >
                {/* Target intended point */}
                <div
                  className="absolute -translate-x-1/2 -translate-y-1/2 w-2 h-2 rounded-full border border-cyan-400"
                  style={{
                    left: `${lastTouchPoint.x - lastTouchPoint.realX}px`,
                    top: `${lastTouchPoint.y - lastTouchPoint.realY}px`,
                  }}
                  title="意图目标中心点"
                />
                {/* Real physically jittered point with ripple */}
                <div className="w-6 h-6 rounded-full bg-amber-500/30 border border-amber-400 animate-ping" />
                <div className="w-2.5 h-2.5 rounded-full bg-amber-400 absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 shadow-lg" />
              </div>
            )}
          </div>

          {/* Android Bottom Navigation Bar */}
          <div className="h-9 bg-slate-950 flex items-center justify-around px-8 z-30 shrink-0 border-t border-slate-800">
            <button
              type="button"
              onClick={() => {
                onLog('TOUCH', 'KEY', '按下 Android 返回键 (Back)');
                if (fsmState === 'POPUP_INTERRUPT') onFsmChange('MAIN_CITY');
                else if (fsmState === 'GUILD_PANEL') onFsmChange('MAIN_CITY');
                else if (fsmState === 'BATTLE_VICTORY') onFsmChange('MAIN_CITY');
              }}
              className="text-slate-500 hover:text-slate-300 cursor-pointer text-xs"
            >
              ◁
            </button>
            <button
              type="button"
              onClick={() => {
                onLog('TOUCH', 'KEY', '按下 Android 主页键 (Home)');
                onFsmChange('MAIN_CITY');
              }}
              className="text-slate-500 hover:text-slate-300 cursor-pointer text-xs"
            >
              ○
            </button>
            <button
              type="button"
              onClick={() => onLog('TOUCH', 'KEY', '按下 Android 多任务键 (Recent Apps)')}
              className="text-slate-500 hover:text-slate-300 cursor-pointer text-xs"
            >
              □
            </button>
          </div>
        </div>
      </div>

      {/* Simulator Control & Telemetry Strip */}
      <div className="w-full xl:w-80 flex flex-col gap-4">
        {/* Pipeline Master Switch */}
        <div className="p-4 bg-slate-900 rounded-xl border border-slate-800">
          <div className="flex items-center justify-between mb-3">
            <div className="text-xs font-bold text-slate-100 flex items-center gap-1.5">
              <Zap className="w-4 h-4 text-amber-400" />
              <span>全自动工程流水线中控</span>
            </div>
            <span
              className={`text-[10px] font-mono px-2 py-0.5 rounded ${
                isAutoRunning ? 'bg-emerald-500/20 text-emerald-300' : 'bg-slate-800 text-slate-400'
              }`}
            >
              {isAutoRunning ? 'RUNNING' : 'STOPPED'}
            </span>
          </div>

          <button
            type="button"
            onClick={onToggleAutoRun}
            className={`w-full py-2.5 px-3 rounded-lg text-xs font-bold flex items-center justify-center gap-2 transition-colors cursor-pointer ${
              isAutoRunning
                ? 'bg-rose-600 hover:bg-rose-500 text-white'
                : 'bg-amber-500 hover:bg-amber-400 text-slate-950'
            }`}
          >
            {isAutoRunning ? (
              <>
                <Pause className="w-3.5 h-3.5" />
                <span>急停中断 (STOP PIPELINE)</span>
              </>
            ) : (
              <>
                <Play className="w-3.5 h-3.5 fill-current" />
                <span>启动全自动流水线 (START)</span>
              </>
            )}
          </button>

          {/* Quick State Injectors */}
          <div className="mt-4 pt-3 border-t border-slate-800/80">
            <div className="text-[11px] text-slate-400 mb-2 font-medium">仿真场景注入与测试:</div>
            <div className="grid grid-cols-2 gap-1.5 text-[10px]">
              <button
                type="button"
                onClick={() => onFsmChange('MAIN_CITY')}
                className="py-1.5 px-2 bg-slate-800 hover:bg-slate-700 rounded text-slate-300 text-left cursor-pointer"
              >
                进入主城
              </button>
              <button
                type="button"
                onClick={() => onFsmChange('BATTLE_RUNNING')}
                className="py-1.5 px-2 bg-slate-800 hover:bg-slate-700 rounded text-slate-300 text-left cursor-pointer"
              >
                开始推关战斗
              </button>
              <button
                type="button"
                onClick={() => onFsmChange('SKILL_CHOICE')}
                className="py-1.5 px-2 bg-indigo-950 hover:bg-indigo-900 border border-indigo-800/50 rounded text-indigo-300 text-left cursor-pointer"
              >
                技能三选一 (OCR)
              </button>
              <button
                type="button"
                onClick={() => onFsmChange('GUILD_PANEL')}
                className="py-1.5 px-2 bg-cyan-950 hover:bg-cyan-900 border border-cyan-800/50 rounded text-cyan-300 text-left cursor-pointer"
              >
                公会捐赠船票
              </button>
              <button
                type="button"
                onClick={() => {
                  onLog('WARN', 'INJECT', '模拟第三方限时首充弹窗打断主流程');
                  onFsmChange('POPUP_INTERRUPT');
                }}
                className="py-1.5 px-2 bg-amber-950 hover:bg-amber-900 border border-amber-800/50 rounded text-amber-300 text-left flex items-center gap-1 cursor-pointer col-span-2"
              >
                <AlertTriangle className="w-3 h-3 text-amber-400 shrink-0" />
                <span>模拟强弹窗打断 (测试守护子线程)</span>
              </button>
            </div>
          </div>
        </div>

        {/* Display Overlay Toggles */}
        <div className="p-4 bg-slate-900 rounded-xl border border-slate-800 space-y-3">
          <div className="text-xs font-bold text-slate-200">模拟视图与视觉调试层</div>

          <label className="flex items-center justify-between text-xs text-slate-300 cursor-pointer">
            <span className="flex items-center gap-2">
              <Eye className="w-3.5 h-3.5 text-emerald-400" />
              <span>显示离线 OCR 检出框与置信度</span>
            </span>
            <input
              type="checkbox"
              checked={showOcrBoxes}
              onChange={(e) => setShowOcrBoxes(e.target.checked)}
              className="accent-amber-500 rounded cursor-pointer"
            />
          </label>

          <label className="flex items-center justify-between text-xs text-slate-300 cursor-pointer">
            <span className="flex items-center gap-2">
              <Target className="w-3.5 h-3.5 text-amber-400" />
              <span>显示高斯落点抖动轨迹 (σ = {config.gaussianStdev}px)</span>
            </span>
            <input
              type="checkbox"
              checked={showTouchPoints}
              onChange={(e) => setShowTouchPoints(e.target.checked)}
              className="accent-amber-500 rounded cursor-pointer"
            />
          </label>

          <label className="flex items-center justify-between text-xs text-slate-300 cursor-pointer">
            <span className="flex items-center gap-2">
              <BatteryCharging className="w-3.5 h-3.5 text-cyan-400" />
              <span>暗屏节能省电模式 (device.setBrightness: 0)</span>
            </span>
            <input
              type="checkbox"
              checked={isDarkScreen}
              onChange={(e) => setIsDarkScreen(e.target.checked)}
              className="accent-amber-500 rounded cursor-pointer"
            />
          </label>
        </div>

        {/* Real-time coordinates monitor */}
        <div className="p-3 bg-slate-900/60 rounded-xl border border-slate-800 text-[11px] font-mono text-slate-400">
          <div className="text-[10px] text-slate-500 mb-1">最近一次触控落点物理参数</div>
          {lastTouchPoint ? (
            <div className="space-y-0.5">
              <div>意图坐标: ({lastTouchPoint.x}, {lastTouchPoint.y})</div>
              <div className="text-amber-400">
                真实落点: ({lastTouchPoint.realX}, {lastTouchPoint.realY}) [Δx: {lastTouchPoint.realX - lastTouchPoint.x}px, Δy: {lastTouchPoint.realY - lastTouchPoint.y}px]
              </div>
            </div>
          ) : (
            <div className="text-slate-600">等待触发模拟点击...</div>
          )}
        </div>
      </div>
    </div>
  );
};
