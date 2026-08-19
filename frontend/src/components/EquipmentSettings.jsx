import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowCounterClockwise,
  Check,
  ClockCounterClockwise,
  Database,
  DownloadSimple,
  MapTrifold,
  Plus,
  Trash,
  UploadSimple,
  Warning,
} from "@phosphor-icons/react";
import { NumberField } from "./Common.jsx";
import EquipmentRoiPicker from "./EquipmentRoiPicker.jsx";
import SettingsConfirmDialog from "./SettingsConfirmDialog.jsx";
import {
  adaptivePolicyConfirmation,
  effectiveThresholdSummary,
  normalizeEquipmentSettings,
  optionalFiniteNumber,
} from "../equipmentSettingsModel.js";

function makeEquipment(existing) {
  let index = existing.length + 1;
  let id = `equipment_${index}`;
  const identifiers = new Set(existing.map((item) => item.id));
  while (identifiers.has(id)) {
    index += 1;
    id = `equipment_${index}`;
  }
  return {
    id,
    display_name: `새 설비 ${index}`,
    enabled: false,
    critical_temperature_c: 80,
    adaptive_delta_c: 10,
    adaptive_threshold_enabled: true,
    roi: { min: [0, 0, 0], max: [0.5, 0.5, 0.5] },
  };
}

function settingsDocument(payload) {
  return normalizeEquipmentSettings(payload);
}

function validate(document) {
  const errors = [];
  const identifiers = new Set();
  document.equipment.forEach((item) => {
    if (!item.display_name.trim()) errors.push(`${item.id}: 설비 이름을 입력하세요.`);
    if (identifiers.has(item.id)) errors.push(`${item.id}: 내부 ID가 중복됩니다.`);
    identifiers.add(item.id);
    if (!(item.critical_temperature_c >= 1 && item.critical_temperature_c <= 300)) {
      errors.push(`${item.display_name}: 즉시 위험 온도는 1~300°C여야 합니다.`);
    }
    if (!(item.adaptive_delta_c >= 0.1 && item.adaptive_delta_c <= 100)) {
      errors.push(`${item.display_name}: 기준선 상승값은 0.1~100°C여야 합니다.`);
    }
    if (item.roi.min.some((value, axis) => Number(value) >= Number(item.roi.max[axis]))) {
      errors.push(`${item.display_name}: ROI 최솟값은 최댓값보다 작아야 합니다.`);
    }
  });
  if (!document.equipment.some((item) => item.enabled)) {
    errors.push("설비를 한 개 이상 활성화해야 합니다.");
  }
  return errors;
}

function formatDate(value) {
  if (!value) return "기록 없음";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "기록 없음" : date.toLocaleString("ko-KR");
}

function baselineRuntime(runtime, equipmentId) {
  return runtime?.equipment?.find((entry) => entry.id === equipmentId) || null;
}

function baselineLabel(runtime, equipmentId) {
  const item = baselineRuntime(runtime, equipmentId);
  if (!item) return runtime?.state === "offline" ? "ROS 미연결" : "상태 확인 중";
  if (item.baseline_state === "active") return "기준선 적용 완료";
  if (item.baseline_state === "collecting") {
    return `기준선 수집 ${item.baseline_sample_count}/${item.baseline_sample_target}`;
  }
  return "기준선 수집 대기";
}

function historyReason(reason) {
  if (reason === "defaults") return "기본값 복원";
  if (reason?.startsWith("restore:")) return "이전 설정 복원";
  return "설정 저장";
}

export default function EquipmentSettings({
  apiOnline,
  deploymentTarget,
  notify,
  onDirtyChange,
  spatialState,
}) {
  const [document, setDocument] = useState({ schema_version: 1, equipment: [] });
  const [savedDocument, setSavedDocument] = useState({ schema_version: 1, equipment: [] });
  const [runtime, setRuntime] = useState({ state: "offline", equipment: [] });
  const [metadata, setMetadata] = useState({ updated_at: null, revision_id: null });
  const [history, setHistory] = useState([]);
  const [selectedId, setSelectedId] = useState("");
  const [query, setQuery] = useState("");
  const [errors, setErrors] = useState([]);
  const [busy, setBusy] = useState(false);
  const [roiPickerOpen, setRoiPickerOpen] = useState(false);
  const [confirmation, setConfirmation] = useState(null);
  const importInput = useRef(null);
  const dirty = JSON.stringify(document) !== JSON.stringify(savedDocument);

  const applyPayload = (payload) => {
    const next = settingsDocument(payload);
    setDocument(next);
    setSavedDocument(next);
    setRuntime(payload.runtime || { state: "offline", equipment: [] });
    setMetadata(payload.metadata || { updated_at: null, revision_id: null });
    setSelectedId((current) => (
      next.equipment.some((item) => item.id === current)
        ? current
        : next.equipment[0]?.id || ""
    ));
    setErrors([]);
  };

  const loadHistory = async () => {
    const response = await fetch("/api/v1/settings/equipment/history", { cache: "no-store" });
    if (response.ok) setHistory((await response.json()).revisions || []);
  };

  useEffect(() => {
    onDirtyChange?.(dirty);
    const beforeUnload = (event) => {
      if (!dirty) return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", beforeUnload);
    return () => window.removeEventListener("beforeunload", beforeUnload);
  }, [dirty, onDirtyChange]);

  useEffect(() => {
    if (!apiOnline) return undefined;
    const controller = new AbortController();
    const load = async () => {
      const response = await fetch("/api/v1/settings/equipment", {
        signal: controller.signal,
        cache: "no-store",
      });
      if (!response.ok) throw new Error(`equipment settings load failed: ${response.status}`);
      applyPayload(await response.json());
      await loadHistory();
    };
    void load().catch(() => {
      if (!controller.signal.aborted) notify("설비 설정을 불러오지 못했습니다.", "warning");
    });
    return () => controller.abort();
  }, [apiOnline]);

  useEffect(() => {
    if (!apiOnline) return undefined;
    const interval = window.setInterval(async () => {
      try {
        const response = await fetch("/api/v1/settings/equipment", { cache: "no-store" });
        if (!response.ok) return;
        const payload = await response.json();
        setRuntime(payload.runtime || { state: "offline", equipment: [] });
        setMetadata(payload.metadata || { updated_at: null, revision_id: null });
      } catch { /* keep the most recent runtime state */ }
    }, 2500);
    return () => window.clearInterval(interval);
  }, [apiOnline]);

  const selected = document.equipment.find((item) => item.id === selectedId);
  const selectedRuntime = selected ? baselineRuntime(runtime, selected.id) : null;
  const visibleEquipment = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    if (!keyword) return document.equipment;
    return document.equipment.filter((item) => (
      item.display_name.toLowerCase().includes(keyword)
      || item.id.toLowerCase().includes(keyword)
    ));
  }, [document.equipment, query]);

  const updateSelected = (changes) => {
    setDocument((current) => ({
      ...current,
      equipment: current.equipment.map((item) => (
        item.id === selectedId ? { ...item, ...changes } : item
      )),
    }));
  };

  const updateRoi = (bound, axis, value) => {
    if (!selected) return;
    const vector = [...selected.roi[bound]];
    vector[axis] = Number(value);
    updateSelected({ roi: { ...selected.roi, [bound]: vector } });
  };

  const applyMapRoi = ({ minimum, maximum }) => {
    if (!selected) return;
    updateSelected({
      roi: {
        min: [Number(minimum[0].toFixed(2)), Number(minimum[1].toFixed(2)), selected.roi.min[2]],
        max: [Number(maximum[0].toFixed(2)), Number(maximum[1].toFixed(2)), selected.roi.max[2]],
      },
    });
    setRoiPickerOpen(false);
    notify("지도에서 선택한 XY 범위를 적용했습니다. Z 높이를 확인한 뒤 저장하세요.", "info");
  };

  const addEquipment = () => {
    const item = makeEquipment(document.equipment);
    setDocument((current) => ({ ...current, equipment: [...current.equipment, item] }));
    setSelectedId(item.id);
    setQuery("");
  };

  const requestConfirmation = (options) => setConfirmation(options);
  const confirmAction = async () => {
    const action = confirmation?.action;
    setConfirmation(null);
    if (!action) return;
    setBusy(true);
    try {
      await action();
    } catch (error) {
      notify(`요청을 완료하지 못했습니다: ${error.message}`, "warning");
    } finally {
      setBusy(false);
    }
  };

  const removeEquipment = () => {
    if (!selected || document.equipment.length === 1) {
      notify("설비는 한 개 이상 남겨야 합니다.", "warning");
      return;
    }
    requestConfirmation({
      title: `${selected.display_name} 설비를 제거할까요?`,
      description: "저장하면 연결된 웨이포인트에서 이 설비를 더 이상 사용할 수 없습니다.",
      impact: `삭제 대상: ${selected.id}`,
      confirmLabel: "설비 제거",
      danger: true,
      action: () => {
        const remaining = document.equipment.filter((item) => item.id !== selected.id);
        setDocument((current) => ({ ...current, equipment: remaining }));
        setSelectedId(remaining[0]?.id || "");
        setErrors([]);
      },
    });
  };

  const loadDefaults = () => requestConfirmation({
    title: "기본 설비 4개를 불러올까요?",
    description: "현재 편집 내용은 기본 설비와 권장 기준값으로 교체되지만 저장 전에는 서버에 반영되지 않습니다.",
    confirmLabel: "기본값 불러오기",
    action: async () => {
      const response = await fetch("/api/v1/settings/equipment/defaults", { cache: "no-store" });
      if (!response.ok) throw new Error("defaults load failed");
      const next = settingsDocument(await response.json());
      setDocument(next);
      setSelectedId(next.equipment[0]?.id || "");
      setErrors([]);
      notify("기본값을 편집 화면에 불러왔습니다. 확인 후 저장하세요.", "info");
    },
  });

  const save = async (event) => {
    event.preventDefault();
    const nextErrors = validate(document);
    setErrors(nextErrors);
    if (nextErrors.length) return;
    if (!apiOnline) {
      notify("서버가 연결되지 않아 설정을 저장하지 못했습니다.", "warning");
      return;
    }
    setBusy(true);
    try {
      const response = await fetch("/api/v1/settings/equipment", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(document),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail || `save failed: ${response.status}`);
      }
      applyPayload(await response.json());
      await loadHistory();
      notify("설비별 온도 기준과 ROI를 저장했습니다.");
    } catch (error) {
      notify(`설정 저장에 실패했습니다: ${error.message}`, "warning");
    } finally {
      setBusy(false);
    }
  };

  const exportSettings = () => {
    const blob = new Blob([`${JSON.stringify(document, null, 2)}\n`], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = globalThis.document.createElement("a");
    anchor.href = url;
    anchor.download = `hazard-guard-equipment-${new Date().toISOString().slice(0, 10)}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const importSettings = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    try {
      if (file.size > 1_000_000) throw new Error("설정 파일은 1MB 이하여야 합니다.");
      const next = settingsDocument(JSON.parse(await file.text()));
      const nextErrors = validate(next);
      if (nextErrors.length) throw new Error(nextErrors[0]);
      setDocument(next);
      setSelectedId(next.equipment[0]?.id || "");
      setErrors([]);
      notify("설정 파일을 불러왔습니다. 확인 후 저장하세요.", "info");
    } catch (error) {
      notify(`설정 파일을 불러오지 못했습니다: ${error.message}`, "warning");
    }
  };

  const restoreRevision = (revision) => requestConfirmation({
    title: "이전 설정으로 복원할까요?",
    description: `${formatDate(revision.created_at)}에 저장된 ${revision.equipment_count}개 설비 설정을 서버에 적용합니다.`,
    impact: "현재 설정도 이력에 남아 다시 복원할 수 있습니다.",
    confirmLabel: "이 설정 복원",
    action: async () => {
      const response = await fetch(
        `/api/v1/settings/equipment/history/${encodeURIComponent(revision.revision_id)}/restore`,
        { method: "POST" },
      );
      if (!response.ok) throw new Error("restore failed");
      applyPayload(await response.json());
      await loadHistory();
      notify("이전 설비 설정을 복원했습니다.");
    },
  });

  const resetBaseline = () => requestConfirmation({
    title: "열화상 기준선을 다시 수집할까요?",
    description: "승인된 기준선은 복구 가능한 백업 파일로 이동하고 모든 설비의 수집 횟수를 0회부터 다시 시작합니다.",
    impact: "활성 순찰 측정 중에는 안전을 위해 실행되지 않습니다.",
    confirmLabel: "기준선 재수집",
    danger: true,
    action: async () => {
      const response = await fetch("/api/v1/settings/equipment/baseline/reset", { method: "POST" });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || "baseline reset failed");
      notify("열화상 기준선 재수집을 시작했습니다.");
    },
  });

  const progressTarget = Number(selectedRuntime?.baseline_sample_target || 0);
  const progressCount = Number(selectedRuntime?.baseline_sample_count || 0);
  const progress = progressTarget ? Math.min(100, (progressCount / progressTarget) * 100) : 0;
  const adaptiveEnabled = selected?.adaptive_threshold_enabled !== false;
  const baselineActive = selectedRuntime?.baseline_state === "active";
  const baselineTemperature = optionalFiniteNumber(selectedRuntime?.baseline_temperature_c);
  const effectiveThreshold = effectiveThresholdSummary(selectedRuntime, selected);
  const mapSpec = spatialState?.map;

  const requestAdaptivePolicy = (enabled) => requestConfirmation({
    ...adaptivePolicyConfirmation(enabled, runtime?.state),
    action: () => updateSelected({ adaptive_threshold_enabled: enabled }),
  });

  return (
    <>
      <form onSubmit={save} className="equipment-settings-form">
        <div className="settings-context-bar">
          <span className={`environment-chip ${deploymentTarget || "unknown"}`}>
            {deploymentTarget === "physical" ? "JETSON · 실물 로봇" : deploymentTarget === "simulation" ? "GAZEBO · 시뮬레이션" : "운용 환경 확인 중"}
          </span>
          <span>마지막 저장 {formatDate(metadata.updated_at)}</span>
          {dirty && <strong>저장되지 않은 변경</strong>}
        </div>

        <div className="equipment-settings-layout">
          <aside className="settings-card equipment-list-card">
            <header>
              <div className="setting-icon"><Database size={21} weight="fill" /></div>
              <div><h2>설비 목록</h2><p>설비를 선택하거나 새로 추가합니다.</p></div>
            </header>
            <div className="equipment-list-tools">
              <input className="text-input" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="설비 이름 또는 ID 검색" aria-label="설비 검색" />
              <button type="button" className="button ghost" onClick={addEquipment}><Plus size={15} weight="bold" />설비 추가</button>
            </div>
            <div className="equipment-list">
              {visibleEquipment.map((item) => (
                <button key={item.id} type="button" className={`equipment-list-item ${item.id === selectedId ? "selected" : ""}`} onClick={() => setSelectedId(item.id)}>
                  <span className={`equipment-state-dot ${item.enabled ? "enabled" : ""}`} />
                  <span><strong>{item.display_name}</strong><small>{item.id}</small></span>
                  <em>{baselineLabel(runtime, item.id)}</em>
                </button>
              ))}
              {!visibleEquipment.length && <p className="equipment-empty">검색 결과가 없습니다.</p>}
            </div>
          </aside>

          {selected && (
            <div className="equipment-editor">
              <section className="settings-card equipment-basic-card">
                <header>
                  <div><h2>{selected.display_name}</h2><p>내부 ID는 순찰 기록과 기준선 연결에 사용되므로 변경되지 않습니다.</p></div>
                  <button type="button" className="icon-button danger" onClick={removeEquipment} title="설비 제거"><Trash size={17} /></button>
                </header>
                <div className="field-grid">
                  <label className="form-field">설비 이름<input className="text-input" value={selected.display_name} maxLength={60} onChange={(event) => updateSelected({ display_name: event.target.value })} /><small>화면과 이벤트에 표시되는 이름</small></label>
                  <label className="form-field">내부 ID<input className="text-input" value={selected.id} readOnly /><small>웨이포인트·기준선 이력 연결 키</small></label>
                </div>
                <label className="equipment-enable-row"><input type="checkbox" checked={selected.enabled} onChange={(event) => updateSelected({ enabled: event.target.checked })} /><span><strong>이 설비 감시</strong><small>비활성화하면 분석과 설비 웨이포인트 연결에서 제외됩니다.</small></span></label>
              </section>

              <section className="settings-card critical-card">
                <header><div className="setting-icon"><Warning size={21} weight="fill" /></div><div><h2>설비별 기준값</h2><p>절대 위험온도는 항상 유지하고 가변 기준은 선택적으로 사용합니다.</p></div></header>
                <label className={`policy-toggle-row ${adaptiveEnabled ? "enabled" : ""}`}>
                  <input type="checkbox" role="switch" checked={adaptiveEnabled} onChange={(event) => requestAdaptivePolicy(event.target.checked)} />
                  <span><strong>자동 가변 기준 사용</strong><small>{adaptiveEnabled ? baselineActive ? "승인 기준선과 상승 추세를 결합해 판정합니다." : `기준선 ${progressCount}/${progressTarget || 10} 수집 후 자동 적용됩니다.` : "고정 위험온도만 위험 판정에 사용합니다."}</small></span>
                  <em>{adaptiveEnabled ? baselineActive ? "적용 중" : "준비 중" : "사용 안 함"}</em>
                </label>
                <div className="field-grid">
                  <NumberField label="즉시 위험 온도" name="critical_temperature_c" value={selected.critical_temperature_c} onChange={(event) => updateSelected({ critical_temperature_c: Number(event.target.value) })} unit="°C" min={1} max={300} />
                  <NumberField label="기준선 대비 상승" name="adaptive_delta_c" value={selected.adaptive_delta_c} onChange={(event) => updateSelected({ adaptive_delta_c: Number(event.target.value) })} unit="°C" min={0.1} max={100} step={0.1} />
                </div>
                <div className="policy-preview">
                  <strong>현재 판정 흐름</strong>
                  <span><b>즉시 위험</b> · P95 온도 ≥ {selected.critical_temperature_c}°C</span>
                  {adaptiveEnabled ? <>
                    <span><b>가변 경고</b> · 지속 상승 추세 <b>그리고</b> 승인 기준선 대비 +{selected.adaptive_delta_c}°C 이상</span>
                    <span><b>한 조건만 만족</b> · 위험으로 확정하지 않고 재확인</span>
                    <span><b>최근 실효 임계점</b> · {effectiveThreshold}</span>
                  </> : <span><b>고정 모드</b> · 가변 이탈은 사용하지 않고 상승 추세만 재확인 정보로 남깁니다.</span>}
                </div>
              </section>

              <section className="settings-card baseline-status-card">
                <header><div><h2>기준선 준비 상태</h2><p>설비 웨이포인트의 정상 순찰 측정값으로 생성합니다.</p></div></header>
                <div className="baseline-status-value">
                  <span className={`equipment-state-dot ${runtime.state !== "offline" ? "enabled" : ""}`} />
                  <strong>{baselineLabel(runtime, selected.id)}</strong>
                  <small>{runtime.state === "pending" ? "현재 순찰 종료 후 설정이 적용됩니다." : `동기화 상태: ${runtime.state || "unknown"}`}</small>
                </div>
                <div className="baseline-progress"><span style={{ width: `${progress}%` }} /></div>
                <dl className="baseline-meta"><div><dt>수집 조건</dt><dd>설비 웨이포인트 정상 측정 {progressTarget || 10}회</dd></div><div><dt>마지막 표본</dt><dd>{selectedRuntime?.baseline_last_sample_unix_sec ? formatDate(selectedRuntime.baseline_last_sample_unix_sec * 1000) : "아직 수집되지 않음"}</dd></div><div><dt>판정 모드</dt><dd>{adaptiveEnabled ? baselineActive ? "자동 가변 기준" : "고정 기준 · 가변 준비 중" : "고정 임계값만"}</dd></div>{baselineTemperature !== null && <div><dt>승인 기준선</dt><dd>{baselineTemperature.toFixed(1)}°C</dd></div>}</dl>
                <button type="button" className="button ghost baseline-reset-button" onClick={resetBaseline} disabled={!apiOnline || runtime.state === "offline"}><ArrowCounterClockwise size={15} />기준선 다시 수집</button>
              </section>

              <section className="settings-card equipment-roi-card">
                <header><div><h2>설비 위치 · ROI</h2><p>map 좌표계에서 열 데이터를 집계할 직육면체 영역입니다.</p></div><button type="button" className="button ghost compact" onClick={() => setRoiPickerOpen((current) => !current)}><MapTrifold size={15} />{roiPickerOpen ? "지도 선택 닫기" : "지도에서 XY 지정"}</button></header>
                {roiPickerOpen && <EquipmentRoiPicker equipment={selected} equipmentList={document.equipment} mapSpec={mapSpec} onApply={applyMapRoi} />}
                <div className="roi-grid">
                  {["X", "Y", "Z"].map((axis, index) => <NumberField key={`min-${axis}`} label={`${axis} 최솟값`} name={`roi-min-${axis}`} value={selected.roi.min[index]} onChange={(event) => updateRoi("min", index, event.target.value)} unit="m" step={0.01} />)}
                  {["X", "Y", "Z"].map((axis, index) => <NumberField key={`max-${axis}`} label={`${axis} 최댓값`} name={`roi-max-${axis}`} value={selected.roi.max[index]} onChange={(event) => updateRoi("max", index, event.target.value)} unit="m" step={0.01} />)}
                </div>
              </section>
            </div>
          )}
        </div>

        {errors.length > 0 && <div className="form-errors" role="alert"><Warning size={19} weight="fill" /><div>{errors.map((error) => <p key={error}>{error}</p>)}</div></div>}

        <section className="settings-card settings-history-card">
          <header><div className="setting-icon"><ClockCounterClockwise size={21} weight="duotone" /></div><div><h2>설정 이력</h2><p>최근 50개 저장본을 보관하며 언제든 복원할 수 있습니다.</p></div></header>
          <div className="settings-history-list">
            {history.slice(0, 6).map((revision) => <div key={revision.revision_id}><span><strong>{historyReason(revision.reason)}</strong><small>{formatDate(revision.created_at)} · 설비 {revision.equipment_count}개</small></span><button type="button" className="button ghost compact" onClick={() => restoreRevision(revision)}>복원</button></div>)}
            {!history.length && <p>아직 저장 이력이 없습니다.</p>}
          </div>
        </section>

        <footer className="form-footer settings-sticky-actions">
          <input ref={importInput} type="file" accept="application/json,.json" hidden onChange={importSettings} />
          <button type="button" className="button ghost" onClick={() => importInput.current?.click()}><UploadSimple size={16} />가져오기</button>
          <button type="button" className="button ghost" onClick={exportSettings}><DownloadSimple size={16} />내보내기</button>
          <button type="button" className="button ghost" onClick={loadDefaults}>기본 설비 불러오기</button>
          <span className="settings-save-state">{dirty ? "변경사항을 검토한 뒤 저장하세요." : "서버 설정과 일치합니다."}</span>
          <button type="submit" className="button primary" disabled={busy || !selected || !dirty}><Check size={17} weight="bold" />{busy ? "저장 중…" : "설정 저장"}</button>
        </footer>
      </form>

      <SettingsConfirmDialog confirmation={confirmation} onCancel={() => setConfirmation(null)} onConfirm={confirmAction} />
    </>
  );
}
