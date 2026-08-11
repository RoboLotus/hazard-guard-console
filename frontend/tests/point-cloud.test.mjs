import assert from "node:assert/strict";
import test from "node:test";

import {
  POINT_CLOUD_HEADER_BYTES,
  POINT_CLOUD_RECORD_BYTES,
  parsePointCloudPacket,
} from "../src/pointCloud.js";

test("parses the compact HazardGuard XYZ/RGB packet", () => {
  const packet = new ArrayBuffer(POINT_CLOUD_HEADER_BYTES + POINT_CLOUD_RECORD_BYTES);
  const view = new DataView(packet);
  new Uint8Array(packet, 0, 4).set(new TextEncoder().encode("HGPC"));
  view.setUint8(4, 1);
  view.setUint8(5, 1);
  view.setUint32(8, 7, true);
  view.setUint32(12, 1, true);
  view.setBigUint64(16, 1234n, true);
  view.setFloat32(24, 1.25, true);
  view.setFloat32(28, -2.5, true);
  view.setFloat32(32, 0.75, true);
  view.setUint8(36, 220);
  view.setUint8(37, 80);
  view.setUint8(38, 40);
  view.setUint8(39, 255);

  const cloud = parsePointCloudPacket(packet);

  assert.equal(cloud.sequence, 7);
  assert.equal(cloud.pointCount, 1);
  assert.equal(cloud.timestampMs, 1234);
  assert.equal(cloud.colorAvailable, true);
  assert.deepEqual([...cloud.positions], [1.25, -2.5, 0.75]);
  assert.ok(Math.abs(cloud.colors[0] - 220 / 255) < 1e-6);
});

test("rejects incomplete point cloud packets", () => {
  assert.throws(
    () => parsePointCloudPacket(new ArrayBuffer(8)),
    /패킷 헤더/,
  );
});
