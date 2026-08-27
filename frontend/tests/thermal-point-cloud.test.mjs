import assert from "node:assert/strict";
import test from "node:test";
import * as THREE from "three";

import { parsePointCloudPacket } from "../src/pointCloud.js";
import {
  DYNAMIC_DELTA,
  STATIC_THERMAL_DELTA,
  ThermalGeometryBuffers,
  parseThermalDelta,
  thermalDeltaAction,
} from "../src/thermalPointCloud.js";

const encoder = new TextEncoder();

function snapshotPacket(records, sequence = 4) {
  const packet = new ArrayBuffer(24 + records.length * 48);
  const bytes = new Uint8Array(packet);
  bytes.set(encoder.encode("HGPC"), 0);
  const view = new DataView(packet);
  view.setUint8(4, 3); view.setUint8(5, 1);
  view.setUint32(8, 1, true); view.setUint32(12, records.length, true);
  view.setBigUint64(16, 1000n, true);
  records.forEach((record, index) => {
    const at = 24 + index * 48;
    record.position.forEach((value, axis) => view.setFloat32(at + axis * 4, value, true));
    view.setUint8(at + 12, record.color?.[0] ?? 1); view.setUint8(at + 13, record.color?.[1] ?? 2); view.setUint8(at + 14, record.color?.[2] ?? 3); view.setUint8(at + 15, 255);
    view.setFloat32(at + 16, record.temperature, true); view.setFloat32(at + 20, record.confidence, true);
    view.setUint8(at + 24, record.kind);
    record.key.forEach((value, axis) => view.setInt32(at + 28 + axis * 4, value, true));
    view.setFloat64(at + 40, sequence, true);
  });
  return packet;
}

function deltaPacket({ type, sequence, base = sequence - 1, session = "s", fingerprint = "f", staticUpdates = [], created = [], updated = [], deleted = [] }) {
  const sessionBytes = encoder.encode(session); const fpBytes = encoder.encode(fingerprint);
  const bodyBytes = type === STATIC_THERMAL_DELTA
    ? 4 + staticUpdates.length * 12
    : 12 + (created.length + updated.length) * 20 + deleted.length * 12;
  const packet = new ArrayBuffer(28 + sessionBytes.length + fpBytes.length + bodyBytes);
  const bytes = new Uint8Array(packet); bytes.set(encoder.encode("HGTD"), 0);
  const view = new DataView(packet);
  view.setUint16(4, 1, true); view.setUint8(6, type);
  view.setBigUint64(8, BigInt(sequence), true); view.setBigUint64(16, BigInt(base), true);
  view.setUint16(24, sessionBytes.length, true); view.setUint16(26, fpBytes.length, true);
  let at = 28; bytes.set(sessionBytes, at); at += sessionBytes.length; bytes.set(fpBytes, at); at += fpBytes.length;
  if (type === STATIC_THERMAL_DELTA) {
    view.setUint32(at, staticUpdates.length, true); at += 4;
    staticUpdates.forEach(([index, temperature, confidence]) => { view.setUint32(at, index, true); view.setFloat32(at + 4, temperature, true); view.setFloat32(at + 8, confidence, true); at += 12; });
  } else {
    view.setUint32(at, created.length, true); view.setUint32(at + 4, updated.length, true); view.setUint32(at + 8, deleted.length, true); at += 12;
    [...created, ...updated].forEach(([x, y, z, temperature, confidence]) => { view.setInt32(at, x, true); view.setInt32(at + 4, y, true); view.setInt32(at + 8, z, true); view.setFloat32(at + 12, temperature, true); view.setFloat32(at + 16, confidence, true); at += 20; });
    deleted.forEach(([x, y, z]) => { view.setInt32(at, x, true); view.setInt32(at + 4, y, true); view.setInt32(at + 8, z, true); at += 12; });
  }
  return packet;
}

function manager() {
  const staticGeometry = new THREE.BufferGeometry(); const dynamicGeometry = new THREE.BufferGeometry();
  return { staticGeometry, dynamicGeometry, buffers: new ThermalGeometryBuffers(staticGeometry, dynamicGeometry, { dynamicVoxelSize: .05 }) };
}

test("HGPC v3 bootstrap creates persistent static and dynamic state", () => {
  const cloud = parsePointCloudPacket(snapshotPacket([
    { kind: 0, key: [7, 0, 0], position: [1, 2, 3], temperature: 30, confidence: .8 },
    { kind: 1, key: [20, 0, -1], position: [1.02, .01, -.02], temperature: 40, confidence: .9 },
  ]));
  const state = manager(); const counts = state.buffers.bootstrap(cloud);
  assert.deepEqual(counts, { staticCount: 1, dynamicCount: 1, sequence: 4 });
  assert.deepEqual([...state.staticGeometry.getAttribute("position").array], [1, 2, 3]);
  assert.equal(state.buffers.dynamicKeyToSlot.size, 1);
});

test("one and multiple static deltas update only ranges without replacing attributes", () => {
  const cloud = parsePointCloudPacket(snapshotPacket([
    { kind: 0, key: [7, 0, 0], position: [0, 0, 0], temperature: 20, confidence: .5 },
    { kind: 0, key: [9, 0, 0], position: [1, 0, 0], temperature: 20, confidence: .5 },
  ]));
  const state = manager(); state.buffers.bootstrap(cloud);
  const position = state.staticGeometry.getAttribute("position"); const color = state.staticGeometry.getAttribute("color");
  let result = state.buffers.apply(parseThermalDelta(deltaPacket({ type: STATIC_THERMAL_DELTA, sequence: 5, staticUpdates: [[7, 35, .8]] })));
  assert.equal(result.staticUpdated, 1); assert.equal(state.staticGeometry.getAttribute("position"), position); assert.equal(state.staticGeometry.getAttribute("color"), color);
  assert.deepEqual(color.updateRanges, [{ start: 0, count: 3 }]);
  result = state.buffers.apply(parseThermalDelta(deltaPacket({ type: STATIC_THERMAL_DELTA, sequence: 6, base: 5, staticUpdates: [[7, 30, .7], [9, 40, .9]] })));
  assert.equal(result.staticUpdated, 2); assert.deepEqual(color.updateRanges, [{ start: 0, count: 6 }]);
});

test("dynamic create update delete uses stable slots and a free-list", () => {
  const state = manager(); state.buffers.bootstrap(parsePointCloudPacket(snapshotPacket([])));
  const attributes = ["position", "color", "temperature", "confidence"].map((name) => state.dynamicGeometry.getAttribute(name));
  state.buffers.apply(parseThermalDelta(deltaPacket({ type: DYNAMIC_DELTA, sequence: 1, base: 0, created: [[2, 4, 6, 30, .8]] })));
  const slot = state.buffers.dynamicKeyToSlot.get("2,4,6");
  const position = state.dynamicGeometry.getAttribute("position").array.slice(slot * 3, slot * 3 + 3);
  assert.ok(Math.abs(position[0] - .125) < 1e-6 && Math.abs(position[1] - .225) < 1e-6 && Math.abs(position[2] - .325) < 1e-6);
  state.buffers.apply(parseThermalDelta(deltaPacket({ type: DYNAMIC_DELTA, sequence: 2, updated: [[2, 4, 6, 45, .9]] })));
  assert.equal(state.dynamicGeometry.getAttribute("temperature").array[slot], 45);
  state.buffers.apply(parseThermalDelta(deltaPacket({ type: DYNAMIC_DELTA, sequence: 3, deleted: [[2, 4, 6]] })));
  assert.equal(state.buffers.dynamicKeyToSlot.size, 0); assert.ok(Number.isNaN(state.dynamicGeometry.getAttribute("position").array[slot * 3]));
  assert.deepEqual(["position", "color", "temperature", "confidence"].map((name) => state.dynamicGeometry.getAttribute(name)), attributes);
});

test("sequence gaps request replay while identity changes require snapshot", () => {
  const normal = parseThermalDelta(deltaPacket({ type: STATIC_THERMAL_DELTA, sequence: 5 }));
  assert.equal(thermalDeltaAction(normal, { sessionId: "s", geometryFingerprint: "f", sequence: 4 }), "APPLY");
  assert.equal(thermalDeltaAction(normal, { sessionId: "s", geometryFingerprint: "f", sequence: 2 }), "REPLAY_REQUIRED");
  assert.equal(thermalDeltaAction(normal, { sessionId: "other", geometryFingerprint: "f", sequence: 4 }), "SNAPSHOT_REQUIRED");
  assert.equal(thermalDeltaAction(normal, { sessionId: "s", geometryFingerprint: "other", sequence: 4 }), "SNAPSHOT_REQUIRED");
});

test("unknown static index refuses partial application and forces snapshot fallback", () => {
  const state = manager(); state.buffers.bootstrap(parsePointCloudPacket(snapshotPacket([{ kind: 0, key: [1, 0, 0], position: [0, 0, 0], temperature: 20, confidence: 1 }])));
  const result = state.buffers.apply(parseThermalDelta(deltaPacket({ type: STATIC_THERMAL_DELTA, sequence: 5, staticUpdates: [[99, 50, 1]] })));
  assert.deepEqual(result, { applied: false, reason: "STATIC_GEOMETRY_MISSING" });
});
