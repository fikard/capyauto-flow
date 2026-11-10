export type FsmState =
  | 'IDLE'
  | 'MAIN_CITY'
  | 'BATTLE_RUNNING'
  | 'SKILL_CHOICE'
  | 'BATTLE_VICTORY'
  | 'BATTLE_DEFEAT'
  | 'GUILD_PANEL'
  | 'POPUP_INTERRUPT'
  | 'ACCOUNT_SWITCHING';

export type AccountType = 'clone_user_0' | 'clone_user_999' | 'phone_auth' | 'guest';

export interface AccountItem {
  id: string;
  name: string;
  type: AccountType;
  userId?: number;
  phone?: string;
  doneToday: boolean;
  stamina: number;
  maxStamina: number;
  boatTicketsDonated: number;
  goldDonatedTimes: number;
  currentStage: string;
  lastRunTime?: string;
  ipResetCount: number;
  enabled: boolean;
}

export interface SkillCandidate {
  id: string;
  name: string;
  category: 'survival' | 'offense' | 'elemental' | 'utility';
  desc: string;
  bounds: {
    left: number;
    top: number;
    right: number;
    bottom: number;
  };
  matchedPriorityRank?: number; // 0 is highest
  confidence: number;
}

export interface TouchEventRecord {
  id: string;
  timestamp: string;
  targetX: number;
  targetY: number;
  realX: number;
  realY: number;
  pressTime: number;
  stdev: number;
  label: string;
}

export interface LogMessage {
  id: string;
  timestamp: string;
  level: 'INFO' | 'WARN' | 'ERROR' | 'FSM' | 'OCR' | 'TOUCH' | 'GUARD';
  tag: string;
  message: string;
}

export interface PipelineConfig {
  skillPriorityList: string[];
  gaussianStdev: number;
  pressDurationMean: number;
  pressDurationStdev: number;
  reactionMinDelay: number;
  reactionMaxDelay: number;
  enableAirplaneModeIpReset: boolean;
  enableScreenDarkening: boolean;
  enableWatchdogThread: boolean;
  autoSweepDaily: boolean;
  maxDailyBoatTickets: number;
  maxDefeatRetries: number;
}
