import React, { useState } from 'react';
import { PipelineConfig } from '../types/pipeline';
import { matchBestSkill, generateHumanClick } from '../core/decision';
import {
  ListOrdered,
  ArrowUp,
  ArrowDown,
  Plus,
  Trash2,
  Sparkles,
  Sliders,
  ShieldCheck,
  Target,
  RefreshCw,
  Cpu,
} from 'lucide-react';

interface SkillPriorityStudioProps {
  config: PipelineConfig;
  onUpdateConfig: (newConfig: PipelineConfig) => void;
}

export const SkillPriorityStudio: React.FC<SkillPriorityStudioProps> = ({
  config,
  onUpdateConfig,
}) => {
  const [newSkillName, setNewSkillName] = useState('');
  const [testCards, setTestCards] = useState([
    '技能：冰刺 lv1 (减速)',
    '技能：越战越硬 (护盾)',
    '技能：连击强化 (攻速)',
  ]);
  const [scatterPoints, setScatterPoints] = useState<{ x: number; y: number }[]>([]);

  // Skill re-ordering
  const moveSkill = (index: number, direction: 'up' | 'down') => {
    const list = [...config.skillPriorityList];
    const targetIndex = direction === 'up' ? index - 1 : index + 1;
    if (targetIndex < 0 || targetIndex >= list.length) return;

    const temp = list[index];
    list[index] = list[targetIndex];
    list[targetIndex] = temp;

    onUpdateConfig({ ...config, skillPriorityList: list });
  };

  const removeSkill = (index: number) => {
    const list = config.skillPriorityList.filter((_, i) => i !== index);
    onUpdateConfig({ ...config, skillPriorityList: list });
  };

  const addSkill = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newSkillName.trim()) return;
    if (config.skillPriorityList.includes(newSkillName.trim())) return;

    onUpdateConfig({
      ...config,
      skillPriorityList: [...config.skillPriorityList, newSkillName.trim()],
    });
    setNewSkillName('');
  };

  // Run live OCR match test
  const testMatchResult = matchBestSkill(
    testCards.map((text) => ({ text })),
    config.skillPriorityList
  );

  // Generate 25 scatter points for the interactive target plate
  const simulateScatter = () => {
    const points: { x: number; y: number }[] = [];
    for (let i = 0; i < 35; i++) {
      const click = generateHumanClick(120, 120, config.gaussianStdev);
      points.push({ x: click.realX, y: click.realY });
    }
    setScatterPoints(points);
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
      {/* Left: Skill Priority Queue */}
      <div className="p-5 bg-slate-900 rounded-xl border border-slate-800 flex flex-col justify-between">
        <div>
          <div className="flex items-center justify-between pb-3 mb-3 border-b border-slate-800">
            <div className="flex items-center gap-2">
              <ListOrdered className="w-4 h-4 text-amber-400" />
              <div>
                <h3 className="text-sm font-bold text-slate-100">局内 Roguelike 技能优先级队列</h3>
                <p className="text-xs text-slate-400">排名越靠前越优先选择（离线 PaddleOCR 关键字加权）</p>
              </div>
            </div>
            <span className="text-[11px] font-mono text-amber-400 bg-amber-950/40 px-2 py-0.5 rounded border border-amber-900/60">
              {config.skillPriorityList.length} 核心技能
            </span>
          </div>

          {/* Add skill input */}
          <form onSubmit={addSkill} className="flex gap-2 mb-3">
            <input
              type="text"
              value={newSkillName}
              onChange={(e) => setNewSkillName(e.target.value)}
              placeholder="新增技能关键词 (例: 暴击率, 伤害吸收)"
              className="flex-1 bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-slate-100 focus:outline-hidden focus:border-amber-500"
            />
            <button
              type="submit"
              className="py-1.5 px-3 bg-amber-500 hover:bg-amber-400 text-slate-950 text-xs font-bold rounded-lg flex items-center gap-1 cursor-pointer"
            >
              <Plus className="w-3.5 h-3.5" />
              <span>添加</span>
            </button>
          </form>

          {/* List items */}
          <div className="space-y-1.5 max-h-80 overflow-y-auto pr-1">
            {config.skillPriorityList.map((skill, index) => (
              <div
                key={skill}
                className="flex items-center justify-between p-2 rounded-lg bg-slate-950 border border-slate-800/80 text-xs group hover:border-slate-700 transition-colors"
              >
                <div className="flex items-center gap-2.5">
                  <span className="font-mono text-[11px] font-bold text-amber-400 w-6 text-center">
                    #{index + 1}
                  </span>
                  <span className="font-medium text-slate-200">{skill}</span>
                  {index === 0 && (
                    <span className="text-[9px] bg-amber-500/10 text-amber-300 font-mono px-1.5 py-0.2 rounded border border-amber-500/30">
                      最高优
                    </span>
                  )}
                </div>

                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    onClick={() => moveSkill(index, 'up')}
                    disabled={index === 0}
                    className="p-1 text-slate-400 hover:text-slate-100 disabled:opacity-30 disabled:hover:text-slate-400 cursor-pointer"
                    title="上移"
                  >
                    <ArrowUp className="w-3.5 h-3.5" />
                  </button>
                  <button
                    type="button"
                    onClick={() => moveSkill(index, 'down')}
                    disabled={index === config.skillPriorityList.length - 1}
                    className="p-1 text-slate-400 hover:text-slate-100 disabled:opacity-30 disabled:hover:text-slate-400 cursor-pointer"
                    title="下移"
                  >
                    <ArrowDown className="w-3.5 h-3.5" />
                  </button>
                  <button
                    type="button"
                    onClick={() => removeSkill(index)}
                    className="p-1 text-slate-500 hover:text-rose-400 transition-colors cursor-pointer"
                    title="删除"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Live OCR Decision Sandbox */}
        <div className="mt-4 pt-3 border-t border-slate-800 bg-slate-950 p-3 rounded-xl border border-slate-800/60">
          <div className="text-xs font-semibold text-slate-300 mb-2 flex items-center justify-between">
            <span className="flex items-center gap-1.5">
              <Sparkles className="w-3.5 h-3.5 text-indigo-400" />
              <span>实时 OCR 决策验算测试</span>
            </span>
            <span className="text-[10px] text-slate-400 font-mono">
              命中卡牌: #{testMatchResult.matchedIndex + 1}
            </span>
          </div>

          <div className="grid grid-cols-3 gap-2">
            {testCards.map((text, i) => {
              const isHit = testMatchResult.matchedIndex === i;
              return (
                <div
                  key={i}
                  className={`p-2 rounded-lg text-[10px] border transition-colors ${
                    isHit
                      ? 'bg-amber-950/40 border-amber-500 text-amber-200 ring-1 ring-amber-500/40 font-bold'
                      : 'bg-slate-900 border-slate-800 text-slate-400'
                  }`}
                >
                  <div className="text-[8px] font-mono text-slate-500">候选卡牌 {i + 1}</div>
                  <div className="mt-1 truncate">{text}</div>
                  <div className="mt-1.5 font-mono text-[8px]">
                    {isHit ? (
                      <span className="text-amber-400">✓ 决策选定 (Rank #{testMatchResult.highestRank + 1})</span>
                    ) : (
                      '未选中'
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Right: Anti-Ban Gaussian Jitter & Physics Lab */}
      <div className="p-5 bg-slate-900 rounded-xl border border-slate-800 flex flex-col justify-between">
        <div>
          <div className="flex items-center justify-between pb-3 mb-3 border-b border-slate-800">
            <div className="flex items-center gap-2">
              <Target className="w-4 h-4 text-emerald-400" />
              <div>
                <h3 className="text-sm font-bold text-slate-100">高斯分布拟人触控防封仿真台</h3>
                <p className="text-xs text-slate-400">物理落点微抖动与按压时延离散度调优</p>
              </div>
            </div>
            <span className="text-[11px] font-mono text-emerald-400 bg-emerald-950/40 px-2 py-0.5 rounded border border-emerald-900/60">
              安全等级: 极高 (Human-Like)
            </span>
          </div>

          {/* Interactive Target Plate */}
          <div className="flex flex-col sm:flex-row items-center gap-6 my-2">
            {/* Target Circle Canvas */}
            <div
              onClick={simulateScatter}
              className="w-60 h-60 bg-slate-950 border border-slate-800 rounded-2xl relative overflow-hidden flex items-center justify-center cursor-pointer group shadow-inner"
              title="点击在靶心模拟生成 35 次高斯拟人点击"
            >
              {/* Outer target concentric rings */}
              <div className="w-48 h-48 rounded-full border border-slate-800/80 absolute"></div>
              <div className="w-32 h-32 rounded-full border border-slate-800 absolute"></div>
              <div className="w-16 h-16 rounded-full border border-amber-500/30 bg-amber-500/5 absolute"></div>
              {/* Exact center crosshair */}
              <div className="w-full h-[1px] bg-slate-800/60 absolute"></div>
              <div className="h-full w-[1px] bg-slate-800/60 absolute"></div>

              {/* Exact intended target (Blue point) */}
              <div className="w-2.5 h-2.5 rounded-full bg-cyan-400 z-10 shadow-lg shadow-cyan-400/50 absolute"></div>

              {/* Jittered points (Orange dots) */}
              {scatterPoints.map((pt, i) => (
                <div
                  key={i}
                  className="w-1.5 h-1.5 rounded-full bg-amber-400 absolute opacity-80 animate-in fade-in zoom-in-50"
                  style={{
                    left: `${pt.x}px`,
                    top: `${pt.y}px`,
                  }}
                />
              ))}

              <div className="absolute bottom-2 text-[9px] text-slate-500 font-mono">
                {scatterPoints.length > 0 ? `${scatterPoints.length} 次离散采样` : '点击靶盘生成离散落点'}
              </div>
            </div>

            {/* Sliders and Parameters */}
            <div className="flex-1 space-y-4 w-full">
              <div>
                <div className="flex items-center justify-between text-xs text-slate-300 mb-1">
                  <span>高斯抖动标准差 (Gaussian σ)</span>
                  <span className="font-mono text-amber-400 font-bold">{config.gaussianStdev} px</span>
                </div>
                <input
                  type="range"
                  min="2"
                  max="16"
                  value={config.gaussianStdev}
                  onChange={(e) =>
                    onUpdateConfig({ ...config, gaussianStdev: Number(e.target.value) })
                  }
                  className="w-full accent-amber-500 cursor-pointer"
                />
                <div className="flex justify-between text-[10px] text-slate-500 font-mono mt-0.5">
                  <span>2px (偏机械)</span>
                  <span>6px (推荐人类手感)</span>
                  <span>16px (强离散)</span>
                </div>
              </div>

              <div>
                <div className="flex items-center justify-between text-xs text-slate-300 mb-1">
                  <span>按压时长均值 (Press Duration)</span>
                  <span className="font-mono text-cyan-400 font-bold">{config.pressDurationMean} ms</span>
                </div>
                <input
                  type="range"
                  min="40"
                  max="140"
                  value={config.pressDurationMean}
                  onChange={(e) =>
                    onUpdateConfig({ ...config, pressDurationMean: Number(e.target.value) })
                  }
                  className="w-full accent-cyan-500 cursor-pointer"
                />
                <div className="flex justify-between text-[10px] text-slate-500 font-mono mt-0.5">
                  <span>40ms (轻触)</span>
                  <span>80ms (正常手指)</span>
                  <span>140ms (长按)</span>
                </div>
              </div>

              <div>
                <div className="flex items-center justify-between text-xs text-slate-300 mb-1">
                  <span>生理反应随机停顿 (Reaction Delay)</span>
                  <span className="font-mono text-emerald-400 font-bold">
                    {config.reactionMinDelay} ~ {config.reactionMaxDelay} ms
                  </span>
                </div>
                <div className="text-[11px] text-slate-400 bg-slate-950 p-2.5 rounded-lg border border-slate-800">
                  杜绝绝对 1.0 秒机械节拍。每次点击与滑动后自动引入均匀离散停顿，彻底规避游戏引擎行为熵检测。
                </div>
              </div>
            </div>
          </div>
        </div>

        <button
          type="button"
          onClick={simulateScatter}
          className="w-full mt-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold rounded-lg flex items-center justify-center gap-1.5 transition-colors cursor-pointer"
        >
          <RefreshCw className="w-3.5 h-3.5 text-amber-400" />
          <span>重新采样高斯落点 (Sample 35 Points)</span>
        </button>
      </div>
    </div>
  );
};
