import test from "node:test";
import assert from "node:assert/strict";

import {
  beaconSlots,
  incidentActions,
  incidentMapMarkers,
  incidentToEvent,
  mergeIncidentEvents,
  normalizeDispenserBattery,
} from "../src/incidents.js";

const incident = {
  incident_id: "incident-1",
  detection_id: "detection-1",
  state: "approval_required",
  severity: "critical",
  equipment_id: "motor-1",
  temperature_c: 84.6,
  x: 1.2,
  y: -0.4,
  frame_id: "map",
};

test("incident event replaces its raw thermal detection", () => {
  const event = incidentToEvent(incident);
  const merged = mergeIncidentEvents(
    [{ id: "detection-1", title: "raw" }, { id: "other", title: "other" }],
    [incident],
  );

  assert.equal(event.status, "new");
  assert.equal(merged.length, 2);
  assert.equal(merged[0].incident.incident_id, "incident-1");
});

test("incident event replaces a mismatched raw ID for the same equipment visit", () => {
  const authoritative = {
    ...incident,
    incident_id: "thermal:mission-1:motor-1:visit-7",
    detection_id: "thermal:mission-hash",
  };
  const sameVisit = {
    id: "thermal-motor-1-visit-7",
    detectionId: "thermal-motor-1",
    equipmentId: "motor-1",
    visitIndex: 7,
    level: "critical",
    title: "raw duplicate",
  };
  const nextVisit = {
    ...sameVisit,
    id: "thermal-motor-1-visit-8",
    visitIndex: 8,
    level: "watch",
    title: "next watch",
  };

  const merged = mergeIncidentEvents([sameVisit, nextVisit], [authoritative]);

  assert.equal(merged.length, 2);
  assert.equal(merged[0].incident.incident_id, authoritative.incident_id);
  assert.equal(merged[0].visitIndex, 7);
  assert.equal(merged[1].title, "next watch");
});

test("raw watch event remains when no authoritative incident exists", () => {
  const watch = {
    id: "thermal-motor-1-visit-9",
    detectionId: "thermal-motor-1",
    equipmentId: "motor-1",
    visitIndex: 9,
    level: "watch",
  };

  assert.deepEqual(mergeIncidentEvents([watch], []), [watch]);
});

test("drop actions allow partial BLE but fail closed at zero", () => {
  const partial = incidentActions(incident, {
    stale: false,
    connected: 1,
    available_for_drop: 1,
  });
  const zero = incidentActions(incident, {
    stale: false,
    connected: 0,
    available_for_drop: 0,
  });

  assert.equal(partial.find((action) => action.id === "drop_then_resume").enabled, true);
  assert.equal(zero.find((action) => action.id === "drop_then_resume").enabled, false);
  assert.equal(zero.find((action) => action.id === "resume").enabled, true);
});

test("monitoring cannot be released until normalization requests administrator approval", () => {
  assert.deepEqual(incidentActions({ ...incident, state: "monitoring" }, {}), []);
  const actions = incidentActions(
    { ...incident, state: "admin_release_required" },
    {},
  );
  assert.deepEqual(actions.map((action) => action.id), ["complete_monitoring"]);
});

test("battery slots retain three-card UI with missing devices", () => {
  const slots = beaconSlots({
    stale: false,
    beacons: [{ connected: true, available_for_drop: true, percent: 72 }],
  });
  assert.equal(slots.length, 3);
  assert.equal(slots[0].availableForDrop, true);
  assert.equal(slots[1].connected, false);
  const staleSlots = beaconSlots({
    stale: true,
    beacons: [{ connected: true, available_for_drop: true, percent: 72 }],
  });
  assert.equal(staleSlots[0].connected, false);
  assert.equal(staleSlots[0].availableForDrop, false);
  assert.equal(staleSlots[0].percent, null);
  const installedSlots = beaconSlots({
    stale: false,
    beacons: [{ connected: false, installed: true, percent: 72 }],
  });
  assert.equal(installedSlots[0].installed, true);
  assert.equal(installedSlots[0].availableForDrop, false);
});

test("battery payload validation fails closed for stale or incomplete data", () => {
  assert.equal(normalizeDispenserBattery(undefined), null);
  assert.equal(normalizeDispenserBattery({ expected: 3, connected: 2 }), null);
  assert.equal(normalizeDispenserBattery({
    expected: 3,
    connected: 0,
    available_for_drop: 1,
    stale: false,
    beacons: [],
  }), null);
  assert.equal(normalizeDispenserBattery({
    expected: 3,
    connected: 2,
    available_for_drop: 1,
    beacons: [],
  }), null);
  assert.deepEqual(
    normalizeDispenserBattery({
      expected: 3,
      connected: 2,
      available_for_drop: 2,
      stale: true,
      beacons: [],
    }),
    {
      expected: 3,
      connected: 2,
      available_for_drop: 0,
      stale: true,
      beacons: [],
    },
  );
});

test("map markers distinguish installed and field-check estimates", () => {
  const installed = incidentMapMarkers([
    {
      ...incident,
      decision: "drop_then_monitor",
      state: "monitoring",
      beacon_pose_available: true,
      beacon_frame_id: "map",
      beacon_x: 2.4,
      beacon_y: -0.8,
    },
  ]);
  const check = incidentMapMarkers([
    {
      ...incident,
      decision: "drop_then_monitor",
      state: "field_check_required",
      beacon_pose_available: true,
      beacon_frame_id: "map",
      beacon_x: 2.4,
      beacon_y: -0.8,
    },
  ]);

  assert.equal(installed[0].state, "installed");
  assert.equal(installed[0].x, 2.4);
  assert.equal(check[0].state, "check");
  assert.deepEqual(incidentMapMarkers([
    { ...incident, decision: "drop_then_monitor", state: "monitoring" },
  ]), []);
});
