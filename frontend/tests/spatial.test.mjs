import assert from "node:assert/strict";
import test from "node:test";

import {
  buildFovPolygon,
  buildFootprintPolygon,
  detectionColor,
  detectionLevel,
  detectionOpacity,
  mapToGrid,
  matchesMapFrame,
  sensorLegend,
  thermalDetectionsToEvents,
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

test("only overlays spatial values in the active map frame", () => {
  const activeMap = { ...mapSpec, frame_id: "map" };

  assert.equal(matchesMapFrame({ frame_id: "map" }, activeMap), true);
  assert.equal(matchesMapFrame({ frame_id: "odom" }, activeMap), false);
  assert.equal(matchesMapFrame({}, activeMap), true);
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


test("trend decision controls map color and Korean label", () => {
  const warning = { temperature_c: 42, trend_status: "warning" };
  assert.equal(detectionColor(warning), "#ed7b2f");
  assert.equal(detectionLevel(warning), "추세 경고");
  assert.equal(detectionLevel({ temperature_c: 42, trend_status: "watch" }), "관찰");
});
test("builds current-map risk events from thermal trend detections", () => {
  const events = thermalDetectionsToEvents([
    {
      detection_id: "thermal-primary_shredder_motor",
      equipment_id: "primary_shredder_motor",
      x: -0.89,
      y: 0.28,
      temperature_c: 84.08,
      trend_status: "critical",
      simulated: true,
      updated_at: "2026-08-12T13:40:38Z",
    },
    {
      detection_id: "thermal-baler_hydraulic_tank",
      equipment_id: "baler_hydraulic_tank",
      x: 1.06,
      y: 0.24,
      temperature_c: 47.1,
      trend_status: "watch",
      source: "thermal_trend:baler_hydraulic_tank:watch:environment_adjusted_anomaly_only",
      simulated: true,
      updated_at: "2026-08-12T13:40:02Z",
    },
    {
      detection_id: "normal-cold-surface",
      temperature_c: 31,
      trend_status: "normal",
    },
  ]);

  assert.equal(events.length, 2);
  assert.equal(events[0].level, "critical");
  assert.equal(events[0].temperature, "84.1°C");
  assert.match(events[0].location, /1차 파쇄기 모터/);
  assert.match(events[0].location, /map \(-0\.89, 0\.28\)/);
  assert.equal(events[1].level, "watch");
  assert.equal(events[1].threshold, "환경 대비 온도 이상 관찰");
  assert.equal(events[1].simulated, true);
});
test("labels a persistent multi-visit rise as a long-term trend", () => {
  const [event] = thermalDetectionsToEvents([{
    detection_id: "thermal-primary_shredder_motor",
    equipment_id: "primary_shredder_motor",
    temperature_c: 70,
    trend_status: "warning",
    source: "thermal_trend:primary_shredder_motor:warning:persistent_trend_and_environment_adjusted_anomaly",
  }]);

  assert.equal(event.threshold, "장기 상승 추세 경고");
});

test("parses composite trend status and creates a visit-specific event", () => {
  const [event] = thermalDetectionsToEvents([{
    detection_id: "thermal-baler_hydraulic_tank",
    equipment_id: "baler_hydraulic_tank",
    temperature_c: 43.5,
    trend_status: "watch:environment_adjusted_anomaly_only",
    trend_reason: "environment_adjusted_anomaly_only",
    visit_index: 3,
  }]);

  assert.equal(event.id, "thermal-baler_hydraulic_tank-visit-3");
  assert.equal(event.level, "watch");
  assert.equal(event.visitIndex, 3);
  assert.equal(event.threshold, "환경 대비 온도 이상 관찰");
});
test("keeps warning separate from watch", () => {
  const [event] = thermalDetectionsToEvents([{
    detection_id: "thermal-primary_shredder_motor",
    equipment_id: "primary_shredder_motor",
    temperature_c: 52,
    trend_status: "warning",
    trend_reason: "persistent_trend_and_environment_adjusted_anomaly",
  }]);

  assert.equal(event.level, "warning");
});

test("keeps repeated patrol events distinct after the history window", () => {
  const events = [6, 7].map((visitIndex) => thermalDetectionsToEvents([{
    detection_id: "thermal-primary_shredder_motor",
    equipment_id: "primary_shredder_motor",
    temperature_c: 52,
    trend_status: "warning",
    trend_reason: "persistent_trend_and_environment_adjusted_anomaly",
    visit_index: visitIndex,
  }])[0]);

  assert.deepEqual(
    events.map((event) => event.id),
    [
      "thermal-primary_shredder_motor-visit-6",
      "thermal-primary_shredder_motor-visit-7",
    ],
  );
});

test("shows a missing production baseline as a configuration watch", () => {
  const [event] = thermalDetectionsToEvents([{
    detection_id: "thermal-primary_shredder_motor",
    equipment_id: "primary_shredder_motor",
    frame_id: "map",
    x: 0.2,
    y: 0.4,
    temperature_c: 200,
    trend_status: "watch",
    trend_reason: "baseline_required_not_configured",
    updated_at: "2026-08-18T00:00:00Z",
  }]);

  assert.equal(event.threshold, "설비 정상 기준값 미설정");
  assert.equal(event.title, "설비 기준값 설정 필요");
});

test("shows the baseline residual reason from the patrol trend policy", () => {
  const [event] = thermalDetectionsToEvents([{
    detection_id: "thermal-primary_shredder_motor",
    equipment_id: "primary_shredder_motor",
    frame_id: "map",
    x: 0.2,
    y: 0.4,
    temperature_c: 74,
    trend_status: "warning",
    trend_reason: "persistent_trend_and_baseline_residual",
    updated_at: "2026-08-18T00:00:00Z",
  }]);

  assert.equal(event.threshold, "장기 상승·기준선 이탈 경고");
});
