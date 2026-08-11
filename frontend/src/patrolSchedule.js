export function toLocalDateTimeInput(date) {
  const value = date instanceof Date ? date : new Date(date);
  if (Number.isNaN(value.getTime())) return "";
  const pad = (part) => String(part).padStart(2, "0");
  return `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}`
    + `T${pad(value.getHours())}:${pad(value.getMinutes())}`;
}

export function createDefaultPatrolSchedule(now = new Date()) {
  const closing = new Date(now);
  closing.setHours(18, 0, 0, 0);
  if (closing <= now) closing.setDate(closing.getDate() + 1);
  return {
    startMode: "now",
    startAt: "",
    repeatMode: "once",
    repeatCount: 2,
    repeatIntervalMinutes: 10,
    endAt: toLocalDateTimeInput(closing),
  };
}

export function normalizePatrolSchedule(value, now = new Date()) {
  const defaults = createDefaultPatrolSchedule(now);
  if (!value || typeof value !== "object") return defaults;
  return {
    startMode: value.startMode === "scheduled" ? "scheduled" : "now",
    startAt: typeof value.startAt === "string" ? value.startAt : "",
    repeatMode: ["once", "count", "until_time", "forever"].includes(value.repeatMode)
      ? value.repeatMode
      : "once",
    repeatCount: Math.max(2, Math.min(1000, Number(value.repeatCount) || 2)),
    repeatIntervalMinutes: Math.max(
      0,
      Math.min(1440, Number(value.repeatIntervalMinutes) || 0),
    ),
    endAt: typeof value.endAt === "string" && value.endAt
      ? value.endAt
      : defaults.endAt,
  };
}

export function buildPatrolSchedulePayload(settings, now = new Date()) {
  const normalized = normalizePatrolSchedule(settings, now);
  let startAt = null;
  if (normalized.startMode === "scheduled") {
    const parsedStart = new Date(normalized.startAt);
    if (!normalized.startAt || Number.isNaN(parsedStart.getTime())) {
      throw new Error("예약 시작 시각을 입력하세요.");
    }
    if (parsedStart <= now) {
      throw new Error("예약 시작 시각은 현재보다 뒤여야 합니다.");
    }
    startAt = parsedStart;
  }

  let endAt = null;
  if (normalized.repeatMode === "until_time") {
    const parsedEnd = new Date(normalized.endAt);
    if (!normalized.endAt || Number.isNaN(parsedEnd.getTime())) {
      throw new Error("순찰 종료 시각을 입력하세요.");
    }
    if (parsedEnd <= (startAt || now)) {
      throw new Error("종료 시각은 순찰 시작 시각보다 뒤여야 합니다.");
    }
    endAt = parsedEnd;
  }

  return {
    repeat_mode: normalized.repeatMode,
    repeat_count: normalized.repeatMode === "count" ? normalized.repeatCount : 1,
    repeat_interval_seconds: normalized.repeatMode === "once"
      ? 0
      : normalized.repeatIntervalMinutes * 60,
    start_at: startAt?.toISOString() || null,
    end_at: endAt?.toISOString() || null,
  };
}

export function formatUnixTime(unixMs) {
  if (!Number(unixMs)) return null;
  return new Intl.DateTimeFormat("ko-KR", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(Number(unixMs)));
}
