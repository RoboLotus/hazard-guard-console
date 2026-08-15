import assert from "node:assert/strict";
import test from "node:test";

import {
  POINT_CLOUD_HEADER_BYTES,
  POINT_CLOUD_RECORD_BYTES,
  parsePointCloudPacket,
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
