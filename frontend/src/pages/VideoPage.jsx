
import { useRef, useState } from "react";
import {
  ArrowsOut,
  Camera,
  ImageSquare,
  Siren,
  ThermometerHot,
} from "@phosphor-icons/react";
import rgbFeed from "../assets/industrial-rgb.webp";
import thermalFeed from "../assets/industrial-thermal.webp";
import {
  DetailHeading,
  LiveImage,
  downloadAsset,
} from "../components/Common.jsx";
import { EventLevelIcon } from "./EventsPage.jsx";

export default function VideoPage({ mediaStatus, telemetry, events, notify }) {
  const [view, setView] = useState("split");
  const viewerRef = useRef(null);
  const rgbLive = Boolean(mediaStatus?.rgb?.available);
  const thermalLive = Boolean(mediaStatus?.thermal?.available);
  const gazeboThermal = mediaStatus?.thermal?.source === "gazebo:/thermal_camera/image_raw";

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
                {thermalLive && <span className="simulation-watermark">{gazeboThermal ? "GAZEBO THERMAL · SIMULATED" : "RGB 기반 합성 열화상"}</span>}
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
