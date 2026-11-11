import test from 'node:test';
import assert from 'node:assert/strict';
import { buildMirrorUrl, isTapInside, toNormalized } from './deviceClient';

test('buildMirrorUrl converts http base to ws and keeps query', () => {
  assert.equal(
    buildMirrorUrl('s1', 'http://127.0.0.1:8084'),
    'ws://127.0.0.1:8084/ws/mirror?sessionId=s1'
  );
  assert.equal(
    buildMirrorUrl('a b', 'https://example.test'),
    'wss://example.test/ws/mirror?sessionId=a%20b'
  );
});

test('toNormalized maps pointer offsets and rejects out-of-range', () => {
  assert.deepEqual(toNormalized(500, 1000, 1000, 2000), { x: 0.5, y: 0.5 });
  assert.deepEqual(toNormalized(-10, 2500, 1000, 2000), { x: 0, y: 1 });
});

test('isTapInside only accepts the unit square', () => {
  assert.equal(isTapInside(0, 0), true);
  assert.equal(isTapInside(1, 1), true);
  assert.equal(isTapInside(-0.01, 0.5), false);
  assert.equal(isTapInside(1.01, 0.5), false);
  assert.equal(isTapInside(Number.NaN, 0.5), false);
});
