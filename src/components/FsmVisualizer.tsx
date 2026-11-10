import React from 'react';
import { FsmState } from '../types/pipeline';
import {
  Layers,
  ArrowRight,
  ShieldAlert,
  Clock,
  CheckCircle,
  AlertOctagon,
  RefreshCw,
  GitBranch,
} from 'lucide-react';

interface FsmVisualizerProps {
  currentState: FsmState;
  onStateSelect: (state: FsmState) => void;
}

interface StateNode {
  key: FsmState;
  label: string;
  sub: string;
  type: 'normal' | 'decision' | 'guard' | 'branch';
}

export const FsmVisualizer: React.FC<FsmVisualizerProps> = ({
  currentState,
  onStateSelect,
}) => {
  const nodes: StateNode[] = [
    { key: 'IDLE', label: '01. 系统初始化', sub: '权限自检 / 守护线程', type: 'normal' },
    { key: 'MAIN_CITY', label: '02. 主城状态', sub: '20倍游历 / 属性加点', type: 'normal' },
    { key: 'BATTLE_RUNNING', label: '03. 战斗进行中', sub: '实时波次监控 / 轮询', type: 'normal' },
    { key: 'SKILL_CHOICE', label: '04. 技能三选一', sub: 'PaddleOCR 权重匹配', type: 'decision' },
    { key: 'BATTLE_VICTORY', label: '05. 通关胜利', sub: '拾取船票 / 关卡递增', type: 'normal' },
    { key: 'BATTLE_DEFEAT', label: '06. 战败结算', sub: '超频熔断 / 战力瓶颈', type: 'normal' },
    { key: 'GUILD_PANEL', label: '07. 公会建设', sub: '金币3捐 / 航海贡献', type: 'normal' },
    { key: 'ACCOUNT_SWITCHING', label: '08. 账号轮转', sub: '分身隔离 / 飞行模式IP', type: 'branch' },
    { key: 'POPUP_INTERRUPT', label: '09. 异常拦截', sub: 'Thread守护 / 自动消除', type: 'guard' },
  ];

  return (
    <div className="p-5 bg-slate-900 rounded-xl border border-slate-800">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-4 mb-4 border-b border-slate-800 gap-2">
        <div className="flex items-center gap-2">
          <GitBranch className="w-5 h-5 text-amber-400" />
          <div>
            <h3 className="text-sm font-bold text-slate-100">核心有限状态机 (FSM) 实时拓扑</h3>
            <p className="text-xs text-slate-400">单机自动化闭环模型与异常状态自愈恢复链路</p>
          </div>
        </div>
        <div className="flex items-center gap-3 text-xs font-mono">
          <span className="text-slate-400">当前活跃状态:</span>
          <span className="px-2 py-0.5 rounded bg-amber-500/20 text-amber-300 font-bold border border-amber-500/30">
            {currentState}
          </span>
        </div>
      </div>

      {/* Nodes Grid */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {nodes.map((node) => {
          const isActive = currentState === node.key;
          return (
            <button
              key={node.key}
              type="button"
              onClick={() => onStateSelect(node.key)}
              className={`text-left p-3 rounded-xl border transition-all cursor-pointer relative ${
                isActive
                  ? 'bg-amber-950/40 border-amber-500 ring-2 ring-amber-500/30 shadow-lg'
                  : 'bg-slate-950/60 border-slate-800 hover:border-slate-700'
              }`}
            >
              <div className="flex items-center justify-between">
                <span
                  className={`text-xs font-bold ${
                    isActive ? 'text-amber-400' : 'text-slate-200'
                  }`}
                >
                  {node.label}
                </span>
                {isActive && (
                  <span className="w-2 h-2 rounded-full bg-amber-400 animate-ping"></span>
                )}
              </div>
              <div className="text-[11px] text-slate-400 mt-1">{node.sub}</div>

              {/* Tag indicator */}
              <div className="mt-2 flex items-center justify-between text-[10px] font-mono text-slate-500">
                <span>{node.key}</span>
                {node.type === 'decision' && (
                  <span className="text-indigo-400">OCR DECISION</span>
                )}
                {node.type === 'guard' && (
                  <span className="text-rose-400">DAEMON WATCHDOG</span>
                )}
                {node.type === 'branch' && (
                  <span className="text-cyan-400">MULTI-USER</span>
                )}
              </div>
            </button>
          );
        })}
      </div>

      {/* State Transitions Flow Diagram Note */}
      <div className="mt-4 p-3 bg-slate-950 rounded-lg border border-slate-800/80 text-xs text-slate-400 space-y-1">
        <div className="font-semibold text-slate-300 flex items-center gap-1.5">
          <Clock className="w-3.5 h-3.5 text-amber-400" />
          <span>状态转移规则与熔断保护 (Watchdog Invariants):</span>
        </div>
        <div className="text-[11px] text-slate-400 font-mono">
          [主城] ──出战──&gt; [战斗中] ──满经验──&gt; [技能选择] ──离线OCR──&gt; [选定重回战斗] ──通关──&gt; [公会供票] ──登出──&gt; [分身轮换]
        </div>
        <div className="text-[11px] text-slate-500">
          * 任何状态若卡顿停留超过 45s 即判定为异常阻塞，调用 <code className="text-slate-400 font-mono">back()</code> 退出并强制重置回主城。
        </div>
      </div>
    </div>
  );
};
