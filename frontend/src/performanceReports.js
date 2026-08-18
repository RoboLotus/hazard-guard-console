export function metricValue(metric, key = "mean") {
  const value = metric?.[key];
  if (value === null || value === undefined || value === "") return null;
  return Number.isFinite(Number(value)) ? Number(value) : null;
}

export function formatMetric(metric, key = "mean", digits = 1) {
  const value = metricValue(metric, key);
  return value === null ? "—" : value.toFixed(digits);
}

export function formatDuration(seconds) {
  const total = Math.max(0, Math.round(Number(seconds) || 0));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const remaining = total % 60;
  return [hours, minutes, remaining]
    .map((value) => String(value).padStart(2, "0"))
    .join(":");
}

export function reportStatusLabel(status) {
  return {
    completed: "완료",
    failed: "실패",
    canceled: "취소",
    interrupted: "중단",
  }[status] || "기록됨";
}

export function sortReports(reports) {
  return [...(reports || [])].sort((left, right) =>
    String(right.started_at || "").localeCompare(String(left.started_at || "")),
  );
}
