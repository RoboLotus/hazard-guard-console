import { useEffect, useRef, useState } from "react";
import {
  Camera,
  DownloadSimple,
  FloppyDisk,
  Path,
  Robot,
  SlidersHorizontal,
  ThermometerHot,
  VideoCamera,
} from "@phosphor-icons/react";
import slamMap from "../assets/slam-map.webp";
import {
  DetailHeading,
  SystemModeControl,
  downloadAsset,
} from "../components/Common.jsx";
import MapPanel from "../components/MapPanel.jsx";
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

export default function MapPage({
  mediaStatus,
  telemetry,
  spatialState,
  systemMode,
  modeBusy,
  onModeChange,
  onSaveSystemMap,
  notify,
}) {
  const [goalMode, setGoalMode] = useState(false);
  const [goalCandidate, setGoalCandidate] = useState(null);
  const savedRoute = useRef(loadWaypointRoute());
  const [waypoints, setWaypoints] = useState(() => savedRoute.current?.waypoints || []);
  const [savedMapSignature, setSavedMapSignature] = useState(
    () => savedRoute.current?.mapSignature || null,
  );
  const [selectedWaypointId, setSelectedWaypointId] = useState(null);
  const [repositionWaypointId, setRepositionWaypointId] = useState(null);
  const [missionStatus, setMissionStatus] = useState(null);
  const [navigationStatus, setNavigationStatus] = useState(null);
  const [routeBusy, setRouteBusy] = useState(false);
  const [layers, setLayers] = useState({
    depth: true,
    thermal: true,
    heatmap: true,
    trail: true,
    footprint: true,
  });
  const mapLive = Boolean(mediaStatus?.map?.available);
  const mapSpec = resolveMapSpec(mediaStatus, spatialState);
  const currentMapSignature = routeMapSignature(mapSpec);
  const mapMismatch = Boolean(
    mapLive
    && savedMapSignature
    && savedMapSignature !== currentMapSignature,
  );
  const patrolModeSelected = systemMode?.mode === "patrol";
  const patrolModeReady = Boolean(systemMode?.navigation_ready);
  const modeTransitioning = ["starting", "stopping"].includes(systemMode?.state);
  const sensors = spatialState?.sensors || fallbackSpatialState.sensors;
  const heatDetections = spatialState?.heatmap?.detections || [];
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
    const next = !goalMode;
    setGoalMode(next);
    setGoalCandidate(null);
    if (!next) setRepositionWaypointId(null);
  };

  const persistRoute = () => {
    saveWaypointRoute(waypoints, mapSpec);
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
    clearWaypointRoute();
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
      const response = await fetch("/api/v1/navigation/route", {
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
      setMissionStatus(result);
      if (!response.ok || !result.accepted) {
        notify(result.detail || result.message || "순찰 임무를 시작하지 못했습니다.", "warning");
        return;
      }
      notify("경로 안전성 확인 후 순찰을 시작합니다.");
    } catch {
      notify("순찰 임무 API에 연결하지 못했습니다.", "warning");
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

  return (
    <div className="detail-page map-page">
      <DetailHeading eyebrow="DIGITAL TWIN" title="지도 관제" description="SLAM 지도 위에서 로봇 위치, 센서 시야각, 이동 궤적과 열원 분포를 실시간으로 확인합니다.">
        <span className={`api-status ${mapLive ? "online" : ""}`}><span />{mapLive ? "공간 데이터 연결" : "디지털 트윈 목업"}</span>
      </DetailHeading>
      <div className="map-workspace">
        <MapPanel
          detail
          mediaStatus={mediaStatus}
          spatialState={spatialState}
          layers={layers}
          goalMode={goalMode}
          goalCandidate={goalCandidate}
          waypoints={waypoints}
          selectedWaypointId={selectedWaypointId}
          onWaypointSelect={setSelectedWaypointId}
          onGoalCandidate={selectGoal}
          onLocate={() => notify("현재 로봇 위치를 지도 중앙에 표시했습니다.")}
        />
        <aside className="map-side-panel">
          <SystemModeControl
            systemMode={systemMode}
            busy={modeBusy}
            onChange={onModeChange}
          />
          <WaypointMissionPanel
            waypoints={waypoints}
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
            onRequestPatrolMode={() => onModeChange("patrol")}
            onCancelMission={cancelRoute}
            onRecommend={recommendRoute}
            onSave={persistRoute}
            onClear={clearRoute}
          />
          <section className="detail-card">
            <div className="detail-card-title"><Robot size={20} weight="fill" /><div><strong>로봇 주행 상태</strong><span>ROS 2 텔레메트리</span></div></div>
            <dl className="status-list">
              <div><dt>운행 모드</dt><dd>{telemetry?.mode === "paused" ? "일시정지" : telemetry?.mode === "stopped" ? "정지" : "자율 순찰"}</dd></div>
              <div><dt>현재 속도</dt><dd>{(telemetry?.speed_mps ?? 0.32).toFixed(2)} m/s</dd></div>
              <div><dt>LiDAR</dt><dd className="healthy">{telemetry?.lidar_status === "error" ? "확인 필요" : "정상"}</dd></div>
              <div><dt>지도 소스</dt><dd>{mapLive ? "ROS /map" : "UI 목업"}</dd></div>
              <div><dt>로봇 위치</dt><dd>{spatialState?.pose?.available ? `X ${spatialState.pose.x.toFixed(2)} · Y ${spatialState.pose.y.toFixed(2)}` : "확인 중"}</dd></div>
              <div><dt>Nav2 상태</dt><dd className={navigationStatus?.status === "executing" ? "healthy" : ""}>{navStatusLabels[navigationStatus?.status] || "확인 중"}</dd></div>
            </dl>
          </section>
          <section className="detail-card layer-card">
            <div className="detail-card-title"><SlidersHorizontal size={20} /><div><strong>지도 레이어</strong><span>실시간 표시 선택</span></div></div>
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
              <p><ThermometerHot size={14} weight="fill" />{heatDetections.length}개 열원 관측 · {spatialState?.heatmap?.simulated ? "시뮬레이션 데이터" : "센서 데이터"}</p>
            </div>
          </section>
          <section className="detail-card compact-card">
            <div className="detail-card-title"><FloppyDisk size={20} /><div><strong>지도 파일</strong><span>순찰용 지도와 현재 화면 저장</span></div></div>
            <div className="map-file-actions">
              <button
                type="button"
                className="button primary wide-button"
                onClick={onSaveSystemMap}
                disabled={systemMode?.mode !== "mapping" || !systemMode?.control_enabled}
              >
                <FloppyDisk size={18} />ROS 지도 저장
              </button>
              <button type="button" className="button ghost wide-button" onClick={saveMapImage}><DownloadSimple size={18} />PNG로 저장</button>
            </div>
            <p className={`map-storage-status ${systemMode?.map_available ? "available" : ""}`}>
              {systemMode?.map_available
                ? "AMCL 순찰에 사용할 지도 파일이 준비되었습니다."
                : "맵 생성 모드에서 지도를 작성한 뒤 ROS 지도를 저장하세요."}
            </p>
          </section>
        </aside>
      </div>
    </div>
  );
}
