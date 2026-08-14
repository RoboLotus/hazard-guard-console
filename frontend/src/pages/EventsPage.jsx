
import { useState } from "react";
import {
  Check,
  CheckCircle,
  ClockCounterClockwise,
  Funnel,
  ListChecks,
  MagnifyingGlass,
  NotePencil,
  Play,
  Siren,
  Warning,
} from "@phosphor-icons/react";
import rgbFeed from "../assets/industrial-rgb.webp";
import thermalFeed from "../assets/industrial-thermal.webp";
import { DetailHeading } from "../components/Common.jsx";
import { eventStatusLabels } from "../data/dashboardData.js";

export function EventLevelIcon({ level, size = 19 }) {
  if (level === "critical") return <Siren size={size} weight="fill" />;
  if (level === "warning") return <Warning size={size} weight="fill" />;
  if (level === "watch") return <ClockCounterClockwise size={size} weight="fill" />;
  return <CheckCircle size={size} weight="fill" />;
}

export default function EventsPage({ events, onUpdateStatus, notify, onOpenVideo }) {
  const [selectedId, setSelectedId] = useState(events[0]?.id ?? null);
  const [levelFilter, setLevelFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [query, setQuery] = useState("");
  const filtered = events.filter((event) => {
    const matchesLevel = levelFilter === "all" || event.level === levelFilter;
    const matchesStatus = statusFilter === "all" || event.status === statusFilter;
    const haystack = `${event.title} ${event.location} ${event.detail}`.toLowerCase();
    return matchesLevel && matchesStatus && haystack.includes(query.trim().toLowerCase());
  });
  const selected = events.find((event) => event.id === selectedId) || filtered[0] || null;

  const updateStatus = (status) => {
    if (!selected) return;
    onUpdateStatus(selected.id, status);
    notify(`이벤트 상태를 '${eventStatusLabels[status]}'으로 변경했습니다.`);
  };

  return (
    <div className="detail-page events-page">
      <DetailHeading eyebrow="EVENT MANAGEMENT" title="위험 이벤트" description="감지 기록을 분류하고 확인부터 해결까지 처리 상태를 관리합니다.">
        <span className="count-badge large">{events.filter((event) => event.status === "new").length} 신규</span>
      </DetailHeading>
      <section className="event-toolbar panel">
        <div className="search-field"><MagnifyingGlass size={18} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="이벤트명, 위치 검색" aria-label="이벤트 검색" /></div>
        <label><Funnel size={17} /><span>등급</span><select value={levelFilter} onChange={(event) => setLevelFilter(event.target.value)}><option value="all">전체</option><option value="critical">위험</option><option value="warning">경고</option><option value="watch">관찰</option><option value="info">정보</option></select></label>
        <label><ClockCounterClockwise size={17} /><span>상태</span><select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option value="all">전체</option><option value="new">신규</option><option value="acknowledged">확인됨</option><option value="working">처리 중</option><option value="resolved">해결됨</option></select></label>
        <span className="filter-result">{filtered.length}건 표시</span>
      </section>
      <div className="event-workspace">
        <section className="panel event-master">
          <div className="event-table-head"><span>이벤트</span><span>발생 위치</span><span>온도</span><span>상태</span><span>시간</span></div>
          <div className="event-table-body">
            {filtered.map((event) => (
              <button key={event.id} type="button" className={`event-table-row ${event.level} ${selected?.id === event.id ? "selected" : ""}`} onClick={() => setSelectedId(event.id)}>
                <span className="event-name-cell"><i><EventLevelIcon level={event.level} /></i><b>{event.title}</b><small>{event.code || `HG-${String(event.id).padStart(4, "0")}`}</small></span>
                <span>{event.location}</span>
                <strong>{event.temperature || "—"}</strong>
                <em className={`event-state ${event.status}`}>{eventStatusLabels[event.status]}</em>
                <time>{event.time}</time>
              </button>
            ))}
            {!filtered.length && <div className="empty-state"><ListChecks size={30} /><strong>조건에 맞는 이벤트가 없습니다.</strong><span>필터나 검색어를 변경해 보세요.</span></div>}
          </div>
        </section>
        <aside className="panel event-detail-panel">
          {selected ? (
            <>
              <header className={`event-detail-header ${selected.level}`}>
                <div className="event-icon"><EventLevelIcon level={selected.level} size={21} /></div>
                <div><span>HG-{String(selected.id).padStart(4, "0")}</span><h2>{selected.title}</h2><p>{selected.date} · {selected.time}</p></div>
                <em className={`event-state ${selected.status}`}>{eventStatusLabels[selected.status]}</em>
              </header>
              <div className="event-detail-body">
                <dl className="event-detail-list">
                  <div><dt>발생 위치</dt><dd>{selected.location}</dd></div>
                  <div><dt>측정 온도</dt><dd className={selected.temperature ? "danger-value" : ""}>{selected.temperature || "해당 없음"}</dd></div>
                  <div><dt>판정 기준</dt><dd>{selected.threshold || "상태 정보"}</dd></div>
                  <div><dt>담당자</dt><dd>{selected.assignee}</dd></div>
                </dl>
                <div className="event-note"><NotePencil size={18} /><div><strong>운영 메모</strong><p>{selected.note}</p></div></div>
                <div className="event-preview-grid">
                  <button type="button" onClick={onOpenVideo}><img src={rgbFeed} alt="이벤트 RGB 스냅샷" /><span>RGB 확인</span></button>
                  <button type="button" onClick={onOpenVideo}><img src={thermalFeed} alt="이벤트 열화상 스냅샷" /><span>열화상 확인</span></button>
                </div>
              </div>
              <footer className="event-detail-actions">
                {selected.status === "new" && <button type="button" className="button secondary" onClick={() => updateStatus("acknowledged")}><Check size={17} weight="bold" />확인 처리</button>}
                {["new", "acknowledged"].includes(selected.status) && <button type="button" className="button primary" onClick={() => updateStatus("working")}><Play size={17} weight="fill" />처리 시작</button>}
                {selected.status === "working" && <button type="button" className="button primary" onClick={() => updateStatus("resolved")}><CheckCircle size={17} weight="fill" />해결 완료</button>}
                {selected.status === "resolved" && <span className="resolved-copy"><CheckCircle size={18} weight="fill" />처리가 완료된 이벤트입니다.</span>}
              </footer>
            </>
          ) : <div className="empty-state"><ListChecks size={30} /><strong>이벤트를 선택하세요.</strong></div>}
        </aside>
      </div>
    </div>
  );
}
