import test from 'node:test';
import assert from 'node:assert/strict';
import { mapPixel, heatColor, loadRecording } from '../src/demo/data.js';

test('map coordinates account for origin, scale and image inversion', () => {
  assert.deepEqual(mapPixel(2, 3, { origin: [1, 1, 0], resolution: .5, height: 10 }), [2, 6]);
  const [x, y] = mapPixel(0, 1, { origin: [0, 0, Math.PI / 2], resolution: 1, height: 10 });
  assert.ok(Math.abs(x - 1) < 1e-10); assert.equal(y, 10);
});
test('thermal palette clamps and supports constant temperature', () => {
  assert.deepEqual(heatColor(-100, 20, 40), heatColor(20, 20, 40));
  assert.deepEqual(heatColor(100, 20, 40), heatColor(40, 20, 40));
  assert.ok(heatColor(20, 20, 20).every(Number.isFinite));
});
test('demo requests only fixed static assets and rejects invalid geometry', async t => {
  const requests = [];
  t.mock.method(globalThis, 'fetch', async url => {
    requests.push(url);
    return { ok: true, json: async () => ({}), arrayBuffer: async () => new ArrayBuffer(0) };
  });
  await assert.rejects(loadRecording(), /지도 형식/);
  assert.equal(requests.length, 4);
  assert.ok(requests.every(url => url.startsWith('/demo-data/')));
});
