import test from "node:test";
import assert from "node:assert/strict";
import { freshPose, normalizeSpatial, robotCenteredView } from "../src/spatialFreshness.js";

test("저장 지도는 남기고 오래된 위치와 단절된 위치는 숨긴다", () => {
  const pose = { available: true, x: 1, y: 2, yaw: 0, updated_at: new Date(10000).toISOString() };
  const state = { source: "ros", mock: false, map: { map_id: "saved" }, pose, poses: { map: pose } };
  assert.equal(freshPose(pose, 14000), true);
  assert.equal(normalizeSpatial(state, true, 16000).pose.available, false);
  const disconnected = normalizeSpatial(state, false, 10000);
  assert.deepEqual(disconnected.map, state.map);
  assert.equal(disconnected.poses.map.available, false);
  assert.equal(freshPose({ ...pose, x: null }, 10000), false);
});

test("확대 배율과 레터박스를 반영하여 로봇을 화면 중앙으로 이동한다", () => {
  const view = robotCenteredView({ x: 20, y: 30 }, { left: 10, top: 20, scale: 2 }, { width: 200, height: 200 }, 2);
  assert.deepEqual(view, { zoom: 2, x: 100, y: 40 });
});
