import assert from "node:assert/strict";
import test from "node:test";

import {
  buildFovPolygon,
  buildFootprintPolygon,
  detectionOpacity,
  mapToGrid,
  sensorLegend,
  temperatureColor,
} from "../src/spatial.js";

const mapSpec = {
  width: 200,
  height: 100,
  resolution: 0.05,
  origin_x: -5,
  origin_y: -2.5,
};

test("converts ROS map coordinates to the top-left image grid", () => {
  assert.deepEqual(mapToGrid(-5, -2.5, mapSpec), { x: 0, y: 100 });
  assert.deepEqual(mapToGrid(5, 2.5, mapSpec), { x: 200, y: 0 });
});

test("builds a camera sector from pose, FOV and range", () => {
  const polygon = buildFovPolygon(
    { available: true, x: 0, y: 0, yaw: 0 },
    { horizontal_fov_deg: 60, range_max_m: 4 },
    mapSpec,
    6,
  );
  const points = polygon.split(" ");
  assert.equal(points.length, 8);
  assert.equal(points[0], "100.00,50.00");
});

test("projects the dispenser-aware robot footprint at the current heading", () => {
  const polygon = buildFootprintPolygon(
    { available: true, x: 0, y: 0, yaw: 0 },
    mapSpec,
  ).split(" ");
  assert.equal(polygon.length, 4);
  assert.equal(polygon[0], "91.80,53.10");
  assert.equal(polygon[2], "103.80,46.90");
});

test("uses stable heat colors for warning and critical temperatures", () => {
  assert.equal(temperatureColor(84.6), "#d8323c");
  assert.equal(temperatureColor(63.2), "#ed7b2f");
  assert.equal(temperatureColor(46.8), "#f2b63f");
});

test("fades old or uncertain detections without making them invisible", () => {
  assert.equal(detectionOpacity({ age_sec: 0, confidence: 1 }), 1);
  assert.ok(detectionOpacity({ age_sec: 200, confidence: 0.1 }) >= 0.09);
});

test("builds map legends from live sensor metadata", () => {
  const state = {
    sensors: [
      {
        id: "thermal",
        display_name: "TMC160B",
        model: "ThermoEye TMC160B",
        horizontal_fov_deg: 57,
      },
    ],
  };

  assert.equal(sensorLegend(state, "thermal"), "TMC160B 57°");
  assert.equal(sensorLegend(state, "depth"), null);
});
