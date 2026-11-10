import React, { useState } from 'react';
import {
  Smartphone,
  Terminal,
  CheckCircle2,
  Copy,
  Check,
  ShieldAlert,
  AlertTriangle,
  FolderOpen,
  Volume2,
} from 'lucide-react';

export const DeploymentGuide: React.FC = () => {
  const [copiedCmd, setCopiedCmd] = useState<string | null>(null);

  const copyToClipboard = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopiedCmd(id);
    setTimeout(() => setCopiedCmd(null), 2000);
  };

  const adbPushCmd = `# 1. 开启手机无线调试并配对连接
adb connect 192.168.1.105:5555

# 2. 在手机内部存储创建工程根目录
adb shell mkdir -p /sdcard/CapyScript/

# 3. 将本地解压的代码目录整包推送至手机
adb push ./CapyScript/* /sdcard/CapyScript/`;

  const shellTestCmd = `# 免Root启动分身应用 (User 999 炼妖壶/应用双开)
adb shell am start --user 999 -n com.game.capy/com.unity3d.player.UnityPlayerActivity

# 杀掉应用释放内存
adb shell am force-stop com.game.capy`;

  return (
    <div className="space-y-5">
      {/* Step by step cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Step 1: Environment */}
        <div className="p-4 bg-slate-900 rounded-xl border border-slate-800 space-y-3">
          <div className="flex items-center gap-2">
            <span className="w-6 h-6 rounded-full bg-amber-500/20 text-amber-300 font-mono font-bold text-xs flex items-center justify-center border border-amber-500/40">
              1
            </span>
            <h4 className="text-sm font-bold text-slate-100">安装手机宿主与离线推理插件</h4>
          </div>
          <p className="text-xs text-slate-400">
            在单台目标安卓机上部署，无需连接电脑常驻。
          </p>
          <ul className="text-xs text-slate-300 space-y-2 list-disc list-inside">
            <li>
              <span className="font-semibold text-slate-100">AutoX.js v6.6+</span>: 开源安卓自动化宿主环境。
            </li>
            <li>
              <span className="font-semibold text-slate-100">PaddleOCR-NCNN 扩展包</span>: 本地离线高并发文本识别（避免云端 OCR 网络延迟与计费）。
            </li>
          </ul>
        </div>

        {/* Step 2: Permissions */}
        <div className="p-4 bg-slate-900 rounded-xl border border-slate-800 space-y-3">
          <div className="flex items-center gap-2">
            <span className="w-6 h-6 rounded-full bg-amber-500/20 text-amber-300 font-mono font-bold text-xs flex items-center justify-center border border-amber-500/40">
              2
            </span>
            <h4 className="text-sm font-bold text-slate-100">安卓关键权限授权清单</h4>
          </div>
          <div className="space-y-1.5 text-xs">
            <div className="p-2 rounded bg-slate-950 border border-slate-800 flex items-center justify-between">
              <span className="text-slate-200">无障碍服务 (Accessibility)</span>
              <span className="text-[10px] text-emerald-400 font-mono">必选</span>
            </div>
            <div className="p-2 rounded bg-slate-950 border border-slate-800 flex items-center justify-between">
              <span className="text-slate-200">媒体投影截屏 (MediaProjection)</span>
              <span className="text-[10px] text-emerald-400 font-mono">必选 (勾选不再提示)</span>
            </div>
            <div className="p-2 rounded bg-slate-950 border border-slate-800 flex items-center justify-between">
              <span className="text-slate-200">显示悬浮窗 (Overlay Window)</span>
              <span className="text-[10px] text-cyan-400 font-mono">监控日志悬浮窗</span>
            </div>
            <div className="p-2 rounded bg-slate-950 border border-slate-800 flex items-center justify-between">
              <span className="text-slate-200">忽略电池优化 / 白名单无限制</span>
              <span className="text-[10px] text-amber-400 font-mono">防息屏杀进程</span>
            </div>
          </div>
        </div>
      </div>

      {/* ADB Commands Helper */}
      <div className="p-5 bg-slate-900 rounded-xl border border-slate-800 space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Terminal className="w-4 h-4 text-amber-400" />
            <h4 className="text-sm font-bold text-slate-100">无线 ADB 一键部署指令</h4>
          </div>
          <button
            type="button"
            onClick={() => copyToClipboard(adbPushCmd, 'push')}
            className="py-1 px-2.5 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs rounded font-medium flex items-center gap-1 cursor-pointer"
          >
            {copiedCmd === 'push' ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
            <span>{copiedCmd === 'push' ? '已复制指令' : '复制命令'}</span>
          </button>
        </div>

        <div className="p-3 bg-slate-950 rounded-lg border border-slate-800 font-mono text-xs text-slate-300 overflow-x-auto leading-relaxed">
          <pre>{adbPushCmd}</pre>
        </div>
      </div>

      {/* Emergency Stop & Safe Guard */}
      <div className="p-4 bg-amber-950/20 border border-amber-900/50 rounded-xl flex items-start gap-3">
        <AlertTriangle className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
        <div className="text-xs text-slate-300 space-y-1">
          <div className="font-bold text-amber-300">实机运行与紧急制动 (急停按键)</div>
          <p className="text-slate-400 leading-normal">
            当脚本在手机运行过程中发生意外手势漂移或死循环时，AutoX.js 预置了物理急停开关：<strong className="text-slate-200">连续按两次手机【音量下键】</strong>，系统将立即强制杀死所有自动化执行线程并释放无障碍手势监听。
          </p>
        </div>
      </div>
    </div>
  );
};
