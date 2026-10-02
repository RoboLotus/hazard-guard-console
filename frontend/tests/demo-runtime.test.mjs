import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import { createRecordedFetch, recordedRead } from '../src/demo/runtime.js';
import { populateRecordedScene } from '../src/demo/populateScene.js';
const data = {
  manifest: { session: 'saved', world: 'facility_map', fingerprint: 'abc', equipment: [],
    map: { width: 2, height: 2, resolution: .05, origin: [0, 0, 0] }, temperatureMin: 20, temperatureMax: 40 },
  points: new Float32Array([1, 2, 3, 4, 5, 6]), colors: new Uint8Array([255, 0, 0, 0, 255, 0]),
  thermal: { indices: [1], temperatures: [40] },
};
test('recorded API cannot enable robot controls or fabricate live telemetry', () => {
  const mode = recordedRead(data, '/api/v1/system/mode');
  assert.equal(mode.control_enabled, false); assert.equal(mode.navigation_ready, false);
  const media = recordedRead(data, '/api/v1/media/status');
  assert.equal(media.rgb.available, false); assert.equal(media.thermal.available, false);
  assert.equal(media.map.recorded, true);
  assert.equal(recordedRead(data, '/api/health'), undefined);
});
test('all writes, remote origins and unknown API reads never reach network', async () => {
  const requests = [];
  const fetch = createRecordedFetch(data, async (...args) => { requests.push(args); return new Response('image'); }, 'http://localhost:5179');
  for (const method of ['POST', 'PUT', 'PATCH', 'DELETE']) {
    assert.equal((await fetch('/api/v1/commands/patrol', { method })).status, 403);
    assert.equal((await fetch(new Request('http://localhost:5179/api/v1/system/mode', { method }))).status, 403);
  }
  assert.equal((await fetch('http://robot:8000/api/health')).status, 403);
  assert.equal((await fetch('/api/v1/unknown')).status, 503);
  assert.equal((await fetch('/api/v1/system/mode')).status, 200);
  assert.equal(requests.length, 0);
  await fetch('/api/v1/media/map');
  assert.equal(requests[0][0], '/demo-data/map.png');
});
test('recorded thermal values use canonical indices in original renderer', () => {
  const scene = { geometry: new THREE.BufferGeometry(), baseGeometry: new THREE.BufferGeometry(),
    material: { uniforms: { uConfidenceOpacityEnabled: {}, uTemperatureMin: {}, uTemperatureMax: {} } }, dynamicPoints: {} };
  populateRecordedScene(scene, data, 'thermal');
  assert.deepEqual([...scene.geometry.getAttribute('position').array], [4, 5, 6]);
  assert.deepEqual([...scene.geometry.getAttribute('temperature').array], [40]);
  assert.equal(scene.baseGeometry.getAttribute('position').count, 2);
  assert.equal(scene.dynamicPoints.visible, false);
  scene.geometry.dispose(); scene.baseGeometry.dispose();
});
