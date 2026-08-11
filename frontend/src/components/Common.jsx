import { useEffect, useState } from "react";
import {
  CaretDown,
  Clock,
  MapTrifold,
  NavigationArrow,
  Robot,
} from "@phosphor-icons/react";
import SimulationTeleop from "./SimulationTeleop.jsx";

export function CollapsibleCard({
  icon: Icon,
  title,
  subtitle,
  className = "",
  defaultOpen = true,
  headerAside,
  children,
}) {
  const [expanded, setExpanded] = useState(defaultOpen);
  return (
    <section className={`detail-card collapsible-card ${expanded ? "expanded" : "collapsed"} ${className}`.trim()}>
      <header className="collapsible-card-header">
        <div className="detail-card-title">
          {Icon && <Icon size={20} weight="fill" />}
          <div>
            <strong>{title}</strong>
            <span>{subtitle}</span>
          </div>
        </div>
        <div className="collapsible-card-actions">
          {headerAside}
          <button
            type="button"
            className="card-collapse-button"
            aria-label={`${title} 상세 ${expanded ? "숨기기" : "표시"}`}
            aria-expanded={expanded}
            onClick={() => setExpanded((current) => !current)}
          >
            <CaretDown size={16} weight="bold" />
          </button>
        </div>
      </header>
      {expanded && <div className="collapsible-card-body">{children}</div>}
    </section>
  );
}

export function StatusPill({ tone = "success", children }) {
  return <span className={`status-pill ${tone}`}><span className="status-dot" />{children}</span>;
}

export function PanelHeader({ eyebrow, title, action }) {
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

export async function downloadAsset(source, filename) {
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

export function LiveImage({ endpoint, fallback, enabled, interval = 500, ...props }) {
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

export function CurrentTime() {
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

export const systemModeLabels = {
  mapping: "맵 생성 모드",
  patrol: "순찰 모드",
  idle: "모드 미선택",
};

const systemStateLabels = {
  disabled: "터미널 제어",
  stopped: "정지",
  starting: "시작 중",
  running: "실행 중",
  stopping: "종료 중",
  external: "외부 실행",
  failed: "오류",
};

export function SystemModeControl({ systemMode, busy, onChange }) {
  const mode = systemMode?.mode || "idle";
  const state = systemMode?.state || "disabled";
  const controlEnabled = Boolean(systemMode?.control_enabled);
  const navigationReady = Boolean(systemMode?.navigation_ready);
  const navigationPreparing = (
    mode === "patrol"
    && ["running", "external"].includes(state)
    && !navigationReady
  );
  const changing = busy || ["starting", "stopping"].includes(state);
  const unavailable = !controlEnabled || changing;
  const stateTone = (state === "running" && !navigationPreparing)
    ? "success"
    : state === "failed"
      ? "danger"
      : "neutral";
  const stateLabel = navigationPreparing
    ? "Nav2 준비 중"
    : systemStateLabels[state] || state;
  const activeMappingProfile = systemMode?.mapping_profile || "toolbox";
  const physicalTarget = systemMode?.deployment_target === "physical";
  const [mappingProfile, setMappingProfile] = useState(activeMappingProfile);

  useEffect(() => {
    setMappingProfile(activeMappingProfile);
  }, [activeMappingProfile]);

  return (
    <CollapsibleCard
      icon={MapTrifold}
      title="지도 운용 모드"
      subtitle={physicalTarget ? "실물 M1 SLAM·Nav2 전환" : "시뮬레이션 SLAM·Nav2 전환"}
      className={`system-mode-control ${state}`}
      headerAside={<StatusPill tone={stateTone}>{stateLabel}</StatusPill>}
    >
      <p className="system-mode-description">
        {mode === "mapping"
          ? physicalTarget
            ? "실물 조이스틱으로 공간을 주행하며 회차별 새 지도를 작성합니다."
            : "회차별 새 세션에서 공간을 수동 주행하며 지도를 작성합니다."
          : mode === "patrol"
            ? "저장된 지도에서 위치를 추정하고 웨이포인트를 순찰합니다."
            : "작업 목적에 맞는 모드를 선택하세요."}
      </p>
      <fieldset className="mapping-profile-selector" disabled={!controlEnabled || changing}>
        <legend>지도 생성 방식</legend>
        <button
          type="button"
          className={mappingProfile === "toolbox" ? "active" : ""}
          aria-pressed={mappingProfile === "toolbox"}
          onClick={() => setMappingProfile("toolbox")}
        >
          <span>2D 표준<strong>SLAM Toolbox</strong></span>
        </button>
        <button
          type="button"
          className={mappingProfile === "toolbox_rtabmap" ? "active" : ""}
          aria-pressed={mappingProfile === "toolbox_rtabmap"}
          onClick={() => setMappingProfile("toolbox_rtabmap")}
        >
          <span>2D + RGB-D 3D<strong>Toolbox + RTAB-Map</strong></span>
        </button>
      </fieldset>
      <div className="system-mode-buttons">
        <button
          type="button"
          className={mode === "mapping" ? "active" : ""}
          disabled={unavailable}
          aria-pressed={mode === "mapping"}
          onClick={() => onChange("mapping", mappingProfile)}
        >
          <MapTrifold size={18} weight={mode === "mapping" ? "fill" : "regular"} />
          <span>새 맵 생성<small>SLAM 세션</small></span>
        </button>
        <button
          type="button"
          className={mode === "patrol" ? "active" : ""}
          disabled={unavailable}
          aria-pressed={mode === "patrol"}
          onClick={() => onChange("patrol", activeMappingProfile)}
        >
          <NavigationArrow size={18} weight={mode === "patrol" ? "fill" : "regular"} />
          <span>순찰<small>AMCL · Nav2</small></span>
        </button>
      </div>
      {physicalTarget ? (
        <div className="physical-operation-note">
          <Robot size={17} weight="fill" />
          <span><strong>실물 로봇 제어</strong>WebUI 가상 조작은 차단되며 동봉 조이스틱을 사용합니다.</span>
        </div>
      ) : (
        <SimulationTeleop systemMode={systemMode} />
      )}
      {mode === "mapping" && activeMappingProfile === "toolbox_rtabmap" && (
        <div className={`rtabmap-session-status ${systemMode?.rtabmap?.live ? "live" : "waiting"}`}>
          <span />
          <strong>{systemMode?.rtabmap?.live ? "3D 수집 중" : "RGB-D 데이터 대기"}</strong>
          <small>{(systemMode?.rtabmap?.point_count || 0).toLocaleString("ko-KR")} points</small>
        </div>
      )}
      <footer>
        <span>
          {navigationPreparing
            ? (systemMode?.readiness_message || "AMCL·Nav2 준비를 기다리고 있습니다.")
            : systemModeLabels[mode] || "상태 확인 중"}
        </span>
        <small className={systemMode?.map_available ? "available" : ""}>
          {systemMode?.map_available ? "순찰 지도 준비됨" : "저장 지도 없음"}
        </small>
      </footer>
    </CollapsibleCard>
  );
}
export function DetailHeading({ eyebrow, title, description, children }) {
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

export function MetricCard({ label, value, unit, meta, tone = "" }) {
  return (
    <article className={`metric-card ${tone}`}>
      <span>{label}</span>
      <div><strong>{value}</strong>{unit && <small>{unit}</small>}</div>
      <p>{meta}</p>
    </article>
  );
}

export function NumberField({ label, name, value, onChange, unit, hint, min = 0, max = 999 }) {
  return (
    <label className="form-field">
      <span>{label}</span>
      <div className="number-input"><input type="number" name={name} value={value} min={min} max={max} step="1" onChange={onChange} /><b>{unit}</b></div>
      {hint && <small>{hint}</small>}
    </label>
  );
}
