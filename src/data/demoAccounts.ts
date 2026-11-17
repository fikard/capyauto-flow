import type { AccountItem } from '../types/pipeline';

/**
 * 仅用于「仿真」页签的演示数据 —— 不反映真机状态，不写入后端，也不会被自动化任务消费。
 * 真机模式的账号列表一律来自 /api/accounts（见 useDeviceBridge.accounts）。
 * 保留它是因为 PhoneSimulator 需要一个可交互的调度对象；不要把它当作设备事实源。
 */
export const DEMO_ACCOUNTS: AccountItem[] = [
  {
    id: 'main_01',
    name: '主力大号 (主空间)',
    type: 'clone_user_0',
    userId: 0,
    doneToday: false,
    stamina: 85,
    maxStamina: 100,
    boatTicketsDonated: 2,
    goldDonatedTimes: 3,
    currentStage: '第 32 章 · 沼泽巨石阵',
    lastRunTime: '11:20:00',
    ipResetCount: 1,
    enabled: true,
  },
  {
    id: 'alt_island_02',
    name: '公会供票小号 A (Island 999)',
    type: 'clone_user_999',
    userId: 999,
    doneToday: true,
    stamina: 15,
    maxStamina: 100,
    boatTicketsDonated: 4,
    goldDonatedTimes: 3,
    currentStage: '第 24 章 · 迷雾森林',
    lastRunTime: '10:45:12',
    ipResetCount: 2,
    enabled: true,
  },
  {
    id: 'alt_island_03',
    name: '公会供票小号 B (Shelter 10)',
    type: 'clone_user_999',
    userId: 10,
    doneToday: false,
    stamina: 95,
    maxStamina: 100,
    boatTicketsDonated: 1,
    goldDonatedTimes: 1,
    currentStage: '第 18 章 · 熔岩地窟',
    lastRunTime: '09:12:30',
    ipResetCount: 1,
    enabled: true,
  },
  {
    id: 'alt_phone_04',
    name: '矩阵小号 C (凭证轮换)',
    type: 'phone_auth',
    phone: '13800138000',
    doneToday: false,
    stamina: 100,
    maxStamina: 100,
    boatTicketsDonated: 0,
    goldDonatedTimes: 0,
    currentStage: '第 12 章 · 哥布林荒原',
    lastRunTime: '昨天',
    ipResetCount: 0,
    enabled: true,
  },
];
