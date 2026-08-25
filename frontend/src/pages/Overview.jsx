import { useEffect, useState } from "react";
import {
  Bell,
  Camera,
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
  ThermometerHot,
  Warning,
  WifiHigh,
} from "@phosphor-icons/react";
import MapPanel from "../components/MapPanel.jsx";
import { batteryPresentation } from "../batteryTelemetry.js";
import { beaconSlots, incidentMapMarkers } from "../incidents.js";
import { telemetryModeLabel, telemetryPresentation } from "../telemetry.js";
import {
  LiveImage,
  ConnectionPlaceholder,
  PanelHeader,
  StatusPill,
} from "../components/Common.jsx";

function CameraPanel({ thermal = false, maxTemperature = null, mediaStatus, onOpen, className = "" }) {
  const stream = thermal ? mediaStatus?.thermal : mediaStatus?.rgb;
  const live = Boolean(stream?.available);
  const gazeboThermal = thermal && stream?.source === "gazebo:/thermal_camera/image_raw";
  const physicalThermal = thermal && stream?.source === "ros:/thermal_camera/image_color";
  const endpoint = thermal ? "/api/v1/media/thermal" : "/api/v1/media/rgb";
  const temperatureAvailable = maxTemperature != null && Number.isFinite(Number(maxTemperature));
  return (
    <section className={`panel camera-panel ${className}`}>
      <PanelHeader
        eyebrow={thermal ? "THERMAL CAMERA" : "RGB CAMERA"}
        title={thermal ? "열화상 영상" : "실시간 영상"}
        action={
          <div className="panel-inline-actions">
            <span className={`live-label ${live ? "" : "offline"}`}><span />{live ? (thermal && gazeboThermal ? "SIMULATED" : "LIVE") : "연결 필요"}</span>
            {onOpen && <button type="button" className="icon-action" aria-label={`${thermal ? "열화상" : "RGB"} 영상 상세 화면 열기`} onClick={onOpen}><CaretRight size={18} /></button>}
          </div>
        }
      />
      <div className="camera-stage">
        {live ? <>
          <LiveImage
            endpoint={endpoint}
            enabled
            interval={thermal ? 400 : 300}
            alt={thermal ? (physicalThermal ? "ThermoEye SDK 실시간 열화상 영상" : gazeboThermal ? "Gazebo 열화상 카메라 시뮬레이션 영상" : "열화상 카메라 영상") : "전방 RGB 카메라 영상"}
          />
          <div className="camera-meta top-left">CAM-{thermal ? "TH01" : "RGB01"}</div>
          {thermal ? (
          <>
            {temperatureAvailable && <div className="thermal-reading"><span>MAX</span><strong>{Number(maxTemperature).toFixed(1)}°C</strong></div>}
            <div className="camera-thermal-scale" aria-label="열화상 색상 범위"><span>40°</span><i /><span>20°</span></div>
          </>
          ) : null}
        </> : (
          <ConnectionPlaceholder
            icon={thermal ? ThermometerHot : Camera}
            title={`${thermal ? "열화상" : "RGB"} 카메라 연결이 필요합니다`}
            description="센서와 서버가 연결되면 실시간 영상이 표시됩니다."
          />
        )}
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

function OperationControlCard({ patrolState, controllerEnabled, telemetryLive, onTogglePatrol, onStop, onToggleController }) {
  const stopped = patrolState === "stopped";
  const modeKnown = telemetryLive && patrolState !== "unknown";
  const modeLabel = modeKnown ? telemetryModeLabel(patrolState) : "상태 확인 필요";
  const canTogglePatrol = telemetryLive && ["patrol", "paused"].includes(patrolState);
  const patrolTitle = !telemetryLive
    ? "로봇 텔레메트리 연결 필요"
    : canTogglePatrol ? (patrolState === "paused" ? "순찰 재개" : "일시정지") : "순찰 모드에서 사용 가능";
  return (
    <article className="dock-block operations">
      <div className="dock-title"><Robot size={18} weight="fill" /><span>운행 제어</span><StatusPill tone={patrolState === "patrol" ? "success" : "neutral"}>{modeLabel}</StatusPill></div>
      <div className="button-row operation-buttons">
        <button type="button" className="button secondary" aria-label={patrolState === "paused" ? "순찰 재개" : "일시정지"} title={patrolTitle} onClick={onTogglePatrol} disabled={!canTogglePatrol}>
          {patrolState === "paused" ? <Play size={17} weight="fill" /> : <Pause size={17} weight="fill" />}
          <span className="operation-label" aria-hidden="true">{patrolState === "paused" ? "순찰 재개" : "일시정지"}</span>
        </button>
        <button type="button" className="button danger" aria-label="운행 정지" title={telemetryLive ? "운행 정지" : "로봇 텔레메트리 연결 필요"} onClick={onStop} disabled={!telemetryLive || stopped}><Stop size={17} weight="fill" /><span className="operation-label" aria-hidden="true">운행 정지</span></button>
        <button
          type="button"
          className={`button controller-toggle ${controllerEnabled ? "active" : "ghost"}`}
          aria-pressed={controllerEnabled}
          aria-label={`컨트롤러 ${controllerEnabled ? "켜짐" : "꺼짐"}`}
          title={telemetryLive ? (controllerEnabled ? "컨트롤러 입력 끄기" : "컨트롤러 입력 켜기") : "로봇 텔레메트리 연결 필요"}
          onClick={onToggleController}
          disabled={!telemetryLive}
        >
          <GameController size={17} weight="fill" />
          <span className="operation-label" aria-hidden="true">컨트롤러<small>{controllerEnabled ? "ON" : "OFF"}</small></span>
        </button>
      </div>
    </article>
  );
}

function RobotStatusCard({ telemetry, telemetryLive }) {
  const battery = batteryPresentation(telemetryLive ? telemetry : null);
  const status = telemetryPresentation(telemetry, telemetryLive);
  return (
    <article className="dock-block telemetry">
      <div className="dock-title"><ChartBar size={18} /><span>로봇 상태</span></div>
      <div className="telemetry-grid">
        <div className={battery.available ? "" : "telemetry-unavailable"}>
          <span>배터리</span>
          <strong>{battery.percentLabel}</strong>
          <small>{battery.voltageLabel}</small>
          <div className={`meter ${battery.level}`}>
            <i style={{ width: `${battery.meterWidth}%` }} />
          </div>
        </div>
        <div className={status.available ? "" : "telemetry-unavailable"}><span>네트워크</span><strong className={status.networkHealthy ? "healthy" : ""}><WifiHigh size={17} weight="fill" /> {status.networkLabel}</strong><small>{status.networkDetail}</small></div>
        <div className={status.available ? "" : "telemetry-unavailable"}><span>LiDAR</span><strong className={status.lidarHealthy ? "healthy" : ""}>{status.lidarLabel}</strong><small>{status.lidarDetail}</small></div>
        <div className={status.available ? "" : "telemetry-unavailable"}><span>속도</span><strong>{status.speedLabel}</strong><small>{status.speedDetail}</small></div>
      </div>
    </article>
  );
}

function WarningDevicesCard({ battery }) {
  const slots = beaconSlots(battery);
  const connectionLabel = battery?.stale
    ? "상태 확인 필요"
    : `${battery?.connected || 0}/${battery?.expected || 3} 연결`;
  return (
    <article className="dock-block devices">
      <div className="dock-title"><Bell size={18} /><span>후면 경고장치</span><span className={`status-pill ${battery?.stale ? "offline" : "online"}`}>{connectionLabel}</span></div>
      <div className="device-row">
        {slots.map((slot) => (
          <button
            type="button"
            disabled
            key={slot.slot}
            className={`${slot.installed ? "installed" : slot.connected ? "connected" : "disconnected"} ${slot.availableForDrop ? "available" : ""}`}
            title={slot.address || `비콘 ${slot.slot}`}
          >
            <Bell size={16} weight={slot.connected ? "fill" : "regular"} />
            <b>비콘 {slot.slot}</b>
            <span>{slot.installed ? "설치됨" : slot.connected ? (slot.percent == null ? "연결됨" : `배터리 ${slot.percent}%`) : (battery?.stale ? "상태 미확인" : "미연결")}</span>
          </button>
        ))}
      </div>
    </article>
  );
}

function ControlDock({ telemetry, telemetryLive, battery, patrolState, controllerEnabled, onTogglePatrol, onStop, onToggleController }) {
  return (
    <section className="control-dock" aria-label="로봇 관제 제어 및 상태">
      <RobotStatusCard telemetry={telemetry} telemetryLive={telemetryLive} />
      <WarningDevicesCard battery={battery} />
      <OperationControlCard
        patrolState={patrolState}
        controllerEnabled={controllerEnabled}
        telemetryLive={telemetryLive}
        onTogglePatrol={onTogglePatrol}
        onStop={onStop}
        onToggleController={onToggleController}
      />
    </section>
  );
}

export default function Overview({ events, onAcknowledge, onNavigate, notify, telemetry, telemetryLive, mediaStatus, spatialState, sendCommand, dispenserBattery, incidents }) {
  const [patrolState, setPatrolState] = useState("unknown");
  const [controllerEnabled, setControllerEnabled] = useState(false);

  useEffect(() => {
    if (!telemetryLive || !telemetry) {
      setPatrolState("unknown");
      setControllerEnabled(false);
      return;
    }
    if (telemetry.mode) setPatrolState(telemetry.mode);
    if (typeof telemetry.controller_enabled === "boolean") {
      setControllerEnabled(telemetry.controller_enabled);
    }
  }, [telemetry, telemetryLive]);

  const issueCommand = async (command, enabled, fallbackMessage, tone = "success") => {
    if (!telemetryLive) {
      notify("로봇 텔레메트리 연결을 확인한 뒤 다시 시도하세요.", "warning");
      return;
    }
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
      notify(`${fallbackMessage} 서버 연결을 확인하세요.`, "warning");
    }
  };
  const togglePatrol = () => {
    const command = patrolState === "paused" ? "resume" : "pause";
    const next = command === "resume" ? "patrol" : "paused";
    void issueCommand(command, false, next === "paused" ? "순찰을 일시정지했습니다." : "순찰을 재개했습니다.");
  };
  const stopPatrol = () => {
    void issueCommand("stop", false, "운행 정지를 요청했습니다.", "warning");
  };
  const toggleController = () => {
    const next = !controllerEnabled;
    void issueCommand("controller", next, `동봉 컨트롤러 입력을 ${next ? "활성화" : "비활성화"}했습니다.`);
  };
  return (
    <div className="overview-layout">
      <div className="dashboard-grid">
        <MapPanel mediaStatus={mediaStatus} spatialState={spatialState} incidentMarkers={incidentMapMarkers(incidents)} onLocate={() => notify("현재 로봇 위치를 지도 중앙에 표시했습니다.")} onOpen={() => onNavigate("map")} />
        <div className="camera-stack">
          <CameraPanel mediaStatus={mediaStatus} onOpen={() => onNavigate("video")} />
          <CameraPanel thermal mediaStatus={mediaStatus} maxTemperature={telemetryLive ? telemetry?.max_temperature_c : null} onOpen={() => onNavigate("video")} />
        </div>
        <EventsPanel events={events} onAcknowledge={onAcknowledge} onViewAll={() => onNavigate("events")} />
      </div>
      <ControlDock
        telemetry={telemetry}
        telemetryLive={telemetryLive}
        battery={dispenserBattery}
        patrolState={patrolState}
        controllerEnabled={controllerEnabled}
        onTogglePatrol={togglePatrol}
        onStop={stopPatrol}
        onToggleController={toggleController}
      />
    </div>
  );
}
