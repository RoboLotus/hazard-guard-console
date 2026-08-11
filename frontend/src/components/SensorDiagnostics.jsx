import { useEffect, useState } from "react";
import {
  Camera,
  CheckCircle,
  Pulse,
  Warning,
} from "@phosphor-icons/react";

const stateLabels = {
  live: "실시간",
  waiting: "데이터 대기",
  stale: "갱신 중단",
  offline: "ROS 미연결",
};

export default function SensorDiagnostics({ apiOnline }) {
  const [diagnostics, setDiagnostics] = useState(null);

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
  const liveCount = diagnostics?.summary?.live || 0;
  return (
    <section className="sensor-diagnostics settings-card">
      <header>
        <div className="setting-icon"><Pulse size={21} weight="duotone" /></div>
        <div>
          <h2>ROS 센서 연결 진단</h2>
          <p>실물 로봇 연동에 필요한 토픽의 수신 여부와 갱신 상태를 확인합니다.</p>
        </div>
        <span className={`diagnostic-summary ${diagnostics?.ros_active ? "online" : ""}`}>
          {diagnostics?.ros_active ? `${liveCount}/${sensors.length} 실시간` : apiOnline ? "ROS 대기" : "서버 미연결"}
        </span>
      </header>
      <div className="sensor-diagnostic-grid">
        {sensors.map((sensor) => (
          <article key={sensor.id} className={`sensor-diagnostic-row ${sensor.state}`}>
            <span className="sensor-diagnostic-icon">
              {sensor.state === "live"
                ? <CheckCircle size={17} weight="fill" />
                : sensor.state === "stale" ? <Warning size={17} weight="fill" /> : <Camera size={17} />}
            </span>
            <div>
              <strong>{sensor.label}</strong>
              <code>{sensor.topic}</code>
            </div>
            <span className="sensor-purpose">
              {sensor.required_for.length ? sensor.required_for.join(" · ") : "선택"}
            </span>
            <span className="sensor-state">
              {stateLabels[sensor.state] || sensor.state}
              {sensor.age_sec !== null ? <small>{sensor.age_sec.toFixed(1)}초 전</small> : null}
            </span>
          </article>
        ))}
        {!sensors.length && <p className="sensor-diagnostic-empty">서버의 센서 진단 정보를 기다리고 있습니다.</p>}
      </div>
      <footer className="sensor-calibration-note">
        RGB·Depth 토픽뿐 아니라 두 CameraInfo와 Odometry가 모두 실시간이어야 3D SLAM 입력이 준비된 것으로 판단할 수 있습니다. 실제 장착 후에는 센서와 <code>base_link</code> 사이 TF 캘리브레이션도 별도로 검증해야 합니다.
      </footer>
    </section>
  );
}
