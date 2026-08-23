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
    { ...incident, decision: "drop_then_monitor", state: "monitoring" },
  ]);
  const check = incidentMapMarkers([
    { ...incident, decision: "drop_then_monitor", state: "field_check_required" },
  ]);

  assert.equal(installed[0].state, "installed");
  assert.equal(check[0].state, "check");
});
