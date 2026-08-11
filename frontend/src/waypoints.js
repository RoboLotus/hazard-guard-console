const LEGACY_STORAGE_KEY = "hazard-guard:waypoint-route:v1";
const STORAGE_PREFIX = "hazard-guard:waypoint-route:v2";

function storageKey(worldId = "facility_map") {
  return `${STORAGE_PREFIX}:${encodeURIComponent(worldId || "facility_map")}`;
}

export function createWaypoint(candidate, index, values = {}) {
  const id = values.id || globalThis.crypto?.randomUUID?.()
    || `waypoint-${Date.now()}-${index}`;
  return {
    id,
    name: values.name?.trim() || `WP-${String(index + 1).padStart(2, "0")}`,
    x: Number(candidate.mapX ?? candidate.x),
    y: Number(candidate.mapY ?? candidate.y),
    yaw: Number(values.yaw ?? candidate.yaw ?? 0),
    dwell_seconds: Number(values.dwell_seconds ?? 0),
    enabled: values.enabled ?? true,
  };
}

export function moveWaypoint(items, sourceId, targetId) {
  const sourceIndex = items.findIndex((item) => item.id === sourceId);
  const targetIndex = items.findIndex((item) => item.id === targetId);
  if (sourceIndex < 0 || targetIndex < 0 || sourceIndex === targetIndex) return items;
  const next = [...items];
  const [source] = next.splice(sourceIndex, 1);
  next.splice(targetIndex, 0, source);
  return next;
}

export function shiftWaypoint(items, id, direction) {
  const index = items.findIndex((item) => item.id === id);
  const target = index + direction;
  if (index < 0 || target < 0 || target >= items.length) return items;
  const next = [...items];
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}

export function routeMapSignature(mapSpec) {
  if (!mapSpec) return "unknown";
  return [
    mapSpec.map_id || "legacy",
    mapSpec.frame_id || "map",
    mapSpec.width,
    mapSpec.height,
    Number(mapSpec.resolution || 0).toFixed(4),
    Number(mapSpec.origin_x || 0).toFixed(3),
    Number(mapSpec.origin_y || 0).toFixed(3),
  ].join(":");
}

export function loadWaypointRoute(worldId = "facility_map") {
  try {
    const current = localStorage.getItem(storageKey(worldId));
    const legacy = worldId === "facility_map"
      ? localStorage.getItem(LEGACY_STORAGE_KEY)
      : null;
    const parsed = JSON.parse(current || legacy || "null");
    if (!parsed || !Array.isArray(parsed.waypoints)) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function saveWaypointRoute(
  waypoints,
  mapSpec,
  routeName = "기본 순찰 경로",
  worldId = "facility_map",
) {
  const payload = {
    version: 2,
    worldId,
    routeName,
    mapSignature: routeMapSignature(mapSpec),
    savedAt: new Date().toISOString(),
    waypoints,
  };
  localStorage.setItem(storageKey(worldId), JSON.stringify(payload));
  return payload;
}

export function clearWaypointRoute(worldId = "facility_map") {
  localStorage.removeItem(storageKey(worldId));
  if (worldId === "facility_map") {
    localStorage.removeItem(LEGACY_STORAGE_KEY);
  }
}

export function activeWaypoints(waypoints) {
  return waypoints.filter((waypoint) => waypoint.enabled !== false);
}
