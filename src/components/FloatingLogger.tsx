import React, { useState } from 'react';
import { LogMessage } from '../types/pipeline';
import {
  Terminal,
  Trash2,
  Copy,
  Check,
  Download,
  Filter,
  Maximize2,
  Minimize2,
} from 'lucide-react';

interface FloatingLoggerProps {
  logs: LogMessage[];
  onClearLogs: () => void;
}

export const FloatingLogger: React.FC<FloatingLoggerProps> = ({
  logs,
  onClearLogs,
}) => {
  const [activeFilter, setActiveFilter] = useState<string>('ALL');
  const [copied, setCopied] = useState(false);

  const filterTabs = ['ALL', 'FSM', 'OCR', 'TOUCH', 'GUARD', 'INFO'];

  const filteredLogs = logs.filter((log) => {
    if (activeFilter === 'ALL') return true;
    return log.level === activeFilter;
  });

  const handleCopy = () => {
    const text = filteredLogs
      .map((l) => `[${l.timestamp}] [${l.level}] [${l.tag}] ${l.message}`)
      .join('\n');
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownload = () => {
    const text = logs
      .map((l) => `[${l.timestamp}] [${l.level}] [${l.tag}] ${l.message}`)
      .join('\n');
    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'CapyScript_run.log';
    a.click();
    URL.revokeObjectURL(url);
  };

  const getLevelColor = (level: LogMessage['level']) => {
    switch (level) {
      case 'FSM':
        return 'text-amber-400 bg-amber-500/10 border-amber-500/30';
      case 'OCR':
        return 'text-indigo-400 bg-indigo-500/10 border-indigo-500/30';
      case 'TOUCH':
        return 'text-cyan-400 bg-cyan-500/10 border-cyan-500/30';
      case 'GUARD':
        return 'text-rose-400 bg-rose-500/10 border-rose-500/30';
      case 'WARN':
        return 'text-amber-300 bg-amber-500/10 border-amber-500/30';
      case 'ERROR':
        return 'text-rose-400 bg-rose-500/20 border-rose-500/40';
      default:
        return 'text-slate-300 bg-slate-800 border-slate-700';
    }
  };

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden flex flex-col h-[520px]">
      {/* Logger Top Bar */}
      <div className="p-3.5 border-b border-slate-800 bg-slate-950/70 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Terminal className="w-4 h-4 text-amber-400" />
          <div>
            <h4 className="text-xs font-bold text-slate-100">AutoX.js 实时日志与悬浮窗管道流</h4>
            <div className="text-[10px] text-slate-500 font-mono">/sdcard/CapyScript/run.log</div>
          </div>
        </div>

        {/* Filter Buttons */}
        <div className="flex items-center gap-1 bg-slate-900 p-1 rounded-lg border border-slate-800">
          {filterTabs.map((tab) => (
            <button
              key={tab}
              type="button"
              onClick={() => setActiveFilter(tab)}
              className={`px-2 py-0.5 text-[10px] font-mono rounded transition-colors cursor-pointer ${
                activeFilter === tab
                  ? 'bg-amber-500 text-slate-950 font-bold'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              {tab}
            </button>
          ))}
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleCopy}
            className="p-1.5 text-slate-400 hover:text-slate-200 hover:bg-slate-800 rounded transition-colors cursor-pointer"
            title="复制日志"
          >
            {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
          </button>
          <button
            type="button"
            onClick={handleDownload}
            className="p-1.5 text-slate-400 hover:text-slate-200 hover:bg-slate-800 rounded transition-colors cursor-pointer"
            title="下载 run.log 文件"
          >
            <Download className="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            onClick={onClearLogs}
            className="p-1.5 text-slate-400 hover:text-rose-400 hover:bg-slate-800 rounded transition-colors cursor-pointer"
            title="清空当前日志"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Log Console Output */}
      <div className="flex-1 p-3 overflow-y-auto font-mono text-xs space-y-1.5 bg-slate-950 text-slate-300">
        {filteredLogs.length === 0 ? (
          <div className="text-slate-600 text-center py-12 text-[11px]">
            暂无日志消息，请点击“启动全自动流水线”或在手机仿真器触发操作...
          </div>
        ) : (
          filteredLogs.map((log) => (
            <div key={log.id} className="flex items-start gap-2 leading-relaxed hover:bg-slate-900/60 p-1 rounded">
              <span className="text-slate-500 text-[10px] shrink-0 tabular-nums">[{log.timestamp}]</span>
              <span
                className={`text-[9px] px-1.5 py-0.2 rounded border shrink-0 font-bold ${getLevelColor(
                  log.level
                )}`}
              >
                {log.level}
              </span>
              <span className="text-[10px] text-slate-500 font-bold shrink-0">[{log.tag}]</span>
              <span className="text-[11px] text-slate-300 break-all">{log.message}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
};
