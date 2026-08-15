import assert from "node:assert/strict";
import test from "node:test";

import {
  ROBOT_POSE_EXPIRED_MS,
  ROBOT_POSE_STALE_MS,
  normalizeFrameId,
  resolvePointCloudRobotState,
  selectPointCloudPose,
} from "../src/pointCloudRobot.js";

const NOW = Date.parse("2026-08-15T12:00:00.000Z");

function pose(ageMs = 0, overrides = {}) {
  return {
    available: true,
    frame_id: "map",
    x: 1.25,
    y: -0.5,
    z: 0.03,
    yaw: 1.57,
    updated_at: new Date(NOW - ageMs).toISOString(),
    ...overrides,
  };
}

test("shows a fresh pose only in the point cloud frame", () => {
  const state = resolvePointCloudRobotState(pose(), "map", NOW);

  assert.equal(state.visible, true);
  assert.equal(state.stale, false);
  assert.equal(state.x, 1.25);
  assert.equal(state.z, 0.03);
  assert.equal(state.reason, "로봇 위치 실시간");
});

test("normalizes a legacy leading slash in ROS frame IDs", () => {
  assert.equal(normalizeFrameId("/map"), "map");
  assert.equal(
    resolvePointCloudRobotState(pose(0, { frame_id: "/odom" }), "odom", NOW).visible,
    true,
  );
});

test("selects the robot pose in the point cloud coordinate frame", () => {
  const mapPose = pose(0, { frame_id: "map", x: 8 });
  const odomPose = pose(0, { frame_id: "/odom", x: 2 });
  const spatialState = {
    pose: mapPose,
    poses: { map: mapPose, odom: odomPose },
  };

  assert.equal(selectPointCloudPose(spatialState, "odom").x, 2);
  assert.equal(selectPointCloudPose(spatialState, "/map").x, 8);
  assert.equal(selectPointCloudPose(spatialState, "camera_link"), null);
});

test("hides a pose when the point cloud frame differs", () => {
  const state = resolvePointCloudRobotState(pose(), "odom", NOW);

  assert.equal(state.visible, false);
  assert.match(state.reason, /좌표계 불일치/);
});

test("marks a delayed pose stale and eventually hides it", () => {
  const stale = resolvePointCloudRobotState(
    pose(ROBOT_POSE_STALE_MS + 1),
    "map",
    NOW,
  );
  const expired = resolvePointCloudRobotState(
    pose(ROBOT_POSE_EXPIRED_MS + 1),
    "map",
    NOW,
  );

  assert.equal(stale.visible, true);
  assert.equal(stale.stale, true);
  assert.equal(expired.visible, false);
  assert.equal(expired.reason, "로봇 위치 수신 끊김");
});

test("rejects incomplete or invalid pose data", () => {
  assert.equal(resolvePointCloudRobotState(null, "map", NOW).visible, false);
  assert.equal(
    resolvePointCloudRobotState(pose(0, { x: Number.NaN }), "map", NOW).visible,
    false,
  );
  assert.equal(
    resolvePointCloudRobotState(pose(0, { updated_at: "invalid" }), "map", NOW).visible,
    false,
  );
});
