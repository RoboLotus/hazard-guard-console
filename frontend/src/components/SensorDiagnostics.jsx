import { useEffect, useMemo, useState } from "react";
import {
  Camera,
  CheckCircle,
  Pulse,
  Warning,
  Wrench,
} from "@phosphor-icons/react";

const stateLabels = {
  live: "실시간",
  waiting: "데이터 대기",
  stale: "갱신 중단",
  offline: "ROS 미연결",
};

const requirementLabels = {
  mapping: "2D 지도 작성",
  patrol: "순찰",
  "3d": "3D 수집",
  inspection: "설비 검사",
};

function hasRateIssue(sensor) {
  return sensor.state === "live"
    && Number.isFinite(sensor.rate_hz)
    && Number.isFinite(sensor.expected_min_hz)
    && sensor.rate_hz < sensor.expected_min_hz * 0.8;
}

function sensorIssue(sensor) {
  return sensor.state !== "live" || sensor.tf_connected === false || hasRateIssue(sensor);
}

function SensorRow({ sensor }) {
  const issue = sensor.required_now && sensorIssue(sensor);
  const requiredFor = Array.isArray(sensor.required_for) ? sensor.required_for : [];
  const rateLabel = Number.isFinite(sensor.rate_hz)
    ? `${sensor.rate_hz.toFixed(1)} Hz`
    : "주기 계산 중";
  return (
    <article className={`sensor-diagnostic-row ${sensor.state} ${issue ? "has-issue" : ""}`}>
      <span className="sensor-diagnostic-icon">
        {!issue && sensor.state === "live"
          ? <CheckCircle size={18} weight="fill" />
          : sensor.state === "stale" || issue ? <Warning size={18} weight="fill" /> : <Camera size={18} />}
      </span>
      <div className="sensor-diagnostic-main">
        <strong>{sensor.label}</strong>
        <code>{sensor.topic}</code>
        <span className="sensor-technical-line">
          <em>{rateLabel}</em>
          {Number.isFinite(sensor.expected_min_hz) && <em>기준 ≥ {sensor.expected_min_hz} Hz</em>}
          {sensor.frame_id && <em>frame: {sensor.frame_id}</em>}
          {sensor.tf_connected === true && <em>TF 연결</em>}
          {sensor.tf_connected === false && <em className="danger">TF 미연결</em>}
        </span>
      </div>
      <span className={`sensor-purpose ${sensor.required_now ? "required" : ""}`}>
        {sensor.required_now ? "현재 필수" : requiredFor.length ? "다른 모드" : "선택"}
      </span>
      <span className="sensor-state">
        {sensor.required_now && hasRateIssue(sensor) ? "주기 부족" : stateLabels[sensor.state] || sensor.state}
        {Number.isFinite(sensor.age_sec) ? <small>{sensor.age_sec.toFixed(1)}초 전</small> : null}
      </span>
    </article>
  );
}

function SensorGroup({ title, description, sensors }) {
  if (!sensors.length) return null;
  return (
    <section className="sensor-diagnostic-group">
      <header><div><h3>{title}</h3><p>{description}</p></div><span>{sensors.length}개</span></header>
      <div className="sensor-diagnostic-grid">
        {sensors.map((sensor) => <SensorRow key={sensor.id} sensor={sensor} />)}
      </div>
    </section>
  );
}

export default function SensorDiagnostics({ apiOnline }) {
  const [diagnostics, setDiagnostics] = useState(null);
  const [filter, setFilter] = useState("current");

  useEffect(() => {
    let disposed = false;
    const refresh = async () => {
      try {
        const response = await fetch("/api/v1/system/sensors", { cache: "no-store" });
        if (!disposed && response.ok) setDiagnostics(await response.json());
      } catch {
        if (!disposed) setDiagnostics(null);
      }
    };
    void refresh();
    const interval = window.setInterval(refresh, 2000);
    return () => {
      disposed = true;
      window.clearInterval(interval);
    };
  }, []);

  const sensors = diagnostics?.sensors || [];
  const summary = diagnostics?.summary || {};
  const activeLabels = (diagnostics?.active_requirements || [])
    .map((item) => requirementLabels[item] || item);
  const groups = useMemo(() => {
    const current = sensors.filter((sensor) => sensor.required_now);
    const optional = sensors.filter((sensor) => !(sensor.required_for || []).length);
    const other = sensors.filter((sensor) => (sensor.required_for || []).length && !sensor.required_now);
    if (filter === "issues") {
      return [{ title: "확인이 필요한 필수 항목", description: "현재 모드에서 미수신·지연·주기 부족·TF 단절 상태입니다.", sensors: sensors.filter((sensor) => sensor.required_now && sensorIssue(sensor)) }];
    }
    if (filter === "all") {
      return [{ title: "전체 ROS 입력", description: "등록된 센서와 시스템 토픽을 모두 표시합니다.", sensors }];
    }
    return [
      { title: "현재 모드 필수", description: activeLabels.length ? `${activeLabels.join(" · ")}에 필요한 입력입니다.` : "운용 모드를 시작하면 필수 입력이 표시됩니다.", sensors: current },
      { title: "다른 모드에서 사용", description: "현재 모드에서는 없어도 되지만 다른 운용 단계에 필요합니다.", sensors: other },
      { title: "선택 기능", description: "기능을 활성화했을 때만 사용하는 선택 입력입니다.", sensors: optional },
    ];
  }, [sensors, filter, activeLabels.join("|")]);

  const issueCount = sensors.filter((sensor) => sensor.required_now && sensorIssue(sensor)).length;
  return (
    <section className="sensor-diagnostics settings-card standalone">
      <header>
        <div className="setting-icon"><Pulse size={21} weight="duotone" /></div>
        <div><h2>ROS 센서 연결 진단</h2><p>현재 운용 모드에 필요한 토픽의 수신 주기와 좌표계 연결을 확인합니다.</p></div>
        <span className={`diagnostic-summary ${diagnostics?.ros_active && summary.required_total > 0 && summary.required_live === summary.required_total ? "online" : ""}`}>
          {!diagnostics?.ros_active
            ? apiOnline ? "ROS 대기" : "서버 미연결"
            : summary.required_total ? `필수 ${summary.required_live}/${summary.required_total}` : "운용 모드 대기"}
        </span>
      </header>

      <div className="diagnostic-overview">
        <div><small>운용 환경</small><strong>{diagnostics?.deployment_target === "physical" ? "Jetson 실물 로봇" : diagnostics?.deployment_target === "simulation" ? "Gazebo 시뮬레이션" : "확인 중"}</strong></div>
        <div><small>현재 필요 기능</small><strong>{activeLabels.length ? activeLabels.join(" · ") : "운용 모드 대기"}</strong></div>
        <div><small>선택 입력</small><strong>{summary.optional_total || 0}개</strong></div>
        <div className={issueCount ? "warning" : "success"}><small>확인 필요</small><strong>{issueCount}개</strong></div>
      </div>

      <div className="diagnostic-filter" role="group" aria-label="센서 연결 필터">
        <button type="button" className={filter === "current" ? "active" : ""} onClick={() => setFilter("current")}>모드별 분류</button>
        <button type="button" className={filter === "issues" ? "active" : ""} onClick={() => setFilter("issues")}>문제만 {issueCount ? `(${issueCount})` : ""}</button>
        <button type="button" className={filter === "all" ? "active" : ""} onClick={() => setFilter("all")}>전체</button>
      </div>

      <div className="sensor-diagnostic-groups">
        {groups.map((group) => <SensorGroup key={group.title} {...group} />)}
        {!sensors.length && <p className="sensor-diagnostic-empty">서버의 센서 진단 정보를 기다리고 있습니다.</p>}
      </div>

      <details className="sensor-troubleshooting">
        <summary><Wrench size={16} />연결 문제 해결 순서</summary>
        <ol>
          <li>현재 운용 모드에 필요한 센서인지 먼저 확인합니다.</li>
          <li>미수신이면 토픽 이름과 센서 노드 실행 여부를 확인합니다.</li>
          <li>주기 부족이면 CPU·GPU 부하와 USB 대역폭을 확인합니다.</li>
          <li>TF 미연결이면 해당 <code>frame_id</code>에서 <code>base_link</code>까지의 정적·동적 TF를 확인합니다.</li>
        </ol>
      </details>

      <footer className="sensor-calibration-note">
        RGB·Depth 토픽뿐 아니라 두 CameraInfo와 Odometry가 모두 실시간이어야 3D 입력이 준비된 것으로 판단할 수 있습니다. 실물 장착 후에는 센서와 <code>base_link</code> 사이 TF 캘리브레이션을 별도로 검증해야 합니다.
      </footer>
    </section>
  );
}
