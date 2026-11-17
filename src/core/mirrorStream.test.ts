import assert from 'node:assert/strict';
import test from 'node:test';
import { metaSizeMismatch, parseMirrorText, reconnectDelay } from './mirrorStream';

test('解析后端 meta 帧并保留全部字段', () => {
  const frame = parseMirrorText(JSON.stringify({
    type: 'meta', seq: 42, ts: 1700000000, width: 1080, height: 2400,
    fps: 5, degraded: true, mode: 'screencap',
  }));
  assert.equal(frame.kind, 'meta');
  if (frame.kind !== 'meta') return;
  assert.equal(frame.meta.seq, 42);
  assert.equal(frame.meta.width, 1080);
  assert.equal(frame.meta.height, 2400);
  assert.equal(frame.meta.degraded, true);
  assert.equal(frame.meta.mode, 'screencap');
});

test('解析 error / pong 帧，坏 JSON 与未知 type 降级为 unknown', () => {
  const error = parseMirrorText(JSON.stringify({ type: 'error', code: 'MIRROR_LOST', message: '断流' }));
  assert.equal(error.kind, 'error');
  assert.equal(error.kind === 'error' && error.error.message, '断流');
  assert.equal(parseMirrorText(JSON.stringify({ type: 'pong' })).kind, 'pong');
  assert.equal(parseMirrorText('not json').kind, 'unknown');
  assert.equal(parseMirrorText(JSON.stringify({ type: 'wat' })).kind, 'unknown');
  assert.equal(parseMirrorText(JSON.stringify(null)).kind, 'unknown');
});

test('meta 帧字段缺失时补默认值，不产生 NaN', () => {
  const frame = parseMirrorText(JSON.stringify({ type: 'meta' }));
  assert.equal(frame.kind, 'meta');
  if (frame.kind !== 'meta') return;
  assert.equal(frame.meta.seq, 0);
  assert.equal(frame.meta.width, 0);
  assert.equal(frame.meta.degraded, false);
  assert.equal(frame.meta.mode, 'unknown');
  assert.equal(Number.isNaN(frame.meta.fps), false);
});

test('重连退避按 1/2/4/8 秒递增并封顶 8 秒', () => {
  assert.deepEqual([0, 1, 2, 3, 4, 10].map(reconnectDelay), [1000, 2000, 4000, 8000, 8000, 8000]);
  assert.equal(reconnectDelay(-1), 1000);
  assert.equal(reconnectDelay(Number.NaN), 1000);
});

test('尺寸不一致检测用于提示画布与设备分辨率错位', () => {
  const meta = { type: 'meta', seq: 1, ts: 0, width: 720, height: 1600, fps: 5, degraded: false, mode: 'scrcpy' } as const;
  assert.equal(metaSizeMismatch(meta, 720, 1600), false);
  assert.equal(metaSizeMismatch(meta, 1080, 2400), true);
  assert.equal(metaSizeMismatch({ ...meta, width: 0 }, 1080, 2400), false);
});
