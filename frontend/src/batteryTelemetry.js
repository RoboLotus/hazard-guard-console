export function batteryPresentation(telemetry) {
  const rawPercent = Number(telemetry?.battery_percent);
  const rawVoltage = Number(telemetry?.battery_voltage);
  const available = telemetry?.battery_stale === false
    && telemetry?.battery_percent != null
    && Number.isFinite(rawPercent);
  if (!available) {
    return {
      available: false,
      percent: null,
      percentLabel: "—",
      voltageLabel: "데이터 없음",
      meterWidth: 0,
      level: "unavailable",
    };
  }

  const percent = Math.round(Math.min(100, Math.max(0, rawPercent)));
  return {
    available: true,
    percent,
    percentLabel: `${percent}%`,
    voltageLabel: telemetry?.battery_voltage != null
      && Number.isFinite(rawVoltage) && rawVoltage > 0
      ? `${rawVoltage.toFixed(1)} V`
      : "전압 수신 중",
    meterWidth: percent,
    level: percent <= 20 ? "danger" : percent <= 35 ? "warning" : "normal",
  };
}
