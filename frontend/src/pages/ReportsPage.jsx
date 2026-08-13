import { useState } from "react";
import {
  CalendarBlank,
  FileCsv,
} from "@phosphor-icons/react";
import {
  DetailHeading,
  MetricCard,
  PanelHeader,
} from "../components/Common.jsx";
import {
  eventStatusLabels,
  reportData,
} from "../data/dashboardData.js";

export default function ReportsPage({ events, notify }) {
  const [period, setPeriod] = useState("week");
  const data = reportData[period];
  const exportCsv = () => {
    const rows = [
      ["기간", data.label],
      ["순찰 시간(시간)", data.patrolHours],
      ["이동 거리(km)", data.distance],
      ["순찰 완료율(%)", data.completion],
      ["전체 이벤트", data.events],
      ["위험", data.critical],
      ["경고", data.warning],
      ["정보", data.info],
      ["평균 확인 시간(분)", data.acknowledge],
      ["평균 해결 시간(분)", data.resolve],
      ["최고 온도(°C)", data.temperature],
    ];
    const csv = `\uFEFF${rows.map((row) => row.join(",")).join("\n")}`;
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `hazard-guard-report-${period}.csv`;
    anchor.click();
    URL.revokeObjectURL(url);
    notify(`${data.label} 리포트를 CSV로 저장했습니다.`);
  };

  return (
    <div className="detail-page reports-page">
      <DetailHeading eyebrow="OPERATIONS REPORT" title="운영 리포트" description="순찰 성과, 위험 이벤트, 센서 상태를 기간별로 요약합니다.">
        <button type="button" className="button ghost compact-button" onClick={exportCsv}><FileCsv size={18} />CSV 내보내기</button>
      </DetailHeading>
      <div className="report-toolbar">
        <div className="segmented-control" aria-label="리포트 기간">
          <button type="button" className={period === "today" ? "active" : ""} onClick={() => setPeriod("today")}>오늘</button>
          <button type="button" className={period === "week" ? "active" : ""} onClick={() => setPeriod("week")}>최근 7일</button>
          <button type="button" className={period === "month" ? "active" : ""} onClick={() => setPeriod("month")}>최근 30일</button>
        </div>
        <span><CalendarBlank size={17} />{data.label} 집계 · 프로토타입 데이터</span>
      </div>
      <section className="metric-grid">
        <MetricCard label="순찰 시간" value={data.patrolHours} unit="시간" meta="자율·수동 운행 합계" />
        <MetricCard label="이동 거리" value={data.distance} unit="km" meta="누적 주행 거리" />
        <MetricCard label="순찰 완료율" value={data.completion} unit="%" meta="계획 경로 대비" tone="success-metric" />
        <MetricCard label="위험 이벤트" value={data.critical} unit="건" meta={`전체 ${data.events}건 중`} tone="danger-metric" />
      </section>
      <div className="report-grid">
        <section className="panel report-card event-breakdown">
          <PanelHeader eyebrow="EVENT BREAKDOWN" title="이벤트 등급 분포" />
          <div className="report-card-body">
            {[
              ["위험", data.critical, "critical"],
              ["경고", data.warning, "warning"],
              ["정보", data.info, "info"],
            ].map(([label, value, tone]) => (
              <div className="report-progress-row" key={label}>
                <span>{label}</span>
                <progress className={tone} value={value} max={data.events}>{value}</progress>
                <strong>{value}건</strong>
              </div>
            ))}
            <div className="report-summary-line"><span>평균 확인 시간<strong>{data.acknowledge}분</strong></span><span>평균 해결 시간<strong>{data.resolve}분</strong></span><span>최고 온도<strong>{data.temperature}°C</strong></span></div>
          </div>
        </section>
        <section className="panel report-card patrol-health">
          <PanelHeader eyebrow="SYSTEM HEALTH" title="운행 및 센서 건전성" />
          <div className="health-grid">
            <div><span>LiDAR 수신률</span><strong>99.8%</strong><progress value="99.8" max="100">99.8%</progress></div>
            <div><span>카메라 가용률</span><strong>98.6%</strong><progress value="98.6" max="100">98.6%</progress></div>
            <div><span>네트워크 연결률</span><strong>97.9%</strong><progress value="97.9" max="100">97.9%</progress></div>
            <div><span>평균 배터리</span><strong>72%</strong><progress value="72" max="100">72%</progress></div>
          </div>
        </section>
        <section className="panel report-card report-table-card">
          <PanelHeader eyebrow="RECENT LOG" title="최근 운영 기록" />
          <div className="report-table">
            <div className="report-table-head"><span>시간</span><span>구분</span><span>내용</span><span>결과</span></div>
            {events.slice(0, 5).map((event) => (
              <div className="report-table-row" key={event.id}><time>{event.time}</time><span>{event.level === "critical" ? "위험" : event.level === "warning" ? "경고" : event.level === "watch" ? "관찰" : "정보"}</span><strong>{event.title}</strong><em className={`event-state ${event.status}`}>{eventStatusLabels[event.status]}</em></div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
