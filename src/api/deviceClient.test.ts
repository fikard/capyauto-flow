import test from 'node:test';
import assert from 'node:assert/strict';
import { DeviceApiError, buildMirrorUrl, deviceClient, isTapInside, toNormalized } from './deviceClient';

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

function captureFetch(payload: unknown) {
  const originalFetch = globalThis.fetch;
  const captured: { url: string; init?: RequestInit } = { url: '' };
  globalThis.fetch = ((url: string, init?: RequestInit) => {
    captured.url = url;
    captured.init = init;
    return Promise.resolve(
      new Response(JSON.stringify(payload), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    );
  }) as unknown as typeof fetch;
  return { captured, restore: () => { globalThis.fetch = originalFetch; } };
}

test('deviceClient.verifyRun posts skip list to the verify endpoint', async () => {
  const payload = {
    serial: '',
    started: '2026-11-15T00:00:00',
    deviceOnline: false,
    summary: { passed: 0, failed: 1, skipped: 9, ok: false },
    checks: [],
    hint: '未检测到在线设备',
  };
  const { captured, restore } = captureFetch(payload);
  try {
    const result = await deviceClient.verifyRun(['V3', 'V10']);
    assert.equal(result.summary.failed, 1);
    assert.ok(captured.url.endsWith('/api/verify/run'));
    assert.equal(captured.init?.method, 'POST');
    assert.deepEqual(JSON.parse(captured.init?.body as string), {
      serial: '',
      skip: ['V3', 'V10'],
    });
  } finally {
    restore();
  }
});

test('deviceClient.tap forwards simulation press and dither parameters', async () => {
  const { captured, restore } = captureFetch({ realX: 1, realY: 2 });
  try {
    await deviceClient.tap('s1', 0.5, 0.5, 120, 9, 25);
    assert.deepEqual(JSON.parse(captured.init?.body as string), {
      sessionId: 's1',
      x: 0.5,
      y: 0.5,
      pressMs: 120,
      sigma: 9,
      pressStdev: 25,
    });
  } finally {
    restore();
  }
});

test('deviceClient.ocr forwards optional normalized region and omits it for full screen', async () => {
  const { captured, restore } = captureFetch({ items: [] });
  try {
    await deviceClient.ocr('s1', [0.1, 0.2, 0.9, 0.8]);
    assert.ok(captured.url.endsWith('/api/vision/ocr'));
    assert.deepEqual(JSON.parse(captured.init?.body as string), {
      sessionId: 's1',
      region: [0.1, 0.2, 0.9, 0.8],
    });
    await deviceClient.ocr('s1');
    assert.deepEqual(JSON.parse(captured.init?.body as string), { sessionId: 's1' });
  } finally {
    restore();
  }
});

test('deviceClient.automationStart forwards the full config including previously unwired fields', async () => {
  const { captured, restore } = captureFetch({ status: 'running' });
  try {
    await deviceClient.automationStart('s1', 'bootstrap', 3, ['技能A'], 0.5, 2, {
      maxStageFails: 2,
      travelStamina: 100,
      allowGemTalentBreakthrough: true,
      stageMode: 'lean',
      fastStageCheckEvery: 8,
      account: '风贰',
      accounts: ['风贰', '风零'],
      serverFrom: '闲云野鹤1区',
      serverTo: '闲云野鹤9区',
      serverDryRun: false,
    });
    const body = JSON.parse(captured.init?.body as string);
    assert.equal(body.maxRuns, 3);
    assert.equal(body.allowGemTalentBreakthrough, true);
    assert.equal(body.serverTo, '闲云野鹤9区');
    assert.equal(body.serverDryRun, false);
    assert.deepEqual(body.accounts, ['风贰', '风零']);
  } finally {
    restore();
  }
});

test('network failure surfaces BACKEND_UNREACHABLE instead of raw TypeError', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (() => Promise.reject(new TypeError('Failed to fetch'))) as typeof fetch;
  try {
    await assert.rejects(deviceClient.health(), (exc: unknown) => {
      assert.ok(exc instanceof DeviceApiError);
      assert.equal(exc.code, 'BACKEND_UNREACHABLE');
      return true;
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});
