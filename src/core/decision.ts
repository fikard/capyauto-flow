import { FsmState, SkillCandidate } from '../types/pipeline';

/**
 * Standard Box-Muller transform for Gaussian distribution
 */
export function randomGaussian(
  mean: number,
  stdev: number,
  rng: () => number = Math.random
): number {
  let u1 = rng();
  let u2 = rng();
  // Prevent log(0)
  while (u1 <= Number.EPSILON) {
    u1 = rng();
  }
  const randStdNormal = Math.sqrt(-2.0 * Math.log(u1)) * Math.sin(2.0 * Math.PI * u2);
  return mean + randStdNormal * stdev;
}

/**
 * Generates human-like click coordinates with Gaussian jitter
 */
export function generateHumanClick(
  targetX: number,
  targetY: number,
  stdev: number = 6,
  pressMean: number = 80,
  pressStdev: number = 20,
  rng: () => number = Math.random
) {
  const realX = Math.round(randomGaussian(targetX, stdev, rng));
  const realY = Math.round(randomGaussian(targetY, stdev, rng));
  const pressTime = Math.max(40, Math.round(randomGaussian(pressMean, pressStdev, rng)));
  return { realX, realY, pressTime };
}

/**
 * Generates Quadratic/Cubic Bezier curve points for human swipe gesture simulation
 */
export function generateBezierPoints(
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  steps: number = 10,
  randomOffsetRange: number = 40,
  rng: () => number = Math.random
): [number, number][] {
  // Control point with organic human arc deviation
  const cx = (x1 + x2) / 2 + (rng() * randomOffsetRange * 2 - randomOffsetRange);
  const cy = (y1 + y2) / 2 + (rng() * randomOffsetRange * 2 - randomOffsetRange);

  const points: [number, number][] = [];
  for (let i = 0; i <= steps; i++) {
    const t = i / steps;
    // B(t) = (1-t)^2 * P0 + 2(1-t)t * P1 + t^2 * P2
    const px = Math.round((1 - t) * (1 - t) * x1 + 2 * (1 - t) * t * cx + t * t * x2);
    const py = Math.round((1 - t) * (1 - t) * y1 + 2 * (1 - t) * t * cy + t * t * y2);
    points.push([px, py]);
  }
  return points;
}

/**
 * OCR Decision Engine:
 * Scans candidate skills against ordered priority list.
 * Priority index 0 is top priority.
 * Returns the highest ranked candidate or default fallback index (center card = 1).
 */
export function matchBestSkill(
  candidates: { text: string; id?: string }[],
  priorityList: string[]
): {
  matchedIndex: number;
  highestRank: number;
  isFallback: boolean;
  matchedText?: string;
} {
  let highestRank = 9999;
  let matchedIndex = -1;
  let matchedText: string | undefined;

  candidates.forEach((candidate, idx) => {
    for (let rank = 0; rank < priorityList.length; rank++) {
      const targetSkill = priorityList[rank];
      if (candidate.text.includes(targetSkill)) {
        if (rank < highestRank) {
          highestRank = rank;
          matchedIndex = idx;
          matchedText = targetSkill;
        }
      }
    }
  });

  if (matchedIndex !== -1) {
    return {
      matchedIndex,
      highestRank,
      isFallback: false,
      matchedText,
    };
  }

  // Fallback to center option (index 1 if 3 cards, or 0)
  const fallbackIndex = candidates.length > 1 ? 1 : 0;
  return {
    matchedIndex: fallbackIndex,
    highestRank: 9999,
    isFallback: true,
  };
}

/**
 * Deterministic FSM State Transition
 */
export function getNextFsmState(
  currentState: FsmState,
  event:
    | 'CLICK_STAGE'
    | 'TRIGGER_UPGRADE'
    | 'SKILL_SELECTED'
    | 'BATTLE_WIN'
    | 'BATTLE_LOSE'
    | 'NEXT_STAGE'
    | 'ENTER_GUILD'
    | 'GUILD_FINISHED'
    | 'TRIGGER_POPUP'
    | 'DISMISS_POPUP'
    | 'SWITCH_ACCOUNT'
    | 'ACCOUNT_READY'
): FsmState {
  switch (currentState) {
    case 'IDLE':
      if (event === 'CLICK_STAGE') return 'BATTLE_RUNNING';
      if (event === 'ENTER_GUILD') return 'GUILD_PANEL';
      if (event === 'SWITCH_ACCOUNT') return 'ACCOUNT_SWITCHING';
      if (event === 'TRIGGER_POPUP') return 'POPUP_INTERRUPT';
      return currentState;

    case 'MAIN_CITY':
      if (event === 'CLICK_STAGE') return 'BATTLE_RUNNING';
      if (event === 'ENTER_GUILD') return 'GUILD_PANEL';
      if (event === 'SWITCH_ACCOUNT') return 'ACCOUNT_SWITCHING';
      if (event === 'TRIGGER_POPUP') return 'POPUP_INTERRUPT';
      return currentState;

    case 'BATTLE_RUNNING':
      if (event === 'TRIGGER_UPGRADE') return 'SKILL_CHOICE';
      if (event === 'BATTLE_WIN') return 'BATTLE_VICTORY';
      if (event === 'BATTLE_LOSE') return 'BATTLE_DEFEAT';
      if (event === 'TRIGGER_POPUP') return 'POPUP_INTERRUPT';
      return currentState;

    case 'SKILL_CHOICE':
      if (event === 'SKILL_SELECTED') return 'BATTLE_RUNNING';
      if (event === 'TRIGGER_POPUP') return 'POPUP_INTERRUPT';
      return currentState;

    case 'BATTLE_VICTORY':
      if (event === 'NEXT_STAGE') return 'BATTLE_RUNNING';
      if (event === 'ENTER_GUILD') return 'GUILD_PANEL';
      if (event === 'SWITCH_ACCOUNT') return 'ACCOUNT_SWITCHING';
      return 'MAIN_CITY';

    case 'BATTLE_DEFEAT':
      if (event === 'CLICK_STAGE') return 'BATTLE_RUNNING';
      if (event === 'ENTER_GUILD') return 'GUILD_PANEL';
      if (event === 'SWITCH_ACCOUNT') return 'ACCOUNT_SWITCHING';
      return 'MAIN_CITY';

    case 'GUILD_PANEL':
      if (event === 'GUILD_FINISHED') return 'MAIN_CITY';
      if (event === 'SWITCH_ACCOUNT') return 'ACCOUNT_SWITCHING';
      if (event === 'TRIGGER_POPUP') return 'POPUP_INTERRUPT';
      return currentState;

    case 'POPUP_INTERRUPT':
      if (event === 'DISMISS_POPUP') return 'MAIN_CITY';
      return currentState;

    case 'ACCOUNT_SWITCHING':
      if (event === 'ACCOUNT_READY') return 'MAIN_CITY';
      return currentState;

    default:
      return currentState;
  }
}
