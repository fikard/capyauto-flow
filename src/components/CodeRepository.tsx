import React, { useState } from 'react';
import { SCRIPT_FILES, ScriptFile } from '../data/scriptFiles';
import {
  FileCode,
  FolderTree,
  Copy,
  Check,
  Download,
  FolderArchive,
  Search,
  ExternalLink,
  Code2,
} from 'lucide-react';
import JSZip from 'jszip';

export const CodeRepository: React.FC = () => {
  const [selectedPath, setSelectedPath] = useState<string>('core/vision.js');
  const [copied, setCopied] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');

  const currentFile = SCRIPT_FILES.find((f) => f.path === selectedPath) || SCRIPT_FILES[0];

  const handleCopy = () => {
    navigator.clipboard.writeText(currentFile.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownloadSingle = () => {
    const blob = new Blob([currentFile.content], { type: 'text/javascript;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = currentFile.name;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleExportZip = async () => {
    setIsExporting(true);
    try {
      const zip = new JSZip();
      const folder = zip.folder('CapyScript');

      SCRIPT_FILES.forEach((f) => {
        folder?.file(f.path, f.content);
      });

      const content = await zip.generateAsync({ type: 'blob' });
      const url = URL.createObjectURL(content);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'CapyScript_AutoX_Project.zip';
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error('Failed to generate zip:', err);
    } finally {
      setIsExporting(false);
    }
  };

  const filteredFiles = SCRIPT_FILES.filter(
    (f) =>
      f.path.toLowerCase().includes(searchQuery.toLowerCase()) ||
      f.description.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden flex flex-col h-[740px]">
      {/* Top Header */}
      <div className="p-4 border-b border-slate-800 flex flex-wrap items-center justify-between gap-3 bg-slate-950/60">
        <div className="flex items-center gap-2">
          <FolderTree className="w-5 h-5 text-amber-400" />
          <div>
            <h3 className="text-sm font-bold text-slate-100">AutoX.js 工程代码仓库与部署包</h3>
            <p className="text-xs text-slate-400">/sdcard/CapyScript/ 完整模块化工程架构</p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleCopy}
            className="py-1.5 px-3 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium rounded-lg flex items-center gap-1.5 transition-colors cursor-pointer"
          >
            {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
            <span>{copied ? '已复制当前文件' : '复制代码'}</span>
          </button>

          <button
            type="button"
            onClick={handleDownloadSingle}
            className="py-1.5 px-3 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium rounded-lg flex items-center gap-1.5 transition-colors cursor-pointer"
          >
            <Download className="w-3.5 h-3.5" />
            <span>下载单文件</span>
          </button>

          <button
            type="button"
            onClick={handleExportZip}
            disabled={isExporting}
            className="py-1.5 px-3.5 bg-amber-500 hover:bg-amber-400 text-slate-950 text-xs font-bold rounded-lg flex items-center gap-1.5 transition-colors shadow-sm cursor-pointer"
          >
            <FolderArchive className="w-3.5 h-3.5" />
            <span>{isExporting ? '正在打包中...' : '一键导出整套工程 (.ZIP)'}</span>
          </button>
        </div>
      </div>

      {/* Main Split Body */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left File Tree Sidebar */}
        <div className="w-72 bg-slate-950/40 border-r border-slate-800 flex flex-col shrink-0">
          <div className="p-2.5 border-b border-slate-800">
            <div className="relative">
              <Search className="w-3.5 h-3.5 text-slate-500 absolute left-2.5 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="搜索工程文件..."
                className="w-full bg-slate-900 border border-slate-800 rounded-md pl-8 pr-2.5 py-1 text-xs text-slate-200 placeholder:text-slate-600 focus:outline-hidden focus:border-amber-500"
              />
            </div>
          </div>

          <div className="flex-1 overflow-y-auto p-2 space-y-1">
            {filteredFiles.map((file) => {
              const isSelected = file.path === selectedPath;
              return (
                <button
                  key={file.path}
                  type="button"
                  onClick={() => setSelectedPath(file.path)}
                  className={`w-full text-left px-2.5 py-2 rounded-lg text-xs transition-colors flex items-start gap-2 cursor-pointer ${
                    isSelected
                      ? 'bg-amber-500/10 text-amber-300 font-medium border border-amber-500/30'
                      : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
                  }`}
                >
                  <FileCode className={`w-3.5 h-3.5 mt-0.5 shrink-0 ${isSelected ? 'text-amber-400' : 'text-slate-500'}`} />
                  <div className="truncate">
                    <div className="font-mono text-[11px] truncate">{file.path}</div>
                    <div className="text-[10px] text-slate-500 truncate mt-0.5">{file.description}</div>
                  </div>
                </button>
              );
            })}
          </div>

          <div className="p-3 border-t border-slate-800 bg-slate-950 text-[10px] text-slate-500 font-mono">
            共 {SCRIPT_FILES.length} 个核心源文件 · 符合标准 AutoX.js 目录规范
          </div>
        </div>

        {/* Right Code Display Viewport */}
        <div className="flex-1 flex flex-col bg-slate-950 overflow-hidden">
          {/* File Tab Header */}
          <div className="px-4 py-2 border-b border-slate-800 bg-slate-900/60 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs text-amber-300 font-semibold">{currentFile.path}</span>
              <span className="text-slate-600">·</span>
              <span className="text-xs text-slate-400">{currentFile.description}</span>
            </div>
            <div className="text-[10px] font-mono text-slate-500">
              {currentFile.content.split('\n').length} 行
            </div>
          </div>

          {/* Code Viewer with Line Numbers */}
          <div className="flex-1 overflow-auto p-4 font-mono text-xs leading-relaxed text-slate-300 selection:bg-amber-500/20 selection:text-amber-300">
            <pre className="flex">
              {/* Line numbers column */}
              <div className="select-none text-slate-600 pr-4 text-right border-r border-slate-800/60 mr-4 font-mono text-[11px]">
                {currentFile.content.split('\n').map((_, i) => (
                  <div key={i}>{i + 1}</div>
                ))}
              </div>
              {/* Actual code */}
              <div className="flex-1 overflow-x-auto text-[11px]">
                <code>{currentFile.content}</code>
              </div>
            </pre>
          </div>
        </div>
      </div>
    </div>
  );
};
