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
    z: 0,
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
export function matchesMapFrame(item, mapSpec) {
  const itemFrame = item?.frame_id;
  const mapFrame = mapSpec?.frame_id;
  return !itemFrame || !mapFrame || itemFrame === mapFrame;
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
  baler_hydraulic_tank: "베일러 유압 탱크",
  bunker_waste_pile: "폐기물 적치 구역",
};

function equipmentLabel(detection) {
  if (detection?.equipment_name) return detection.equipment_name;
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
      const level = ["critical", "warning", "watch"].includes(status)
        ? status
        : temperature >= 80
          ? "critical"
          : temperature >= 60
            ? "warning"
            : "watch";
      const critical = level === "critical";
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
      const configurationWatch = reason === "baseline_required_not_configured";
      const reasonLabels = {
        baseline_required_not_configured: "설비 정상 기준값 미설정",
        persistent_trend_and_baseline_residual: "장기 상승·기준선 이탈 경고",
        persistent_trend_and_environment_adjusted_anomaly: "장기 상승 추세 경고",
        persistent_trend_only: "장기 상승 추세 관찰",
        environment_adjusted_anomaly_only: "환경 대비 온도 이상 관찰",
        warning_approved_baseline_delta: "승인 기준선 대비 온도 상승 경고",
        critical_approved_baseline_delta: "승인 기준선 대비 고온 위험",
        watch_baseline_delta_pending_confirmation: "기준선 이탈 재확인 필요",
        baseline_critical_candidate_requires_corroboration: "고온 후보 교차 확인 필요",
        surface_screening_requires_direct_sensor_confirmation: "직접 온도 센서 확인 필요",
        critical_p95_temperature: "고정 위험온도 초과",
        trend_and_adaptive: "지속 상승·가변 기준 동시 충족",
        trend_only_recheck: "지속 상승 추세 재확인",
        adaptive_only_recheck: "가변 기준 이탈 재확인",
        adaptive_disabled: "고정 임계값 모드",
        baseline_pending: "정상 기준선 수집 중",
      };
      const trendLabel = reasonLabels[reason]
        || (status === "critical"
          ? "즉시 고온 위험"
          : status === "warning"
            ? "온도 상승 경고"
            : status === "watch"
              ? "온도 이상 관찰"
              : "온도 임계값 초과");
      const baseDetectionId = detection.detection_id
        || `thermal-${detection.equipment_id || `${x}-${y}`}`;
      const detectionId = detection.visit_index == null
        ? baseDetectionId
        : `${baseDetectionId}-visit-${detection.visit_index}`;
      const policyLabel = detection.policy_mode === "fixed_only"
        ? "고정 임계값"
        : detection.policy_mode === "adaptive_assisted"
          ? "자동 가변 기준"
          : "판정 정책 확인 중";
      const effectiveThreshold = detection.effective_adaptive_threshold_c == null
        ? Number.NaN
        : Number(detection.effective_adaptive_threshold_c);
      const residual = detection.baseline_residual_c == null
        ? Number.NaN
        : Number(detection.baseline_residual_c);
      const residualThreshold = detection.baseline_residual_threshold_c == null
        ? Number.NaN
        : Number(detection.baseline_residual_threshold_c);
      const policyDetail = [
        policyLabel,
        Number.isFinite(effectiveThreshold) ? `실효 임계점 ${effectiveThreshold.toFixed(1)}°C` : null,
        Number.isFinite(residual) && Number.isFinite(residualThreshold)
          ? `기준선 잔차 ${residual.toFixed(1)}/${residualThreshold.toFixed(1)}°C`
          : null,
      ].filter(Boolean).join(" · ");

      return {
        id: detectionId,
        code: `THERM-${String(detection.equipment_id || detectionId).toUpperCase()}`,
        level,
        status: "new",
        title: configurationWatch
          ? "설비 기준값 설정 필요"
          : critical
            ? "고온 위험 감지"
            : level === "warning"
              ? "온도 상승 경고"
              : "온도 이상 관찰",
        ...timestamp,
        location: `${label} · ${coordinate}`,
        temperature: Number.isFinite(temperature) ? `${temperature.toFixed(1)}°C` : null,
        threshold: trendLabel,
        detail: configurationWatch
          ? `${label}의 정상 운전 기준값을 등록해야 온도 판정을 시작할 수 있습니다.`
          : `${label}에서 ${trendLabel} 판정이 발생했습니다. ${policyDetail}`,
        acknowledged: false,
        assignee: "미지정",
        note: detection.simulated
          ? "시뮬레이션 열화상 카메라의 실측 프레임에서 생성된 이벤트입니다."
          : "로봇 열화상 카메라의 실측 프레임에서 생성된 이벤트입니다.",
        equipmentId: detection.equipment_id || null,
        visitIndex: detection.visit_index ?? null,
        source: detection.source || "thermal",
        policyMode: detection.policy_mode || null,
        simulated: Boolean(detection.simulated),
      };
    })
    .sort((left, right) => {
      const severity = { watch: 1, warning: 2, critical: 3 };
      if (left.level !== right.level) {
        return (severity[right.level] || 0) - (severity[left.level] || 0);
      }
      return `${right.date} ${right.time}`.localeCompare(`${left.date} ${left.time}`);
    });
}

export function gasEventsToEvents(gasEvents = []) {
  const reasonLabels = {
    voc_rise_requires_stationary_recheck: "VOC 급상승 정지 재측정",
    persistent_voc_requires_local_search: "지속 VOC 이상 위치 탐색 필요",
    co_confirms_combustion_risk: "CO 동반 연소 위험",
    co_critical_with_gas_plume: "고농도 CO 긴급 위험",
    gas_clearance_hold: "가스 정상화 확인 대기",
    co_absolute_critical: "CO 절대 긴급 기준 초과",
    thermal_absolute_critical: "동일 설비 절대 위험온도 초과",
    voc_co_thermal_corroborated: "VOC·CO·열화상 3중 확인",
    co_and_thermal_warning_corroborated: "CO·열화상 복합 경고 확인",
    co_warning: "CO 경고 기준 초과",
    thermal_warning: "동일 설비 열화상 경고",
    voc_and_thermal_watch_corroborated: "VOC·열화상 복합 이상 확인",
    persistent_voc_across_locations: "다지점 VOC 지속 이상",
    voc_early_watch: "VOC 조기 이상 관찰",
    thermal_watch: "동일 설비 열화상 관찰",
  };
  return gasEvents
    .filter((event) => ["watch", "warning", "critical"].includes(event?.level))
    .map((event) => {
      const timestamp = eventTimestamp(event.updated_at);
      const peakX = event.peak_x == null ? Number.NaN : Number(event.peak_x);
      const peakY = event.peak_y == null ? Number.NaN : Number(event.peak_y);
      const x = Number.isFinite(peakX) ? peakX : Number(event.x);
      const y = Number.isFinite(peakY) ? peakY : Number(event.y);
      const coordinate = Number.isFinite(x) && Number.isFinite(y)
        ? `${event.frame_id || "odom"} (${x.toFixed(2)}, ${y.toFixed(2)})`
        : "측정 위치 미확인";
      const voc = Number(event.voc_index);
      const co = Number(event.co_ppm);
      const co2 = Number(event.co2_ppm);
      const values = [
        Number.isFinite(voc) ? `VOC ${voc.toFixed(0)}` : null,
        Number.isFinite(co) ? `CO ${co.toFixed(1)} ppm` : null,
        Number.isFinite(co2) ? `CO₂ ${co2.toFixed(0)} ppm` : null,
      ].filter(Boolean).join(" · ");
      const samples = Number(event.search_samples);
      const locations = Number(event.search_location_count);
      const thermalTemperature = Number(event.thermal_temperature_c);
      const thermalDetail = Number.isFinite(thermalTemperature)
        ? ` · 열화상 ${thermalTemperature.toFixed(1)}°C (${event.thermal_status || "확인"})`
        : "";
      const reason = reasonLabels[event.reason] || "가스 이상 확인 필요";
      return {
        id: event.event_id || `gas-${event.source_id || Date.now()}`,
        code: `GAS-${String(event.source_id || "UNKNOWN").toUpperCase()}`,
        level: event.level,
        status: "new",
        title: event.title || "가스 이상 감지",
        ...timestamp,
        location: `${event.source_name || "가스 측정 구역"} · ${coordinate}`,
        temperature: null,
        threshold: reason,
        detail: `${reason}. ${values}${thermalDetail}${Number.isFinite(samples) ? ` · 측정 ${samples}회` : ""}${Number.isFinite(locations) ? ` · 이동 지점 ${locations}곳` : ""}`,
        acknowledged: false,
        assignee: "미지정",
        note: event.simulated
          ? "시뮬레이션 가스 확산 및 센서 지연 모델에서 생성된 이벤트입니다."
          : "로봇 가스 센서에서 생성된 이벤트입니다.",
        equipmentId: event.equipment_id || null,
        source: "gas_fusion",
        simulated: Boolean(event.simulated),
      };
    });
}
