import assert from "node:assert/strict";
import test from "node:test";

import {
  adaptivePolicyConfirmation,
  effectiveThresholdSummary,
  normalizeEquipmentSettings,
} from "../src/equipmentSettingsModel.js";

test("legacy equipment settings enable the adaptive policy by default", () => {
  const normalized = normalizeEquipmentSettings({
    schema_version: 2,
    equipment: [
      { id: "legacy" },
      { id: "fixed", adaptive_threshold_enabled: false },
    ],
  });

  assert.equal(normalized.equipment[0].adaptive_threshold_enabled, true);
  assert.equal(normalized.equipment[1].adaptive_threshold_enabled, false);
});

test("policy confirmation preserves the critical threshold in fixed mode", () => {
  const confirmation = adaptivePolicyConfirmation(false, "pending");

  assert.match(confirmation.description, /절대 위험온도 판정은 계속/);
  assert.equal(confirmation.impact, "현재 순찰 종료 후 변경됩니다.");
  assert.equal(confirmation.danger, true);
});

test("effective threshold renders the actual voxel range", () => {
  assert.equal(
    effectiveThresholdSummary(
      {
        effective_adaptive_threshold_min_c: 54.5,
        effective_adaptive_threshold_max_c: 61.25,
      },
      { adaptive_delta_c: 10 },
    ),
    "54.5~61.3°C (최근 voxel 범위)",
  );
});

test("missing voxel metadata is explicitly marked as an estimate", () => {
  assert.equal(
    effectiveThresholdSummary(
      { baseline_temperature_c: 42 },
      { adaptive_delta_c: 8 },
    ),
    "50.0°C (설비 기준선 추정)",
  );
  assert.equal(
    effectiveThresholdSummary({}, { adaptive_delta_c: 8 }),
    "기준선 활성화 후 계산",
  );
});
