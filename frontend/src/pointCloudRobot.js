export const ROBOT_POSE_STALE_MS = 2500;
export const ROBOT_POSE_EXPIRED_MS = 10000;

export function normalizeFrameId(value) {
  const frameId = String(value || "").trim().replace(/^\/+/, "");
  return frameId || null;
}

function timestampMs(value) {
  const parsed = Date.parse(String(value || ""));
  return Number.isFinite(parsed) ? parsed : null;
}

export function selectPointCloudPose(spatialState, cloudFrameId) {
  const normalizedCloudFrameId = normalizeFrameId(cloudFrameId);
  if (!normalizedCloudFrameId) return spatialState?.pose || null;

  const matchingPose = Object.values(spatialState?.poses || {}).find(
    (pose) => normalizeFrameId(pose?.frame_id) === normalizedCloudFrameId,
  );
  if (matchingPose) return matchingPose;

  const canonicalPose = spatialState?.pose;
  return normalizeFrameId(canonicalPose?.frame_id) === normalizedCloudFrameId
    ? canonicalPose
    : null;
}

export function resolvePointCloudRobotState(
  pose,
  cloudFrameId,
  nowMs = Date.now(),
) {
  const poseFrameId = normalizeFrameId(pose?.frame_id);
  const normalizedCloudFrameId = normalizeFrameId(cloudFrameId);
  const base = {
    visible: false,
    stale: false,
    reason: "로봇 위치 대기 중",
    poseFrameId,
    cloudFrameId: normalizedCloudFrameId,
  };

  if (!pose?.available) return base;
  if (!normalizedCloudFrameId) {
    return { ...base, reason: "3D 지도 좌표계 확인 필요" };
  }
  if (!poseFrameId || poseFrameId !== normalizedCloudFrameId) {
    return {
      ...base,
      reason: `좌표계 불일치 (${poseFrameId || "미확인"} ↔ ${normalizedCloudFrameId})`,
    };
  }

  const x = Number(pose.x);
  const y = Number(pose.y);
  const z = Number(pose.z ?? 0);
  const yaw = Number(pose.yaw);
  if (![x, y, z, yaw].every(Number.isFinite)) {
    return { ...base, reason: "로봇 위치 값 확인 필요" };
  }

  const updatedAtMs = timestampMs(pose.updated_at);
  if (updatedAtMs === null) {
    return { ...base, reason: "로봇 위치 시각 확인 필요" };
  }
  const ageMs = Math.max(0, nowMs - updatedAtMs);
  if (ageMs > ROBOT_POSE_EXPIRED_MS) {
    return { ...base, reason: "로봇 위치 수신 끊김", ageMs };
  }

  const stale = ageMs > ROBOT_POSE_STALE_MS;
  return {
    ...base,
    visible: true,
    stale,
    reason: stale ? "로봇 위치 갱신 지연" : "로봇 위치 실시간",
    ageMs,
    x,
    y,
    z,
    yaw,
  };
}

export function shouldShowPointCloudRobot(
  robotState,
  {
    variant = "rgb",
    pointCount = 0,
    baseScene = null,
    referenceSession = null,
    thermalSessionId = null,
    thermalStatusFrameId = null,
    fixedMapAvailable = null,
  } = {},
) {
  if (!robotState?.visible) return false;
  if (variant !== "thermal") return Number(pointCount) > 0;
  if (fixedMapAvailable !== true || !baseScene?.ready) return false;

  const sceneWorldId = String(baseScene.worldId || "");
  const sceneSessionId = String(baseScene.sessionId || "");
  const referenceWorldId = String(referenceSession?.world_id || "");
  const referenceSessionId = String(referenceSession?.id || "");
  const sceneFrameId = normalizeFrameId(baseScene.frameId);
  const referenceFrameId = normalizeFrameId(
    referenceSession?.cloud_frame_id || referenceSession?.frame_id,
  );
  const streamFrameId = normalizeFrameId(thermalStatusFrameId);

  // Thermal observations can be empty before the first inspection, but the
  // immutable base geometry must be a non-empty, identity-matched scene.
  return Number(baseScene.pointCount) > 0
    && sceneWorldId === referenceWorldId
    && sceneSessionId === referenceSessionId
    && sceneSessionId === String(thermalSessionId || "")
    && Boolean(sceneFrameId)
    && sceneFrameId === referenceFrameId
    && (!streamFrameId || sceneFrameId === streamFrameId)
    && sceneFrameId === robotState.cloudFrameId;
}
