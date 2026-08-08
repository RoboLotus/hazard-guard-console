import { useEffect, useRef, useState } from "react";
import { ArrowsClockwise, Crosshair, Cube } from "@phosphor-icons/react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { PLYLoader } from "three/examples/jsm/loaders/PLYLoader.js";
import { CurrentTime, PanelHeader } from "./Common.jsx";
import { parsePointCloudPacket } from "../pointCloud.js";

const INITIAL_STATUS = {
  connection: "connecting",
  pointCount: 0,
  colorAvailable: false,
  updatedAt: null,
  error: null,
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

export default function PointCloudPanel({ systemMode, archivedSession }) {
  const mountRef = useRef(null);
  const sceneRef = useRef(null);
  const fitRef = useRef(() => {});
  const firstCloudRef = useRef(true);
  const [status, setStatus] = useState(INITIAL_STATUS);
  const [clockTick, setClockTick] = useState(Date.now());

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
    renderer.domElement.setAttribute("aria-label", "RTAB-Map 컬러 3D 포인트클라우드");
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
      size: 0.035,
      sizeAttenuation: true,
      vertexColors: true,
    });
    const points = new THREE.Points(geometry, material);
    scene.add(points);
    sceneRef.current = { camera, controls, geometry, material, points, renderer };
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
      renderer.dispose();
      renderer.domElement.remove();
      sceneRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (archivedSession) return undefined;
    let disposed = false;
    let socket;
    let reconnectTimer;
    const connect = () => {
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      setStatus((current) => ({ ...current, connection: "connecting", error: null }));
      socket = new WebSocket(`${protocol}//${window.location.host}/ws/pointcloud`);
      socket.binaryType = "arraybuffer";
      socket.onopen = () => {
        setStatus((current) => ({ ...current, connection: "connected", error: null }));
      };
      socket.onmessage = ({ data }) => {
        try {
          const cloud = parsePointCloudPacket(data);
          const scene = sceneRef.current;
          if (!scene) return;
          scene.geometry.setAttribute(
            "position",
            new THREE.BufferAttribute(cloud.positions, 3),
          );
          scene.geometry.setAttribute(
            "color",
            new THREE.BufferAttribute(cloud.colors, 3),
          );
          scene.geometry.computeBoundingSphere();
          if (firstCloudRef.current) {
            firstCloudRef.current = false;
            fitRef.current();
          }
          setStatus({
            connection: "connected",
            pointCount: cloud.pointCount,
            colorAvailable: cloud.colorAvailable,
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
  }, [archivedSession?.id]);

  useEffect(() => {
    if (!archivedSession) return undefined;
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
          `/api/v1/system/maps/${encodeURIComponent(archivedSession.world_id)}/${encodeURIComponent(archivedSession.id)}/cloud.ply`,
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
          updatedAt: new Date(archivedSession.updated_at || archivedSession.created_at),
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
  }, [archivedSession?.id]);

  const cloudFresh = Boolean(
    status.updatedAt && clockTick - status.updatedAt.getTime() < 5000,
  );
  const hybridProfile = systemMode?.mapping_profile === "toolbox_rtabmap";
  const connectionLabel = archivedSession
    ? status.connection === "connected" && status.pointCount
      ? "저장된 3D 세션"
      : status.connection === "connecting" ? "저장 지도 변환 중" : "저장 지도 오류"
    : ({
    connecting: "연결 중",
    connected: status.pointCount
      ? (cloudFresh ? "RTAB-Map 실시간" : "최근 3D 지도")
      : "포인트 대기 중",
    disconnected: "연결 끊김",
  }[status.connection]);

  return (
    <section className="panel map-panel map-panel-detail point-cloud-panel">
      <PanelHeader eyebrow="RGB-D MAP" title="3D 컬러 포인트클라우드" action={(
        <div className="panel-actions">
          <CurrentTime />
          <button type="button" className="icon-action" aria-label="3D 지도 화면 맞춤" title="3D 지도 화면 맞춤" onClick={() => fitRef.current()}>
            <Crosshair size={19} />
          </button>
        </div>
      )} />
      <div className="point-cloud-stage">
        <div ref={mountRef} className="point-cloud-canvas" />
        <div className={`map-live-badge ${status.connection === "connected" && status.pointCount && (archivedSession || cloudFresh) ? "" : "mock"}`}>
          <span />{connectionLabel}
        </div>
        {!status.pointCount && (
          <div className="point-cloud-empty">
            <Cube size={38} weight="duotone" />
            <strong>{archivedSession ? "저장된 3D 지도를 준비하고 있습니다" : hybridProfile ? "컬러 3D 지도 데이터를 기다리고 있습니다" : "2D + RGB-D 3D 프로파일이 필요합니다"}</strong>
            <span>
              {archivedSession
                ? "RTAB-Map DB에서 브라우저용 컬러 PLY를 생성하고 있습니다."
                : hybridProfile
                ? "맵 생성 모드에서 로봇을 조작하면 관측한 RGB-D 표면이 누적됩니다."
                : "지도 운용 모드에서 생성 방식을 2D + RGB-D 3D로 선택하고 새 세션을 시작하세요."}
            </span>
          </div>
        )}
        {status.error && <div className="point-cloud-error">{status.error}</div>}
        <div className="point-cloud-controls-hint">
          <ArrowsClockwise size={14} />좌클릭 회전 · 우클릭 이동 · 휠 확대/축소
        </div>
      </div>
      <footer className="map-footer point-cloud-footer">
        <span><i className="point-cloud-color-dot" />{status.colorAvailable ? "RGB 색상 포함" : "기본 색상"}</span>
        <span>{archivedSession ? `저장 세션 · ${archivedSession.name || archivedSession.id}` : "관측 표면 · map 좌표계 · Z축 높이"}</span>
        <strong>{status.pointCount.toLocaleString("ko-KR")} points{status.updatedAt ? ` · ${status.updatedAt.toLocaleTimeString("ko-KR", { hour12: false })}` : ""}</strong>
      </footer>
    </section>
  );
}
