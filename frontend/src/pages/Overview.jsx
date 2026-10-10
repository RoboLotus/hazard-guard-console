import { useEffect, useState } from "react";
import {
  ArrowsClockwise,
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
import { useCameraFeed, CameraFeedLabel, CameraFeedImage } from "../components/CameraFeed.jsx";
import MapPanel from "../components/MapPanel.jsx";
import { batteryPresentation } from "../batteryTelemetry.js";
import { beaconSlots, incidentMapMarkers } from "../incidents.js";
import { awaitDropResult, demoDropAvailability, dropResultMessage, requestCubeScan, requestDemoDrop } from "../demoDrop.js";
import { telemetryModeLabel, telemetryPresentation } from "../telemetry.js";
import {
  PanelHeader,
  StatusPill,
} from "../components/Common.jsx";

function CameraPanel({ thermal = false, mediaStatus, onOpen, className = "" }) {
  const stream = thermal ? mediaStatus?.thermal : mediaStatus?.rgb;
  const feed = useCameraFeed(stream);
  return (
    <section className={`panel camera-panel ${className}`}>
      <PanelHeader
        eyebrow={thermal ? "THERMAL CAMERA" : "RGB CAMERA"}
        title={thermal ? "열화상 영상" : "실시간 영상"}
        action={
          <div className="panel-inline-actions">
            <CameraFeedLabel feed={feed} />
            {onOpen && <button type="button" className="icon-action" aria-label={`${thermal ? "열화상" : "RGB"} 영상 상세 화면 열기`} onClick={onOpen}><CaretRight size={18} /></button>}
          </div>
        }
      />
      <div className="camera-stage">
        <CameraFeedImage feed={feed} thermal={thermal} />
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

function CubeScanButton({ notify }) {
  const [busy, setBusy] = useState(false);
  // 한 대라도 붙어 있으면 로봇이 자동 탐색을 멈춘다. 스캔이 살아 있는 BLE
  // 연결을 흔들기 때문이다. 나중에 켠 큐브는 이 버튼으로 찾는다.
  const scan = async () => {
    setBusy(true);
    try {
      await requestCubeScan();
      notify("큐브를 탐색합니다. 30초쯤 걸립니다.", "info");
      await new Promise((resolve) => setTimeout(resolve, 32000));
    } catch (error) {
      notify(error.message, "warning");
    } finally {
      setBusy(false);
    }
  };
  return (
    <button
      type="button"
      className={`cube-scan${busy ? " busy" : ""}`}
      disabled={busy}
      onClick={scan}
      title={busy ? "큐브 탐색 중" : "큐브 다시 찾기 (30초)"}
      aria-label="큐브 다시 찾기"
    >
      <ArrowsClockwise size={15} />
    </button>
  );
}

function DemoDropButton({ battery, notify }) {
  const [busy, setBusy] = useState(false);
  const { visible, disabled, reason } = demoDropAvailability({
    enabled: true,
    battery,
    busy,
  });
  if (!visible) return null;

  const drop = async () => {
    setBusy(true);
    try {
      const record = await requestDemoDrop();
      notify("배출 요청을 로봇에 전달했습니다. 낙하 보고를 기다립니다.", "info");
      const result = await awaitDropResult(record.request_id);
      const { tone, text } = dropResultMessage(result);
      notify(text, tone);
    } catch (error) {
      notify(error.message, "warning");
    } finally {
      setBusy(false);
    }
  };

  return (
    <button
      type="button"
      className="demo-drop"
      disabled={disabled}
      onClick={drop}
      title={reason || "시연용으로 비콘을 즉시 배출합니다"}
    >
      <Siren size={16} weight={busy ? "fill" : "regular"} />
      <span>{busy ? "배출 중…" : "비콘 수동 배출 (시연용)"}</span>
      {reason ? <small>{reason}</small> : null}
    </button>
  );
}

function WarningDevicesCard({ battery, demoDropEnabled, notify }) {
  const slots = beaconSlots(battery);
  const connectionLabel = battery?.stale
    ? "상태 확인 필요"
    : `${battery?.connected || 0}/${battery?.expected || 3} 연결`;
  return (
    <article className="dock-block devices">
      <div className="dock-title">
        <Bell size={18} />
        <span>후면 경고장치</span>
        <CubeScanButton notify={notify} />
        <span className={`status-pill ${battery?.stale ? "offline" : "online"}`}>{connectionLabel}</span>
      </div>
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
      {demoDropEnabled ? <DemoDropButton battery={battery} notify={notify} /> : null}
    </article>
  );
}

function ControlDock({ telemetry, telemetryLive, battery, demoDropEnabled, notify, patrolState, controllerEnabled, onTogglePatrol, onStop, onToggleController }) {
  return (
    <section className="control-dock" aria-label="로봇 관제 제어 및 상태">
      <RobotStatusCard telemetry={telemetry} telemetryLive={telemetryLive} />
      <WarningDevicesCard battery={battery} demoDropEnabled={demoDropEnabled} notify={notify} />
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

export default function Overview({ events, onAcknowledge, onNavigate, notify, telemetry, telemetryLive, mediaStatus, spatialState, sendCommand, dispenserBattery, demoDropEnabled, incidents }) {
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
          <CameraPanel thermal mediaStatus={mediaStatus} onOpen={() => onNavigate("video")} />
        </div>
        <EventsPanel events={events} onAcknowledge={onAcknowledge} onViewAll={() => onNavigate("events")} />
      </div>
      <ControlDock
        telemetry={telemetry}
        telemetryLive={telemetryLive}
        battery={dispenserBattery}
        demoDropEnabled={demoDropEnabled}
        notify={notify}
        patrolState={patrolState}
        controllerEnabled={controllerEnabled}
        onTogglePatrol={togglePatrol}
        onStop={stopPatrol}
        onToggleController={toggleController}
      />
    </div>
  );
}
