import { useEffect, useRef, useState } from "react";
import {
  ArrowsOut,
  Bell,
  Camera,
  CalendarBlank,
  CaretRight,
  ChartBar,
  Check,
  CheckCircle,
  Clock,
  ClockCounterClockwise,
  Crosshair,
  DownloadSimple,
  FileCsv,
  FloppyDisk,
  Funnel,
  GameController,
  Gear,
  House,
  ImageSquare,
  ListChecks,
  MagnifyingGlass,
  MapTrifold,
  NavigationArrow,
  NotePencil,
  Pause,
  Path,
  Play,
  Question,
  Robot,
  Siren,
  SlidersHorizontal,
  Stop,
  ThermometerHot,
  VideoCamera,
  Warning,
  WifiHigh,
  X,
} from "@phosphor-icons/react";
import rgbFeed from "./assets/industrial-rgb.png";
import thermalFeed from "./assets/industrial-thermal.png";
import slamMap from "./assets/slam-map.png";

const initialThresholds = {
  warningTemperature: 60,
  warningDuration: 5,
  criticalTemperature: 80,
  criticalDuration: 3,
  clearTemperature: 50,
  clearDuration: 10,
  warningRepeat: 60,
  criticalRepeat: 30,
};

const navItems = [
  { id: "overview", label: "Overview", icon: House },
  { id: "map", label: "지도", icon: MapTrifold },
  { id: "events", label: "이벤트", icon: ListChecks, badge: 3 },
  { id: "video", label: "영상", icon: VideoCamera },
  { id: "report", label: "리포트", icon: ChartBar },
];

const initialEvents = [
  { id: 1, level: "critical", status: "new", title: "고온 위험 감지", date: "2026-07-23", time: "14:32:08", location: "A동 펌프실 · P-02", temperature: "84.6°C", threshold: "80°C · 3초", detail: "설정된 위험 조건이 지속되어 확인이 필요합니다.", acknowledged: false, assignee: "미지정", note: "열화상과 RGB 영상을 함께 확인하세요." },
  { id: 2, level: "warning", status: "new", title: "온도 상승 감지", date: "2026-07-23", time: "14:29:41", location: "A동 펌프실 · P-01", temperature: "63.2°C", threshold: "60°C · 5초", detail: "경고 온도 구간에 진입했습니다.", acknowledged: false, assignee: "미지정", note: "온도 상승 추이를 관찰 중입니다." },
  { id: 3, level: "warning", status: "new", title: "진동 주의", date: "2026-07-23", time: "14:18:07", location: "A동 펌프실 · P-03", temperature: null, threshold: "7.0 mm/s", detail: "진동 속도 7.8 mm/s가 감지되었습니다.", acknowledged: false, assignee: "미지정", note: "센서 규격 확정 후 진동 기준을 조정합니다." },
  { id: 4, level: "info", status: "resolved", title: "순찰 지점 통과", date: "2026-07-23", time: "14:15:22", location: "A동 중앙 통로 · WP-04", temperature: null, threshold: null, detail: "예정된 순찰 경로를 정상 주행 중입니다.", acknowledged: true, assignee: "시스템", note: "자동 기록된 순찰 로그입니다." },
  { id: 5, level: "info", status: "resolved", title: "LiDAR 데이터 정상", date: "2026-07-23", time: "14:12:05", location: "시스템 · T-MINI Plus", temperature: null, threshold: null, detail: "주행 센서 데이터가 정상 수신되고 있습니다.", acknowledged: true, assignee: "시스템", note: "자동 상태 점검 결과입니다." },
];

const eventStatusLabels = {
  new: "신규",
  acknowledged: "확인됨",
  working: "처리 중",
  resolved: "해결됨",
};

const reportData = {
  today: { label: "오늘", patrolHours: 6.4, distance: 3.8, completion: 92, events: 5, critical: 1, warning: 2, info: 2, acknowledge: 2.8, resolve: 18, temperature: 84.6 },
  week: { label: "최근 7일", patrolHours: 41.2, distance: 24.7, completion: 89, events: 31, critical: 4, warning: 12, info: 15, acknowledge: 3.4, resolve: 21, temperature: 88.1 },
  month: { label: "최근 30일", patrolHours: 172.8, distance: 103.5, completion: 87, events: 126, critical: 18, warning: 43, info: 65, acknowledge: 4.1, resolve: 24, temperature: 91.3 },
};

function StatusPill({ tone = "success", children }) {
  return <span className={`status-pill ${tone}`}><span className="status-dot" />{children}</span>;
}

function PanelHeader({ eyebrow, title, action }) {
  return (
    <header className="panel-header">
      <div>
        {eyebrow && <span className="eyebrow">{eyebrow}</span>}
        <h2>{title}</h2>
      </div>
      {action}
    </header>
  );
}

async function downloadAsset(source, filename) {
  const response = await fetch(source);
  if (!response.ok) throw new Error(`Download failed: ${response.status}`);
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function LiveImage({ endpoint, fallback, enabled, interval = 500, ...props }) {
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    if (!enabled) {
      setRevision(0);
      return undefined;
    }
    const timer = window.setInterval(
      () => setRevision((current) => current + 1),
      interval,
    );
    return () => window.clearInterval(timer);
  }, [enabled, interval]);

  const source = enabled ? `${endpoint}?frame=${revision}` : fallback;
  return (
    <img
      {...props}
      src={source}
      onError={({ currentTarget }) => {
        currentTarget.onerror = null;
        currentTarget.src = fallback;
      }}
    />
  );
}

function CurrentTime() {
  const [time, setTime] = useState(() => new Date());

  useEffect(() => {
    const timer = window.setInterval(() => setTime(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <div className="panel-clock" aria-label="현재 시간">
      <Clock size={15} weight="bold" />
      <time dateTime={time.toISOString()}>{time.toLocaleTimeString("ko-KR", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" })}</time>
    </div>
  );
}

function Sidebar({ active, onNavigate, pendingEvents }) {
  return (
    <aside className="sidebar" aria-label="주 메뉴">
      <div className="sidebar-main">
        <nav className="nav-primary">
          {navItems.map(({ id, label, icon: Icon, badge }) => (
            <button key={id} type="button" className={`nav-item ${active === id ? "active" : ""}`} onClick={() => onNavigate(id)}>
              <Icon size={20} weight={active === id ? "fill" : "regular"} />
              <span>{label}</span>
              {(id === "events" ? pendingEvents : badge) ? <span className="nav-badge">{id === "events" ? pendingEvents : badge}</span> : null}
            </button>
          ))}
        </nav>
      </div>
      <nav className="nav-secondary" aria-label="보조 메뉴">
        <button type="button" className={`nav-item ${active === "settings" ? "active" : ""}`} onClick={() => onNavigate("settings")}>
          <Gear size={20} weight={active === "settings" ? "fill" : "regular"} />
          <span>설정</span>
        </button>
        <button type="button" className="nav-item" onClick={() => onNavigate("help")}>
          <Question size={20} />
          <span>도움말</span>
        </button>
        <div className="sidebar-version">
          <span>HazardGuard Console</span>
          <small>Prototype v0.1.0</small>
        </div>
      </nav>
    </aside>
  );
}

function MapPanel({
  onLocate,
  onOpen,
  mediaStatus,
  detail = false,
  goalMode = false,
  goalCandidate,
  onGoalCandidate,
}) {
  const mapLive = Boolean(mediaStatus?.map?.available);
  const mapInfo = mediaStatus?.map;
  const mapMetadata = mapInfo?.metadata;
  const stageRef = useRef(null);
  const dragRef = useRef(null);
  const [mapView, setMapView] = useState({ zoom: 1, x: 0, y: 0 });
  const [dragging, setDragging] = useState(false);

  const clampPan = (x, y, zoom) => {
    const bounds = stageRef.current?.getBoundingClientRect();
    if (!bounds) return { x, y };
    const maxX = Math.max(0, (bounds.width * (zoom - 1)) / 2);
    const maxY = Math.max(0, (bounds.height * (zoom - 1)) / 2);
    return {
      x: Math.min(maxX, Math.max(-maxX, x)),
      y: Math.min(maxY, Math.max(-maxY, y)),
    };
  };

  const changeZoom = (delta) => {
    setMapView((current) => {
      const zoom = Math.min(4, Math.max(0.5, Number((current.zoom + delta).toFixed(2))));
      const ratio = zoom / current.zoom;
      const pan = clampPan(current.x * ratio, current.y * ratio, zoom);
      return { zoom, ...pan };
    });
  };

  const resetMapView = () => {
    setMapView({ zoom: 1, x: 0, y: 0 });
    onLocate();
  };

  const startMapDrag = (event) => {
    if (event.button !== 0 || event.target.closest(".map-zoom")) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    dragRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      originX: mapView.x,
      originY: mapView.y,
    };
    setDragging(true);
  };

  const moveMap = (event) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const pan = clampPan(
      drag.originX + event.clientX - drag.startX,
      drag.originY + event.clientY - drag.startY,
      mapView.zoom,
    );
    setMapView((current) => ({ ...current, ...pan }));
  };

  const endMapDrag = (event) => {
    const drag = dragRef.current;
    if (drag?.pointerId !== event.pointerId) return;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    const movement = Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY);
    if (goalMode && movement < 6 && onGoalCandidate) {
      const bounds = stageRef.current?.getBoundingClientRect();
      if (bounds) {
        const unscaledX = ((event.clientX - bounds.left) - bounds.width / 2 - mapView.x) / mapView.zoom + bounds.width / 2;
        const unscaledY = ((event.clientY - bounds.top) - bounds.height / 2 - mapView.y) / mapView.zoom + bounds.height / 2;
        let imageLeft = 0;
        let imageTop = 0;
        let imageWidth = bounds.width;
        let imageHeight = bounds.height;
        if (mapLive && mapInfo?.width && mapInfo?.height) {
          const fitScale = Math.min(
            bounds.width / mapInfo.width,
            bounds.height / mapInfo.height,
          );
          imageWidth = mapInfo.width * fitScale;
          imageHeight = mapInfo.height * fitScale;
          imageLeft = (bounds.width - imageWidth) / 2;
          imageTop = (bounds.height - imageHeight) / 2;
        }
        const normalizedX = (unscaledX - imageLeft) / imageWidth;
        const normalizedY = (unscaledY - imageTop) / imageHeight;
        if (normalizedX >= 0 && normalizedX <= 1 && normalizedY >= 0 && normalizedY <= 1) {
          const candidate = {
            screenX: ((imageLeft + normalizedX * imageWidth) / bounds.width) * 100,
            screenY: ((imageTop + normalizedY * imageHeight) / bounds.height) * 100,
            mapX: null,
            mapY: null,
            frameId: mapMetadata?.frame_id || "map",
          };
          if (
            mapLive
            && Number.isFinite(mapMetadata?.resolution)
            && Number.isFinite(mapMetadata?.origin_x)
            && Number.isFinite(mapMetadata?.origin_y)
          ) {
            candidate.mapX = mapMetadata.origin_x + normalizedX * mapInfo.width * mapMetadata.resolution;
            candidate.mapY = mapMetadata.origin_y + (1 - normalizedY) * mapInfo.height * mapMetadata.resolution;
          }
          onGoalCandidate(candidate);
        }
      }
    }
    dragRef.current = null;
    setDragging(false);
  };

  useEffect(() => {
    const handleResize = () => {
      setMapView((current) => ({
        ...current,
        ...clampPan(current.x, current.y, current.zoom),
      }));
    };
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  return (
    <section className={`panel map-panel ${detail ? "map-panel-detail" : ""}`}>
      <PanelHeader eyebrow="LIVE MAP" title="2D SLAM 지도" action={
        <div className="panel-actions">
          <CurrentTime />
          <button type="button" className="icon-action" aria-label="지도 중앙 정렬" title="지도 중앙 정렬" onClick={resetMapView}><Crosshair size={19} /></button>
          {onOpen && <button type="button" className="icon-action" aria-label="지도 상세 화면 열기" title="지도 상세 화면 열기" onClick={onOpen}><CaretRight size={19} /></button>}
        </div>
      } />
      <div
        ref={stageRef}
        className={`map-stage ${dragging ? "dragging" : ""} ${goalMode ? "goal-mode" : ""}`}
        aria-label="확대 및 드래그 가능한 2D SLAM 지도"
        onPointerDown={startMapDrag}
        onPointerMove={moveMap}
        onPointerUp={endMapDrag}
        onPointerCancel={endMapDrag}
      >
        <div
          className="map-canvas"
          style={{ transform: `translate3d(${mapView.x}px, ${mapView.y}px, 0) scale(${mapView.zoom})` }}
        >
          <LiveImage className={mapLive ? "live-map" : ""} draggable="false" endpoint="/api/v1/media/map" fallback={slamMap} enabled={mapLive} interval={1000} alt="ROS 2 SLAM 점유 지도와 로봇 위치" />
          {!mapLive && <div className="robot-marker" aria-label="목업 로봇 위치"><Robot size={18} weight="fill" /></div>}
          {!mapLive && <div className="map-callout">
            <ThermometerHot size={16} weight="fill" />
            <div><strong>84.6°C</strong><span>P-02 베어링</span></div>
          </div>}
          {goalCandidate && (
            <div
              className="goal-marker"
              style={{ left: `${goalCandidate.screenX}%`, top: `${goalCandidate.screenY}%` }}
              aria-label="목적지 후보"
            >
              <NavigationArrow size={17} weight="fill" />
            </div>
          )}
        </div>
        <div className={`map-live-badge ${mapLive ? "" : "mock"}`}><span />{mapLive ? "SLAM 실시간" : "지도 목업"}</div>
        {goalMode && <div className="goal-mode-hint">지도를 클릭해 목적지 후보를 선택하세요</div>}
        <div className="map-zoom" onPointerDown={(event) => event.stopPropagation()}>
          <button type="button" aria-label="지도 확대" title="지도 확대" disabled={mapView.zoom >= 4} onClick={() => changeZoom(0.25)}>+</button>
          <button type="button" aria-label="지도 축소" title="지도 축소" disabled={mapView.zoom <= 0.5} onClick={() => changeZoom(-0.25)}>−</button>
        </div>
      </div>
      <footer className="map-footer">
        <span><i className="legend-route" />로봇 위치</span>
        <span><i className="legend-risk" />점유 장애물</span>
        <strong>{mapLive ? `ROS /map · ${Math.round(mapView.zoom * 100)}%` : `목업 · ${Math.round(mapView.zoom * 100)}%`}</strong>
      </footer>
    </section>
  );
}

function CameraPanel({ thermal = false, maxTemperature = 84.6, mediaStatus, onOpen, className = "" }) {
  const stream = thermal ? mediaStatus?.thermal : mediaStatus?.rgb;
  const live = Boolean(stream?.available);
  const endpoint = thermal ? "/api/v1/media/thermal" : "/api/v1/media/rgb";
  return (
    <section className={`panel camera-panel ${className}`}>
      <PanelHeader
        eyebrow={thermal ? "THERMAL CAMERA" : "RGB CAMERA"}
        title={thermal ? "열화상 영상" : "실시간 영상"}
        action={
          <div className="panel-inline-actions">
            <span className={`live-label ${live ? "" : "mock"}`}><span />{live ? (thermal ? "SIMULATED" : "LIVE") : "MOCK"}</span>
            {onOpen && <button type="button" className="icon-action" aria-label={`${thermal ? "열화상" : "RGB"} 영상 상세 화면 열기`} onClick={onOpen}><CaretRight size={18} /></button>}
          </div>
        }
      />
      <div className="camera-stage">
        <LiveImage
          endpoint={endpoint}
          fallback={thermal ? thermalFeed : rgbFeed}
          enabled={live}
          interval={thermal ? 400 : 300}
          alt={thermal ? "RGB 영상에서 합성한 시뮬레이션 열화상" : "Gazebo 전방 RGB 카메라 영상"}
        />
        <div className="camera-meta top-left">CAM-{thermal ? "TH01" : "RGB01"}</div>
        {thermal ? (
          <>
            <div className="thermal-reading"><span>MAX</span><strong>{maxTemperature.toFixed(1)}°C</strong></div>
            <div className="thermal-scale" aria-label="열화상 색상 범위"><span>90°</span><i /><span>20°</span></div>
          </>
        ) : <div className="camera-meta bottom-right">A동 펌프실</div>}
      </div>
    </section>
  );
}

function EventsPanel({ events, onAcknowledge, onViewAll }) {
  const pending = events.filter((event) => !event.acknowledged).length;
  return (
    <section className="panel events-panel">
      <PanelHeader eyebrow="EVENT FEED" title="위험 이벤트" action={<span className="count-badge">{pending} 미확인</span>} />
      <div className="event-list">
        {events.map((event) => (
          <article key={event.id} className={`event-card ${event.level} ${event.acknowledged ? "acknowledged" : ""}`}>
            <div className="event-icon">
              {event.level === "critical" ? <Siren size={19} weight="fill" /> : event.level === "warning" ? <Warning size={19} weight="fill" /> : <CheckCircle size={19} weight="fill" />}
            </div>
            <div className="event-content">
              <div className="event-title-row"><strong>{event.title}</strong><time>{event.time}</time></div>
              <p>{event.location}</p>
              <span className="event-detail">{event.detail}</span>
              <div className="event-actions">
                {event.temperature && <b>{event.temperature}</b>}
                {!event.acknowledged ? (
                  <button type="button" onClick={() => onAcknowledge(event.id)}><Check size={14} weight="bold" />확인</button>
                ) : <span className="ack-label"><Check size={14} />확인됨</span>}
              </div>
            </div>
          </article>
        ))}
      </div>
      <button type="button" className="view-all" onClick={onViewAll}>전체 이벤트 보기<CaretRight size={16} /></button>
    </section>
  );
}

function OperationControlCard({ patrolState, controllerEnabled, onTogglePatrol, onStop, onToggleController }) {
  const stopped = patrolState === "stopped";
  const modeLabel = stopped ? "정지됨" : patrolState === "paused" ? "일시정지" : "자율 순찰 중";
  return (
    <article className="dock-block operations">
      <div className="dock-title"><Robot size={18} weight="fill" /><span>운행 제어</span><StatusPill tone={stopped || patrolState === "paused" ? "neutral" : "success"}>{modeLabel}</StatusPill></div>
      <div className="button-row operation-buttons">
        <button type="button" className="button secondary" aria-label={patrolState === "paused" ? "순찰 재개" : "일시정지"} title={patrolState === "paused" ? "순찰 재개" : "일시정지"} onClick={onTogglePatrol} disabled={stopped}>
          {patrolState === "paused" ? <Play size={17} weight="fill" /> : <Pause size={17} weight="fill" />}
          <span className="operation-label" aria-hidden="true">{patrolState === "paused" ? "순찰 재개" : "일시정지"}</span>
        </button>
        <button type="button" className="button danger" aria-label="운행 정지" title="운행 정지" onClick={onStop} disabled={stopped}><Stop size={17} weight="fill" /><span className="operation-label" aria-hidden="true">운행 정지</span></button>
        <button
          type="button"
          className={`button controller-toggle ${controllerEnabled ? "active" : "ghost"}`}
          aria-pressed={controllerEnabled}
          aria-label={`컨트롤러 ${controllerEnabled ? "켜짐" : "꺼짐"}`}
          title={controllerEnabled ? "컨트롤러 입력 끄기" : "컨트롤러 입력 켜기"}
          onClick={onToggleController}
        >
          <GameController size={17} weight="fill" />
          <span className="operation-label" aria-hidden="true">컨트롤러<small>{controllerEnabled ? "ON" : "OFF"}</small></span>
        </button>
      </div>
    </article>
  );
}

function RobotStatusCard({ telemetry }) {
  const battery = Math.round(telemetry?.battery_percent ?? 78);
  const networkGood = (telemetry?.network_quality ?? "good") === "good";
  const lidarNormal = (telemetry?.lidar_status ?? "normal") === "normal";
  return (
    <article className="dock-block telemetry">
      <div className="dock-title"><ChartBar size={18} /><span>로봇 상태</span></div>
      <div className="telemetry-grid">
        <div><span>배터리</span><strong>{battery}%</strong><div className="meter"><i style={{ width: `${battery}%` }} /></div></div>
        <div><span>네트워크</span><strong><WifiHigh size={17} weight="fill" /> {networkGood ? "양호" : "불안정"}</strong><small>{telemetry?.network_rssi_dbm ?? -48} dBm</small></div>
        <div><span>LiDAR</span><strong className={lidarNormal ? "healthy" : ""}>{lidarNormal ? "정상" : "확인 필요"}</strong><small>{(telemetry?.lidar_hz ?? 10.2).toFixed(1)} Hz</small></div>
        <div><span>속도</span><strong>{(telemetry?.speed_mps ?? 0.32).toFixed(2)} m/s</strong><small>제한 0.5 m/s</small></div>
      </div>
    </article>
  );
}

function WarningDevicesCard() {
  return (
    <article className="dock-block devices">
      <div className="dock-title"><Bell size={18} /><span>후면 경고장치</span><span className="mock-badge">UI MOCK</span></div>
      <div className="device-row">
        {[1, 2, 3].map((slot) => <button type="button" disabled key={slot}><Bell size={16} />장치 {slot}<span>대기</span></button>)}
      </div>
    </article>
  );
}

function ControlDock({ telemetry, patrolState, controllerEnabled, onTogglePatrol, onStop, onToggleController }) {
  return (
    <section className="control-dock" aria-label="로봇 관제 제어 및 상태">
      <RobotStatusCard telemetry={telemetry} />
      <WarningDevicesCard />
      <OperationControlCard
        patrolState={patrolState}
        controllerEnabled={controllerEnabled}
        onTogglePatrol={onTogglePatrol}
        onStop={onStop}
        onToggleController={onToggleController}
      />
    </section>
  );
}

function Overview({ events, onAcknowledge, onNavigate, notify, telemetry, mediaStatus, sendCommand }) {
  const [patrolState, setPatrolState] = useState("patrol");
  const [controllerEnabled, setControllerEnabled] = useState(false);

  useEffect(() => {
    if (!telemetry) return;
    if (telemetry.mode) setPatrolState(telemetry.mode);
    if (typeof telemetry.controller_enabled === "boolean") {
      setControllerEnabled(telemetry.controller_enabled);
    }
  }, [telemetry]);

  const issueCommand = async (command, enabled, fallbackMessage, tone = "success") => {
    try {
      const result = await sendCommand(command, enabled);
      if (!result.accepted) {
        notify(result.message, "warning");
        return;
      }
      if (result.mode) setPatrolState(result.mode);
      if (typeof result.controller_enabled === "boolean") {
        setControllerEnabled(result.controller_enabled);
      }
      notify(result.message || fallbackMessage, tone);
    } catch {
      notify(`${fallbackMessage} 서버 미연결 상태라 화면에만 반영했습니다.`, "warning");
    }
  };
  const togglePatrol = () => {
    const command = patrolState === "paused" ? "resume" : "pause";
    const next = command === "resume" ? "patrol" : "paused";
    setPatrolState(next);
    void issueCommand(command, false, next === "paused" ? "순찰을 일시정지했습니다." : "순찰을 재개했습니다.");
  };
  const stopPatrol = () => {
    setPatrolState("stopped");
    setControllerEnabled(false);
    void issueCommand("stop", false, "운행 정지 요청을 기록했습니다. (mock)", "warning");
  };
  const toggleController = () => {
    const next = !controllerEnabled;
    setControllerEnabled(next);
    void issueCommand("controller", next, `동봉 컨트롤러 입력을 ${next ? "활성화" : "비활성화"}했습니다.`);
  };
  return (
    <div className="overview-layout">
      <div className="dashboard-grid">
        <MapPanel mediaStatus={mediaStatus} onLocate={() => notify("현재 로봇 위치를 지도 중앙에 표시했습니다.")} onOpen={() => onNavigate("map")} />
        <div className="camera-stack">
          <CameraPanel mediaStatus={mediaStatus} onOpen={() => onNavigate("video")} />
          <CameraPanel thermal mediaStatus={mediaStatus} maxTemperature={telemetry?.max_temperature_c ?? 84.6} onOpen={() => onNavigate("video")} />
        </div>
        <EventsPanel events={events} onAcknowledge={onAcknowledge} onViewAll={() => onNavigate("events")} />
      </div>
      <ControlDock
        telemetry={telemetry}
        patrolState={patrolState}
        controllerEnabled={controllerEnabled}
        onTogglePatrol={togglePatrol}
        onStop={stopPatrol}
        onToggleController={toggleController}
      />
    </div>
  );
}

function DetailHeading({ eyebrow, title, description, children }) {
  return (
    <header className="detail-heading">
      <div>
        <span className="eyebrow">{eyebrow}</span>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      <div className="detail-heading-actions">
        <CurrentTime />
        {children}
      </div>
    </header>
  );
}

function MapPage({ mediaStatus, telemetry, notify }) {
  const [goalMode, setGoalMode] = useState(false);
  const [goalCandidate, setGoalCandidate] = useState(null);
  const [activeGoal, setActiveGoal] = useState(null);
  const [navigationStatus, setNavigationStatus] = useState(null);
  const [goalSubmitting, setGoalSubmitting] = useState(false);
  const mapLive = Boolean(mediaStatus?.map?.available);
  const navActive = ["sending", "accepted", "executing", "canceling"].includes(navigationStatus?.status);
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

  const selectGoal = (candidate) => {
    setGoalCandidate(candidate);
    notify("목적지 후보를 선택했습니다. 오른쪽 패널에서 확인하세요.", "info");
  };
  const confirmGoal = async () => {
    if (!goalCandidate || goalCandidate.mapX === null || goalCandidate.mapY === null) return;
    setGoalSubmitting(true);
    try {
      const response = await fetch("/api/v1/navigation/goal", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          x: goalCandidate.mapX,
          y: goalCandidate.mapY,
          yaw: 0,
          frame_id: goalCandidate.frameId,
        }),
      });
      const result = await response.json();
      setNavigationStatus(result);
      if (!response.ok || !result.accepted) {
        notify(result.message || "Nav2가 목적지를 수락하지 않았습니다.", "warning");
        return;
      }
      setActiveGoal(goalCandidate);
      setGoalMode(false);
      setGoalCandidate(null);
      notify("Nav2가 목적지를 수락했습니다. 지도와 상태 패널에서 이동을 확인하세요.");
    } catch {
      notify("목적지 전송에 실패했습니다. 시뮬레이션 API 연결을 확인하세요.", "warning");
    } finally {
      setGoalSubmitting(false);
    }
  };
  const cancelGoal = async () => {
    try {
      const response = await fetch("/api/v1/navigation/goal", { method: "DELETE" });
      const result = await response.json();
      setNavigationStatus(result);
      notify(result.message, result.status === "canceling" ? "info" : "warning");
    } catch {
      notify("목적지 취소 요청에 실패했습니다.", "warning");
    }
  };
  const saveMap = async () => {
    try {
      await downloadAsset(mapLive ? "/api/v1/media/map" : slamMap, `hazard-guard-map-${new Date().toISOString().slice(0, 10)}.png`);
      notify("현재 지도를 PNG 파일로 저장했습니다.");
    } catch {
      notify("지도를 저장하지 못했습니다. 미디어 서버 연결을 확인하세요.", "warning");
    }
  };

  return (
    <div className="detail-page map-page">
      <DetailHeading eyebrow="NAVIGATION" title="지도 관제" description="SLAM 지도와 로봇 위치를 확인하고 다음 이동 목적지를 준비합니다.">
        <span className={`api-status ${mapLive ? "online" : ""}`}><span />{mapLive ? "SLAM 연결" : "지도 목업"}</span>
      </DetailHeading>
      <div className="map-workspace">
        <MapPanel
          detail
          mediaStatus={mediaStatus}
          goalMode={goalMode}
          goalCandidate={goalCandidate || activeGoal}
          onGoalCandidate={selectGoal}
          onLocate={() => notify("현재 로봇 위치를 지도 중앙에 표시했습니다.")}
        />
        <aside className="map-side-panel">
          <section className="detail-card">
            <div className="detail-card-title"><NavigationArrow size={20} weight="fill" /><div><strong>이동 목적지</strong><span>2단계 확인 방식</span></div></div>
            <p className="helper-copy">목적지 선택을 켠 뒤 지도를 클릭하면 후보가 표시됩니다. 확인 전에는 로봇에 명령이 전송되지 않습니다.</p>
            <button
              type="button"
              className={`button ${goalMode ? "secondary" : "primary"} wide-button`}
              onClick={() => { setGoalMode((current) => !current); setGoalCandidate(null); }}
            >
              {goalMode ? <X size={18} /> : <Crosshair size={18} />}
              {goalMode ? "목적지 선택 취소" : "지도에서 목적지 선택"}
            </button>
            {goalCandidate && (
              <div className="goal-confirm">
                <span>선택 좌표 · ROS map 좌표계</span>
                <strong>
                  {goalCandidate.mapX === null
                    ? "실시간 지도 좌표 없음"
                    : `X ${goalCandidate.mapX.toFixed(2)} m · Y ${goalCandidate.mapY.toFixed(2)} m`}
                </strong>
                <small>{goalCandidate.mapX === null ? "시뮬레이션의 실시간 SLAM 지도를 연결해야 목적지를 전송할 수 있습니다." : "로봇의 최종 방향은 현재 0°로 전송됩니다."}</small>
                <div>
                  <button type="button" className="button ghost" onClick={() => setGoalCandidate(null)}>다시 선택</button>
                  <button type="button" className="button primary" disabled={goalSubmitting || goalCandidate.mapX === null || navActive} onClick={confirmGoal}><Check size={17} weight="bold" />{goalSubmitting ? "전송 중" : "목적지 요청"}</button>
                </div>
              </div>
            )}
            {activeGoal && !goalCandidate && (
              <div className="active-goal">
                <span className={`navigation-state ${navigationStatus?.status || "accepted"}`}>{navStatusLabels[navigationStatus?.status] || "Nav2 연결"}</span>
                <strong>{navigationStatus?.message || "Nav2 목적지가 활성화되었습니다."}</strong>
                <p>X {activeGoal.mapX.toFixed(2)} m · Y {activeGoal.mapY.toFixed(2)} m</p>
                {Number.isFinite(navigationStatus?.distance_remaining) && <p>남은 거리 {navigationStatus.distance_remaining.toFixed(2)} m</p>}
                {navActive ? <button type="button" className="text-button danger-text" onClick={cancelGoal}>목적지 취소</button> : <button type="button" className="text-button" onClick={() => setActiveGoal(null)}>완료 표시 닫기</button>}
              </div>
            )}
          </section>
          <section className="detail-card">
            <div className="detail-card-title"><Robot size={20} weight="fill" /><div><strong>로봇 주행 상태</strong><span>ROS 2 텔레메트리</span></div></div>
            <dl className="status-list">
              <div><dt>운행 모드</dt><dd>{telemetry?.mode === "paused" ? "일시정지" : telemetry?.mode === "stopped" ? "정지" : "자율 순찰"}</dd></div>
              <div><dt>현재 속도</dt><dd>{(telemetry?.speed_mps ?? 0.32).toFixed(2)} m/s</dd></div>
              <div><dt>LiDAR</dt><dd className="healthy">{telemetry?.lidar_status === "error" ? "확인 필요" : "정상"}</dd></div>
              <div><dt>지도 소스</dt><dd>{mapLive ? "ROS /map" : "UI 목업"}</dd></div>
              <div><dt>Nav2 상태</dt><dd className={navigationStatus?.status === "executing" ? "healthy" : ""}>{navStatusLabels[navigationStatus?.status] || "확인 중"}</dd></div>
            </dl>
          </section>
          <section className="detail-card compact-card">
            <div className="detail-card-title"><FloppyDisk size={20} /><div><strong>지도 파일</strong><span>현재 화면 저장</span></div></div>
            <button type="button" className="button ghost wide-button" onClick={saveMap}><DownloadSimple size={18} />PNG로 저장</button>
          </section>
        </aside>
      </div>
    </div>
  );
}

function EventLevelIcon({ level, size = 19 }) {
  if (level === "critical") return <Siren size={size} weight="fill" />;
  if (level === "warning") return <Warning size={size} weight="fill" />;
  return <CheckCircle size={size} weight="fill" />;
}

function EventsPage({ events, onUpdateStatus, notify, onOpenVideo }) {
  const [selectedId, setSelectedId] = useState(events[0]?.id ?? null);
  const [levelFilter, setLevelFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [query, setQuery] = useState("");
  const filtered = events.filter((event) => {
    const matchesLevel = levelFilter === "all" || event.level === levelFilter;
    const matchesStatus = statusFilter === "all" || event.status === statusFilter;
    const haystack = `${event.title} ${event.location} ${event.detail}`.toLowerCase();
    return matchesLevel && matchesStatus && haystack.includes(query.trim().toLowerCase());
  });
  const selected = events.find((event) => event.id === selectedId) || filtered[0] || null;

  const updateStatus = (status) => {
    if (!selected) return;
    onUpdateStatus(selected.id, status);
    notify(`이벤트 상태를 '${eventStatusLabels[status]}'으로 변경했습니다.`);
  };

  return (
    <div className="detail-page events-page">
      <DetailHeading eyebrow="EVENT MANAGEMENT" title="위험 이벤트" description="감지 기록을 분류하고 확인부터 해결까지 처리 상태를 관리합니다.">
        <span className="count-badge large">{events.filter((event) => event.status === "new").length} 신규</span>
      </DetailHeading>
      <section className="event-toolbar panel">
        <div className="search-field"><MagnifyingGlass size={18} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="이벤트명, 위치 검색" aria-label="이벤트 검색" /></div>
        <label><Funnel size={17} /><span>등급</span><select value={levelFilter} onChange={(event) => setLevelFilter(event.target.value)}><option value="all">전체</option><option value="critical">위험</option><option value="warning">경고</option><option value="info">정보</option></select></label>
        <label><ClockCounterClockwise size={17} /><span>상태</span><select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option value="all">전체</option><option value="new">신규</option><option value="acknowledged">확인됨</option><option value="working">처리 중</option><option value="resolved">해결됨</option></select></label>
        <span className="filter-result">{filtered.length}건 표시</span>
      </section>
      <div className="event-workspace">
        <section className="panel event-master">
          <div className="event-table-head"><span>이벤트</span><span>발생 위치</span><span>온도</span><span>상태</span><span>시간</span></div>
          <div className="event-table-body">
            {filtered.map((event) => (
              <button key={event.id} type="button" className={`event-table-row ${event.level} ${selected?.id === event.id ? "selected" : ""}`} onClick={() => setSelectedId(event.id)}>
                <span className="event-name-cell"><i><EventLevelIcon level={event.level} /></i><b>{event.title}</b><small>HG-{String(event.id).padStart(4, "0")}</small></span>
                <span>{event.location}</span>
                <strong>{event.temperature || "—"}</strong>
                <em className={`event-state ${event.status}`}>{eventStatusLabels[event.status]}</em>
                <time>{event.time}</time>
              </button>
            ))}
            {!filtered.length && <div className="empty-state"><ListChecks size={30} /><strong>조건에 맞는 이벤트가 없습니다.</strong><span>필터나 검색어를 변경해 보세요.</span></div>}
          </div>
        </section>
        <aside className="panel event-detail-panel">
          {selected ? (
            <>
              <header className={`event-detail-header ${selected.level}`}>
                <div className="event-icon"><EventLevelIcon level={selected.level} size={21} /></div>
                <div><span>HG-{String(selected.id).padStart(4, "0")}</span><h2>{selected.title}</h2><p>{selected.date} · {selected.time}</p></div>
                <em className={`event-state ${selected.status}`}>{eventStatusLabels[selected.status]}</em>
              </header>
              <div className="event-detail-body">
                <dl className="event-detail-list">
                  <div><dt>발생 위치</dt><dd>{selected.location}</dd></div>
                  <div><dt>측정 온도</dt><dd className={selected.temperature ? "danger-value" : ""}>{selected.temperature || "해당 없음"}</dd></div>
                  <div><dt>판정 기준</dt><dd>{selected.threshold || "상태 정보"}</dd></div>
                  <div><dt>담당자</dt><dd>{selected.assignee}</dd></div>
                </dl>
                <div className="event-note"><NotePencil size={18} /><div><strong>운영 메모</strong><p>{selected.note}</p></div></div>
                <div className="event-preview-grid">
                  <button type="button" onClick={onOpenVideo}><img src={rgbFeed} alt="이벤트 RGB 스냅샷" /><span>RGB 확인</span></button>
                  <button type="button" onClick={onOpenVideo}><img src={thermalFeed} alt="이벤트 열화상 스냅샷" /><span>열화상 확인</span></button>
                </div>
              </div>
              <footer className="event-detail-actions">
                {selected.status === "new" && <button type="button" className="button secondary" onClick={() => updateStatus("acknowledged")}><Check size={17} weight="bold" />확인 처리</button>}
                {["new", "acknowledged"].includes(selected.status) && <button type="button" className="button primary" onClick={() => updateStatus("working")}><Play size={17} weight="fill" />처리 시작</button>}
                {selected.status === "working" && <button type="button" className="button primary" onClick={() => updateStatus("resolved")}><CheckCircle size={17} weight="fill" />해결 완료</button>}
                {selected.status === "resolved" && <span className="resolved-copy"><CheckCircle size={18} weight="fill" />처리가 완료된 이벤트입니다.</span>}
              </footer>
            </>
          ) : <div className="empty-state"><ListChecks size={30} /><strong>이벤트를 선택하세요.</strong></div>}
        </aside>
      </div>
    </div>
  );
}

function VideoPage({ mediaStatus, telemetry, events, notify }) {
  const [view, setView] = useState("split");
  const viewerRef = useRef(null);
  const rgbLive = Boolean(mediaStatus?.rgb?.available);
  const thermalLive = Boolean(mediaStatus?.thermal?.available);

  const saveSnapshot = async (thermal = false) => {
    const live = thermal ? thermalLive : rgbLive;
    const source = live ? `/api/v1/media/${thermal ? "thermal" : "rgb"}` : (thermal ? thermalFeed : rgbFeed);
    try {
      await downloadAsset(source, `hazard-guard-${thermal ? "thermal" : "rgb"}-${Date.now()}.jpg`);
      notify(`${thermal ? "열화상" : "RGB"} 스냅샷을 저장했습니다.`);
    } catch {
      notify("스냅샷 저장에 실패했습니다.", "warning");
    }
  };
  const openFullscreen = async () => {
    try {
      await viewerRef.current?.requestFullscreen();
    } catch {
      notify("브라우저에서 전체 화면을 시작하지 못했습니다.", "warning");
    }
  };

  return (
    <div className="detail-page video-page">
      <DetailHeading eyebrow="LIVE MONITORING" title="영상 관제" description="전방 RGB와 열화상 스트림을 비교하고 위험 이벤트의 현장 상황을 확인합니다.">
        <span className={`api-status ${rgbLive ? "online" : ""}`}><span />{rgbLive ? "카메라 연결" : "영상 목업"}</span>
      </DetailHeading>
      <div className="video-toolbar">
        <div className="segmented-control" aria-label="영상 보기 방식">
          <button type="button" className={view === "split" ? "active" : ""} onClick={() => setView("split")}>분할 보기</button>
          <button type="button" className={view === "rgb" ? "active" : ""} onClick={() => setView("rgb")}>RGB</button>
          <button type="button" className={view === "thermal" ? "active" : ""} onClick={() => setView("thermal")}>열화상</button>
        </div>
        <button type="button" className="button ghost compact-button" onClick={openFullscreen}><ArrowsOut size={18} />전체 화면</button>
      </div>
      <div className="video-workspace">
        <section ref={viewerRef} className={`video-viewer panel view-${view}`}>
          {(view === "split" || view === "rgb") && (
            <div className="detail-stream">
              <div className="stream-label"><div><Camera size={18} /><strong>RGB 전방 카메라</strong></div><span className={`live-label ${rgbLive ? "" : "mock"}`}><span />{rgbLive ? "LIVE" : "MOCK"}</span></div>
              <div className="detail-stream-stage">
                <LiveImage endpoint="/api/v1/media/rgb" fallback={rgbFeed} enabled={rgbLive} interval={300} alt="로봇 전방 RGB 실시간 영상" />
                <div className="camera-meta top-left">CAM-RGB01</div>
                <div className="camera-meta bottom-right">A동 펌프실</div>
              </div>
              <button type="button" className="snapshot-button" onClick={() => saveSnapshot(false)}><ImageSquare size={17} />RGB 스냅샷</button>
            </div>
          )}
          {(view === "split" || view === "thermal") && (
            <div className="detail-stream thermal-stream">
              <div className="stream-label"><div><ThermometerHot size={18} /><strong>열화상 카메라</strong></div><span className={`live-label ${thermalLive ? "" : "mock"}`}><span />{thermalLive ? "SIMULATED" : "MOCK"}</span></div>
              <div className="detail-stream-stage">
                <LiveImage endpoint="/api/v1/media/thermal" fallback={thermalFeed} enabled={thermalLive} interval={400} alt="열화상 실시간 영상" />
                <div className="thermal-reading detail-reading"><span>MAX</span><strong>{(telemetry?.max_temperature_c ?? 84.6).toFixed(1)}°C</strong></div>
                <div className="thermal-scale" aria-label="열화상 색상 범위"><span>90°</span><i /><span>20°</span></div>
                {thermalLive && <span className="simulation-watermark">RGB 기반 합성 열화상</span>}
              </div>
              <button type="button" className="snapshot-button" onClick={() => saveSnapshot(true)}><ImageSquare size={17} />열화상 스냅샷</button>
            </div>
          )}
        </section>
        <aside className="video-side-panel">
          <section className="detail-card">
            <div className="detail-card-title"><ThermometerHot size={20} weight="fill" /><div><strong>온도 상태</strong><span>현재 프레임 기준</span></div></div>
            <div className="temperature-summary"><strong>{(telemetry?.max_temperature_c ?? 84.6).toFixed(1)}°C</strong><span>위험 기준 80.0°C</span></div>
            <progress className="temperature-progress" value={Math.min(100, telemetry?.max_temperature_c ?? 84.6)} max="100">84.6%</progress>
            <dl className="status-list compact">
              <div><dt>경고 기준</dt><dd>60°C · 5초</dd></div>
              <div><dt>위험 기준</dt><dd>80°C · 3초</dd></div>
              <div><dt>촬영 위치</dt><dd>A동 펌프실</dd></div>
            </dl>
          </section>
          <section className="detail-card video-event-card">
            <div className="detail-card-title"><Siren size={20} weight="fill" /><div><strong>연관 이벤트</strong><span>최근 위험 감지</span></div></div>
            {events.filter((event) => event.level !== "info").slice(0, 3).map((event) => (
              <div key={event.id} className={`mini-event ${event.level}`}>
                <EventLevelIcon level={event.level} size={16} />
                <div><strong>{event.title}</strong><span>{event.location}</span></div>
                <time>{event.time}</time>
              </div>
            ))}
          </section>
        </aside>
      </div>
    </div>
  );
}

function MetricCard({ label, value, unit, meta, tone = "" }) {
  return (
    <article className={`metric-card ${tone}`}>
      <span>{label}</span>
      <div><strong>{value}</strong>{unit && <small>{unit}</small>}</div>
      <p>{meta}</p>
    </article>
  );
}

function ReportsPage({ events, notify }) {
  const [period, setPeriod] = useState("week");
  const data = reportData[period];
  const exportCsv = () => {
    const rows = [
      ["기간", data.label],
      ["순찰 시간(시간)", data.patrolHours],
      ["이동 거리(km)", data.distance],
      ["순찰 완료율(%)", data.completion],
      ["전체 이벤트", data.events],
      ["위험", data.critical],
      ["경고", data.warning],
      ["정보", data.info],
      ["평균 확인 시간(분)", data.acknowledge],
      ["평균 해결 시간(분)", data.resolve],
      ["최고 온도(°C)", data.temperature],
    ];
    const csv = `\uFEFF${rows.map((row) => row.join(",")).join("\n")}`;
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `hazard-guard-report-${period}.csv`;
    anchor.click();
    URL.revokeObjectURL(url);
    notify(`${data.label} 리포트를 CSV로 저장했습니다.`);
  };

  return (
    <div className="detail-page reports-page">
      <DetailHeading eyebrow="OPERATIONS REPORT" title="운영 리포트" description="순찰 성과, 위험 이벤트, 센서 상태를 기간별로 요약합니다.">
        <button type="button" className="button ghost compact-button" onClick={exportCsv}><FileCsv size={18} />CSV 내보내기</button>
      </DetailHeading>
      <div className="report-toolbar">
        <div className="segmented-control" aria-label="리포트 기간">
          <button type="button" className={period === "today" ? "active" : ""} onClick={() => setPeriod("today")}>오늘</button>
          <button type="button" className={period === "week" ? "active" : ""} onClick={() => setPeriod("week")}>최근 7일</button>
          <button type="button" className={period === "month" ? "active" : ""} onClick={() => setPeriod("month")}>최근 30일</button>
        </div>
        <span><CalendarBlank size={17} />{data.label} 집계 · 프로토타입 데이터</span>
      </div>
      <section className="metric-grid">
        <MetricCard label="순찰 시간" value={data.patrolHours} unit="시간" meta="자율·수동 운행 합계" />
        <MetricCard label="이동 거리" value={data.distance} unit="km" meta="누적 주행 거리" />
        <MetricCard label="순찰 완료율" value={data.completion} unit="%" meta="계획 경로 대비" tone="success-metric" />
        <MetricCard label="위험 이벤트" value={data.critical} unit="건" meta={`전체 ${data.events}건 중`} tone="danger-metric" />
      </section>
      <div className="report-grid">
        <section className="panel report-card event-breakdown">
          <PanelHeader eyebrow="EVENT BREAKDOWN" title="이벤트 등급 분포" />
          <div className="report-card-body">
            {[
              ["위험", data.critical, "critical"],
              ["경고", data.warning, "warning"],
              ["정보", data.info, "info"],
            ].map(([label, value, tone]) => (
              <div className="report-progress-row" key={label}>
                <span>{label}</span>
                <progress className={tone} value={value} max={data.events}>{value}</progress>
                <strong>{value}건</strong>
              </div>
            ))}
            <div className="report-summary-line"><span>평균 확인 시간<strong>{data.acknowledge}분</strong></span><span>평균 해결 시간<strong>{data.resolve}분</strong></span><span>최고 온도<strong>{data.temperature}°C</strong></span></div>
          </div>
        </section>
        <section className="panel report-card patrol-health">
          <PanelHeader eyebrow="SYSTEM HEALTH" title="운행 및 센서 건전성" />
          <div className="health-grid">
            <div><span>LiDAR 수신률</span><strong>99.8%</strong><progress value="99.8" max="100">99.8%</progress></div>
            <div><span>카메라 가용률</span><strong>98.6%</strong><progress value="98.6" max="100">98.6%</progress></div>
            <div><span>네트워크 연결률</span><strong>97.9%</strong><progress value="97.9" max="100">97.9%</progress></div>
            <div><span>평균 배터리</span><strong>72%</strong><progress value="72" max="100">72%</progress></div>
          </div>
        </section>
        <section className="panel report-card report-table-card">
          <PanelHeader eyebrow="RECENT LOG" title="최근 운영 기록" />
          <div className="report-table">
            <div className="report-table-head"><span>시간</span><span>구분</span><span>내용</span><span>결과</span></div>
            {events.slice(0, 5).map((event) => (
              <div className="report-table-row" key={event.id}><time>{event.time}</time><span>{event.level === "critical" ? "위험" : event.level === "warning" ? "경고" : "정보"}</span><strong>{event.title}</strong><em className={`event-state ${event.status}`}>{eventStatusLabels[event.status]}</em></div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}

function NumberField({ label, name, value, onChange, unit, hint, min = 0, max = 999 }) {
  return (
    <label className="form-field">
      <span>{label}</span>
      <div className="number-input"><input type="number" name={name} value={value} min={min} max={max} step="1" onChange={onChange} /><b>{unit}</b></div>
      {hint && <small>{hint}</small>}
    </label>
  );
}

function Settings({ notify, apiOnline }) {
  const [values, setValues] = useState(() => {
    try { return { ...initialThresholds, ...JSON.parse(localStorage.getItem("hazardGuardThresholds") || "{}") }; }
    catch { return initialThresholds; }
  });
  const [errors, setErrors] = useState([]);
  const update = ({ target }) => setValues((current) => ({ ...current, [target.name]: Number(target.value) }));
  const reset = () => { setValues(initialThresholds); setErrors([]); notify("권장 데모값으로 되돌렸습니다."); };
  const save = async (event) => {
    event.preventDefault();
    const nextErrors = [];
    if (values.criticalTemperature <= values.warningTemperature) nextErrors.push("위험 온도는 경고 온도보다 높아야 합니다.");
    if (values.clearTemperature >= values.warningTemperature) nextErrors.push("정상 복귀 온도는 경고 온도보다 낮아야 합니다.");
    if ([values.warningDuration, values.criticalDuration, values.clearDuration].some((v) => v < 1)) nextErrors.push("지속 시간은 1초 이상이어야 합니다.");
    setErrors(nextErrors);
    if (nextErrors.length) return;
    localStorage.setItem("hazardGuardThresholds", JSON.stringify(values));
    if (apiOnline) {
      try {
        await fetch("/api/v1/settings/thresholds", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(values) });
      } catch { /* local save remains valid */ }
    }
    notify("화재 판정 조건을 저장했습니다.");
  };
  return (
    <div className="settings-page">
      <div className="page-heading">
        <div><span className="eyebrow">SYSTEM SETTINGS</span><h1>화재 판정 설정</h1><p>열화상 센서의 온도와 지속 시간을 조합해 경고 단계를 정의합니다.</p></div>
        <span className={`api-status ${apiOnline ? "online" : ""}`}><span />{apiOnline ? "서버 연결" : "서버 미연결"}</span>
      </div>
      <form onSubmit={save} className="settings-form">
        <section className="settings-card warning-card">
          <header><div className="setting-icon"><Warning size={21} weight="fill" /></div><div><h2>경고 조건</h2><p>초기 과열 징후를 관리자에게 알립니다.</p></div></header>
          <div className="field-grid"><NumberField label="경고 온도" name="warningTemperature" value={values.warningTemperature} onChange={update} unit="°C" min={1} max={200} /><NumberField label="최소 지속 시간" name="warningDuration" value={values.warningDuration} onChange={update} unit="초" min={1} max={300} /></div>
        </section>
        <section className="settings-card critical-card">
          <header><div className="setting-icon"><Siren size={21} weight="fill" /></div><div><h2>위험 조건</h2><p>즉시 확인이 필요한 고온 상태를 판정합니다.</p></div></header>
          <div className="field-grid"><NumberField label="위험 온도" name="criticalTemperature" value={values.criticalTemperature} onChange={update} unit="°C" min={1} max={250} /><NumberField label="최소 지속 시간" name="criticalDuration" value={values.criticalDuration} onChange={update} unit="초" min={1} max={300} /></div>
        </section>
        <section className="settings-card clear-card">
          <header><div className="setting-icon"><CheckCircle size={21} weight="fill" /></div><div><h2>정상 복귀 조건</h2><p>위험 상태가 해제되었음을 판단합니다.</p></div></header>
          <div className="field-grid"><NumberField label="복귀 온도" name="clearTemperature" value={values.clearTemperature} onChange={update} unit="°C" min={0} max={200} /><NumberField label="최소 지속 시간" name="clearDuration" value={values.clearDuration} onChange={update} unit="초" min={1} max={600} /></div>
        </section>
        <section className="settings-card repeat-card">
          <header><div className="setting-icon"><ClockCounterClockwise size={21} weight="fill" /></div><div><h2>알림 반복 주기</h2><p>동일 이벤트가 계속될 때 재알림 간격을 정합니다.</p></div></header>
          <div className="field-grid"><NumberField label="경고 재알림" name="warningRepeat" value={values.warningRepeat} onChange={update} unit="초" min={10} max={3600} /><NumberField label="미확인 위험 재알림" name="criticalRepeat" value={values.criticalRepeat} onChange={update} unit="초" min={10} max={3600} /></div>
        </section>
        {errors.length > 0 && <div className="form-errors" role="alert"><Warning size={19} weight="fill" /><div>{errors.map((error) => <p key={error}>{error}</p>)}</div></div>}
        <footer className="form-footer"><button type="button" className="button ghost" onClick={reset}>권장값으로 초기화</button><button type="submit" className="button primary"><Check size={17} weight="bold" />설정 저장</button></footer>
      </form>
    </div>
  );
}

export function App() {
  const [active, setActive] = useState("overview");
  const [events, setEvents] = useState(initialEvents);
  const [toast, setToast] = useState(null);
  const [apiOnline, setApiOnline] = useState(false);
  const [telemetry, setTelemetry] = useState(null);
  const [mediaStatus, setMediaStatus] = useState(null);

  const notify = (message, tone = "success") => {
    setToast({ message, tone, id: Date.now() });
  };
  useEffect(() => {
    let disposed = false;
    const checkHealth = async () => {
      const controller = new AbortController();
      const timer = window.setTimeout(() => controller.abort(), 1200);
      try {
        const response = await fetch("/api/health", { signal: controller.signal });
        if (!disposed) setApiOnline(response.ok);
      } catch {
        if (!disposed) setApiOnline(false);
      } finally {
        window.clearTimeout(timer);
      }
    };
    void checkHealth();
    const interval = window.setInterval(checkHealth, 5000);
    return () => { disposed = true; window.clearInterval(interval); };
  }, []);
  useEffect(() => {
    let disposed = false;
    const checkMedia = async () => {
      try {
        const response = await fetch("/api/v1/media/status", { cache: "no-store" });
        if (!disposed && response.ok) setMediaStatus(await response.json());
      } catch {
        if (!disposed) setMediaStatus(null);
      }
    };
    void checkMedia();
    const interval = window.setInterval(checkMedia, 2000);
    return () => { disposed = true; window.clearInterval(interval); };
  }, []);
  useEffect(() => {
    let disposed = false;
    let socket;
    let reconnectTimer;
    const connect = () => {
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      socket = new WebSocket(`${protocol}//${window.location.host}/ws/telemetry`);
      socket.onmessage = ({ data }) => {
        try { setTelemetry(JSON.parse(data)); }
        catch { /* ignore malformed prototype telemetry */ }
      };
      socket.onerror = () => socket.close();
      socket.onclose = () => {
        if (!disposed) reconnectTimer = window.setTimeout(connect, 1500);
      };
    };
    connect();
    return () => {
      disposed = true;
      window.clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, []);
  useEffect(() => {
    if (!toast) return undefined;
    const timer = setTimeout(() => setToast(null), 3200);
    return () => clearTimeout(timer);
  }, [toast]);

  const acknowledge = (id) => {
    setEvents((current) => current.map((event) => event.id === id ? { ...event, acknowledged: true, status: "acknowledged" } : event));
    notify("이벤트를 확인 처리했습니다.");
  };
  const updateEventStatus = (id, status) => {
    setEvents((current) => current.map((event) => event.id === id ? {
      ...event,
      status,
      acknowledged: status !== "new",
      assignee: status === "new" ? "미지정" : status === "resolved" ? "관리자" : "관리자",
    } : event));
  };
  const navigate = (id) => {
    if (["overview", "map", "events", "video", "report", "settings"].includes(id)) setActive(id);
    else notify(`${navItems.find((item) => item.id === id)?.label || "도움말"} 화면은 다음 단계에서 연결됩니다.`, "info");
  };
  const sendCommand = async (command, enabled = false) => {
    const response = await fetch(`/api/v1/commands/${command}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    });
    if (!response.ok) throw new Error(`Command failed: ${response.status}`);
    return response.json();
  };

  return (
    <div className="app-shell">
      <Sidebar active={active} onNavigate={navigate} pendingEvents={events.filter((event) => event.status === "new").length} />
      <main className="main-content">
        {active === "overview" && <Overview events={events} onAcknowledge={acknowledge} onNavigate={navigate} notify={notify} telemetry={telemetry} mediaStatus={mediaStatus} sendCommand={sendCommand} />}
        {active === "map" && <MapPage mediaStatus={mediaStatus} telemetry={telemetry} notify={notify} />}
        {active === "events" && <EventsPage events={events} onUpdateStatus={updateEventStatus} notify={notify} onOpenVideo={() => navigate("video")} />}
        {active === "video" && <VideoPage mediaStatus={mediaStatus} telemetry={telemetry} events={events} notify={notify} />}
        {active === "report" && <ReportsPage events={events} notify={notify} />}
        {active === "settings" && <Settings notify={notify} apiOnline={apiOnline} />}
      </main>
      {toast && <div className={`toast ${toast.tone}`} role="status"><CheckCircle size={19} weight="fill" /><span>{toast.message}</span></div>}
    </div>
  );
}
