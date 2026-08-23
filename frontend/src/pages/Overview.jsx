import { useEffect, useState } from "react";
import {
  Bell,
  CaretRight,
  ChartBar,
  Check,
  CheckCircle,
  ClockCounterClockwise,
  GameController,
  Pause,
  Play,
  Robot,
  Siren,
  Stop,
  Warning,
  WifiHigh,
} from "@phosphor-icons/react";
import rgbFeed from "../assets/industrial-rgb.webp";
import thermalFeed from "../assets/industrial-thermal.webp";
import MapPanel from "../components/MapPanel.jsx";
import {
  LiveImage,
  PanelHeader,
  StatusPill,
} from "../components/Common.jsx";

function CameraPanel({ thermal = false, maxTemperature = 84.6, mediaStatus, onOpen, className = "" }) {
  const stream = thermal ? mediaStatus?.thermal : mediaStatus?.rgb;
  const live = Boolean(stream?.available);
  const gazeboThermal = thermal && stream?.source === "gazebo:/thermal_camera/image_raw";
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
          alt={thermal ? (gazeboThermal ? "Gazebo 열화상 카메라 시뮬레이션 영상" : "RGB 영상에서 합성한 시뮬레이션 열화상") : "Gazebo 전방 RGB 카메라 영상"}
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
              {event.level === "critical" ? <Siren size={19} weight="fill" /> : event.level === "warning" ? <Warning size={19} weight="fill" /> : event.level === "watch" ? <ClockCounterClockwise size={19} weight="fill" /> : <CheckCircle size={19} weight="fill" />}
            </div>
            <div className="event-content">
              <div className="event-title-row"><strong>{event.title}</strong><time>{event.time}</time></div>
              <p>{event.location}</p>
              <span className="event-detail">{event.detail}</span>
              <div className="event-actions">
                {event.temperature && <b>{event.temperature}</b>}
                {!event.acknowledged ? (
                  <button type="button" onClick={() => event.incident ? onViewAll() : onAcknowledge(event.id)}><Check size={14} weight="bold" />{event.incident ? "조치 선택" : "확인"}</button>
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

export default function Overview({ events, onAcknowledge, onNavigate, notify, telemetry, mediaStatus, spatialState, sendCommand }) {
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
        <MapPanel mediaStatus={mediaStatus} spatialState={spatialState} onLocate={() => notify("현재 로봇 위치를 지도 중앙에 표시했습니다.")} onOpen={() => onNavigate("map")} />
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
