import React from 'react';
import { PipelineConfig } from '../types/pipeline';
import {
  ShieldAlert,
  Flame,
  Radio,
  EyeOff,
  BatteryMedium,
  CheckCircle,
  AlertTriangle,
  Zap,
  Cpu,
  Lock,
} from 'lucide-react';

interface AntiBanTelemetryProps {
  config: PipelineConfig;
  onUpdateConfig: (newConfig: PipelineConfig) => void;
  interceptedCount: number;
}

export const AntiBanTelemetry: React.FC<AntiBanTelemetryProps> = ({
  config,
  onUpdateConfig,
  interceptedCount,
}) => {
  return (
    <div className="space-y-4">
      {/* Risk Dimension Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {/* Anti-Fingerprint IP Rotation */}
        <div className="p-4 bg-slate-900 rounded-xl border border-slate-800 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-slate-100 flex items-center gap-1.5">
                <Radio className="w-4 h-4 text-emerald-400" />
                <span>动态蜂窝 IP 轮换 (防矩阵关联)</span>
              </span>
              <span className="text-[10px] font-mono text-emerald-400 bg-emerald-950/50 px-2 py-0.5 rounded border border-emerald-900/50">
                ACTIVE
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-2">
              同一 Wi-Fi 下多个账号集中向公会提交船票易被标记为“工作室群控”。每个账号跑完后自动触发 5s 飞行模式，重置运营商公网 IP。
            </p>
          </div>
          <div className="mt-4 pt-3 border-t border-slate-800 text-[11px] font-mono text-slate-500">
            广播指令: am broadcast -a android.intent.action.AIRPLANE_MODE
          </div>
        </div>

        {/* Watchdog Daemon Thread */}
        <div className="p-4 bg-slate-900 rounded-xl border border-slate-800 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-slate-100 flex items-center gap-1.5">
                <ShieldAlert className="w-4 h-4 text-amber-400" />
                <span>守护子线程 (弹窗自愈)</span>
              </span>
              <span className="text-[10px] font-mono text-amber-400 bg-amber-950/50 px-2 py-0.5 rounded border border-amber-900/50">
                2s 轮询守护
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-2">
              通过 <code className="text-amber-300 font-mono">threads.start()</code> 独立于主流程运行，自动拦截并消除“648限时首充、网络断开重试、残忍拒绝”等意外阻断。
            </p>
          </div>
          <div className="mt-4 pt-3 border-t border-slate-800 flex items-center justify-between text-[11px]">
            <span className="text-slate-400">已自动消除弹窗:</span>
            <span className="font-mono text-amber-400 font-bold">{interceptedCount} 次拦截</span>
          </div>
        </div>

        {/* Thermal Throttling & Battery */}
        <div className="p-4 bg-slate-900 rounded-xl border border-slate-800 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-slate-100 flex items-center gap-1.5">
                <Flame className="w-4 h-4 text-cyan-400" />
                <span>硬件降温与长时保活</span>
              </span>
              <span className="text-[10px] font-mono text-cyan-400 bg-cyan-950/50 px-2 py-0.5 rounded border border-cyan-900/50">
                0% 亮度暗屏
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-2">
              长时间自动化会导致手机发热降频被杀进程。启动后自动设为 0 亮度，游戏锁 30fps，挂起唤醒锁并在全部跑完后自动释放休眠。
            </p>
          </div>
          <div className="mt-4 pt-3 border-t border-slate-800 text-[11px] font-mono text-slate-500">
            唤醒锁: device.keepScreenOn(3600*1000)
          </div>
        </div>
      </div>

      {/* Security Switches Checklist */}
      <div className="p-5 bg-slate-900 rounded-xl border border-slate-800">
        <h4 className="text-xs font-bold text-slate-100 mb-3">风控鲁棒性策略总开关 (Config Toggles)</h4>
        
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
          <label className="flex items-center justify-between p-3 rounded-lg bg-slate-950 border border-slate-800 cursor-pointer">
            <div>
              <div className="font-semibold text-slate-200">启用账号间飞行模式切网 (IP跳跃)</div>
              <div className="text-[11px] text-slate-500 mt-0.5">杜绝同局域网IP被批量查封</div>
            </div>
            <input
              type="checkbox"
              checked={config.enableAirplaneModeIpReset}
              onChange={(e) =>
                onUpdateConfig({ ...config, enableAirplaneModeIpReset: e.target.checked })
              }
              className="accent-amber-500 rounded cursor-pointer"
            />
          </label>

          <label className="flex items-center justify-between p-3 rounded-lg bg-slate-950 border border-slate-800 cursor-pointer">
            <div>
              <div className="font-semibold text-slate-200">暗屏节电模式 (Brightness 0)</div>
              <div className="text-[11px] text-slate-500 mt-0.5">控制发热避免手机CPU降频卡死</div>
            </div>
            <input
              type="checkbox"
              checked={config.enableScreenDarkening}
              onChange={(e) =>
                onUpdateConfig({ ...config, enableScreenDarkening: e.target.checked })
              }
              className="accent-amber-500 rounded cursor-pointer"
            />
          </label>

          <label className="flex items-center justify-between p-3 rounded-lg bg-slate-950 border border-slate-800 cursor-pointer">
            <div>
              <div className="font-semibold text-slate-200">全局弹窗守护子线程 (Watchdog Daemon)</div>
              <div className="text-[11px] text-slate-500 mt-0.5">自动消除关闭、跳过、残忍拒绝等阻断弹窗</div>
            </div>
            <input
              type="checkbox"
              checked={config.enableWatchdogThread}
              onChange={(e) =>
                onUpdateConfig({ ...config, enableWatchdogThread: e.target.checked })
              }
              className="accent-amber-500 rounded cursor-pointer"
            />
          </label>

          <label className="flex items-center justify-between p-3 rounded-lg bg-slate-950 border border-slate-800 cursor-pointer">
            <div>
              <div className="font-semibold text-slate-200">战败自动熔断与降级 (Fail Recovery)</div>
              <div className="text-[11px] text-slate-500 mt-0.5">战力不足时自动返回主城，不无限死循环</div>
            </div>
            <input
              type="checkbox"
              checked={true}
              readOnly
              className="accent-amber-500 rounded cursor-pointer"
            />
          </label>
        </div>
      </div>
    </div>
  );
};
