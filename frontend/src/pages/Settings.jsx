import { useEffect, useState } from "react";
import {
  BellRinging,
  Pulse,
  SlidersHorizontal,
} from "@phosphor-icons/react";
import EquipmentSettings from "../components/EquipmentSettings.jsx";
import SensorDiagnostics from "../components/SensorDiagnostics.jsx";

const sections = new Set(["detection", "connections"]);

function initialSection() {
  const section = new URLSearchParams(window.location.search).get("settings");
  return sections.has(section) ? section : "detection";
}

export default function Settings({ notify, apiOnline, spatialState }) {
  const [section, setSection] = useState(initialSection);
  const [deploymentTarget, setDeploymentTarget] = useState(null);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    const handlePopState = () => setSection(initialSection());
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  useEffect(() => {
    if (!apiOnline) {
      setDeploymentTarget(null);
      return;
    }
    void fetch("/api/health", { cache: "no-store" })
      .then((response) => response.ok ? response.json() : null)
      .then((payload) => setDeploymentTarget(payload?.deployment_target || null))
      .catch(() => setDeploymentTarget(null));
  }, [apiOnline]);

  const selectSection = (nextSection) => {
    const url = new URL(window.location.href);
    url.searchParams.set("settings", nextSection);
    window.history.pushState({}, "", url);
    setSection(nextSection);
  };

  return (
    <div className="settings-page">
      <div className="page-heading settings-heading">
        <div>
          <span className="eyebrow">SYSTEM SETTINGS</span>
          <h1>시스템 설정</h1>
          <p>이상 탐지 정책과 ROS 센서 연결 상태를 용도별로 관리합니다.</p>
        </div>
        <div className="settings-heading-badges">
          <span className={`environment-chip ${deploymentTarget || "unknown"}`}>
            {deploymentTarget === "physical" ? "JETSON · 실물" : deploymentTarget === "simulation" ? "GAZEBO · 시뮬레이션" : "환경 확인 중"}
          </span>
          <span className={`api-status ${apiOnline ? "online" : ""}`}>
            <span />{apiOnline ? "서버 연결" : "서버 미연결"}
          </span>
        </div>
      </div>

      <div className="settings-section-tabs" role="tablist" aria-label="설정 구분">
        <button type="button" role="tab" aria-selected={section === "detection"} className={section === "detection" ? "active" : ""} onClick={() => selectSection("detection")}>
          <SlidersHorizontal size={18} weight="duotone" />
          <span><strong>이상 탐지 설정</strong><small>설비·온도·ROI·기준선</small></span>
          {dirty && <em>저장 필요</em>}
        </button>
        <button type="button" role="tab" aria-selected={section === "connections"} className={section === "connections" ? "active" : ""} onClick={() => selectSection("connections")}>
          <Pulse size={18} weight="duotone" />
          <span><strong>연결 상태 점검</strong><small>ROS 토픽·주기·TF</small></span>
        </button>
        <div className="settings-future-note"><BellRinging size={16} /><span>알림 채널 설정은 발송 기능 연동 후 이곳에 추가됩니다.</span></div>
      </div>

      <section role="tabpanel" hidden={section !== "detection"}>
        <EquipmentSettings
          apiOnline={apiOnline}
          deploymentTarget={deploymentTarget}
          notify={notify}
          onDirtyChange={setDirty}
          spatialState={spatialState}
        />
      </section>
      <section role="tabpanel" hidden={section !== "connections"}>
        <SensorDiagnostics apiOnline={apiOnline} />
      </section>
    </div>
  );
}
