import { fetchJson, startPolling } from "../polling.js";
import { createEquipmentLabelSprite, disposeObject3d } from "../pointCloudScene.js";
import { useEffect, useRef, useState } from "react";
import { ArrowsClockwise, Crosshair, Cube, ThermometerHot } from "@phosphor-icons/react";
import * as THREE from "three";
import { usePointCloudScene } from "../hooks/usePointCloudScene.js";
import { PLYLoader } from "three/examples/jsm/loaders/PLYLoader.js";
import { CurrentTime, PanelHeader } from "./Common.jsx";
import {
  formatThermalLayerAge,
  parsePointCloudPacket,
  replacePointCloudGeometrySnapshot,
  resolveThermalLayerPresentation,
} from "../pointCloud.js";
import {
  normalizeFrameId,
  resolvePointCloudRobotState,
  selectPointCloudPose,
  shouldShowPointCloudRobot,
} from "../pointCloudRobot.js";
import {
  HGTD_PROTOCOL_VERSION,
  ThermalGeometryBuffers,
  parseThermalDelta,
  thermalDeltaAction,
} from "../thermalPointCloud.js";
import {
  setThermalMaterialTemperatureWindow,
  updateThermalPointMaterial,
} from "../thermalPointMaterial.js";

const INITIAL_STATUS = {
  connection: "connecting",
  pointCount: 0,
  colorAvailable: false,
  frameId: null,
  updatedAt: null,
  error: null,
};
const EMPTY_THERMAL_RENDER_CONFIG = Object.freeze({});
const EMPTY_BASE_SCENE = Object.freeze({
  ready: false,
  pointCount: 0,
  worldId: null,
  sessionId: null,
  frameId: null,
});

// Both variants are the same viewer over the same packet format; only the
// stream and the words around it change. Thermal packets are authoritative
// cumulative snapshots built on the robot against the frozen 3D surface.
const VARIANTS = {
  rgb: {
    socketPath: "/ws/pointcloud",
    eyebrow: "RGB-D MAP",
    title: "3D 컬러 포인트클라우드",
    ariaLabel: "RTAB-Map 컬러 3D 포인트클라우드",
    icon: Cube,
    liveLabel: "RTAB-Map 실시간",
    idleLabel: "최근 3D 지도",
    emptyTitle: "컬러 3D 지도 데이터를 기다리고 있습니다",
    emptyBody: "맵 생성 모드에서 로봇을 조작하면 관측한 RGB-D 표면이 누적됩니다.",
    supportsArchive: true,
  },
  thermal: {
    socketPath: "/ws/pointcloud/thermal",
    eyebrow: "CUMULATIVE THERMAL LAYER",
    title: "고정 3D 맵 누적 열화상",
    ariaLabel: "고정 3D 표면의 누적 열화상 계층",
    icon: ThermometerHot,
    liveLabel: "관측 영역 갱신 중",
    idleLabel: "마지막 측정 유지",
    emptyTitle: "누적 열화상 계층을 기다리고 있습니다",
    emptyBody:
      "순찰이 시작되면 고정 3D 표면과 일치한 영역의 온도만 갱신합니다. 보지 않는 영역은 마지막 측정을 그대로 유지합니다.",
    supportsArchive: false,
  },
};

export default function PointCloudPanel({
  systemMode,
  archivedSession,
  referenceSession,
  spatialState,
  variant = "rgb",
  equipment = [],
  selectedEquipmentId = null,
  thermalRenderConfig = EMPTY_THERMAL_RENDER_CONFIG,
}) {
  const spec = VARIANTS[variant] || VARIANTS.rgb;
  const archived = spec.supportsArchive ? archivedSession : null;
  const mountRef = useRef(null);
  const sceneRef = useRef(null);
  const fitRef = useRef(() => {});
  const firstCloudRef = useRef(true);
  const thermalBuffersRef = useRef(null);
  const [status, setStatus] = useState(INITIAL_STATUS);
  const [baseScene, setBaseScene] = useState(EMPTY_BASE_SCENE);
  const [clockTick, setClockTick] = useState(Date.now());
  const [temperatureWindow, setTemperatureWindow] = useState(null);
  const [thermalApiStatus, setThermalApiStatus] = useState(null);

  useEffect(() => {
    const timer = window.setInterval(() => setClockTick(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  usePointCloudScene({ mountRef, sceneRef, fitRef, variant, spec, thermalRenderConfig });

  useEffect(() => {
    const currentScene = sceneRef.current;
    if (!currentScene) return;
    if (variant !== "thermal") currentScene.material.size = 0.035;
    currentScene.renderer.domElement.setAttribute("aria-label", spec.ariaLabel);
    currentScene.dynamicPoints.visible = variant === "thermal";
  }, [spec.ariaLabel, variant]);

  useEffect(() => {
    if (variant !== "thermal") return;
    const scene = sceneRef.current;
    if (!scene) return;
    updateThermalPointMaterial(scene.material, thermalRenderConfig);
    updateThermalPointMaterial(scene.dynamicMaterial, thermalRenderConfig);
  }, [thermalRenderConfig, variant]);

  useEffect(() => {
    if (variant !== "thermal" || !temperatureWindow) return;
    const scene = sceneRef.current;
    if (!scene) return;
    setThermalMaterialTemperatureWindow(scene.material, temperatureWindow[0], temperatureWindow[1]);
    setThermalMaterialTemperatureWindow(scene.dynamicMaterial, temperatureWindow[0], temperatureWindow[1]);
  }, [temperatureWindow, variant]);

  useEffect(() => {
    const group = sceneRef.current?.equipmentGroup;
    if (!group) return;
    const clear = () => {
      while (group.children.length) {
        const child = group.children[0];
        group.remove(child);
        disposeObject3d(child);
      }
    };
    clear();
    equipment.forEach((item) => {
      const minimum = item.roi?.min;
      const maximum = item.roi?.max;
      if (!minimum || !maximum) return;
      const size = maximum.map((value, axis) => Number(value) - Number(minimum[axis]));
      if (size.some((value) => !Number.isFinite(value) || value <= 0)) return;
      const center = maximum.map((value, axis) => (Number(value) + Number(minimum[axis])) / 2);
      const selected = item.id === selectedEquipmentId;
      const geometry = new THREE.BoxGeometry(size[0], size[1], size[2]);
      const edges = new THREE.EdgesGeometry(geometry);
      geometry.dispose();
      const material = new THREE.LineBasicMaterial({
        color: selected ? 0xffc857 : item.enabled ? 0x56c596 : 0x8593a3,
        transparent: true,
        opacity: selected ? 1 : 0.72,
      });
      const box = new THREE.LineSegments(edges, material);
      box.position.set(center[0], center[1], center[2]);
      box.userData.equipmentId = item.id;
      group.add(box);

      const label = createEquipmentLabelSprite(item, selected);
      label.position.set(center[0], center[1], Number(maximum[2]) + 0.08);
      group.add(label);
    });
    return clear;
  }, [equipment, selectedEquipmentId]);

  useEffect(() => {
    if (variant !== "thermal") return undefined;
    return startPolling(
      (signal) => fetchJson("/api/v1/spatial/cloud/thermal/status", signal),
      (body) => {
        setThermalApiStatus(body);
        const minimum = body.min_temp_c;
        const maximum = body.max_temp_c;
        if (Number.isFinite(minimum) && Number.isFinite(maximum) && maximum > minimum) {
          setTemperatureWindow([minimum, maximum]);
        }
      },
      () => setThermalApiStatus((current) => ({ ...current, request_failed: true })),
      { interval: 5000 },
    );
  }, [variant]);

  useEffect(() => {
    if (archived) return undefined;
    // A session reset deliberately emits an empty authoritative snapshot.
    // Keep the first-fit pending until the first non-empty cloud arrives.
    firstCloudRef.current = true;
    let disposed = false;
    let socket;
    let deltaSocket;
    let reconnectTimer;
    let currentSequence = 0;
    let identity = null;
    let fallbackGeneration = 0;
    const websocketUrl = (path) => {
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      return `${protocol}//${window.location.host}${path}`;
    };

    if (variant === "thermal") {
      const setCloudStatus = (cloud, counts = null) => setStatus({
        connection: "connected",
        pointCount: counts ? counts.staticCount + counts.dynamicCount : cloud.pointCount,
        colorAvailable: cloud.colorAvailable,
        frameId: cloud.frameId,
        updatedAt: new Date(cloud.timestampMs),
        error: null,
      });
      const loadSnapshot = async (reason = null) => {
        const generation = ++fallbackGeneration;
        if (deltaSocket) { deltaSocket.onclose = null; deltaSocket.close(); }
        const bootstrapResponse = await fetch(
          "/api/v1/spatial/cloud/thermal/delta/bootstrap", { cache: "no-store" },
        );
        if (!bootstrapResponse.ok) throw new Error("열화상 delta bootstrap을 불러오지 못했습니다.");
        const bootstrap = await bootstrapResponse.json();
        if (bootstrap.protocol_version !== HGTD_PROTOCOL_VERSION) throw new Error("지원하지 않는 열화상 delta protocol입니다.");
        identity = {
          sessionId: bootstrap.session_id,
          fingerprint: bootstrap.geometry_fingerprint,
        };
        socket?.close();
        socket = new WebSocket(websocketUrl(spec.socketPath));
        socket.binaryType = "arraybuffer";
        socket.onopen = () => setStatus((current) => ({ ...current, connection: "connecting", error: reason }));
        socket.onmessage = ({ data }) => {
          if (disposed || generation !== fallbackGeneration) return;
          try {
            const cloud = parsePointCloudPacket(data);
            const scene = sceneRef.current;
            if (!scene) return;
            if (cloud.version < 3) {
              replacePointCloudGeometrySnapshot(scene.geometry, new THREE.BufferAttribute(cloud.positions, 3), new THREE.BufferAttribute(cloud.colors, 3));
              setCloudStatus(cloud);
              return;
            }
            const manager = new ThermalGeometryBuffers(scene.geometry, scene.dynamicGeometry, {
              temperatureMin: temperatureWindow?.[0] ?? 20,
              temperatureMax: temperatureWindow?.[1] ?? 40,
              dynamicVoxelSize: Number(bootstrap.dynamic_voxel_size_m) || 0.05,
            });
            const counts = manager.bootstrap(cloud);
            thermalBuffersRef.current = manager;
            currentSequence = counts.sequence;
            setCloudStatus(cloud, counts);
            if (cloud.pointCount > 0 && firstCloudRef.current) { firstCloudRef.current = false; fitRef.current(); }
            socket.onclose = null;
            socket.close();
            connectDelta();
          } catch (error) {
            setStatus((current) => ({ ...current, error: error.message }));
          }
        };
        socket.onerror = () => socket.close();
        socket.onclose = () => {
          if (!disposed && generation === fallbackGeneration) reconnectTimer = window.setTimeout(() => startSnapshot("snapshot 재연결 중"), 1500);
        };
      };
      const startSnapshot = (reason = null) => {
        void loadSnapshot(reason).catch((error) => {
          if (disposed) return;
          setStatus((current) => ({ ...current, connection: "disconnected", error: error.message }));
          reconnectTimer = window.setTimeout(() => startSnapshot("bootstrap 재연결 중"), 1500);
        });
      };
      const requestResync = async (reason) => {
        try {
          const query = new URLSearchParams({
            session_id: identity?.sessionId || "",
            geometry_fingerprint: identity?.fingerprint || "",
            base_sequence: String(currentSequence),
          });
          const response = await fetch(`/api/v1/spatial/cloud/thermal/delta/resync?${query}`, { cache: "no-store" });
          const result = response.ok ? await response.json() : { status: "RESYNC_REQUIRED" };
          if (result.status === "REPLAY_AVAILABLE" || result.status === "UP_TO_DATE") connectDelta();
          else await loadSnapshot(reason || result.reason || "delta 복구를 위해 snapshot을 다시 받습니다.");
        } catch { await loadSnapshot("delta 복구를 위해 snapshot을 다시 받습니다."); }
      };
      const connectDelta = () => {
        if (disposed || !identity?.sessionId || !identity?.fingerprint) return;
        if (deltaSocket) { deltaSocket.onclose = null; deltaSocket.close(); }
        const query = new URLSearchParams({ session_id: identity.sessionId, geometry_fingerprint: identity.fingerprint, base_sequence: String(currentSequence) });
        deltaSocket = new WebSocket(websocketUrl(`/ws/pointcloud/thermal/delta?${query}`));
        deltaSocket.binaryType = "arraybuffer";
        deltaSocket.onopen = () => setStatus((current) => ({ ...current, connection: "connected", error: null }));
        deltaSocket.onmessage = ({ data }) => {
          if (typeof data === "string") {
            const control = JSON.parse(data);
            if (control.status === "RESYNC_REQUIRED") startSnapshot(control.reason);
            return;
          }
          try {
            const delta = parseThermalDelta(data);
            const action = thermalDeltaAction(delta, { sessionId: identity.sessionId, geometryFingerprint: identity.fingerprint, sequence: currentSequence });
            if (action === "SNAPSHOT_REQUIRED") { startSnapshot("열화상 session 또는 geometry가 변경되었습니다."); return; }
            if (action === "REPLAY_REQUIRED") { void requestResync("delta sequence 복구가 필요합니다."); return; }
            const result = thermalBuffersRef.current?.apply(delta);
            if (!result?.applied) { startSnapshot("새 static geometry가 필요합니다."); return; }
            currentSequence = delta.sequence;
            setStatus((current) => ({ ...current, connection: "connected", pointCount: (thermalBuffersRef.current?.staticIndexToSlot.size || 0) + (thermalBuffersRef.current?.dynamicActiveCount || 0), updatedAt: new Date(), error: null }));
          } catch (error) { void requestResync(error.message); }
        };
        deltaSocket.onerror = () => deltaSocket.close();
        deltaSocket.onclose = () => { if (!disposed) reconnectTimer = window.setTimeout(connectDelta, 1500); };
      };
      setStatus((current) => ({ ...current, connection: "connecting", error: null }));
      startSnapshot();
      return () => {
        disposed = true; fallbackGeneration += 1;
        window.clearTimeout(reconnectTimer); socket?.close(); deltaSocket?.close();
        thermalBuffersRef.current = null;
      };
    }

    const connect = () => {
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      setStatus((current) => ({ ...current, connection: "connecting", error: null }));
      socket = new WebSocket(`${protocol}//${window.location.host}${spec.socketPath}`);
      socket.binaryType = "arraybuffer";
      socket.onopen = () => {
        setStatus((current) => ({ ...current, connection: "connected", error: null }));
      };
      socket.onmessage = ({ data }) => {
        try {
          const cloud = parsePointCloudPacket(data);
          const scene = sceneRef.current;
          if (!scene) return;
          replacePointCloudGeometrySnapshot(
            scene.geometry,
            new THREE.BufferAttribute(cloud.positions, 3),
            new THREE.BufferAttribute(cloud.colors, 3),
          );
          if (cloud.pointCount === 0) {
            firstCloudRef.current = true;
          } else if (firstCloudRef.current) {
            firstCloudRef.current = false;
            fitRef.current();
          }
          setStatus({
            connection: "connected",
            pointCount: cloud.pointCount,
            colorAvailable: cloud.colorAvailable,
            frameId: cloud.frameId,
            updatedAt: new Date(cloud.timestampMs),
            error: null,
          });
        } catch (error) {
          setStatus((current) => ({
            ...current,
            error: error.message || "3D 지도 데이터를 해석하지 못했습니다.",
          }));
        }
      };
      socket.onerror = () => socket.close();
      socket.onclose = () => {
        if (disposed) return;
        setStatus((current) => ({ ...current, connection: "disconnected" }));
        reconnectTimer = window.setTimeout(connect, 1500);
      };
    };
    connect();
    return () => {
      disposed = true;
      window.clearTimeout(reconnectTimer);
      socket?.close();
      deltaSocket?.close();
    };
  }, [archived?.id, spec.socketPath, variant]);

  useEffect(() => {
    if (variant !== "thermal") return undefined;
    const scene = sceneRef.current;
    scene?.baseGeometry?.deleteAttribute("position");
    scene?.baseGeometry?.deleteAttribute("color");
    setBaseScene(EMPTY_BASE_SCENE);
    if (!referenceSession?.id || !referenceSession?.world_id) return undefined;
    const referenceIdentity = {
      worldId: String(referenceSession.world_id),
      sessionId: String(referenceSession.id),
      frameId: normalizeFrameId(
        referenceSession.cloud_frame_id || referenceSession.frame_id,
      ),
    };
    const controller = new AbortController();
    let disposed = false;
    const loadReferenceCloud = async () => {
      try {
        const response = await fetch(
          `/api/v1/system/maps/${encodeURIComponent(referenceSession.world_id)}/${encodeURIComponent(referenceSession.id)}/cloud.ply`,
          { cache: "no-store", signal: controller.signal },
        );
        if (!response.ok) return;
        const source = new PLYLoader().parse(await response.arrayBuffer());
        const position = source.getAttribute("position");
        const currentScene = sceneRef.current;
        if (
          disposed
          || !currentScene?.baseGeometry
          || !position?.count
          || !referenceIdentity.frameId
        ) {
          source.dispose();
          return;
        }
        currentScene.baseGeometry.setAttribute("position", position.clone());
        const sourceColor = source.getAttribute("color");
        if (sourceColor) {
          currentScene.baseGeometry.setAttribute("color", sourceColor.clone());
        } else {
          const colors = new Float32Array(position.count * 3);
          for (let index = 0; index < position.count; index += 1) {
            colors.set([0.25, 0.43, 0.58], index * 3);
          }
          currentScene.baseGeometry.setAttribute(
            "color",
            new THREE.BufferAttribute(colors, 3),
          );
        }
        currentScene.baseGeometry.computeBoundingSphere();
        source.dispose();
        setBaseScene({
          ready: true,
          pointCount: position.count,
          ...referenceIdentity,
        });
        fitRef.current();
      } catch (error) {
        if (error.name !== "AbortError") {
          // The live base stream and thermal stream remain as fallbacks.
        }
      }
    };
    void loadReferenceCloud();
    return () => {
      disposed = true;
      controller.abort();
    };
  }, [
    referenceSession?.cloud_frame_id,
    referenceSession?.frame_id,
    referenceSession?.id,
    referenceSession?.world_id,
    variant,
  ]);

  useEffect(() => {
    if (!archived) return undefined;
    const controller = new AbortController();
    const load = async () => {
      const currentScene = sceneRef.current;
      currentScene?.geometry.deleteAttribute("position");
      currentScene?.geometry.deleteAttribute("color");
      setStatus({
        ...INITIAL_STATUS,
        connection: "connecting",
      });
      try {
        const response = await fetch(
          `/api/v1/system/maps/${encodeURIComponent(archived.world_id)}/${encodeURIComponent(archived.id)}/cloud.ply`,
          { cache: "no-store", signal: controller.signal },
        );
        if (!response.ok) {
          const detail = await response.json().catch(() => ({}));
          throw new Error(detail.detail || "저장된 3D 지도를 불러오지 못했습니다.");
        }
        const source = new PLYLoader().parse(await response.arrayBuffer());
        const position = source.getAttribute("position");
        if (!position?.count) throw new Error("저장된 PLY에 포인트가 없습니다.");
        const scene = sceneRef.current;
        if (!scene) return;
        scene.geometry.setAttribute("position", position.clone());
        const sourceColor = source.getAttribute("color");
        if (sourceColor) {
          scene.geometry.setAttribute("color", sourceColor.clone());
        } else {
          const colors = new Float32Array(position.count * 3);
          for (let index = 0; index < position.count; index += 1) {
            colors.set([0.3, 0.57, 0.86], index * 3);
          }
          scene.geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));
        }
        scene.geometry.computeBoundingSphere();
        source.dispose();
        firstCloudRef.current = false;
        fitRef.current();
        setStatus({
          connection: "connected",
          pointCount: position.count,
          colorAvailable: Boolean(sourceColor),
          frameId: archived.cloud_frame_id || archived.frame_id || null,
          updatedAt: new Date(archived.updated_at || archived.created_at),
          error: null,
        });
      } catch (error) {
        if (error.name === "AbortError") return;
        setStatus({
          ...INITIAL_STATUS,
          connection: "disconnected",
          error: error.message || "저장된 3D 지도를 불러오지 못했습니다.",
        });
      }
    };
    void load();
    return () => controller.abort();
  }, [archived?.id]);

  const thermalLayer = resolveThermalLayerPresentation(
    thermalApiStatus || {},
    status,
    clockTick,
  );
  const markerFrameId = variant === "thermal" ? baseScene.frameId : status.frameId;
  const cloudPose = selectPointCloudPose(spatialState, markerFrameId);
  const robotState = resolvePointCloudRobotState(
    cloudPose,
    markerFrameId,
    clockTick,
  );
  const robotMarkerVisible = shouldShowPointCloudRobot(robotState, {
    variant,
    pointCount: status.pointCount,
    baseScene,
    referenceSession,
    thermalSessionId: thermalLayer.sessionId,
    thermalStatusFrameId: status.frameId,
    fixedMapAvailable: thermalLayer.fixedMapAvailable,
  });

  useEffect(() => {
    const marker = sceneRef.current?.robotMarker;
    if (!marker) return;
    marker.group.visible = robotMarkerVisible;
    if (!robotMarkerVisible) return;
    marker.group.position.set(robotState.x, robotState.y, Math.max(0, robotState.z));
    marker.group.rotation.set(0, 0, robotState.yaw);
    marker.setStale(robotState.stale);
  }, [
    robotState.stale,
    robotState.visible,
    robotState.x,
    robotState.y,
    robotState.yaw,
    robotState.z,
    robotMarkerVisible,
  ]);

  const cloudFresh = Boolean(
    status.updatedAt && clockTick - status.updatedAt.getTime() < 5000,
  );
  const thermalLayerAge = formatThermalLayerAge(
    thermalLayer.updatedAtMs,
    clockTick,
  );
  const thermalActivityLabel = thermalLayer.updatedAtMs === null
    ? "열화상 계층 대기"
    : thermalLayer.stale ? "마지막 측정 유지" : "관측 영역 갱신 중";
  const fixedMapLabel = thermalLayer.fixedMapAvailable === false
    ? "고정 맵 대기"
    : thermalLayer.fixedMapAvailable === true ? "고정 3D 맵" : "기준 맵 확인 중";
  const rgbdMode = systemMode?.mode === "rgbd_mapping"
    || systemMode?.mapping_profile === "toolbox_rtabmap";
  const displayedCloudFresh = variant === "thermal"
    ? thermalLayer.updatedAtMs !== null && !thermalLayer.stale
    : cloudFresh;
  const connectionLabel = archived
    ? status.connection === "connected" && status.pointCount
      ? "저장된 3D 세션"
      : status.connection === "connecting" ? "저장 지도 변환 중" : "저장 지도 오류"
    : ({
    connecting: "연결 중",
    connected: status.pointCount
      ? (displayedCloudFresh ? spec.liveLabel : spec.idleLabel)
      : "포인트 대기 중",
    disconnected: "연결 끊김",
  }[status.connection]);
  const robotStatusClass = robotMarkerVisible
    ? (robotState.stale ? "stale" : "live")
    : "unavailable";
  let emptyTitle;
  let emptyBody;
  if (archived) {
    emptyTitle = "저장된 3D 지도를 준비하고 있습니다";
    emptyBody = "RTAB-Map DB에서 브라우저용 컬러 PLY를 생성하고 있습니다.";
  } else if (variant === "thermal") {
    emptyTitle = thermalLayer.fixedMapAvailable === false
      ? "먼저 고정 3D 지도를 생성하세요"
      : spec.emptyTitle;
    emptyBody = thermalLayer.fixedMapAvailable === false
      ? "2단계 RGB-D 3D 수집을 완료하면 해당 표면을 기준으로 열화상 누적을 시작할 수 있습니다."
      : spec.emptyBody;
  } else if (rgbdMode) {
    emptyTitle = spec.emptyTitle;
    emptyBody = spec.emptyBody;
  } else {
    emptyTitle = "2단계 RGB-D 3D 수집을 시작하세요";
    emptyBody = "2D 지도를 저장한 뒤 지도 운용 모드에서 2단계 RGB-D 3D 수집을 시작하세요.";
  }
  const EmptyIcon = spec.icon;

  return (
    <section className="panel map-panel map-panel-detail point-cloud-panel">
      <PanelHeader eyebrow={spec.eyebrow} title={spec.title} action={(
        <div className="panel-actions">
          <CurrentTime />
          <button type="button" className="icon-action" aria-label="3D 지도 화면 맞춤" title="3D 지도 화면 맞춤" onClick={() => fitRef.current()}>
            <Crosshair size={19} />
          </button>
        </div>
      )} />
      <div className="point-cloud-stage">
        <div ref={mountRef} className="point-cloud-canvas" />
        <div className={`map-live-badge ${status.connection === "connected" && status.pointCount && (archived || displayedCloudFresh) ? "" : "mock"}`}>
          <span />{connectionLabel}
        </div>
        {robotMarkerVisible && (
          <div className={`point-cloud-robot-status ${robotStatusClass}`}>
            <span />
            <strong>{robotState.reason}</strong>
            {robotMarkerVisible && (
              <small>
                {markerFrameId} · {robotState.x.toFixed(2)}, {robotState.y.toFixed(2)} m
              </small>
            )}
          </div>
        )}
        {variant === "thermal" && (
          <aside
            className={`thermal-layer-status ${thermalLayer.stale ? "stale" : "live"}`}
            aria-label="누적 열화상 계층 상태"
          >
            <div className="thermal-layer-status-heading">
              <span />
              <strong>{thermalActivityLabel}</strong>
            </div>
            <dl>
              <div>
                <dt>기준 형상</dt>
                <dd>{fixedMapLabel}</dd>
              </div>
              <div>
                <dt>관측 복셀</dt>
                <dd>{thermalLayer.observedVoxelCount.toLocaleString("ko-KR")}</dd>
              </div>
              <div>
                <dt>마지막 갱신</dt>
                <dd>{thermalLayerAge}</dd>
              </div>
              {thermalLayer.matchRatio !== null && (
                <div>
                  <dt>표면 매칭</dt>
                  <dd>{(thermalLayer.matchRatio * 100).toFixed(0)}%</dd>
                </div>
              )}
            </dl>
            <p>다시 보이는 표면만 최신 온도로 갱신하고, 보지 않는 영역은 마지막 측정을 유지합니다.</p>
          </aside>
        )}
        {!status.pointCount && !(variant === "thermal" && baseScene.ready) && (
          <div className="point-cloud-empty">
            <EmptyIcon size={38} weight="duotone" />
            <strong>{emptyTitle}</strong>
            <span>{emptyBody}</span>
          </div>
        )}
        {status.error && <div className="point-cloud-error">{status.error}</div>}
        <div className="point-cloud-controls-hint">
          <ArrowsClockwise size={14} />좌클릭 회전 · 우클릭 이동 · 휠 확대/축소
        </div>
      </div>
      <footer className="map-footer point-cloud-footer">
        {variant === "thermal" ? (
          <span className="thermal-scale">
            <i />
            {temperatureWindow
              ? `${temperatureWindow[0].toFixed(0)} ~ ${temperatureWindow[1].toFixed(0)}°C`
              : "온도 색상"}
          </span>
        ) : (
          <span><i className="point-cloud-color-dot" />{status.colorAvailable ? "RGB 색상 포함" : "기본 색상"}</span>
        )}
        <span>
          {archived
            ? `저장 세션 · ${archived.name || archived.id}`
            : variant === "thermal"
            ? `고정 3D 표면 · 누적 열화상 계층 · ${markerFrameId || "좌표계 미확인"} 좌표계`
            : `${status.frameId || "좌표계 미확인"} 좌표계 · Z축 높이`}
        </span>
        <strong>
          {variant === "thermal"
            ? `관측 복셀 ${thermalLayer.observedVoxelCount.toLocaleString("ko-KR")}`
            : `${status.pointCount.toLocaleString("ko-KR")} points`}
          {variant === "thermal"
            ? thermalLayer.updatedAtMs === null ? "" : ` · ${thermalLayerAge}`
            : status.updatedAt ? ` · ${status.updatedAt.toLocaleTimeString("ko-KR", { hour12: false })}` : ""}
        </strong>
      </footer>
    </section>
  );
}
