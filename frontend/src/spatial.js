export const fallbackSpatialState = {
  source: "mock",
  mock: true,
  map: {
    map_id: "mock:facility-v1",
    frame_id: "map",
    width: 240,
    height: 180,
    resolution: 0.05,
    origin_x: -6,
    origin_y: -4.5,
    source: "mock:slam-map",
  },
  pose: {
    available: true,
    frame_id: "map",
    x: -2.4,
    y: -2.55,
    yaw: 0.12,
    mock: true,
  },
  trail: [
    { x: -3.2, y: -3.2 },
    { x: -3.05, y: -2.95 },
    { x: -2.8, y: -2.72 },
    { x: -2.4, y: -2.55 },
  ],
  sensors: [
    {
      id: "depth",
      label: "Depth",
      display_name: "Depth",
      model: "Nuwa-HP60C",
      horizontal_fov_deg: 73.8,
      range_min_m: 0.2,
      range_max_m: 4,
      range_note: "제조사 깊이 측정 범위",
      color: "#2675d8",
    },
    {
      id: "thermal",
      label: "Thermal",
      display_name: "TMC160B",
      model: "ThermoEye TMC160B",
      resolution: "160×120",
      frame_rate_hz: 8.7,
      horizontal_fov_deg: 57,
      range_min_m: 0,
      range_max_m: 5,
      range_note: "시뮬레이션 시야 표시 범위(제조사 측정거리 아님)",
      temperature_high_gain_c: [-10, 140],
      temperature_low_gain_c: [-10, 400],
      color: "#e45832",
    },
  ],
  heatmap: {
    available: true,
    simulated: true,
    minimum_c: 20,
    maximum_c: 84.6,
    detections: [
      { detection_id: "mock-pump-p02", x: 1.8, y: 1.2, temperature_c: 84.6, confidence: 0.94, radius_m: 0.48, simulated: true, source: "simulation:pump_block", age_sec: 0 },
      { detection_id: "mock-partition-p01", x: -0.3, y: -1.3, temperature_c: 63.2, confidence: 0.86, radius_m: 0.38, simulated: true, source: "simulation:center_partition", age_sec: 0 },
      { detection_id: "mock-tank-normal", x: -1.8, y: 1.8, temperature_c: 46.8, confidence: 0.8, radius_m: 0.52, simulated: true, source: "simulation:tank_block", age_sec: 0 },
    ],
  },
};

export function sensorLegend(spatialState, sensorId) {
  const sensor = spatialState?.sensors?.find((item) => item.id === sensorId);
  if (!sensor) return null;
  const name = sensor.display_name || sensor.label || sensor.model || sensor.id;
  const fov = Number(sensor.horizontal_fov_deg);
  return Number.isFinite(fov) ? `${name} ${fov}°` : name;
}

export function resolveMapSpec(mediaStatus, spatialState) {
  const mapInfo = mediaStatus?.map;
  const metadata = mapInfo?.metadata;
  const fallback = spatialState?.map || fallbackSpatialState.map;
  return {
    map_id: metadata?.map_id || fallback.map_id || "legacy",
    frame_id: metadata?.frame_id || fallback.frame_id || "map",
    width: mapInfo?.width || fallback.width,
    height: mapInfo?.height || fallback.height,
    resolution: metadata?.resolution ?? fallback.resolution,
    origin_x: metadata?.origin_x ?? fallback.origin_x,
    origin_y: metadata?.origin_y ?? fallback.origin_y,
  };
}

export function mapToGrid(x, y, mapSpec) {
  if (
    !mapSpec
    || !Number.isFinite(x)
    || !Number.isFinite(y)
    || !Number.isFinite(mapSpec.resolution)
    || mapSpec.resolution <= 0
  ) return null;
  return {
    x: (x - mapSpec.origin_x) / mapSpec.resolution,
    y: mapSpec.height - (y - mapSpec.origin_y) / mapSpec.resolution,
  };
}

export function buildFovPolygon(pose, sensor, mapSpec, segments = 24) {
  if (!pose?.available || !sensor || !mapSpec) return "";
  const origin = mapToGrid(pose.x, pose.y, mapSpec);
  if (!origin) return "";
  const halfAngle = (sensor.horizontal_fov_deg * Math.PI) / 360;
  const centerAngle = pose.yaw + (sensor.mount_yaw_rad || 0);
  const points = [`${origin.x.toFixed(2)},${origin.y.toFixed(2)}`];
  for (let index = 0; index <= segments; index += 1) {
    const angle = centerAngle - halfAngle + (index / segments) * halfAngle * 2;
    const x = pose.x + sensor.range_max_m * Math.cos(angle);
    const y = pose.y + sensor.range_max_m * Math.sin(angle);
    const point = mapToGrid(x, y, mapSpec);
    if (point) points.push(`${point.x.toFixed(2)},${point.y.toFixed(2)}`);
  }
  return points.join(" ");
}

export const DISPENSER_FOOTPRINT = [
  { x: -0.41, y: -0.155 },
  { x: -0.41, y: 0.155 },
  { x: 0.19, y: 0.155 },
  { x: 0.19, y: -0.155 },
];

export function buildFootprintPolygon(
  pose,
  mapSpec,
  footprint = DISPENSER_FOOTPRINT,
) {
  if (!pose?.available || !mapSpec) return "";
  const cosine = Math.cos(pose.yaw || 0);
  const sine = Math.sin(pose.yaw || 0);
  return footprint
    .map((point) => {
      const worldX = pose.x + point.x * cosine - point.y * sine;
      const worldY = pose.y + point.x * sine + point.y * cosine;
      return mapToGrid(worldX, worldY, mapSpec);
    })
    .filter(Boolean)
    .map((point) => `${point.x.toFixed(2)},${point.y.toFixed(2)}`)
    .join(" ");
}

export function waypointToGrid(waypoint, mapSpec) {
  if (!waypoint || !mapSpec) return null;
  return mapToGrid(waypoint.x, waypoint.y, mapSpec);
}

export function temperatureColor(temperature) {
  if (temperature >= 80) return "#d8323c";
  if (temperature >= 60) return "#ed7b2f";
  if (temperature >= 45) return "#f2b63f";
  return "#5ab89a";
}

export function detectionColor(detection) {
  const status = detection?.trend_status;
  if (status === "critical") return "#d8323c";
  if (status === "warning") return "#ed7b2f";
  if (status === "watch") return "#f2b63f";
  if (status === "normal") return "#5ab89a";
  return temperatureColor(detection?.temperature_c);
}

export function detectionLevel(detection) {
  const labels = {
    critical: "위험",
    warning: "추세 경고",
    watch: "관찰",
    normal: "정상",
  };
  return labels[detection?.trend_status] || temperatureLevel(detection?.temperature_c);
}

export function temperatureLevel(temperature) {
  if (temperature >= 80) return "위험";
  if (temperature >= 60) return "주의";
  return "관측";
}

export function detectionOpacity(detection) {
  const age = Math.max(0, Number(detection?.age_sec) || 0);
  const freshness = Math.max(0.28, 1 - age / 90);
  const confidence = Math.max(0.35, Math.min(1, Number(detection?.confidence) || 0));
  return Number((freshness * confidence).toFixed(3));
}
const EQUIPMENT_LABELS = {
  primary_shredder_motor: "1차 파쇄기 모터",
  secondary_processor_pump: "2차 처리기 펌프",
  baler_hydraulic_tank: "압축기 유압 탱크",
  bunker_waste_pile: "벙커 폐기물 더미",
};

function equipmentLabel(detection) {
  const equipmentId = detection?.equipment_id || detection?.detection_id || "unknown";
  return EQUIPMENT_LABELS[equipmentId]
    || String(equipmentId).replace(/^thermal-/, "").replaceAll("_", " ");
}

function eventTimestamp(value) {
  const parsed = new Date(value || Date.now());
  const safe = Number.isNaN(parsed.getTime()) ? new Date() : parsed;
  return {
    date: safe.toLocaleDateString("sv-SE"),
    time: safe.toLocaleTimeString("ko-KR", { hour12: false }),
  };
}

export function thermalDetectionsToEvents(detections = []) {
  return detections
    .filter((detection) => {
      const status = String(detection?.trend_status || "").split(":")[0];
      const temperature = Number(detection?.temperature_c);
      return ["critical", "warning", "watch"].includes(status)
        || temperature >= 60;
    })
    .map((detection) => {
      const temperature = Number(detection.temperature_c);
      const status = String(detection?.trend_status || "").split(":")[0];
      const critical = status === "critical" || temperature >= 80;
      const label = equipmentLabel(detection);
      const timestamp = eventTimestamp(detection.updated_at);
      const x = Number(detection.x);
      const y = Number(detection.y);
      const coordinate = Number.isFinite(x) && Number.isFinite(y)
        ? `map (${x.toFixed(2)}, ${y.toFixed(2)})`
        : "map 좌표 미확인";
      const reason = detection.trend_reason
        || String(detection.source || "").split(":")[3]
        || "";
      const trendLabel = status === "critical"
        ? "즉시 고온 위험"
        : reason === "persistent_trend_and_environment_adjusted_anomaly"
          ? "장기 상승 추세 경고"
          : reason === "persistent_trend_only"
            ? "장기 상승 추세 관찰"
            : reason === "environment_adjusted_anomaly_only"
              ? "환경 대비 온도 이상 관찰"
              : status === "warning"
                ? "장기 상승 추세 경고"
                : status === "watch"
                  ? "온도 이상 관찰"
                  : "온도 임계값 초과";
      const baseDetectionId = detection.detection_id
        || `thermal-${detection.equipment_id || `${x}-${y}`}`;
      const detectionId = detection.visit_index == null
        ? baseDetectionId
        : `${baseDetectionId}-visit-${detection.visit_index}`;

      return {
        id: detectionId,
        code: `THERM-${String(detection.equipment_id || detectionId).toUpperCase()}`,
        level: critical ? "critical" : "warning",
        status: "new",
        title: critical ? "고온 위험 감지" : "온도 이상 감지",
        ...timestamp,
        location: `${label} · ${coordinate}`,
        temperature: Number.isFinite(temperature) ? `${temperature.toFixed(1)}°C` : null,
        threshold: trendLabel,
        detail: `${label}에서 ${trendLabel} 판정이 발생했습니다.`,
        acknowledged: false,
        assignee: "미지정",
        note: detection.simulated
          ? "시뮬레이션 열화상 카메라의 실측 프레임에서 생성된 이벤트입니다."
          : "로봇 열화상 카메라의 실측 프레임에서 생성된 이벤트입니다.",
        equipmentId: detection.equipment_id || null,
        visitIndex: detection.visit_index ?? null,
        source: detection.source || "thermal",
        simulated: Boolean(detection.simulated),
      };
    })
    .sort((left, right) => {
      if (left.level !== right.level) return left.level === "critical" ? -1 : 1;
      return `${right.date} ${right.time}`.localeCompare(`${left.date} ${left.time}`);
    });
}
