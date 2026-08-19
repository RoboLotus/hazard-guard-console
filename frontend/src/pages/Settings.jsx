import { useEffect, useMemo, useState } from "react";
import {
  Check,
  Database,
  Plus,
  Trash,
  Warning,
} from "@phosphor-icons/react";
import { NumberField } from "../components/Common.jsx";
import SensorDiagnostics from "../components/SensorDiagnostics.jsx";

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
    roi: { min: [0, 0, 0], max: [0.5, 0.5, 0.5] },
  };
}

function baselineLabel(runtime, equipmentId) {
  const item = runtime?.equipment?.find((entry) => entry.id === equipmentId);
  if (!item) return runtime?.state === "offline" ? "ROS 미연결" : "상태 확인 중";
  if (item.baseline_state === "active") return "기준선 적용 완료";
  if (item.baseline_state === "collecting") {
    return `기준선 수집 ${item.baseline_sample_count}/${item.baseline_sample_target}`;
  }
  return "기준선 수집 대기";
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

export default function Settings({ notify, apiOnline }) {
  const [document, setDocument] = useState({ schema_version: 1, equipment: [] });
  const [runtime, setRuntime] = useState({ state: "offline", equipment: [] });
  const [selectedId, setSelectedId] = useState("");
  const [query, setQuery] = useState("");
  const [errors, setErrors] = useState([]);
  const [busy, setBusy] = useState(false);

  const loadSettings = async (signal) => {
    const response = await fetch("/api/v1/settings/equipment", {
      signal,
      cache: "no-store",
    });
    if (!response.ok) throw new Error(`equipment settings load failed: ${response.status}`);
    const payload = await response.json();
    setDocument({ schema_version: payload.schema_version, equipment: payload.equipment });
    setRuntime(payload.runtime || { state: "offline", equipment: [] });
    setSelectedId((current) => (
      payload.equipment.some((item) => item.id === current)
        ? current
        : payload.equipment[0]?.id || ""
    ));
  };

  useEffect(() => {
    if (!apiOnline) return undefined;
    const controller = new AbortController();
    void loadSettings(controller.signal).catch(() => {
      if (!controller.signal.aborted) notify("설비 설정을 불러오지 못했습니다.");
    });
    return () => controller.abort();
  }, [apiOnline]);

  const selected = document.equipment.find((item) => item.id === selectedId);
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

  const addEquipment = () => {
    const item = makeEquipment(document.equipment);
    setDocument((current) => ({
      ...current,
      equipment: [...current.equipment, item],
    }));
    setSelectedId(item.id);
    setQuery("");
  };

  const removeEquipment = () => {
    if (!selected || document.equipment.length === 1) {
      notify("설비는 한 개 이상 남겨야 합니다.");
      return;
    }
    if (!window.confirm(`${selected.display_name} 설비를 목록에서 제거할까요?`)) return;
    const remaining = document.equipment.filter((item) => item.id !== selected.id);
    setDocument((current) => ({ ...current, equipment: remaining }));
    setSelectedId(remaining[0]?.id || "");
    setErrors([]);
  };

  const resetDefaults = async () => {
    if (!apiOnline) {
      notify("서버 연결 후 기본값을 복원할 수 있습니다.");
      return;
    }
    if (!window.confirm("기본 설비 4개와 권장 기준값으로 되돌릴까요?")) return;
    setBusy(true);
    try {
      const response = await fetch("/api/v1/settings/equipment/reset-defaults", {
        method: "POST",
      });
      if (!response.ok) throw new Error(`reset failed: ${response.status}`);
      const payload = await response.json();
      setDocument({ schema_version: payload.schema_version, equipment: payload.equipment });
      setRuntime(payload.runtime || { state: "offline", equipment: [] });
      setSelectedId(payload.equipment[0]?.id || "");
      setErrors([]);
      notify("기본 설비 4개와 권장 기준값을 복원했습니다.");
    } catch {
      notify("기본값 복원에 실패했습니다.");
    } finally {
      setBusy(false);
    }
  };

  const save = async (event) => {
    event.preventDefault();
    const nextErrors = validate(document);
    setErrors(nextErrors);
    if (nextErrors.length) return;
    if (!apiOnline) {
      notify("서버가 연결되지 않아 설정을 저장하지 못했습니다.");
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
      const payload = await response.json();
      setDocument({ schema_version: payload.schema_version, equipment: payload.equipment });
      setRuntime(payload.runtime || { state: "offline", equipment: [] });
      setErrors([]);
      notify("설비별 온도 기준과 ROI를 저장했습니다.");
    } catch (error) {
      notify(`설정 저장에 실패했습니다: ${error.message}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="settings-page">
      <div className="page-heading">
        <div>
          <span className="eyebrow">SYSTEM SETTINGS</span>
          <h1>설비 및 이상 탐지 설정</h1>
          <p>설비 이름, 감시 영역과 설비별 온도 기준을 관리합니다.</p>
        </div>
        <span className={`api-status ${apiOnline ? "online" : ""}`}>
          <span />{apiOnline ? "서버 연결" : "서버 미연결"}
        </span>
      </div>

      <form onSubmit={save} className="equipment-settings-form">
        <div className="equipment-settings-layout">
          <aside className="settings-card equipment-list-card">
            <header>
              <div className="setting-icon"><Database size={21} weight="fill" /></div>
              <div><h2>설비 목록</h2><p>설비를 선택하거나 새로 추가합니다.</p></div>
            </header>
            <div className="equipment-list-tools">
              <input
                className="text-input"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="설비 이름 또는 ID 검색"
                aria-label="설비 검색"
              />
              <button type="button" className="button ghost" onClick={addEquipment}>
                <Plus size={15} weight="bold" />설비 추가
              </button>
            </div>
            <div className="equipment-list">
              {visibleEquipment.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={`equipment-list-item ${item.id === selectedId ? "selected" : ""}`}
                  onClick={() => setSelectedId(item.id)}
                >
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
                  <div>
                    <h2>{selected.display_name}</h2>
                    <p>내부 ID는 순찰 기록과 기준선 연결에 사용되므로 변경되지 않습니다.</p>
                  </div>
                  <button type="button" className="icon-button danger" onClick={removeEquipment} title="설비 제거">
                    <Trash size={17} />
                  </button>
                </header>
                <div className="field-grid">
                  <label className="form-field">
                    설비 이름
                    <input
                      className="text-input"
                      value={selected.display_name}
                      maxLength={60}
                      onChange={(event) => updateSelected({ display_name: event.target.value })}
                    />
                    <small>화면과 이벤트에 표시되는 이름</small>
                  </label>
                  <label className="form-field">
                    내부 ID
                    <input className="text-input" value={selected.id} readOnly />
                    <small>웨이포인트·기준선 이력 연결 키</small>
                  </label>
                </div>
                <label className="equipment-enable-row">
                  <input
                    type="checkbox"
                    checked={selected.enabled}
                    onChange={(event) => updateSelected({ enabled: event.target.checked })}
                  />
                  <span><strong>이 설비 감시</strong><small>비활성화하면 분석과 설비 웨이포인트 연결에서 제외됩니다.</small></span>
                </label>
              </section>

              <section className="settings-card critical-card">
                <header>
                  <div className="setting-icon"><Warning size={21} weight="fill" /></div>
                  <div><h2>설비별 기준값</h2><p>현재 온도와 기준선 대비 상승을 함께 판단합니다.</p></div>
                </header>
                <div className="field-grid">
                  <NumberField
                    label="즉시 위험 온도"
                    name="critical_temperature_c"
                    value={selected.critical_temperature_c}
                    onChange={(event) => updateSelected({ critical_temperature_c: Number(event.target.value) })}
                    unit="°C" min={1} max={300}
                  />
                  <NumberField
                    label="기준선 대비 상승"
                    name="adaptive_delta_c"
                    value={selected.adaptive_delta_c}
                    onChange={(event) => updateSelected({ adaptive_delta_c: Number(event.target.value) })}
                    unit="°C" min={0.1} max={100} step={0.1}
                  />
                </div>
              </section>

              <section className="settings-card equipment-roi-card">
                <header>
                  <div><h2>설비 위치 · ROI</h2><p>map 좌표계에서 열 데이터를 집계할 직육면체 영역입니다.</p></div>
                </header>
                <div className="roi-grid">
                  {["X", "Y", "Z"].map((axis, index) => (
                    <NumberField
                      key={`min-${axis}`}
                      label={`${axis} 최솟값`}
                      name={`roi-min-${axis}`}
                      value={selected.roi.min[index]}
                      onChange={(event) => updateRoi("min", index, event.target.value)}
                      unit="m" step={0.01}
                    />
                  ))}
                  {["X", "Y", "Z"].map((axis, index) => (
                    <NumberField
                      key={`max-${axis}`}
                      label={`${axis} 최댓값`}
                      name={`roi-max-${axis}`}
                      value={selected.roi.max[index]}
                      onChange={(event) => updateRoi("max", index, event.target.value)}
                      unit="m" step={0.01}
                    />
                  ))}
                </div>
              </section>

              <section className="settings-card baseline-status-card">
                <header>
                  <div><h2>기준선 준비 상태</h2><p>설정 저장 후 분석 노드가 보고한 현재 상태입니다.</p></div>
                </header>
                <div className="baseline-status-value">
                  <span className={`equipment-state-dot ${runtime.state !== "offline" ? "enabled" : ""}`} />
                  <strong>{baselineLabel(runtime, selected.id)}</strong>
                  <small>{runtime.state === "pending" ? "현재 순찰 종료 후 적용됩니다." : `동기화 상태: ${runtime.state || "unknown"}`}</small>
                </div>
              </section>
            </div>
          )}
        </div>

        {errors.length > 0 && (
          <div className="form-errors" role="alert">
            <Warning size={19} weight="fill" />
            <div>{errors.map((error) => <p key={error}>{error}</p>)}</div>
          </div>
        )}
        <footer className="form-footer">
          <button type="button" className="button ghost" onClick={resetDefaults} disabled={busy}>
            기본 설비 4개 복원
          </button>
          <button type="submit" className="button primary" disabled={busy || !selected}>
            <Check size={17} weight="bold" />{busy ? "저장 중…" : "설정 저장"}
          </button>
        </footer>
      </form>
      <SensorDiagnostics apiOnline={apiOnline} />
    </div>
  );
}
