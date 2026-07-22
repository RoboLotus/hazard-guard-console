import { useEffect, useState } from "react";
import {
  Bell,
  Camera,
  CaretRight,
  ChartBar,
  Check,
  CheckCircle,
  Clock,
  ClockCounterClockwise,
  Crosshair,
  GameController,
  Gear,
  House,
  ListChecks,
  MapTrifold,
  Pause,
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
  { id: 1, level: "critical", title: "고온 위험 감지", time: "14:32:08", location: "A동 펌프실 · P-02", temperature: "84.6°C", detail: "설정된 위험 조건이 지속되어 확인이 필요합니다.", acknowledged: false },
  { id: 2, level: "warning", title: "온도 상승 감지", time: "14:29:41", location: "A동 펌프실 · P-01", temperature: "63.2°C", detail: "경고 온도 구간에 진입했습니다.", acknowledged: false },
  { id: 3, level: "warning", title: "진동 주의", time: "14:18:07", location: "A동 펌프실 · P-03", temperature: null, detail: "진동 속도 7.8 mm/s가 감지되었습니다.", acknowledged: false },
  { id: 4, level: "info", title: "순찰 지점 통과", time: "14:15:22", location: "A동 중앙 통로 · WP-04", temperature: null, detail: "예정된 순찰 경로를 정상 주행 중입니다.", acknowledged: true },
  { id: 5, level: "info", title: "LiDAR 데이터 정상", time: "14:12:05", location: "시스템 · T-MINI Plus", temperature: null, detail: "주행 센서 데이터가 정상 수신되고 있습니다.", acknowledged: true },
];

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

function Sidebar({ active, onNavigate }) {
  return (
    <aside className="sidebar" aria-label="주 메뉴">
      <div className="sidebar-main">
        <nav className="nav-primary">
          {navItems.map(({ id, label, icon: Icon, badge }) => (
            <button key={id} type="button" className={`nav-item ${active === id ? "active" : ""}`} onClick={() => onNavigate(id)}>
              <Icon size={20} weight={active === id ? "fill" : "regular"} />
              <span>{label}</span>
              {badge ? <span className="nav-badge">{badge}</span> : null}
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

function MapPanel({ onLocate }) {
  return (
    <section className="panel map-panel">
      <PanelHeader eyebrow="LIVE MAP" title="2D SLAM 지도" action={
        <div className="panel-actions">
          <CurrentTime />
          <button type="button" className="icon-action" aria-label="로봇 위치로 이동" title="로봇 위치로 이동" onClick={onLocate}><Crosshair size={19} /></button>
        </div>
      } />
      <div className="map-stage">
        <img src={slamMap} alt="산업 시설 2D SLAM 지도와 파란색 순찰 경로" />
        <div className="map-live-badge"><span />지도 동기화됨</div>
        <div className="robot-marker" aria-label="현재 로봇 위치"><Robot size={18} weight="fill" /></div>
        <div className="map-callout">
          <ThermometerHot size={16} weight="fill" />
          <div><strong>84.6°C</strong><span>P-02 베어링</span></div>
        </div>
        <div className="map-zoom" aria-hidden="true"><button>+</button><button>−</button></div>
      </div>
      <footer className="map-footer">
        <span><i className="legend-route" />순찰 경로</span>
        <span><i className="legend-risk" />위험 위치</span>
        <strong>WP-05 / 08</strong>
      </footer>
    </section>
  );
}

function CameraPanel({ thermal = false }) {
  return (
    <section className="panel camera-panel">
      <PanelHeader eyebrow={thermal ? "THERMAL CAMERA" : "RGB CAMERA"} title={thermal ? "열화상 영상" : "실시간 영상"} action={<span className="live-label"><span />LIVE</span>} />
      <div className="camera-stage">
        <img src={thermal ? thermalFeed : rgbFeed} alt={thermal ? "펌프실 열화상 카메라 영상" : "펌프실 RGB 카메라 영상"} />
        <div className="camera-meta top-left">CAM-{thermal ? "TH01" : "RGB01"}</div>
        {thermal ? (
          <>
            <div className="thermal-reading"><span>MAX</span><strong>84.6°C</strong></div>
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
  return (
    <article className="dock-block operations">
      <div className="dock-title"><Robot size={18} weight="fill" /><span>운행 제어</span><StatusPill tone={stopped ? "neutral" : "success"}>{stopped ? "정지됨" : "자율 순찰 중"}</StatusPill></div>
      <div className="button-row operation-buttons">
        <button type="button" className="button secondary" onClick={onTogglePatrol} disabled={stopped}>
          {patrolState === "paused" ? <Play size={17} weight="fill" /> : <Pause size={17} weight="fill" />}
          {patrolState === "paused" ? "순찰 재개" : "일시정지"}
        </button>
        <button type="button" className="button danger" onClick={onStop} disabled={stopped}><Stop size={17} weight="fill" />운행 정지</button>
        <button
          type="button"
          className={`button controller-toggle ${controllerEnabled ? "active" : "ghost"}`}
          aria-pressed={controllerEnabled}
          title={controllerEnabled ? "컨트롤러 입력 끄기" : "컨트롤러 입력 켜기"}
          onClick={onToggleController}
        >
          <GameController size={17} weight="fill" />
          <span>컨트롤러<small>{controllerEnabled ? "ON" : "OFF"}</small></span>
        </button>
      </div>
    </article>
  );
}

function RobotStatusCard() {
  return (
    <article className="dock-block telemetry">
      <div className="dock-title"><ChartBar size={18} /><span>로봇 상태</span></div>
      <div className="telemetry-grid">
        <div><span>배터리</span><strong>78%</strong><div className="meter"><i style={{ width: "78%" }} /></div></div>
        <div><span>네트워크</span><strong><WifiHigh size={17} weight="fill" /> 양호</strong><small>-48 dBm</small></div>
        <div><span>LiDAR</span><strong className="healthy">정상</strong><small>10.2 Hz</small></div>
        <div><span>속도</span><strong>0.32 m/s</strong><small>제한 0.5 m/s</small></div>
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

function ControlDock({ patrolState, controllerEnabled, onTogglePatrol, onStop, onToggleController }) {
  return (
    <section className="control-dock" aria-label="로봇 관제 제어 및 상태">
      <RobotStatusCard />
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

function Overview({ events, onAcknowledge, notify }) {
  const [patrolState, setPatrolState] = useState("running");
  const [controllerEnabled, setControllerEnabled] = useState(false);
  const togglePatrol = () => {
    const next = patrolState === "paused" ? "running" : "paused";
    setPatrolState(next);
    notify(next === "paused" ? "순찰을 일시정지했습니다." : "순찰을 재개했습니다.");
  };
  const stopPatrol = () => {
    setPatrolState("stopped");
    notify("운행 정지 요청을 기록했습니다. (데모)", "warning");
  };
  const toggleController = () => {
    const next = !controllerEnabled;
    setControllerEnabled(next);
    notify(`동봉 컨트롤러 입력을 ${next ? "활성화" : "비활성화"}했습니다.`);
  };
  return (
    <div className="overview-layout">
      <div className="dashboard-grid">
        <MapPanel onLocate={() => notify("현재 로봇 위치를 지도 중앙에 표시했습니다.")} />
        <div className="camera-stack"><CameraPanel /><CameraPanel thermal /></div>
        <EventsPanel events={events} onAcknowledge={onAcknowledge} onViewAll={() => notify("전체 이벤트 화면은 다음 단계에서 연결됩니다.")} />
      </div>
      <ControlDock
        patrolState={patrolState}
        controllerEnabled={controllerEnabled}
        onTogglePatrol={togglePatrol}
        onStop={stopPatrol}
        onToggleController={toggleController}
      />
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

  const notify = (message, tone = "success") => {
    setToast({ message, tone, id: Date.now() });
  };
  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 1200);
    fetch("/api/health", { signal: controller.signal })
      .then((response) => setApiOnline(response.ok))
      .catch(() => setApiOnline(false))
      .finally(() => clearTimeout(timer));
    return () => { clearTimeout(timer); controller.abort(); };
  }, []);
  useEffect(() => {
    if (!toast) return undefined;
    const timer = setTimeout(() => setToast(null), 3200);
    return () => clearTimeout(timer);
  }, [toast]);

  const acknowledge = (id) => {
    setEvents((current) => current.map((event) => event.id === id ? { ...event, acknowledged: true } : event));
    notify("이벤트를 확인 처리했습니다.");
  };
  const navigate = (id) => {
    if (["overview", "settings"].includes(id)) setActive(id);
    else notify(`${navItems.find((item) => item.id === id)?.label || "도움말"} 화면은 다음 단계에서 연결됩니다.`, "info");
  };

  return (
    <div className="app-shell">
      <Sidebar active={active} onNavigate={navigate} />
      <main className="main-content">
        {active === "settings" ? <Settings notify={notify} apiOnline={apiOnline} /> : <Overview events={events} onAcknowledge={acknowledge} notify={notify} />}
      </main>
      {toast && <div className={`toast ${toast.tone}`} role="status"><CheckCircle size={19} weight="fill" /><span>{toast.message}</span></div>}
    </div>
  );
}
