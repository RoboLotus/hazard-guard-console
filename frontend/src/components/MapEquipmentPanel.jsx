import { useMemo, useState } from "react";
import {
  Buildings,
  Cube,
  FloppyDisk,
  MapPin,
  Plus,
  Trash,
} from "@phosphor-icons/react";
import { CollapsibleCard } from "./Common.jsx";

const CLEARANCE_M = 0.03;
const ROI_STEP_M = 0.01;

function roundedCoordinate(value) {
  return Number(Number(value).toFixed(2));
}

function roiConflict(first, second) {
  return [0, 1, 2].every((axis) => (
    Number(first.roi.max[axis]) + CLEARANCE_M > Number(second.roi.min[axis])
    && Number(second.roi.max[axis]) + CLEARANCE_M > Number(first.roi.min[axis])
  ));
}

function conflicts(equipment) {
  const enabled = equipment.filter((item) => item.enabled);
  const result = new Set();
  enabled.forEach((first, index) => {
    enabled.slice(index + 1).forEach((second) => {
      if (roiConflict(first, second)) {
        result.add(first.id);
        result.add(second.id);
      }
    });
  });
  return result;
}

export default function MapEquipmentPanel({
  document,
  spatialContext,
  selectedId,
  pointMode,
  onSelect,
  onChange,
  onStartPoint,
  onOpen3d,
  onSaved,
  notify,
}) {
  const [busy, setBusy] = useState(false);
  const equipment = document?.equipment || [];
  const selected = equipment.find((item) => item.id === selectedId) || null;
  const overlapping = useMemo(() => conflicts(equipment), [equipment]);
  const registrationReady = Boolean(spatialContext?.registration_ready);

  const updateSelected = (patch) => {
    if (!selected) return;
    onChange({
      ...document,
      equipment: equipment.map((item) => (
        item.id === selected.id ? { ...item, ...patch } : item
      )),
    });
  };

  const updateRoi = (bound, axis, value) => {
    const next = {
      min: [...selected.roi.min],
      max: [...selected.roi.max],
    };
    next[bound][axis] = Number(value);
    updateSelected({ roi: next });
  };

  const adjustRoi = (bound, axis, delta) => {
    if (!selected) return;
    const minimum = Number(selected.roi.min[axis]);
    const maximum = Number(selected.roi.max[axis]);
    const current = bound === "min" ? minimum : maximum;
    const candidate = roundedCoordinate(current + delta);
    const nextValue = bound === "min"
      ? Math.min(candidate, roundedCoordinate(maximum - ROI_STEP_M))
      : Math.max(candidate, roundedCoordinate(minimum + ROI_STEP_M));
    updateRoi(bound, axis, nextValue);
  };

  const save = async () => {
    if (!registrationReady || !document) return;
    if (overlapping.size) {
      notify(`설비 ROI는 서로 겹치거나 ${CLEARANCE_M * 100}cm보다 가까울 수 없습니다.`, "warning");
      return;
    }
    setBusy(true);
    try {
      const response = await fetch("/api/v1/settings/equipment", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          schema_version: 2,
          world_id: spatialContext.world_id,
          map_session_id: spatialContext.map_session_id,
          frame_id: "map",
          geometry_fingerprint: document.geometry_fingerprint || null,
          equipment,
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "설비 ROI를 저장하지 못했습니다.");
      onSaved(payload);
    } catch (error) {
      notify(error.message, "warning");
    } finally {
      setBusy(false);
    }
  };

  return (
    <CollapsibleCard
      icon={Buildings}
      title="지도 설비 등록"
      subtitle="고정 map 좌표계 ROI"
      className="map-equipment-card"
    >
      <div className={`map-registration-gate ${registrationReady ? "ready" : "blocked"}`}>
        <span />
        <div>
          <strong>{registrationReady ? "등록 가능" : "등록 대기"}</strong>
          <small>{spatialContext?.message || "지도 상태를 확인하고 있습니다."}</small>
        </div>
      </div>
      <div className="map-equipment-toolbar">
        <button type="button" className="button secondary" disabled={!registrationReady} onClick={onStartPoint}>
          <MapPin size={15} weight="duotone" />{pointMode ? "지도에서 선택 중" : "2D 위치 추가"}
        </button>
        <button type="button" className="button secondary" disabled={!registrationReady || !selected} onClick={onOpen3d}>
          <Cube size={15} />3D ROI 확인
        </button>
      </div>
      {equipment.length ? (
        <div className="map-equipment-list" aria-label="현재 지도 세션 설비 목록">
          {equipment.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`${item.id === selectedId ? "selected" : ""} ${overlapping.has(item.id) ? "conflict" : ""}`}
              onClick={() => onSelect(item.id)}
            >
              <span />
              <strong>{item.display_name}</strong>
              <small>{item.enabled ? "감시" : "비활성"}{overlapping.has(item.id) ? " · ROI 충돌" : ""}</small>
            </button>
          ))}
        </div>
      ) : (
        <p className="map-equipment-empty">현재 지도에 등록된 설비가 없습니다.</p>
      )}
      {selected && (
        <div className="map-equipment-editor">
          <label>
            <span>설비 이름</span>
            <input value={selected.display_name} onChange={(event) => updateSelected({ display_name: event.target.value })} />
          </label>
          <label className="map-equipment-enabled">
            <input type="checkbox" checked={selected.enabled} onChange={(event) => updateSelected({ enabled: event.target.checked })} />
            <span>순찰 열화상 감시 활성화</span>
          </label>
          <div className="map-roi-grid">
            {["X", "Y", "Z"].map((axis, index) => (
              <div key={axis} className="map-roi-axis">
                <strong>{axis} 범위 <small>m</small></strong>
                {[["min", "최소"], ["max", "최대"]].map(([bound, label]) => (
                  <label key={bound} className="map-roi-bound">
                    <span>{label}</span>
                    <div className="map-roi-stepper">
                      <button type="button" aria-label={`${axis} ${label} 0.01m 감소`} onClick={() => adjustRoi(bound, index, -ROI_STEP_M)}>−</button>
                      <input type="number" inputMode="decimal" step="0.01" value={Number(selected.roi[bound][index]).toFixed(2)} aria-label={`${axis} ${label}`} onChange={(event) => updateRoi(bound, index, event.target.value)} />
                      <button type="button" aria-label={`${axis} ${label} 0.01m 증가`} onClick={() => adjustRoi(bound, index, ROI_STEP_M)}>+</button>
                    </div>
                  </label>
                ))}
              </div>
            ))}
          </div>
          <div className="map-equipment-actions">
            <button
              type="button"
              className="button danger ghost"
              onClick={() => {
                onChange({ ...document, equipment: equipment.filter((item) => item.id !== selected.id) });
                onSelect(equipment.find((item) => item.id !== selected.id)?.id || null);
              }}
            >
              <Trash size={15} />삭제
            </button>
            <button type="button" className="button primary" disabled={busy || overlapping.size > 0} onClick={save}>
              <FloppyDisk size={15} />{busy ? "저장 중" : "저장"}
            </button>
          </div>
        </div>
      )}
      {!selected && registrationReady && (
        <button type="button" className="map-equipment-add-empty" onClick={onStartPoint}>
          <Plus size={16} />첫 설비 위치 등록
        </button>
      )}
    </CollapsibleCard>
  );
}
