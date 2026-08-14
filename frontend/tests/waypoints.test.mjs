import assert from "node:assert/strict";
import test from "node:test";

import {
  activeWaypoints,
  clearWaypointRoute,
  createWaypoint,
  loadWaypointRoute,
  moveWaypoint,
  routeMapSignature,
  shiftWaypoint,
} from "../src/waypoints.js";

const route = [
  { id: "a", name: "A", enabled: true },
  { id: "b", name: "B", enabled: true },
  { id: "c", name: "C", enabled: false },
];

test("creates a named waypoint from a map click", () => {
  const waypoint = createWaypoint(
    { mapX: 1.25, mapY: -0.75 },
    2,
    {
      id: "pump",
      name: " 펌프 구역 ",
      equipment_id: " secondary_processor_pump ",
      yaw: 1.2,
      dwell_seconds: 4,
    },
  );
  assert.deepEqual(waypoint, {
    id: "pump",
    name: "펌프 구역",
    equipment_id: "secondary_processor_pump",
    x: 1.25,
    y: -0.75,
    yaw: 1.2,
    dwell_seconds: 4,
    enabled: true,
  });
});

test("supports drag reorder and one-step order changes", () => {
  assert.deepEqual(
    moveWaypoint(route, "a", "c").map((item) => item.id),
    ["b", "c", "a"],
  );
  assert.deepEqual(
    shiftWaypoint(route, "b", -1).map((item) => item.id),
    ["b", "a", "c"],
  );
});

test("filters disabled points and fingerprints the current map", () => {
  assert.deepEqual(activeWaypoints(route).map((item) => item.id), ["a", "b"]);
  assert.equal(
    routeMapSignature({
      frame_id: "map",
      map_id: "static:donut:abc123",
      width: 120,
      height: 80,
      resolution: 0.05,
      origin_x: -3,
      origin_y: -2,
    }),
    "static:donut:abc123:map:120:80:0.0500:-3.000:-2.000",
  );
});

test("clearing the default route also removes its legacy fallback", (t) => {
  const values = new Map();
  globalThis.localStorage = {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  };
  t.after(() => {
    delete globalThis.localStorage;
  });
  values.set(
    "hazard-guard:waypoint-route:v1",
    JSON.stringify({ waypoints: [{ id: "legacy" }] }),
  );

  assert.equal(loadWaypointRoute("facility_map").waypoints[0].id, "legacy");

  clearWaypointRoute("facility_map");

  assert.equal(loadWaypointRoute("facility_map"), null);
});
