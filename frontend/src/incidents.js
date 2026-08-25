const INCIDENT_STATUS = {
  approval_required: "new",
  dispensing: "working",
  monitoring: "working",
  admin_release_required: "working",
  field_check_required: "working",
  hardware_error: "working",
  resuming: "working",
  resolved: "resolved",
  canceled: "resolved",
};

export const incidentStateLabels = {
  approval_required: "관리자 승인 대기",
  dispensing: "비콘 배출 중",
  monitoring: "현장 감시 중",
  admin_release_required: "관리자 재개 확인 필요",
  field_check_required: "현장 확인 필요",
  hardware_error: "장치 오류 확인 필요",
  resuming: "순찰 재개 중",
  resolved: "처리 완료",
  canceled: "취소됨",
};

export const incidentDecisionLabels = {
  resume: "비콘 없이 순찰 재개",
  drop_then_resume: "비콘 1개 배출 후 순찰 재개",
  drop_then_monitor: "비콘 1개 배출 후 해당 지점 감시",
  complete_monitoring: "감시 종료 후 순찰 재개",
  acknowledge_field_check: "현장 확인 완료 후 순찰 재개",
};

function safeDate(value) {
  const parsed = new Date(value || Date.now());
  return Number.isNaN(parsed.getTime()) ? new Date() : parsed;
}

function incidentVisitIndex(incident) {
  const explicit = Number(incident?.visit_index);
  if (Number.isInteger(explicit) && explicit >= 1) return explicit;
  const match = String(incident?.incident_id || "").match(/:visit-(\d+)$/);
  if (!match) return null;
  const parsed = Number(match[1]);
  return Number.isInteger(parsed) && parsed >= 1 ? parsed : null;
}

function equipmentVisitKey(equipmentId, visitIndex) {
  const equipment = String(equipmentId || "").trim();
  const visit = Number(visitIndex);
  if (!equipment || !Number.isInteger(visit) || visit < 1) return null;
  return `${equipment}:visit-${visit}`;
}

export function incidentToEvent(incident) {
  const date = safeDate(incident.observed_at || incident.created_at);
  const temperature = Number(incident.temperature_c);
  const x = Number(incident.x);
  const y = Number(incident.y);
  const equipment = incident.equipment_id || "설비 미지정";
  const coordinate = Number.isFinite(x) && Number.isFinite(y)
    ? `map (${x.toFixed(2)}, ${y.toFixed(2)})`
    : "위치 미확인";
  return {
    id: incident.incident_id,
    code: incident.incident_id,
    detectionId: incident.detection_id,
    level: ["critical", "warning", "watch"].includes(incident.severity)
      ? incident.severity
      : "warning",
    status: INCIDENT_STATUS[incident.state] || "working",
    title: incident.severity === "critical" ? "고온 위험 승인 요청" : "온도 이상 승인 요청",
    date: date.toLocaleDateString("sv-SE"),
    time: date.toLocaleTimeString("ko-KR", { hour12: false }),
    location: `${equipment} · ${coordinate}`,
    temperature: Number.isFinite(temperature) ? `${temperature.toFixed(1)}°C` : null,
    threshold: "설비별 위험 판정 정책",
    detail: incident.message || incidentStateLabels[incident.state] || "관리자 확인이 필요합니다.",
    acknowledged: incident.state !== "approval_required",
    assignee: incident.operator_id || "관리자 대기",
    note: incidentStateLabels[incident.state] || "Robot 임무 관리자 상태를 확인하세요.",
    equipmentId: incident.equipment_id || null,
    visitIndex: incidentVisitIndex(incident),
    incident,
  };
}

export function mergeIncidentEvents(thermalEvents = [], incidents = []) {
  const incidentEvents = incidents.map(incidentToEvent);
  const authoritativeDetectionIds = new Set(
    incidents.map((incident) => incident.detection_id).filter(Boolean),
  );
  const authoritativeVisitKeys = new Set(
    incidents
      .map((incident) => equipmentVisitKey(
        incident.equipment_id,
        incidentVisitIndex(incident),
      ))
      .filter(Boolean),
  );
  return [
    ...incidentEvents,
    ...thermalEvents.filter((event) => {
      const detectionId = event.detectionId || event.id;
      const visitKey = equipmentVisitKey(event.equipmentId, event.visitIndex);
      return !authoritativeDetectionIds.has(detectionId)
        && (!visitKey || !authoritativeVisitKeys.has(visitKey));
    }),
  ];
}

export function incidentActions(incident, battery) {
  if (!incident) return [];
  const available = !battery?.stale && Number(battery?.available_for_drop || 0) > 0;
  if (incident.state === "approval_required") {
    return [
      { id: "resume", label: incidentDecisionLabels.resume, tone: "neutral", enabled: true },
      {
        id: "drop_then_resume",
        label: incidentDecisionLabels.drop_then_resume,
        tone: "primary",
        enabled: available,
        disabledReason: available ? null : "배출 가능한 비콘이 없습니다.",
      },
      {
        id: "drop_then_monitor",
        label: incidentDecisionLabels.drop_then_monitor,
        tone: "warning",
        enabled: available,
        disabledReason: available ? null : "배출 가능한 비콘이 없습니다.",
      },
    ];
  }
  if (incident.state === "admin_release_required") {
    return [{
      id: "complete_monitoring",
      label: incidentDecisionLabels.complete_monitoring,
      tone: "primary",
      enabled: true,
    }];
  }
  if (["field_check_required", "hardware_error"].includes(incident.state)) {
    return [{
      id: "acknowledge_field_check",
      label: incidentDecisionLabels.acknowledge_field_check,
      tone: "warning",
      enabled: true,
    }];
  }
  return [];
}

export function beaconSlots(battery, count = 3) {
  const beacons = Array.isArray(battery?.beacons) ? battery.beacons : [];
  return Array.from({ length: count }, (_, index) => {
    const beacon = beacons[index];
    if (!beacon) {
      return {
        slot: index + 1,
        connected: false,
        availableForDrop: false,
        batteryState: battery?.stale ? "stale" : "unknown",
        percent: null,
      };
    }
    return {
      slot: index + 1,
      connected: Boolean(beacon.connected) && !battery?.stale,
      availableForDrop: Boolean(beacon.available_for_drop) && !battery?.stale,
      installed: Boolean(beacon.installed),
      batteryState: battery?.stale ? "stale" : (beacon.battery_state || "unknown"),
      percent: !battery?.stale && beacon.percent != null && Number.isFinite(Number(beacon.percent))
        ? Math.round(Number(beacon.percent))
        : null,
      address: beacon.address,
    };
  });
}

export function normalizeDispenserBattery(battery) {
  const expected = Number(battery?.expected);
  const connected = Number(battery?.connected);
  const available = Number(battery?.available_for_drop);
  if (
    !battery
    || typeof battery.stale !== "boolean"
    || !Array.isArray(battery.beacons)
    || !Number.isInteger(expected)
    || !Number.isInteger(connected)
    || !Number.isInteger(available)
    || expected < 0
    || connected < 0
    || available < 0
    || connected > expected
    || available > connected
  ) return null;
  const stale = battery.stale;
  return {
    ...battery,
    expected,
    connected,
    available_for_drop: stale || battery.enabled === false ? 0 : available,
    beacons: battery.beacons,
    stale,
  };
}

export function incidentMapMarkers(incidents = []) {
  return incidents.flatMap((incident) => {
    if (!String(incident.decision || "").startsWith("drop_then_")) return [];
    if (!incident.beacon_pose_available) return [];
    const x = Number(incident.beacon_x);
    const y = Number(incident.beacon_y);
    if (!Number.isFinite(x) || !Number.isFinite(y)) return [];
    const requiresCheck = ["field_check_required", "hardware_error"].includes(incident.state);
    const installed = [
      "monitoring", "admin_release_required", "resuming", "resolved",
    ].includes(incident.state);
    if (!requiresCheck && !installed) return [];
    return [{
      id: incident.incident_id,
      x,
      y,
      frame_id: incident.beacon_frame_id || "map",
      state: requiresCheck ? "check" : "installed",
      label: requiresCheck ? "배출 위치 확인 필요" : "비콘 설치 위치",
    }];
  });
}
