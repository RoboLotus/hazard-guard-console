import assert from "node:assert/strict";
import test from "node:test";

import {
  formatThermalLayerAge,
  POINT_CLOUD_HEADER_BYTES,
  POINT_CLOUD_RECORD_BYTES,
  parsePointCloudPacket,
  replacePointCloudGeometrySnapshot,
  resolveThermalLayerPresentation,
} from "../src/pointCloud.js";

test("parses the compact HazardGuard XYZ/RGB packet", () => {
  const frameId = new TextEncoder().encode("map");
  const packet = new ArrayBuffer(
    POINT_CLOUD_HEADER_BYTES + frameId.byteLength + POINT_CLOUD_RECORD_BYTES,
  );
  const view = new DataView(packet);
  new Uint8Array(packet, 0, 4).set(new TextEncoder().encode("HGPC"));
  view.setUint8(4, 2);
  view.setUint8(5, 1);
  view.setUint16(6, frameId.byteLength, true);
  view.setUint32(8, 7, true);
  view.setUint32(12, 1, true);
  view.setBigUint64(16, 1234n, true);
  new Uint8Array(packet, POINT_CLOUD_HEADER_BYTES, frameId.byteLength).set(frameId);
  const recordOffset = POINT_CLOUD_HEADER_BYTES + frameId.byteLength;
  view.setFloat32(recordOffset, 1.25, true);
  view.setFloat32(recordOffset + 4, -2.5, true);
  view.setFloat32(recordOffset + 8, 0.75, true);
  view.setUint8(recordOffset + 12, 220);
  view.setUint8(recordOffset + 13, 80);
  view.setUint8(recordOffset + 14, 40);
  view.setUint8(recordOffset + 15, 255);

  const cloud = parsePointCloudPacket(packet);

  assert.equal(cloud.sequence, 7);
  assert.equal(cloud.pointCount, 1);
  assert.equal(cloud.timestampMs, 1234);
  assert.equal(cloud.frameId, "map");
  assert.equal(cloud.colorAvailable, true);
  assert.deepEqual([...cloud.positions], [1.25, -2.5, 0.75]);
  assert.ok(Math.abs(cloud.colors[0] - 220 / 255) < 1e-6);
});

test("keeps parsing legacy v1 packets without frame metadata", () => {
  const packet = new ArrayBuffer(POINT_CLOUD_HEADER_BYTES + POINT_CLOUD_RECORD_BYTES);
  const view = new DataView(packet);
  new Uint8Array(packet, 0, 4).set(new TextEncoder().encode("HGPC"));
  view.setUint8(4, 1);
  view.setUint32(12, 1, true);
  view.setFloat32(POINT_CLOUD_HEADER_BYTES, 1, true);

  const cloud = parsePointCloudPacket(packet);

  assert.equal(cloud.version, 1);
  assert.equal(cloud.frameId, null);
  assert.equal(cloud.pointCount, 1);
});

test("rejects incomplete point cloud packets", () => {
  assert.throws(
    () => parsePointCloudPacket(new ArrayBuffer(8)),
    /패킷 헤더/,
  );
});

test("presents post-mapping thermal metadata as a cumulative fixed-map layer", () => {
  const now = Date.parse("2026-08-23T12:00:04Z");
  const presentation = resolveThermalLayerPresentation({
    cumulative: true,
    observed_voxel_count: 12_345,
    point_count: 8_000,
    fixed_map_available: true,
    match_ratio: 0.82,
    rejected_observation_count: 17,
    persisted_at: "2026-08-23T12:00:02Z",
    session_id: "factory-a-3d",
    updated_at: "2026-08-23T12:00:01Z",
    stale: true,
  }, {
    pointCount: 8_000,
    updatedAt: new Date("2026-08-23T12:00:03Z"),
  }, now);

  assert.equal(presentation.cumulative, true);
  assert.equal(presentation.observedVoxelCount, 12_345);
  assert.equal(presentation.fixedMapAvailable, true);
  assert.equal(presentation.matchRatio, 0.82);
  assert.equal(presentation.rejectedObservationCount, 17);
  assert.equal(presentation.sessionId, "factory-a-3d");
  assert.equal(presentation.updatedAtMs, Date.parse("2026-08-23T12:00:03Z"));
  assert.equal(presentation.stale, false);
  assert.equal(formatThermalLayerAge(presentation.updatedAtMs, now), "방금 전");
});

test("falls back to legacy thermal cloud status and marks retained measurements stale", () => {
  const now = Date.parse("2026-08-23T12:01:00Z");
  const presentation = resolveThermalLayerPresentation({
    point_count: 321,
    age_sec: 20,
  }, {}, now);

  assert.equal(presentation.observedVoxelCount, 321);
  assert.equal(presentation.fixedMapAvailable, true);
  assert.equal(presentation.updatedAtMs, now - 20_000);
  assert.equal(presentation.stale, true);
  assert.equal(formatThermalLayerAge(presentation.updatedAtMs, now), "20초 전");
});

test("uses the last observation time instead of a recent cumulative republish", () => {
  const now = Date.parse("2026-08-23T12:01:00Z");
  const presentation = resolveThermalLayerPresentation({
    observed_voxel_count: 450,
    last_observation_at: "2026-08-23T12:00:30Z",
    updated_at: "2026-08-23T12:00:59Z",
    age_sec: 1,
  }, {
    pointCount: 450,
    updatedAt: new Date("2026-08-23T12:00:59.900Z"),
  }, now);

  assert.equal(presentation.hasObservationTimestamp, true);
  assert.equal(presentation.updatedAtMs, Date.parse("2026-08-23T12:00:30Z"));
  assert.equal(presentation.stale, true);
  assert.equal(formatThermalLayerAge(presentation.updatedAtMs, now), "30초 전");
});

test("keeps a stationary five-second thermal refresh healthy across poll jitter", () => {
  const now = Date.parse("2026-08-23T12:01:00Z");
  const presentation = resolveThermalLayerPresentation({
    observed_voxel_count: 450,
    last_observation_at: "2026-08-23T12:00:50Z",
    stale_after_sec: 15,
  }, {}, now);

  assert.equal(presentation.staleAfterMs, 15_000);
  assert.equal(presentation.stale, false);
});

test("replaces point cloud geometry with each authoritative cumulative snapshot", () => {
  const attributes = { position: "old positions", color: "old colors" };
  let boundsComputed = 0;
  const geometry = {
    setAttribute(name, value) {
      attributes[name] = value;
    },
    computeBoundingSphere() {
      boundsComputed += 1;
    },
  };

  replacePointCloudGeometrySnapshot(geometry, "new positions", "new colors");

  assert.deepEqual(attributes, {
    position: "new positions",
    color: "new colors",
  });
  assert.equal(boundsComputed, 1);
});
