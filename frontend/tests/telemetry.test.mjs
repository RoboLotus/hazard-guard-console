import assert from "node:assert/strict";
import test from "node:test";

import {
  TELEMETRY_STALE_AFTER_MS,
  telemetryPresentation,
} from "../src/telemetry.js";

test("텔레메트리 유예시간은 순간 지연을 허용하는 5초다", () => {
  assert.equal(TELEMETRY_STALE_AFTER_MS, 5_000);
});

test("미연결 상태는 고정 목업값 대신 데이터 없음으로 표시한다", () => {
  assert.deepEqual(telemetryPresentation(null, false), {
    available: false,
    mode: "unknown",
    modeLabel: "상태 확인 필요",
    networkLabel: "확인 필요",
    networkDetail: "데이터 없음",
    networkHealthy: false,
    lidarLabel: "확인 필요",
    lidarDetail: "데이터 없음",
    lidarHealthy: false,
    speedLabel: "—",
    speedDetail: "데이터 없음",
  });
});

test("연결 상태에서는 수신한 실제 텔레메트리만 표시한다", () => {
  const result = telemetryPresentation({
    mode: "patrol",
    network_quality: "good",
    network_rssi_dbm: -56.4,
    lidar_status: "normal",
    lidar_hz: 9.86,
    speed_mps: 0.274,
  }, true);

  assert.equal(result.modeLabel, "자율 순찰 중");
  assert.equal(result.networkDetail, "-56 dBm");
  assert.equal(result.lidarDetail, "9.9 Hz");
  assert.equal(result.speedLabel, "0.27 m/s");
});

test("연결 표시가 오래되면 보관 중인 과거 값도 노출하지 않는다", () => {
  const result = telemetryPresentation({
    mode: "patrol",
    network_quality: "good",
    network_rssi_dbm: -48,
    lidar_status: "normal",
    lidar_hz: 10.2,
    speed_mps: 0.32,
  }, false);

  assert.equal(result.available, false);
  assert.equal(result.modeLabel, "상태 확인 필요");
  assert.equal(result.speedLabel, "—");
});
