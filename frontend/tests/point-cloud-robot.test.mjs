import assert from "node:assert/strict";
import test from "node:test";

import {
  ROBOT_POSE_EXPIRED_MS,
  ROBOT_POSE_STALE_MS,
  normalizeFrameId,
  resolvePointCloudRobotState,
  selectPointCloudPose,
  shouldShowPointCloudRobot,
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

test("shows a fresh map pose over a fixed thermal scene with zero thermal points", () => {
  const spatialState = {
    pose: pose(),
    poses: { map: pose() },
  };
  const robotState = resolvePointCloudRobotState(
    selectPointCloudPose(spatialState, "map"),
    "map",
    NOW,
  );

  assert.equal(shouldShowPointCloudRobot(robotState, {
    variant: "thermal",
    pointCount: 0,
    baseScene: {
      ready: true,
      pointCount: 12_000,
      worldId: "facility_map",
      sessionId: "session-a",
      frameId: "map",
    },
    referenceSession: {
      world_id: "facility_map",
      id: "session-a",
      cloud_frame_id: "map",
    },
    thermalSessionId: "session-a",
    fixedMapAvailable: true,
  }), true);
});

test("hides the robot marker when the fixed base scene has no points", () => {
  const robotState = resolvePointCloudRobotState(pose(), "map", NOW);

  assert.equal(shouldShowPointCloudRobot(robotState, {
    variant: "thermal",
    pointCount: 0,
    baseScene: {
      ready: true,
      pointCount: 0,
      worldId: "facility_map",
      sessionId: "session-a",
      frameId: "map",
    },
    referenceSession: {
      world_id: "facility_map",
      id: "session-a",
      cloud_frame_id: "map",
    },
    thermalSessionId: "session-a",
    fixedMapAvailable: true,
  }), false);
  assert.equal(shouldShowPointCloudRobot(robotState, {
    variant: "rgb",
    pointCount: 0,
  }), false);
});

test("rejects a prior thermal scene after a reference session switch or fetch failure", () => {
  const robotState = resolvePointCloudRobotState(pose(), "map", NOW);
  const priorScene = {
    ready: true,
    pointCount: 12_000,
    worldId: "facility_map",
    sessionId: "session-old",
    frameId: "map",
  };
  const newReference = {
    world_id: "facility_map",
    id: "session-new",
    cloud_frame_id: "map",
  };

  assert.equal(shouldShowPointCloudRobot(robotState, {
    variant: "thermal",
    baseScene: priorScene,
    referenceSession: newReference,
    thermalSessionId: "session-new",
    fixedMapAvailable: true,
  }), false);
  assert.equal(shouldShowPointCloudRobot(robotState, {
    variant: "thermal",
    baseScene: { ...priorScene, ready: false, pointCount: 0 },
    referenceSession: newReference,
    thermalSessionId: "session-new",
    fixedMapAvailable: true,
  }), false);
});

test("rejects frame mismatch and stale pose on an otherwise matching thermal scene", () => {
  const matching = {
    variant: "thermal",
    baseScene: {
      ready: true,
      pointCount: 12_000,
      worldId: "facility_map",
      sessionId: "session-a",
      frameId: "odom",
    },
    referenceSession: {
      world_id: "facility_map",
      id: "session-a",
      cloud_frame_id: "map",
    },
    thermalSessionId: "session-a",
    fixedMapAvailable: true,
  };

  assert.equal(shouldShowPointCloudRobot(
    resolvePointCloudRobotState(pose(), "map", NOW),
    matching,
  ), false);
  assert.equal(shouldShowPointCloudRobot(
    resolvePointCloudRobotState(pose(ROBOT_POSE_EXPIRED_MS + 1), "map", NOW),
    { ...matching, baseScene: { ...matching.baseScene, frameId: "map" } },
  ), false);
});

test("rejects an authoritative thermal stream frame that differs from the base scene", () => {
  const robotState = resolvePointCloudRobotState(pose(), "map", NOW);
  const matchingScene = {
    ready: true,
    pointCount: 12_000,
    worldId: "facility_map",
    sessionId: "session-a",
    frameId: "map",
  };
  const referenceSession = {
    world_id: "facility_map",
    id: "session-a",
    cloud_frame_id: "map",
  };

  for (const pointCount of [0, 25]) {
    assert.equal(shouldShowPointCloudRobot(robotState, {
      variant: "thermal",
      pointCount,
      baseScene: matchingScene,
      referenceSession,
      thermalSessionId: "session-a",
      thermalStatusFrameId: "odom",
      fixedMapAvailable: true,
    }), false);
  }
  assert.equal(shouldShowPointCloudRobot(robotState, {
    variant: "thermal",
    pointCount: 0,
    baseScene: matchingScene,
    referenceSession,
    thermalSessionId: "session-a",
    thermalStatusFrameId: "/map",
    fixedMapAvailable: true,
  }), true);
});
