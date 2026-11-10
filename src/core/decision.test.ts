import test from 'node:test';
import assert from 'node:assert/strict';
import {
  randomGaussian,
  generateHumanClick,
  generateBezierPoints,
  matchBestSkill,
  getNextFsmState,
} from './decision';

test('randomGaussian generates numbers centered around mean', () => {
  const mean = 100;
  const stdev = 5;
  let sum = 0;
  const iterations = 500;
  for (let i = 0; i < iterations; i++) {
    sum += randomGaussian(mean, stdev);
  }
  const avg = sum / iterations;
  // Should be close to mean
  assert.ok(Math.abs(avg - mean) < 1.5, `Average ${avg} should be within 1.5 of ${mean}`);
});

test('generateHumanClick returns bounded coordinates and non-zero press time', () => {
  const targetX = 360;
  const targetY = 540;
  const click = generateHumanClick(targetX, targetY, 6, 80, 20);
  
  assert.ok(typeof click.realX === 'number');
  assert.ok(typeof click.realY === 'number');
  assert.ok(click.pressTime >= 40, 'Press time should be at least 40ms');
  assert.ok(Math.abs(click.realX - targetX) < 50, 'Jitter should be within reasonable bounds');
  assert.ok(Math.abs(click.realY - targetY) < 50, 'Jitter should be within reasonable bounds');
});

test('generateBezierPoints returns smooth multi-step trajectory', () => {
  const points = generateBezierPoints(100, 200, 500, 600, 8);
  assert.equal(points.length, 9); // steps + 1
  assert.deepEqual(points[0], [100, 200]); // Start point
  assert.deepEqual(points[points.length - 1], [500, 600]); // End point
});

test('matchBestSkill picks highest priority ranked skill correctly', () => {
  const priorityList = [
    '越战越硬',
    '伤害减免',
    '普攻减免',
    '格挡率',
    '冰刺',
    '冰冻精通',
  ];

  // Candidates: Card 0 is 冰刺 (rank 4), Card 1 is 伤害减免 (rank 1), Card 2 is 火焰冲击 (no match)
  const candidates = [
    { text: '技能：冰刺 lv1' },
    { text: '技能：伤害减免 15%' },
    { text: '技能：火焰冲击 20%' },
  ];

  const result = matchBestSkill(candidates, priorityList);
  assert.equal(result.matchedIndex, 1, 'Should choose index 1 (伤害减免) as it has higher rank (1 vs 4)');
  assert.equal(result.highestRank, 1);
  assert.equal(result.isFallback, false);
  assert.equal(result.matchedText, '伤害减免');
});

test('matchBestSkill falls back to center card when no skill matches priority list', () => {
  const priorityList = ['越战越硬', '伤害减免'];
  const candidates = [
    { text: '闪电链' },
    { text: '风刃术' },
    { text: '陨石术' },
  ];

  const result = matchBestSkill(candidates, priorityList);
  assert.equal(result.matchedIndex, 1, 'Should fall back to center card (index 1)');
  assert.equal(result.isFallback, true);
});

test('getNextFsmState handles transitions cleanly', () => {
  assert.equal(getNextFsmState('IDLE', 'CLICK_STAGE'), 'BATTLE_RUNNING');
  assert.equal(getNextFsmState('BATTLE_RUNNING', 'TRIGGER_UPGRADE'), 'SKILL_CHOICE');
  assert.equal(getNextFsmState('SKILL_CHOICE', 'SKILL_SELECTED'), 'BATTLE_RUNNING');
  assert.equal(getNextFsmState('BATTLE_RUNNING', 'BATTLE_WIN'), 'BATTLE_VICTORY');
  assert.equal(getNextFsmState('BATTLE_VICTORY', 'ENTER_GUILD'), 'GUILD_PANEL');
  assert.equal(getNextFsmState('GUILD_PANEL', 'GUILD_FINISHED'), 'MAIN_CITY');
  assert.equal(getNextFsmState('MAIN_CITY', 'TRIGGER_POPUP'), 'POPUP_INTERRUPT');
  assert.equal(getNextFsmState('POPUP_INTERRUPT', 'DISMISS_POPUP'), 'MAIN_CITY');
});
