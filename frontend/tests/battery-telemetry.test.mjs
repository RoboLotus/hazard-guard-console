import test from "node:test";
import assert from "node:assert/strict";

import { batteryPresentation } from "../src/batteryTelemetry.js";


test("실물 배터리 잔량과 전압을 현재 카드 형식으로 표시한다", () => {
  assert.deepEqual(
    batteryPresentation({
      battery_percent: 63.6,
      battery_voltage: 11.84,
      battery_stale: false,
    }),
    {
      available: true,
      percent: 64,
      percentLabel: "64%",
      voltageLabel: "11.8 V",
      meterWidth: 64,
      level: "normal",
    },
  );
});


test("오래됐거나 없는 배터리 값은 목업 수치 대신 데이터 없음으로 표시한다", () => {
  for (const telemetry of [null, {}, {
    battery_percent: 78,
    battery_voltage: 12.0,
    battery_stale: true,
  }]) {
    const result = batteryPresentation(telemetry);
    assert.equal(result.available, false);
    assert.equal(result.percentLabel, "—");
    assert.equal(result.voltageLabel, "데이터 없음");
    assert.equal(result.meterWidth, 0);
  }
});


test("잔량 범위를 제한하고 낮은 배터리 상태를 구분한다", () => {
  assert.equal(batteryPresentation({
    battery_percent: 18,
    battery_stale: false,
  }).level, "danger");
  assert.equal(batteryPresentation({
    battery_percent: 30,
    battery_stale: false,
  }).level, "warning");
  assert.equal(batteryPresentation({
    battery_percent: 120,
    battery_stale: false,
  }).percent, 100);
});
