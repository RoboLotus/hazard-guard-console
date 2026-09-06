export const TELEMETRY_STALE_AFTER_MS = 5_000;

const MODE_LABELS = {
  idle: "대기",
  mapping: "2D 지도 작성 중",
  rgbd_mapping: "3D 지도 수집 중",
  patrol: "자율 순찰 중",
  paused: "일시정지",
  stopped: "정지됨",
  manual: "수동 운행",
};

export function telemetryModeLabel(mode) {
  return MODE_LABELS[mode] || "상태 확인 필요";
}

function finiteNumber(value) {
  if (value == null || typeof value === "boolean" || String(value).trim() === "") return null;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

export function isLiveTelemetry(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  if (value.mock !== false || value.stale === true) return false;
  if (value.age_sec != null && (!Number.isFinite(value.age_sec) || value.age_sec > 5 || value.age_sec < 0)) return false;
  return typeof value.mode === "string" && typeof value.robot_id === "string";
}

export function telemetryPresentation(telemetry, live) {
  const available = Boolean(live && telemetry && telemetry.mock !== true && telemetry.stale !== true);
  const networkRssi = available ? finiteNumber(telemetry.network_rssi_dbm) : null;
  const lidarHz = available ? finiteNumber(telemetry.lidar_hz) : null;
  const speed = available ? finiteNumber(telemetry.speed_mps) : null;
  const networkQuality = available ? telemetry.network_quality : null;
  const lidarStatus = available ? telemetry.lidar_status : null;

  return {
    available,
    mode: available && telemetry.mode ? telemetry.mode : "unknown",
    modeLabel: available && telemetry.mode
      ? telemetryModeLabel(telemetry.mode)
      : "상태 확인 필요",
    networkLabel: networkQuality == null
      ? "확인 필요"
      : networkQuality === "good" ? "양호" : "불안정",
    networkDetail: networkRssi == null ? "데이터 없음" : `${networkRssi.toFixed(0)} dBm`,
    networkHealthy: networkQuality === "good",
    lidarLabel: lidarStatus == null
      ? "확인 필요"
      : lidarStatus === "normal" ? "정상" : "확인 필요",
    lidarDetail: lidarHz == null ? "데이터 없음" : `${lidarHz.toFixed(1)} Hz`,
    lidarHealthy: lidarStatus === "normal",
    speedLabel: speed == null ? "—" : `${speed.toFixed(2)} m/s`,
    speedDetail: speed == null ? "데이터 없음" : "실시간 측정",
  };
}
