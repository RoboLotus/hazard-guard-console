import { lazy, Suspense, useEffect, useState } from "react";
import {
  Camera,
  Cube,
  Path,
  Robot,
  SlidersHorizontal,
  ThermometerHot,
  MapTrifold,
  VideoCamera,
} from "@phosphor-icons/react";
import slamMap from "../assets/slam-map.webp";
import {
  CollapsibleCard,
  DetailHeading,
  SystemModeControl,
  downloadAsset,
} from "../components/Common.jsx";
import MapPanel from "../components/MapPanel.jsx";
import SimulationMapManager from "../components/SimulationMapManager.jsx";
import WaypointMissionPanel from "../WaypointMissionPanel.jsx";
import {
  fallbackSpatialState,
  resolveMapSpec,
} from "../spatial.js";
import {
  activeWaypoints,
  clearWaypointRoute,
  createWaypoint,
  loadWaypointRoute,
  moveWaypoint,
  routeMapSignature,
  saveWaypointRoute,
  shiftWaypoint,
} from "../waypoints.js";
import {
  buildPatrolSchedulePayload,
  normalizePatrolSchedule,
} from "../patrolSchedule.js";

const PointCloudPanel = lazy(() => import("../components/PointCloudPanel.jsx"));

const personSafetyLabels = {
  CLEAR: "정상",
  CAUTION: "사람 감지 · 거리 확인",
  SLOW: "사람 감지 · 감속",
  STOP: "사람 감지 · 정지",
  SENSOR_FAULT: "센서 확인 필요",
};

export default function MapPage({
  mediaStatus,
  telemetry,
  spatialState,
  systemMode,
  modeBusy,
  onModeChange,
  onInitializeLocalization,
  onSystemModeUpdate,
  onSaveSystemMap,
  onSaveAndStop,
  onStopSystemMode,
  notify,
}) {
  const [goalMode, setGoalMode] = useState(false);
  const [mapDimension, setMapDimension] = useState("2d");
  const [selected3dSession, setSelected3dSession] = useState(null);
  const [goalCandidate, setGoalCandidate] = useState(null);
  const activeWorldId = systemMode?.active_world_id || "facility_map";
  const physicalTarget = systemMode?.deployment_target === "physical";
  const initialRoute = loadWaypointRoute(activeWorldId);
  const [waypoints, setWaypoints] = useState(() => initialRoute?.waypoints || []);
  const [patrolSchedule, setPatrolSchedule] = useState(
    () => normalizePatrolSchedule(initialRoute?.schedule),
  );
  const [savedMapSignature, setSavedMapSignature] = useState(
    () => initialRoute?.mapSignature || null,
  );
  const [selectedWaypointId, setSelectedWaypointId] = useState(null);
  const [repositionWaypointId, setRepositionWaypointId] = useState(null);
  const [missionStatus, setMissionStatus] = useState(null);
  const [navigationStatus, setNavigationStatus] = useState(null);
  const [equipmentOptions, setEquipmentOptions] = useState([]);
  const [routeBusy, setRouteBusy] = useState(false);
  const [layers, setLayers] = useState({
    depth: true,
    thermal: true,
    heatmap: true,
    trail: true,
    footprint: true,
  });
  const mapLive = Boolean(mediaStatus?.map?.available);
  const personSafety = telemetry?.person_safety;
  const personSafetyConnected = Boolean(personSafety?.updated_at);
  const personSafetyName = personSafetyConnected
    ? personSafety.state_name
    : "DISABLED";
  const personSafetyClass = personSafetyName === "CLEAR"
    ? "healthy"
    : ["STOP", "SENSOR_FAULT"].includes(personSafetyName)
      ? "danger"
      : personSafetyName === "DISABLED" ? "" : "warning";
  const personSafetyLabel = personSafetyLabels[personSafetyName]
    || (physicalTarget ? "기능 대기" : "시뮬레이션 비활성");
  const mapSpatialState = physicalTarget
    ? {
        ...spatialState,
        pose: spatialState?.pose?.mock
          ? { ...spatialState.pose, available: false }
          : spatialState?.pose,
        trail: spatialState?.pose?.mock ? [] : spatialState?.trail,
        heatmap: spatialState?.heatmap?.simulated
          ? { ...spatialState.heatmap, detections: [] }
          : spatialState?.heatmap,
      }
    : spatialState;
  const mapSpec = resolveMapSpec(mediaStatus, mapSpatialState);
  const currentMapSignature = routeMapSignature(mapSpec);
  const mapMismatch = Boolean(
    mapLive
    && savedMapSignature
    && savedMapSignature !== currentMapSignature,
  );
  const patrolModeSelected = ["patrol", "rgbd_mapping"].includes(
    systemMode?.mode,
  );
  const patrolModeReady = Boolean(systemMode?.navigation_ready);
  const modeTransitioning = ["starting", "stopping"].includes(systemMode?.state);
  const sensors = spatialState?.sensors || fallbackSpatialState.sensors;
  const heatDetections = spatialState?.heatmap?.detections || [];
  const trendWarnings = heatDetections.filter((item) => ["warning", "critical"].includes(item.trend_status)).length;
  const trendWatches = heatDetections.filter((item) => item.trend_status === "watch").length;
  const navStatusLabels = {
    idle: "대기",
    mock: "Nav2 미연결",
    sending: "전송 중",
    accepted: "이동 준비",
    executing: "이동 중",
    canceling: "취소 중",
    canceled: "취소됨",
    succeeded: "도착",
    rejected: "거부됨",
    failed: "실패",
  };

  useEffect(() => {
    const route = loadWaypointRoute(activeWorldId);
    setWaypoints(route?.waypoints || []);
    setPatrolSchedule(normalizePatrolSchedule(route?.schedule));
    setSavedMapSignature(route?.mapSignature || null);
    setSelectedWaypointId(null);
    setRepositionWaypointId(null);
    setGoalCandidate(null);
    setGoalMode(false);
    setSelected3dSession(null);
  }, [activeWorldId]);

  useEffect(() => {
    const controller = new AbortController();
    const loadEquipment = async () => {
      try {
        const response = await fetch("/api/v1/settings/equipment", {
          cache: "no-store",
          signal: controller.signal,
        });
        if (!response.ok) return;
        const payload = await response.json();
        setEquipmentOptions(
          (payload.equipment || []).filter((equipment) => equipment.enabled),
        );
      } catch (error) {
        if (error.name !== "AbortError") setEquipmentOptions([]);
      }
    };
    void loadEquipment();
    return () => controller.abort();
  }, []);

  useEffect(() => {
    let disposed = false;
    const refresh = async () => {
      try {
        const response = await fetch("/api/v1/navigation/status", { cache: "no-store" });
        if (!disposed && response.ok) setNavigationStatus(await response.json());
      } catch {
        if (!disposed) setNavigationStatus(null);
      }
    };
    void refresh();
    const interval = window.setInterval(refresh, 750);
    return () => { disposed = true; window.clearInterval(interval); };
  }, []);

  useEffect(() => {
    let disposed = false;
    const refreshMission = async () => {
      try {
        const response = await fetch("/api/v1/navigation/route/status", { cache: "no-store" });
        if (!disposed && response.ok) setMissionStatus(await response.json());
      } catch {
        if (!disposed) setMissionStatus(null);
      }
    };
    void refreshMission();
    const interval = window.setInterval(refreshMission, 750);
    return () => { disposed = true; window.clearInterval(interval); };
  }, []);

  const selectGoal = (candidate) => {
    if (repositionWaypointId) {
      setWaypoints((current) => current.map((waypoint) => (
        waypoint.id === repositionWaypointId
          ? { ...waypoint, x: candidate.mapX, y: candidate.mapY }
          : waypoint
      )));
      setSelectedWaypointId(repositionWaypointId);
      setRepositionWaypointId(null);
      setGoalMode(false);
      setGoalCandidate(null);
      setSavedMapSignature(null);
      notify("웨이포인트 위치를 변경했습니다. 경로를 다시 저장하세요.");
      return;
    }
    setGoalCandidate(candidate);
    notify("웨이포인트 위치를 선택했습니다. 이름과 방향을 확인하세요.", "info");
  };

  const addWaypoint = (values) => {
    if (!goalCandidate || goalCandidate.mapX === null || goalCandidate.mapY === null) return;
    const waypoint = createWaypoint(goalCandidate, waypoints.length, values);
    setWaypoints((current) => [...current, waypoint]);
    setSelectedWaypointId(waypoint.id);
    setGoalCandidate(null);
    setSavedMapSignature(null);
    notify(`${waypoint.name} 웨이포인트를 추가했습니다.`);
  };

  const updateWaypoint = (id, patch) => {
    setWaypoints((current) => current.map((waypoint) => (
      waypoint.id === id ? { ...waypoint, ...patch } : waypoint
    )));
    setSavedMapSignature(null);
  };

  const deleteWaypoint = (id) => {
    setWaypoints((current) => current.filter((waypoint) => waypoint.id !== id));
    if (selectedWaypointId === id) setSelectedWaypointId(null);
    setSavedMapSignature(null);
  };

  const reorderWaypoints = (sourceId, targetId) => {
    setWaypoints((current) => moveWaypoint(current, sourceId, targetId));
    setSavedMapSignature(null);
  };

  const shiftWaypointOrder = (id, direction) => {
    setWaypoints((current) => shiftWaypoint(current, id, direction));
    setSavedMapSignature(null);
  };

  const beginReposition = (id) => {
    setSelectedWaypointId(id);
    setRepositionWaypointId(id);
    setGoalCandidate(null);
    setGoalMode(true);
    notify("지도에서 웨이포인트의 새 위치를 클릭하세요.", "info");
  };

  const toggleWaypointMode = () => {
    if (mapDimension !== "2d") {
      setMapDimension("2d");
      setGoalMode(true);
      setGoalCandidate(null);
      setRepositionWaypointId(null);
      notify("웨이포인트를 지정할 수 있도록 2D 지도로 전환했습니다.", "info");
      return;
    }
    const next = !goalMode;
    setGoalMode(next);
    setGoalCandidate(null);
    if (!next) setRepositionWaypointId(null);
  };

  const persistRoute = () => {
    saveWaypointRoute(
      waypoints,
      mapSpec,
      "기본 순찰 경로",
      activeWorldId,
      patrolSchedule,
    );
    setSavedMapSignature(currentMapSignature);
    notify("현재 지도 버전과 함께 순찰 경로를 브라우저에 저장했습니다.");
  };

  const clearRoute = () => {
    setWaypoints([]);
    setSelectedWaypointId(null);
    setGoalCandidate(null);
    setGoalMode(false);
    setRepositionWaypointId(null);
    setSavedMapSignature(null);
    clearWaypointRoute(activeWorldId);
    notify("모든 웨이포인트를 삭제했습니다.", "info");
  };

  const recommendRoute = async () => {
    const enabled = activeWaypoints(waypoints);
    if (enabled.length < 2) return;
    setRouteBusy(true);
    try {
      const response = await fetch("/api/v1/navigation/route/recommend", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: "기본 순찰 경로",
          frame_id: mapSpec.frame_id || "map",
          return_to_start: false,
          waypoints: enabled,
        }),
      });
      const result = await response.json();
      if (!response.ok || !result.accepted || !Array.isArray(result.ordered_ids)) {
        notify(result.detail || result.message || "순찰 순서를 계산하지 못했습니다.", "warning");
        return;
      }
      const byId = new Map(waypoints.map((waypoint) => [waypoint.id, waypoint]));
      const ordered = result.ordered_ids.map((id) => byId.get(id)).filter(Boolean);
      const disabled = waypoints.filter((waypoint) => waypoint.enabled === false);
      setWaypoints([...ordered, ...disabled]);
      setSavedMapSignature(null);
      notify(
        result.mock
          ? "ROS 경로 서버가 없어 직선거리 기준으로 순서를 추천했습니다."
          : `Nav2 경로 비용 기준으로 순서를 추천했습니다. 예상 이동거리 ${result.total_distance_m.toFixed(2)}m`,
        result.mock ? "warning" : "info",
      );
    } catch {
      notify("순찰 순서 추천 API에 연결하지 못했습니다.", "warning");
    } finally {
      setRouteBusy(false);
    }
  };

  const startRoute = async () => {
    const enabled = activeWaypoints(waypoints);
    if (!enabled.length) return;
    if (!patrolModeReady) {
      notify(
        patrolModeSelected
          ? (systemMode?.readiness_message || "AMCL·Nav2 준비가 끝난 뒤 다시 시도하세요.")
          : "맵 생성 모드에서는 순찰을 시작할 수 없습니다. 먼저 순찰 / AMCL·Nav2 모드로 전환하세요.",
        "warning",
      );
      return;
    }
    setRouteBusy(true);
    try {
      const schedulePayload = buildPatrolSchedulePayload(patrolSchedule);
      const response = await fetch("/api/v1/navigation/route", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: "기본 순찰 경로",
          frame_id: mapSpec.frame_id || "map",
          return_to_start: false,
          ...schedulePayload,
          waypoints: enabled,
        }),
      });
      const result = await response.json();
      setMissionStatus(result);
      if (!response.ok || !result.accepted) {
        notify(result.detail || result.message || "순찰 임무를 시작하지 못했습니다.", "warning");
        return;
      }
      notify("경로 안전성 확인 후 순찰을 시작합니다.");
    } catch (error) {
      notify(error?.message || "순찰 임무 API에 연결하지 못했습니다.", "warning");
    } finally {
      setRouteBusy(false);
    }
  };

  const cancelRoute = async () => {
    try {
      const response = await fetch("/api/v1/navigation/route", { method: "DELETE" });
      const result = await response.json();
      setMissionStatus(result);
      notify(result.message, response.ok ? "info" : "warning");
    } catch {
      notify("순찰 중단 요청에 실패했습니다.", "warning");
    }
  };
  const saveMapImage = async () => {
    try {
      await downloadAsset(mapLive ? "/api/v1/media/map" : slamMap, `hazard-guard-map-${new Date().toISOString().slice(0, 10)}.png`);
      notify("현재 지도를 PNG 파일로 저장했습니다.");
    } catch {
      notify("지도를 저장하지 못했습니다. 미디어 서버 연결을 확인하세요.", "warning");
    }
  };
  const toggleLayer = (layer) => {
    setLayers((current) => ({ ...current, [layer]: !current[layer] }));
  };
  const changeMapDimension = (dimension) => {
    setMapDimension(dimension);
    if (dimension !== "2d") {
      setGoalMode(false);
      setGoalCandidate(null);
      setRepositionWaypointId(null);
    }
  };

  return (
    <div className="detail-page map-page">
      <DetailHeading eyebrow="DIGITAL TWIN" title="지도 관제" description="2D 점유 지도, RTAB-Map RGB-D 컬러 포인트클라우드, 캘리브레이션으로 온도를 입힌 열화상 3D 지도를 전환해 확인합니다.">
        <div className="map-dimension-switch" aria-label="지도 표시 방식">
          <button type="button" className={mapDimension === "2d" ? "active" : ""} aria-pressed={mapDimension === "2d"} onClick={() => changeMapDimension("2d")}>
            <MapTrifold size={16} />2D 지도
          </button>
          <button type="button" className={mapDimension === "3d" ? "active" : ""} aria-pressed={mapDimension === "3d"} onClick={() => changeMapDimension("3d")}>
            <Cube size={16} />3D RGB-D
          </button>
          <button type="button" className={mapDimension === "thermal" ? "active" : ""} aria-pressed={mapDimension === "thermal"} onClick={() => changeMapDimension("thermal")}>
            <ThermometerHot size={16} />3D 열화상
          </button>
        </div>
        <span className={`api-status ${mapLive ? "online" : ""}`}><span />{
          physicalTarget
            ? mapLive ? "실물 로봇 지도 연결" : "실물 로봇 데이터 대기"
            : mapLive ? "공간 데이터 연결" : "디지털 트윈 목업"
        }</span>
      </DetailHeading>
      <div className="map-workspace">
        {mapDimension === "2d" ? (
          <MapPanel
            detail
            mediaStatus={mediaStatus}
            spatialState={mapSpatialState}
            layers={layers}
            goalMode={goalMode}
            goalCandidate={goalCandidate}
            waypoints={waypoints}
            selectedWaypointId={selectedWaypointId}
            onWaypointSelect={setSelectedWaypointId}
            onGoalCandidate={selectGoal}
            onLocate={() => notify("현재 로봇 위치를 지도 중앙에 표시했습니다.")}
            waitingForMap={!mapLive && (physicalTarget || systemMode?.mode === "mapping")}
            waitingLabel={physicalTarget ? "실물 ROS /map 수신 대기 중" : undefined}
            allowMockFallback={!physicalTarget}
          />
        ) : (
          <Suspense fallback={<div className="point-cloud-panel point-cloud-loading">3D 지도 뷰어를 불러오는 중입니다.</div>}>
            <PointCloudPanel
              systemMode={systemMode}
              archivedSession={selected3dSession}
              spatialState={spatialState}
              variant={mapDimension === "thermal" ? "thermal" : "rgb"}
            />
          </Suspense>
        )}
        <aside className="map-side-panel">
          <SystemModeControl
            systemMode={systemMode}
            busy={modeBusy}
            onChange={onModeChange}
            onInitializeLocalization={onInitializeLocalization}
          />
          <WaypointMissionPanel
            waypoints={waypoints}
            equipmentOptions={equipmentOptions}
            candidate={goalCandidate}
            goalMode={goalMode}
            repositioning={Boolean(repositionWaypointId)}
            selectedId={selectedWaypointId}
            mapLive={mapLive}
            mapMismatch={mapMismatch}
            patrolModeSelected={patrolModeSelected}
            patrolModeReady={patrolModeReady}
            modeControlEnabled={Boolean(systemMode?.control_enabled)}
            modeTransitioning={modeTransitioning}
            readinessMessage={systemMode?.readiness_message}
            missionStatus={missionStatus}
            schedule={patrolSchedule}
            busy={routeBusy}
            onSelect={setSelectedWaypointId}
            onToggleAdd={toggleWaypointMode}
            onAdd={addWaypoint}
            onCancelCandidate={() => setGoalCandidate(null)}
            onUpdate={updateWaypoint}
            onDelete={deleteWaypoint}
            onMove={reorderWaypoints}
            onShift={shiftWaypointOrder}
            onReposition={beginReposition}
            onStart={startRoute}
            onScheduleChange={(patch) => setPatrolSchedule((current) => ({
              ...current,
              ...patch,
            }))}
            onRequestPatrolMode={() => onModeChange("patrol")}
            onCancelMission={cancelRoute}
            onRecommend={recommendRoute}
            onSave={persistRoute}
            onClear={clearRoute}
          />
          <CollapsibleCard icon={Robot} title="로봇 주행 상태" subtitle="ROS 2 텔레메트리">
            <dl className="status-list">
              <div><dt>운행 모드</dt><dd>{telemetry?.mode === "paused" ? "일시정지" : telemetry?.mode === "stopped" ? "정지" : "자율 순찰"}</dd></div>
              <div><dt>현재 속도</dt><dd>{(telemetry?.speed_mps ?? 0.32).toFixed(2)} m/s</dd></div>
              <div><dt>LiDAR</dt><dd className="healthy">{telemetry?.lidar_status === "error" ? "확인 필요" : "정상"}</dd></div>
              <div><dt>사람 안전</dt><dd className={personSafetyClass}>{personSafetyLabel}{personSafety?.distance_valid ? ` · ${personSafety.nearest_distance_m.toFixed(1)}m` : ""}</dd></div>
              <div><dt>운용 대상</dt><dd>{physicalTarget ? "실물 ROSMASTER M1" : "Gazebo 시뮬레이션"}</dd></div>
              <div><dt>지도 소스</dt><dd>{mapDimension === "thermal" ? "열화상 × Depth 캘리브레이션" : mapDimension === "3d" ? "RTAB-Map RGB-D" : mapLive ? "ROS /map" : physicalTarget ? "센서 대기" : "UI 목업"}</dd></div>
              <div><dt>로봇 위치</dt><dd>{spatialState?.pose?.available ? `X ${spatialState.pose.x.toFixed(2)} · Y ${spatialState.pose.y.toFixed(2)}` : "확인 중"}</dd></div>
              <div><dt>Nav2 상태</dt><dd className={navigationStatus?.status === "executing" ? "healthy" : ""}>{navStatusLabels[navigationStatus?.status] || "확인 중"}</dd></div>
            </dl>
          </CollapsibleCard>
          <CollapsibleCard icon={SlidersHorizontal} title="지도 레이어" subtitle="실시간 표시 선택" className="layer-card">
            <div className="layer-toggle-grid">
              {[
                ["heatmap", "열원 히트맵", ThermometerHot],
                ["depth", "Depth 시야", Camera],
                ["thermal", "Thermal 시야", VideoCamera],
                ["trail", "이동 궤적", Path],
                ["footprint", "실제 충돌 외곽", Robot],
              ].map(([id, label, Icon]) => (
                <button key={id} type="button" className={layers[id] ? "active" : ""} aria-pressed={layers[id]} onClick={() => toggleLayer(id)}>
                  <Icon size={16} weight={layers[id] ? "fill" : "regular"} />
                  <span>{label}</span>
                  <i />
                </button>
              ))}
            </div>
            <div className="sensor-spec-list">
              {sensors.map((sensor) => (
                <div key={sensor.id}>
                  <i className={`sensor-color sensor-color-${sensor.id}`} />
                  <span>
                    <strong>{sensor.model}</strong>
                    <small>{sensor.resolution ? `${sensor.resolution} · ` : ""}수평 {sensor.horizontal_fov_deg}° · {sensor.id === "thermal" ? "표시 " : ""}{sensor.range_min_m}~{sensor.range_max_m}m</small>
                  </span>
                </div>
              ))}
              <p><ThermometerHot size={14} weight="fill" />{heatDetections.length}개 열원 관측 · 장기판정 경고 {trendWarnings} / 관찰 {trendWatches} · {spatialState?.heatmap?.simulated ? "시뮬레이션 데이터" : "센서 데이터"}</p>
            </div>
          </CollapsibleCard>
          <SimulationMapManager
            systemMode={systemMode}
            onSystemModeUpdate={onSystemModeUpdate}
            onSaveSystemMap={onSaveSystemMap}
            onSaveAndStop={onSaveAndStop}
            onStopSystemMode={onStopSystemMode}
            onSaveImage={saveMapImage}
            selected3dSession={selected3dSession}
            onSelect3dSession={(session) => {
              setSelected3dSession(session);
              setMapDimension("3d");
              notify(`${session.name || "저장된 세션"} 3D 지도를 불러옵니다.`, "info");
            }}
            notify={notify}
          />
        </aside>
      </div>
    </div>
  );
}
