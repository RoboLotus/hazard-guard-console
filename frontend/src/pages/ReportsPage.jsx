import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowsClockwise,
  Clock,
  Cpu,
  DownloadSimple,
  Gauge,
  GraphicsCard,
  HardDrives,
  PencilSimple,
  Trash,
} from "@phosphor-icons/react";
import { DetailHeading, MetricCard, PanelHeader } from "../components/Common.jsx";
import {
  formatDuration,
  formatMetric,
  reportStatusLabel,
  sortReports,
} from "../performanceReports.js";

function observedAt(value) {
  if (!value) return "시간 미확인";
  return new Date(value).toLocaleString("ko-KR", { hour12: false });
}

function toneForStatus(status) {
  if (status === "completed") return "completed";
  if (status === "failed") return "failed";
  return "interrupted";
}

function CurrentCollection({ active }) {
  if (!active?.length) return null;
  const item = active[0];
  const latest = item.latest || {};
  return (
    <section className={`performance-live panel ${item.stale ? "stale" : ""}`}>
      <span className="performance-live-pulse" aria-hidden="true" />
      <div>
        <strong>{item.stale ? "수집 중단 여부 확인 필요" : "순찰 성능 수집 중"}</strong>
        <p>{item.name} · {item.phase || "준비"} · {item.sample_count || 0} samples</p>
      </div>
      <div className="performance-live-values">
        <span>CPU <strong>{formatMetric({ mean: latest.cpu?.total_percent })}%</strong></span>
        <span>GPU <strong>{formatMetric({ mean: latest.jetson?.gpu_percent })}%</strong></span>
        <span>RAM <strong>{formatMetric({ mean: latest.memory?.used_percent })}%</strong></span>
      </div>
      {item.stale && <span className="performance-live-guidance">수집 프로세스 상태를 확인하세요</span>}
    </section>
  );
}

function ReportList({ reports, selectedId, onSelect }) {
  return (
    <aside className="panel performance-report-list">
      <PanelHeader eyebrow="PATROL RUNS" title={`성능 기록 ${reports.length}건`} />
      <div className="performance-report-list-body">
        {reports.map((report) => (
          <button
            type="button"
            key={report.id}
            className={selectedId === report.id ? "selected" : ""}
            onClick={() => onSelect(report.id)}
          >
            <span className={`performance-report-state ${toneForStatus(report.status)}`}>
              {reportStatusLabel(report.status)}
            </span>
            <strong>{report.name || report.id}</strong>
            <small>{observedAt(report.started_at)}</small>
            <em>{formatDuration(report.duration_sec)} · {report.sample_count || 0} samples</em>
          </button>
        ))}
      </div>
    </aside>
  );
}

function MetricStatistics({ label, metric, unit = "%" }) {
  return (
    <div className="performance-stat-row">
      <strong>{label}</strong>
      <span>평균 <b>{formatMetric(metric)}{unit}</b></span>
      <span>중앙 <b>{formatMetric(metric, "median")}{unit}</b></span>
      <span>P95 <b>{formatMetric(metric, "p95")}{unit}</b></span>
      <span>최대 <b>{formatMetric(metric, "max")}{unit}</b></span>
    </div>
  );
}

function RenameDialog({ value, busy, onChange, onCancel, onSubmit }) {
  return (
    <div className="performance-dialog-backdrop" role="presentation">
      <form className="panel performance-dialog" role="dialog" aria-modal="true" aria-labelledby="performance-rename-title" onSubmit={onSubmit}>
        <span className="eyebrow">REPORT NAME</span>
        <h2 id="performance-rename-title">성능 기록 이름 변경</h2>
        <p>측정 파일은 그대로 유지하고 화면과 보고서에 표시되는 이름만 변경합니다.</p>
        <label htmlFor="performance-report-name">리포트 이름</label>
        <input
          id="performance-report-name"
          autoFocus
          maxLength={80}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          disabled={busy}
        />
        <div className="performance-dialog-actions">
          <button type="button" className="button ghost compact-button" onClick={onCancel} disabled={busy}>취소</button>
          <button type="submit" className="button primary compact-button" disabled={busy || !value.trim()}>저장</button>
        </div>
      </form>
    </div>
  );
}

function DeleteDialog({ target, busy, onCancel, onConfirm }) {
  if (!target) return null;
  return (
    <div className="performance-dialog-backdrop" role="presentation">
      <section className="panel performance-dialog" role="dialog" aria-modal="true" aria-labelledby="performance-delete-title">
        <span className="eyebrow danger-text">DELETE REPORT</span>
        <h2 id="performance-delete-title">성능 기록을 삭제할까요?</h2>
        <p><strong>{target.name}</strong>의 요약 보고서와 원본 측정 로그가 모두 삭제되며 복구할 수 없습니다.</p>
        <div className="performance-dialog-actions">
          <button type="button" className="button ghost compact-button" onClick={onCancel} disabled={busy}>취소</button>
          <button type="button" className="button danger compact-button" onClick={onConfirm} disabled={busy}>기록 삭제</button>
        </div>
      </section>
    </div>
  );
}

export default function ReportsPage({ notify }) {
  const [reports, setReports] = useState([]);
  const [active, setActive] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [renameOpen, setRenameOpen] = useState(false);
  const [renameValue, setRenameValue] = useState("");
  const [deleteTarget, setDeleteTarget] = useState(null);

  const loadList = useCallback(async ({ quiet = false } = {}) => {
    if (!quiet) setLoading(true);
    try {
      const response = await fetch("/api/v1/performance/reports", { cache: "no-store" });
      if (!response.ok) throw new Error("성능 리포트 목록을 불러오지 못했습니다.");
      const payload = await response.json();
      const nextReports = sortReports(payload.reports);
      setReports(nextReports);
      setActive(payload.active || []);
      setSelectedId((current) => (
        current && nextReports.some((item) => item.id === current)
          ? current
          : nextReports[0]?.id || null
      ));
      setError("");
    } catch (loadError) {
      setError(loadError.message || "성능 리포트 API에 연결하지 못했습니다.");
    } finally {
      if (!quiet) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadList();
    const interval = window.setInterval(() => void loadList({ quiet: true }), 3000);
    return () => window.clearInterval(interval);
  }, [loadList]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      setDetailLoading(false);
      return undefined;
    }
    let disposed = false;
    setDetail(null);
    setDetailLoading(true);
    setRenameOpen(false);
    setDeleteTarget(null);
    const loadDetail = async () => {
      try {
        const response = await fetch(`/api/v1/performance/reports/${encodeURIComponent(selectedId)}`, { cache: "no-store" });
        if (!response.ok) throw new Error("성능 리포트 상세 정보를 불러오지 못했습니다.");
        if (!disposed) setDetail(await response.json());
      } catch (loadError) {
        if (!disposed) setError(loadError.message);
      } finally {
        if (!disposed) setDetailLoading(false);
      }
    };
    void loadDetail();
    return () => { disposed = true; };
  }, [selectedId]);

  const processes = useMemo(() => detail?.processes || [], [detail]);
  const cores = useMemo(() => Object.entries(detail?.cores || {}), [detail]);
  const phases = useMemo(() => Object.entries(detail?.phases || {}), [detail]);

  const openRename = () => {
    if (!detail) return;
    setRenameValue(detail.name || "");
    setRenameOpen(true);
  };

  const renameReport = async (event) => {
    event.preventDefault();
    const name = renameValue.trim();
    if (!detail || !name) return;
    if (name === detail.name) {
      setRenameOpen(false);
      return;
    }
    setBusy(true);
    try {
      const response = await fetch(`/api/v1/performance/reports/${encodeURIComponent(detail.id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "이름을 변경하지 못했습니다.");
      setDetail(payload);
      await loadList({ quiet: true });
      setRenameOpen(false);
      notify("성능 리포트 이름을 변경했습니다.");
    } catch (renameError) {
      notify(renameError.message, "warning");
    } finally {
      setBusy(false);
    }
  };

  const deleteReport = async () => {
    if (!deleteTarget) return;
    setBusy(true);
    try {
      const response = await fetch(`/api/v1/performance/reports/${encodeURIComponent(deleteTarget.id)}?confirm=true`, { method: "DELETE" });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "리포트를 삭제하지 못했습니다.");
      setDetail(null);
      setSelectedId(null);
      setDeleteTarget(null);
      await loadList({ quiet: true });
      notify("성능 리포트와 원본 로그를 삭제했습니다.");
    } catch (deleteError) {
      notify(deleteError.message, "warning");
    } finally {
      setBusy(false);
    }
  };

  const download = (format) => {
    if (!detail) return;
    window.location.href = `/api/v1/performance/reports/${encodeURIComponent(detail.id)}/download?format=${format}`;
  };

  return (
    <div className="detail-page reports-page performance-reports-page">
      <DetailHeading eyebrow="JETSON PERFORMANCE" title="순찰 성능 리포트" description="순찰 중 Jetson과 주요 ROS 프로세스의 CPU·GPU·RAM 부하를 임무 단위로 확인합니다.">
        <button type="button" className="button ghost compact-button" onClick={() => loadList()} disabled={loading}><ArrowsClockwise size={18} />새로고침</button>
      </DetailHeading>

      <CurrentCollection active={active} />
      {error && <div className="performance-error" role="alert">{error}</div>}

      <div className="performance-layout">
        <ReportList reports={reports} selectedId={selectedId} onSelect={setSelectedId} />
        <section className="performance-detail">
          {loading && reports.length === 0 ? (
            <div className="panel performance-empty"><Gauge size={42} /><strong>성능 리포트를 불러오는 중입니다</strong></div>
          ) : detailLoading ? (
            <div className="panel performance-empty"><Gauge size={42} /><strong>선택한 성능 리포트를 불러오는 중입니다</strong></div>
          ) : !detail ? (
            <div className="panel performance-empty"><Gauge size={42} /><strong>아직 완료된 순찰 성능 리포트가 없습니다</strong><p>순찰을 시작하면 자동으로 측정하고 종료 시 보고서를 생성합니다.</p></div>
          ) : (
            <>
              <section className="panel performance-detail-header">
                <div>
                  <span className={`performance-report-state ${toneForStatus(detail.status)}`}>{reportStatusLabel(detail.status)}</span>
                  <h2>{detail.name}</h2>
                  <p><Clock size={16} />{observedAt(detail.started_at)} · {formatDuration(detail.duration_sec)} · {detail.sample_count} samples</p>
                </div>
                <div className="performance-actions">
                  <button type="button" className="button ghost compact-button" onClick={openRename} disabled={busy}><PencilSimple size={17} />이름 변경</button>
                  <button type="button" className="button ghost compact-button" onClick={() => download("csv")}><DownloadSimple size={17} />CSV</button>
                  <button type="button" className="button ghost compact-button danger-button" onClick={() => setDeleteTarget(detail)} disabled={busy}><Trash size={17} />삭제</button>
                </div>
              </section>

              <section className="metric-grid performance-metrics">
                <MetricCard label="CPU 평균" value={formatMetric(detail.system?.cpu_percent)} unit="%" meta={`P95 ${formatMetric(detail.system?.cpu_percent, "p95")}%`} />
                <MetricCard label="GPU 평균" value={formatMetric(detail.system?.gpu_percent)} unit="%" meta={`P95 ${formatMetric(detail.system?.gpu_percent, "p95")}%`} />
                <MetricCard label="RAM 평균" value={formatMetric(detail.system?.ram_percent)} unit="%" meta={`P95 ${formatMetric(detail.system?.ram_percent, "p95")}%`} />
                <MetricCard label="측정 시간" value={formatDuration(detail.duration_sec)} unit="" meta={`${detail.sample_count}개 유효 샘플`} />
              </section>

              <section className="panel performance-statistics">
                <PanelHeader eyebrow="DISTRIBUTION" title="시스템 통계" />
                <div className="performance-statistics-body">
                  <MetricStatistics label="전체 CPU" metric={detail.system?.cpu_percent} />
                  <MetricStatistics label="Jetson GPU" metric={detail.system?.gpu_percent} />
                  <MetricStatistics label="RAM" metric={detail.system?.ram_percent} />
                </div>
              </section>

              <section className="panel performance-table-panel">
                <PanelHeader eyebrow="PROCESS LOAD" title="프로세스별 사용량" />
                <div className="performance-table-scroll">
                  <div className="performance-process-row head"><span>프로세스</span><span>CPU 평균</span><span>CPU P95</span><span>RAM 평균</span><span>RAM P95</span></div>
                  {processes.length ? processes.map((process) => (
                    <div className="performance-process-row" key={process.label}>
                      <strong>{process.label}</strong>
                      <span>{formatMetric(process.cpu_core_percent)}%</span>
                      <span>{formatMetric(process.cpu_core_percent, "p95")}%</span>
                      <span>{formatMetric(process.rss_mb)} MB</span>
                      <span>{formatMetric(process.rss_mb, "p95")} MB</span>
                    </div>
                  )) : <p className="performance-no-data">추적 대상 프로세스 샘플이 없습니다.</p>}
                </div>
              </section>

              <div className="performance-secondary-grid">
                <section className="panel performance-core-panel">
                  <PanelHeader eyebrow="CPU CORES" title="코어별 부하" />
                  <div className="performance-core-grid">
                    {cores.map(([name, metric]) => <div key={name}><Cpu size={18} /><span>{name}</span><strong>{formatMetric(metric, "p95")}%</strong><small>P95 · 평균 {formatMetric(metric)}%</small></div>)}
                    {!cores.length && <p className="performance-no-data">코어별 샘플이 없습니다.</p>}
                  </div>
                </section>
                <section className="panel performance-phase-panel">
                  <PanelHeader eyebrow="MISSION PHASE" title="임무 단계별 부하" />
                  <div className="performance-phase-list">
                    {phases.map(([name, phase]) => <div key={name}><strong>{name}</strong><span><Cpu />CPU {formatMetric(phase.cpu_percent)}%</span><span><GraphicsCard />GPU {formatMetric(phase.gpu_percent)}%</span><span><HardDrives />RAM {formatMetric(phase.ram_percent)}%</span></div>)}
                    {!phases.length && <p className="performance-no-data">단계별 샘플이 없습니다.</p>}
                  </div>
                </section>
              </div>
            </>
          )}
        </section>
      </div>
      {renameOpen && (
        <RenameDialog
          value={renameValue}
          busy={busy}
          onChange={setRenameValue}
          onCancel={() => setRenameOpen(false)}
          onSubmit={renameReport}
        />
      )}
      <DeleteDialog
        target={deleteTarget}
        busy={busy}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={deleteReport}
      />
    </div>
  );
}
