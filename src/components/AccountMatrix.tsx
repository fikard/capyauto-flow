import React, { useState } from 'react';
import { AccountItem } from '../types/pipeline';
import {
  Users,
  CheckCircle2,
  Circle,
  Play,
  RotateCcw,
  Plus,
  Radio,
  Smartphone,
  Cpu,
  Trash2,
  Check,
  Ship,
  Coins,
  ShieldCheck,
} from 'lucide-react';

interface AccountMatrixProps {
  accounts: AccountItem[];
  activeAccountId: string;
  onSelectAccount: (acc: AccountItem) => void;
  onToggleAccountDone: (id: string) => void;
  onAddAccount: (acc: Omit<AccountItem, 'id' | 'boatTicketsDonated' | 'goldDonatedTimes' | 'currentStage' | 'ipResetCount'>) => void;
  onResetAllDaily: () => void;
  onSimulateIpReset: () => void;
  isResettingIp: boolean;
}

export const AccountMatrix: React.FC<AccountMatrixProps> = ({
  accounts,
  activeAccountId,
  onSelectAccount,
  onToggleAccountDone,
  onAddAccount,
  onResetAllDaily,
  onSimulateIpReset,
  isResettingIp,
}) => {
  const [showAddModal, setShowAddModal] = useState(false);
  const [newAccName, setNewAccName] = useState('');
  const [newAccType, setNewAccType] = useState<AccountItem['type']>('clone_user_999');
  const [newUserId, setNewUserId] = useState(999);
  const [newPhone, setNewPhone] = useState('');

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newAccName.trim()) return;

    onAddAccount({
      name: newAccName.trim(),
      type: newAccType,
      userId: newAccType === 'clone_user_999' ? Number(newUserId) : 0,
      phone: newAccType === 'phone_auth' ? newPhone : undefined,
      doneToday: false,
      stamina: 100,
      maxStamina: 100,
      enabled: true,
    });

    setNewAccName('');
    setShowAddModal(false);
  };

  const totalBoatTickets = accounts.reduce((acc, curr) => acc + curr.boatTicketsDonated, 0);
  const totalGoldDonations = accounts.reduce((acc, curr) => acc + curr.goldDonatedTimes, 0);
  const completedAccounts = accounts.filter((a) => a.doneToday).length;

  return (
    <div className="space-y-4">
      {/* Top Aggregation Strip */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
        <div className="p-3 bg-slate-900 rounded-xl border border-slate-800">
          <div className="text-[10px] text-slate-400 font-medium">账号矩阵规模</div>
          <div className="text-xl font-bold font-mono text-slate-100 mt-1">
            {completedAccounts} <span className="text-xs text-slate-500 font-sans font-normal">/ {accounts.length} 账号就绪</span>
          </div>
        </div>

        <div className="p-3 bg-slate-900 rounded-xl border border-slate-800">
          <div className="text-[10px] text-cyan-400 font-medium flex items-center gap-1">
            <Ship className="w-3.5 h-3.5" />
            <span>今日累计供奉公会船票</span>
          </div>
          <div className="text-xl font-bold font-mono text-cyan-300 mt-1">
            {totalBoatTickets} <span className="text-xs text-slate-500 font-sans font-normal">张已提交</span>
          </div>
        </div>

        <div className="p-3 bg-slate-900 rounded-xl border border-slate-800">
          <div className="text-[10px] text-amber-400 font-medium flex items-center gap-1">
            <Coins className="w-3.5 h-3.5" />
            <span>公会金币建设贡献</span>
          </div>
          <div className="text-xl font-bold font-mono text-amber-300 mt-1">
            {totalGoldDonations * 100} <span className="text-xs text-slate-500 font-sans font-normal">点公会经验</span>
          </div>
        </div>

        <div className="p-3 bg-slate-900 rounded-xl border border-slate-800 flex flex-col justify-between">
          <div className="text-[10px] text-emerald-400 font-medium flex items-center gap-1">
            <Radio className="w-3.5 h-3.5" />
            <span>基站飞行模式 IP 跳跃</span>
          </div>
          <button
            type="button"
            onClick={onSimulateIpReset}
            disabled={isResettingIp}
            className={`py-1.5 px-3 rounded-lg text-xs font-semibold flex items-center justify-center gap-1.5 transition-colors cursor-pointer ${
              isResettingIp
                ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
                : 'bg-slate-800 hover:bg-slate-700 text-slate-200'
            }`}
          >
            {isResettingIp ? (
              <>
                <Radio className="w-3.5 h-3.5 animate-spin text-amber-400" />
                <span>飞行模式重置蜂窝IP中 (5s)...</span>
              </>
            ) : (
              <>
                <Radio className="w-3.5 h-3.5 text-emerald-400" />
                <span>执行一次动态 IP 重置</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Main Account Matrix Table */}
      <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
        <div className="p-4 border-b border-slate-800 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Users className="w-4 h-4 text-amber-400" />
            <div>
              <h3 className="text-sm font-bold text-slate-100">单机多账号隔离调度矩阵</h3>
              <p className="text-xs text-slate-400">支持 Android User 0/User 999 炼妖壶分身冷启动与凭证循环</p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onResetAllDaily}
              className="py-1.5 px-3 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium rounded-lg transition-colors cursor-pointer"
            >
              重置今日指标
            </button>
            <button
              type="button"
              onClick={() => setShowAddModal(true)}
              className="py-1.5 px-3 bg-amber-500 hover:bg-amber-400 text-slate-950 text-xs font-bold rounded-lg transition-colors flex items-center gap-1 cursor-pointer"
            >
              <Plus className="w-3.5 h-3.5" />
              <span>添加账号</span>
            </button>
          </div>
        </div>

        {/* Table List */}
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-950/60 text-slate-400 font-mono border-b border-slate-800">
              <tr>
                <th className="py-2.5 px-4">当前调度</th>
                <th className="py-2.5 px-4">账号标识 / 备注</th>
                <th className="py-2.5 px-4">系统隔离策略 (Android Space)</th>
                <th className="py-2.5 px-4">体力 (游历)</th>
                <th className="py-2.5 px-4">公会船票</th>
                <th className="py-2.5 px-4">金币捐献</th>
                <th className="py-2.5 px-4">当前关卡</th>
                <th className="py-2.5 px-4 text-center">今日状态</th>
                <th className="py-2.5 px-4 text-right">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {accounts.map((acc) => {
                const isCurrentActive = activeAccountId === acc.id;
                return (
                  <tr
                    key={acc.id}
                    className={`hover:bg-slate-800/40 transition-colors ${
                      isCurrentActive ? 'bg-amber-950/20' : ''
                    }`}
                  >
                    <td className="py-3 px-4">
                      {isCurrentActive ? (
                        <span className="inline-flex items-center gap-1 text-[10px] font-mono text-amber-400 font-bold bg-amber-500/10 px-2 py-0.5 rounded border border-amber-500/30">
                          <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-ping"></span>
                          RUNNING
                        </span>
                      ) : (
                        <span className="text-slate-600 font-mono text-[11px]">-</span>
                      )}
                    </td>

                    <td className="py-3 px-4 font-medium text-slate-200">
                      <div>{acc.name}</div>
                      <div className="text-[10px] font-mono text-slate-500">{acc.id}</div>
                    </td>

                    <td className="py-3 px-4">
                      {acc.type === 'clone_user_0' && (
                        <span className="text-[11px] font-mono text-indigo-300 bg-indigo-950/50 px-2 py-0.5 rounded border border-indigo-900/50">
                          User 0 (主空间)
                        </span>
                      )}
                      {acc.type === 'clone_user_999' && (
                        <span className="text-[11px] font-mono text-cyan-300 bg-cyan-950/50 px-2 py-0.5 rounded border border-cyan-900/50">
                          User {acc.userId || 999} (Island炼妖壶)
                        </span>
                      )}
                      {acc.type === 'phone_auth' && (
                        <span className="text-[11px] font-mono text-emerald-300 bg-emerald-950/50 px-2 py-0.5 rounded border border-emerald-900/50">
                          凭证注销轮换 ({acc.phone?.slice(-4)}尾号)
                        </span>
                      )}
                      {acc.type === 'guest' && (
                        <span className="text-[11px] font-mono text-amber-300 bg-amber-950/50 px-2 py-0.5 rounded border border-amber-900/50">
                          游客设备 UUID
                        </span>
                      )}
                    </td>

                    <td className="py-3 px-4 font-mono">
                      <span className="text-slate-300">{acc.stamina}</span>
                      <span className="text-slate-600">/{acc.maxStamina}</span>
                    </td>

                    <td className="py-3 px-4 font-mono text-cyan-400 font-semibold">
                      +{acc.boatTicketsDonated} 张
                    </td>

                    <td className="py-3 px-4 font-mono text-amber-400">
                      {acc.goldDonatedTimes}/3 次
                    </td>

                    <td className="py-3 px-4 text-slate-300 font-mono">
                      {acc.currentStage}
                    </td>

                    <td className="py-3 px-4 text-center">
                      <button
                        type="button"
                        onClick={() => onToggleAccountDone(acc.id)}
                        className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-medium transition-colors cursor-pointer ${
                          acc.doneToday
                            ? 'bg-emerald-950/50 text-emerald-400 border border-emerald-800'
                            : 'bg-slate-800 text-slate-400 hover:text-slate-200'
                        }`}
                      >
                        {acc.doneToday ? (
                          <>
                            <Check className="w-3 h-3" />
                            <span>今日已跑完</span>
                          </>
                        ) : (
                          <>
                            <Circle className="w-2.5 h-2.5 text-slate-500" />
                            <span>待调度</span>
                          </>
                        )}
                      </button>
                    </td>

                    <td className="py-3 px-4 text-right">
                      <button
                        type="button"
                        onClick={() => onSelectAccount(acc)}
                        className="py-1 px-2.5 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs rounded transition-colors font-medium cursor-pointer"
                      >
                        模拟切换实机
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Add Account Modal */}
      {showAddModal && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-xs flex items-center justify-center p-4 z-50">
          <div className="bg-slate-900 border border-slate-700 rounded-xl p-5 w-full max-w-md shadow-2xl animate-in fade-in zoom-in-95">
            <h4 className="text-sm font-bold text-slate-100 mb-3">添加小号至自动化调度矩阵</h4>

            <form onSubmit={handleCreate} className="space-y-3">
              <div>
                <label className="block text-xs text-slate-400 mb-1">账号名称 / 备注</label>
                <input
                  type="text"
                  required
                  value={newAccName}
                  onChange={(e) => setNewAccName(e.target.value)}
                  placeholder="例: 公会供票号 05 (Island工作区)"
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-100 focus:outline-hidden focus:border-amber-500"
                />
              </div>

              <div>
                <label className="block text-xs text-slate-400 mb-1">Android 隔离模式</label>
                <select
                  value={newAccType}
                  onChange={(e) => setNewAccType(e.target.value as AccountItem['type'])}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-100 focus:outline-hidden focus:border-amber-500"
                >
                  <option value="clone_user_999">系统应用分身 / 炼妖壶 (User 999)</option>
                  <option value="clone_user_0">主用户空间 (User 0)</option>
                  <option value="phone_auth">游戏内账号密码注销轮换</option>
                  <option value="guest">游客 UUID 轮换</option>
                </select>
              </div>

              {newAccType === 'clone_user_999' && (
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Android 用户空间 ID</label>
                  <input
                    type="number"
                    value={newUserId}
                    onChange={(e) => setNewUserId(Number(e.target.value))}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-100 font-mono"
                  />
                  <p className="text-[10px] text-slate-500 mt-0.5">小米双开一般为 999，Shelter/炼妖壶一般为 10 或 11</p>
                </div>
              )}

              {newAccType === 'phone_auth' && (
                <div>
                  <label className="block text-xs text-slate-400 mb-1">登录手机号</label>
                  <input
                    type="text"
                    value={newPhone}
                    onChange={(e) => setNewPhone(e.target.value)}
                    placeholder="13800000000"
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-100 font-mono"
                  />
                </div>
              )}

              <div className="flex items-center justify-end gap-2 pt-3 border-t border-slate-800">
                <button
                  type="button"
                  onClick={() => setShowAddModal(false)}
                  className="py-1.5 px-3 bg-slate-800 text-slate-300 text-xs rounded-lg hover:bg-slate-700 cursor-pointer"
                >
                  取消
                </button>
                <button
                  type="submit"
                  className="py-1.5 px-4 bg-amber-500 hover:bg-amber-400 text-slate-950 text-xs font-bold rounded-lg cursor-pointer"
                >
                  确认添加
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
