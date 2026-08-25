import { useEffect, useRef, useState } from "react";
import { ArrowsClockwise, Crosshair, Cube, ThermometerHot } from "@phosphor-icons/react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { PLYLoader } from "three/examples/jsm/loaders/PLYLoader.js";
import { CurrentTime, PanelHeader } from "./Common.jsx";
import {
  formatThermalLayerAge,
  parsePointCloudPacket,
  replacePointCloudGeometrySnapshot,
  resolveThermalLayerPresentation,
} from "../pointCloud.js";
import {
  resolvePointCloudRobotState,
  selectPointCloudPose,
} from "../pointCloudRobot.js";

const INITIAL_STATUS = {
  connection: "connecting",
  pointCount: 0,
  colorAvailable: false,
  frameId: null,
  updatedAt: null,
  error: null,
};

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

function fitCameraToCloud(camera, controls, geometry) {
  geometry.computeBoundingBox();
  const bounds = geometry.boundingBox;
  if (!bounds || bounds.isEmpty()) return;
  const center = bounds.getCenter(new THREE.Vector3());
  const size = bounds.getSize(new THREE.Vector3());
  const distance = Math.max(size.length() * 0.85, 2.5);
  controls.target.copy(center);
  camera.position.set(
    center.x + distance * 0.72,
    center.y - distance,
    center.z + distance * 0.62,
  );
  camera.near = Math.max(distance / 1000, 0.01);
  camera.far = Math.max(distance * 20, 100);
  camera.updateProjectionMatrix();
  controls.update();
}

function createRobotMarker() {
  const group = new THREE.Group();
  group.name = "hazard-guard-robot-marker";
  group.visible = false;

  const chassisMaterial = new THREE.MeshBasicMaterial({ color: 0x2f80ed });
  const frontMaterial = new THREE.MeshBasicMaterial({ color: 0xe9f4ff });
  const ringMaterial = new THREE.MeshBasicMaterial({
    color: 0x66b6ff,
    transparent: true,
    opacity: 0.72,
    side: THREE.DoubleSide,
  });
  const chassisGeometry = new THREE.BoxGeometry(0.34, 0.26, 0.12);
  const frontGeometry = new THREE.ConeGeometry(0.075, 0.18, 3);
  const ringGeometry = new THREE.RingGeometry(0.22, 0.25, 40);

  const chassis = new THREE.Mesh(chassisGeometry, chassisMaterial);
  chassis.position.z = 0.07;
  group.add(chassis);

  const front = new THREE.Mesh(frontGeometry, frontMaterial);
  front.rotation.z = -Math.PI / 2;
  front.position.set(0.25, 0, 0.08);
  group.add(front);

  const ring = new THREE.Mesh(ringGeometry, ringMaterial);
  ring.position.z = 0.006;
  group.add(ring);

  return {
    group,
    setStale(stale) {
      chassisMaterial.color.setHex(stale ? 0x748190 : 0x2f80ed);
      frontMaterial.color.setHex(stale ? 0xb8c0c8 : 0xe9f4ff);
      ringMaterial.color.setHex(stale ? 0x8a949f : 0x66b6ff);
    },
    dispose() {
      chassisGeometry.dispose();
      frontGeometry.dispose();
      ringGeometry.dispose();
      chassisMaterial.dispose();
      frontMaterial.dispose();
      ringMaterial.dispose();
    },
  };
}

export default function PointCloudPanel({
  systemMode,
  archivedSession,
  spatialState,
  variant = "rgb",
  equipment = [],
  selectedEquipmentId = null,
}) {
  const spec = VARIANTS[variant] || VARIANTS.rgb;
  const archived = spec.supportsArchive ? archivedSession : null;
  const mountRef = useRef(null);
  const sceneRef = useRef(null);
  const fitRef = useRef(() => {});
  const firstCloudRef = useRef(true);
  const [status, setStatus] = useState(INITIAL_STATUS);
  const [clockTick, setClockTick] = useState(Date.now());
  const [temperatureWindow, setTemperatureWindow] = useState(null);
  const [thermalApiStatus, setThermalApiStatus] = useState(null);

  useEffect(() => {
    const timer = window.setInterval(() => setClockTick(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return undefined;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x111a25);
    scene.fog = new THREE.FogExp2(0x111a25, 0.025);
    const camera = new THREE.PerspectiveCamera(48, 1, 0.01, 200);
    camera.up.set(0, 0, 1);
    camera.position.set(4.5, -5.5, 3.6);
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.domElement.setAttribute("aria-label", spec.ariaLabel);
    mount.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.target.set(0, 0, 0.6);
    controls.update();

    const grid = new THREE.GridHelper(12, 24, 0x315f8f, 0x273849);
    grid.rotation.x = Math.PI / 2;
    grid.material.opacity = 0.5;
    grid.material.transparent = true;
    scene.add(grid);
    scene.add(new THREE.AxesHelper(0.75));

    const geometry = new THREE.BufferGeometry();
    const material = new THREE.PointsMaterial({
      size: variant === "thermal" ? 0.055 : 0.035,
      sizeAttenuation: true,
      vertexColors: true,
      transparent: false,
      opacity: 1,
      depthWrite: true,
    });
    const points = new THREE.Points(geometry, material);
    scene.add(points);
    const robotMarker = createRobotMarker();
    scene.add(robotMarker.group);
    const equipmentGroup = new THREE.Group();
    equipmentGroup.name = "hazard-guard-equipment-rois";
    scene.add(equipmentGroup);
    sceneRef.current = {
      camera,
      controls,
      geometry,
      material,
      points,
      renderer,
      robotMarker,
      equipmentGroup,
    };
    fitRef.current = () => fitCameraToCloud(camera, controls, geometry);

    const resize = () => {
      const width = Math.max(1, mount.clientWidth);
      const height = Math.max(1, mount.clientHeight);
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(mount);
    resize();

    let animationFrame;
    const render = () => {
      controls.update();
      renderer.render(scene, camera);
      animationFrame = window.requestAnimationFrame(render);
    };
    render();

    return () => {
      observer.disconnect();
      window.cancelAnimationFrame(animationFrame);
      controls.dispose();
      geometry.dispose();
      material.dispose();
      robotMarker.dispose();
      renderer.dispose();
      renderer.domElement.remove();
      sceneRef.current = null;
    };
  }, []);

  useEffect(() => {
    const currentScene = sceneRef.current;
    if (!currentScene) return;
    currentScene.material.size = variant === "thermal" ? 0.055 : 0.035;
    currentScene.material.needsUpdate = true;
    currentScene.renderer.domElement.setAttribute("aria-label", spec.ariaLabel);
  }, [spec.ariaLabel, variant]);

  useEffect(() => {
    const group = sceneRef.current?.equipmentGroup;
    if (!group) return;
    const clear = () => {
      while (group.children.length) {
        const child = group.children[0];
        group.remove(child);
        child.geometry?.dispose();
        child.material?.dispose();
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
    });
    return clear;
  }, [equipment, selectedEquipmentId]);

  useEffect(() => {
    if (variant !== "thermal") return undefined;
    let disposed = false;
    const loadStatus = () => {
      fetch("/api/v1/spatial/cloud/thermal/status", { cache: "no-store" })
        .then((response) => (response.ok ? response.json() : null))
        .then((body) => {
          if (disposed || !body) return;
          setThermalApiStatus(body);
          const minimum = Number(body.min_temp_c);
          const maximum = Number(body.max_temp_c);
          if (Number.isFinite(minimum) && Number.isFinite(maximum) && maximum > minimum) {
            setTemperatureWindow([minimum, maximum]);
          }
        })
        .catch(() => {});
    };
    loadStatus();
    const timer = window.setInterval(loadStatus, 5000);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [variant]);

  useEffect(() => {
    if (archived) return undefined;
    // A session reset deliberately emits an empty authoritative snapshot.
    // Keep the first-fit pending until the first non-empty cloud arrives.
    firstCloudRef.current = true;
    let disposed = false;
    let socket;
    let reconnectTimer;
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
    };
  }, [archived?.id, spec.socketPath]);

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

  const cloudPose = selectPointCloudPose(spatialState, status.frameId);
  const robotState = resolvePointCloudRobotState(
    cloudPose,
    status.frameId,
    clockTick,
  );

  useEffect(() => {
    const marker = sceneRef.current?.robotMarker;
    if (!marker) return;
    const visible = Boolean(status.pointCount && robotState.visible);
    marker.group.visible = visible;
    if (!visible) return;
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
    status.pointCount,
  ]);

  const cloudFresh = Boolean(
    status.updatedAt && clockTick - status.updatedAt.getTime() < 5000,
  );
  const thermalLayer = resolveThermalLayerPresentation(
    thermalApiStatus || {},
    status,
    clockTick,
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
  const robotStatusClass = robotState.visible
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
        {Boolean(status.pointCount) && (
          <div className={`point-cloud-robot-status ${robotStatusClass}`}>
            <span />
            <strong>{robotState.reason}</strong>
            {robotState.visible && (
              <small>
                {status.frameId} · {robotState.x.toFixed(2)}, {robotState.y.toFixed(2)} m
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
        {!status.pointCount && (
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
            ? `고정 3D 표면 · 누적 열화상 계층 · ${status.frameId || "좌표계 미확인"} 좌표계`
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
