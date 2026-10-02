export const SPATIAL_STALE_MS = 5000;

export function freshPose(pose, now = Date.now()) {
  const stamp = Date.parse(pose?.updated_at);
  const age = now - stamp;
  return Boolean(pose?.available && pose.mock !== true && Number.isFinite(stamp)
    && age >= -SPATIAL_STALE_MS && age <= SPATIAL_STALE_MS
    && [pose.x, pose.y, pose.yaw].every(Number.isFinite));
}

export function normalizeSpatial(snapshot, connected = true, now = Date.now()) {
  const live = connected && snapshot?.source === "ros" && snapshot?.mock === false;
  const normalize = (pose) => ({ ...pose, available: live && freshPose(pose, now) });
  return {
    ...snapshot, transport_live: live,
    pose: normalize(snapshot?.pose),
    poses: Object.fromEntries(Object.entries(snapshot?.poses || {}).map(([key, pose]) => [key, normalize(pose)])),
  };
}

export function robotCenteredView(point, geometry, stage, zoom = 1) {
  return {
    zoom,
    x: (stage.width / 2 - geometry.left - point.x * geometry.scale) * zoom,
    y: (stage.height / 2 - geometry.top - point.y * geometry.scale) * zoom,
  };
}
