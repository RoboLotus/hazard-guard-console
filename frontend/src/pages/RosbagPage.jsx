import { Database, HardDrive, Power, Record, Stop, Clock, ArrowClockwise } from "@phosphor-icons/react";
import { useState } from "react";
import { PanelHeader } from "../components/Common.jsx";

const profiles = [
  ["navigation-core", "2D 맵·주행", "LiDAR, TF, Odom, Nav2"],
  ["rgbd-mapping", "3D 맵 수집", "RGB-D, TF, RTAB-Map"],
  ["patrol-core", "순찰 검증", "주행, 열화상 분석, 이벤트"],
];
const formatBytes = (value = 0) => value >= 1024 ** 3 ? `${(value / 1024 ** 3).toFixed(1)} GB` : `${Math.round(value / 1024 ** 2)} MB`;

export default function RosbagPage({ status, enabled, onEnabledChange, sessions, onRefreshSessions, onControl }) {
  const [profile, setProfile] = useState("navigation-core");
  const [sessionName, setSessionName] = useState("field-session");
  const controllable = enabled && status.control_enabled && status.state !== "offline";
  return <div className="page rosbag-page">
    <div className="page-title"><div><span className="eyebrow">DATA CAPTURE</span><h1>ROS Bag 기록</h1><p>주행별 센서 데이터를 명시적으로 기록하고 세션 결과를 확인합니다.</p></div></div>
    <section className="panel rosbag-hero"><PanelHeader eyebrow="RECORDING CONTROL" title="이번 작업 기록" />
      <div className="rosbag-switch-row"><div><strong>{enabled ? "기록 사용" : "기록 사용 안 함"}</strong><p>OFF 상태에서는 주행과 맵 생성이 가능하지만 ROS Bag 기록을 시작할 수 없습니다.</p></div><button className={`toggle ${enabled ? "on" : ""}`} onClick={() => !status.recording && onEnabledChange(!enabled)} aria-pressed={enabled}><span /></button></div>
      <div className={`rosbag-runtime ${status.recording ? "recording" : ""}`}><Record size={18} weight="fill" /><span>{status.recording ? `기록 중 · ${status.profile || "프로파일 확인 중"}` : status.state === "offline" ? "ROS Bag 노드 미연결" : "기록 대기"}</span>{status.recording && <b><Clock size={16} /> {Math.round(status.elapsed_seconds || 0)}초</b>}</div>
    </section>
    <section className="panel"><PanelHeader eyebrow="PROFILE" title="수집 프로파일" /><div className="rosbag-profiles">{profiles.map(([id, title, detail]) => <button key={id} className={`rosbag-profile ${profile === id ? "selected" : ""}`} onClick={() => setProfile(id)} disabled={status.recording}><Database size={20}/><strong>{title}</strong><span>{detail}</span></button>)}</div>
      <div className="rosbag-actions"><label>세션 이름<input value={sessionName} maxLength="80" onChange={(event) => setSessionName(event.target.value)} disabled={status.recording}/></label>{status.recording ? <button className="danger-button" onClick={() => onControl("stop", profile, sessionName)}><Stop size={17} weight="fill"/>기록 중지</button> : <button className="primary-button" disabled={!controllable} onClick={() => onControl("start", profile, sessionName)}><Record size={17} weight="fill"/>기록 시작</button>}</div>
      {!status.control_enabled && <p className="rosbag-note">Robot launch에서 <code>enable_control_services:=true</code>를 명시해야 WebUI 제어가 열립니다.</p>}
    </section>
    <section className="panel"><PanelHeader eyebrow="SESSIONS" title="최근 기록" action={<button className="icon-action" onClick={onRefreshSessions} aria-label="세션 새로고침"><ArrowClockwise size={18}/></button>} /><div className="rosbag-sessions">{sessions.length ? sessions.map((session) => <article key={session.session_id}><HardDrive size={18}/><div><strong>{session.session_id}</strong><span>{session.profile} · {Math.round(session.duration_seconds || 0)}초 · {formatBytes(session.bag_size_bytes)}</span></div><b className={`status-${session.status}`}>{session.status}</b></article>) : <p>조회된 ROS Bag 세션이 없습니다.</p>}</div></section>
  </div>;
}
