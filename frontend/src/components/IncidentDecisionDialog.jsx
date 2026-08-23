import { useEffect, useMemo, useRef, useState } from "react";
import {
  BellRinging,
  Binoculars,
  CircleNotch,
  LockKey,
  Play,
  ShieldCheck,
  Warning,
  X,
} from "@phosphor-icons/react";
import {
  incidentActions,
  incidentStateLabels,
} from "../incidents.js";

const actionIcons = {
  resume: Play,
  drop_then_resume: BellRinging,
  drop_then_monitor: Binoculars,
  complete_monitoring: Play,
  acknowledge_field_check: ShieldCheck,
};

function createRequestId() {
  const suffix = globalThis.crypto?.randomUUID?.()
    || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `decision:${suffix}`;
}

export default function IncidentDecisionDialog({
  incident,
  battery,
  onClose,
  onSubmit,
}) {
  const actions = useMemo(
    () => incidentActions(incident, battery),
    [incident, battery],
  );
  const [selected, setSelected] = useState(actions[0]?.id || null);
  const [adminToken, setAdminToken] = useState(
    () => window.sessionStorage.getItem("hazardGuardAdminToken") || "",
  );
  const [requestId, setRequestId] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const dialogRef = useRef(null);
  const closeButtonRef = useRef(null);
  const submittingRef = useRef(false);
  const onCloseRef = useRef(onClose);
  submittingRef.current = submitting;
  onCloseRef.current = onClose;

  useEffect(() => {
    setSelected(actions[0]?.id || null);
    setRequestId(null);
    setError("");
  }, [incident?.incident_id]);

  useEffect(() => {
    const previouslyFocused = document.activeElement;
    closeButtonRef.current?.focus();
    const handleKeyDown = (event) => {
      if (event.key === "Escape" && !submittingRef.current) {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = dialogRef.current?.querySelectorAll(
        'button:not(:disabled), input:not(:disabled), [tabindex]:not([tabindex="-1"])',
      );
      if (!focusable?.length) {
        event.preventDefault();
        dialogRef.current?.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      previouslyFocused?.focus?.();
    };
  }, [incident?.incident_id]);

  if (!incident) return null;
  const selectedAction = actions.find((action) => action.id === selected);
  const canSubmit = Boolean(selectedAction?.enabled && adminToken.trim() && !submitting);

  const submit = async (event) => {
    event.preventDefault();
    if (!canSubmit) return;
    const stableRequestId = requestId || createRequestId();
    setRequestId(stableRequestId);
    setSubmitting(true);
    setError("");
    try {
      window.sessionStorage.setItem("hazardGuardAdminToken", adminToken.trim());
      await onSubmit({
        incident,
        decision: selected,
        adminToken: adminToken.trim(),
        requestId: stableRequestId,
      });
      onClose();
    } catch (submitError) {
      setError(submitError.message || "관리자 조치를 전송하지 못했습니다.");
      if (submitError.retryable === false) setRequestId(null);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="incident-dialog-backdrop" role="presentation">
      <form
        ref={dialogRef}
        className="panel incident-dialog"
        role="dialog"
        tabIndex={-1}
        aria-modal="true"
        aria-labelledby="incident-dialog-title"
        onSubmit={submit}
      >
        <header>
          <div className="incident-dialog-icon"><Warning size={22} weight="fill" /></div>
          <div>
            <span>ADMIN APPROVAL</span>
            <h2 id="incident-dialog-title">위험 이벤트 조치 선택</h2>
            <p>{incidentStateLabels[incident.state] || incident.state}</p>
          </div>
          <button ref={closeButtonRef} type="button" className="icon-action" aria-label="닫기" onClick={onClose} disabled={submitting}><X size={18} /></button>
        </header>

        <div className="incident-dialog-summary">
          <div><span>설비</span><strong>{incident.equipment_id || "미지정"}</strong></div>
          <div><span>측정 온도</span><strong>{Number(incident.temperature_c).toFixed(1)}°C</strong></div>
          <div><span>비콘</span><strong>{battery?.available_for_drop || 0}/{battery?.expected || 3} 배출 가능</strong></div>
        </div>

        <fieldset disabled={submitting}>
          <legend>수행할 조치</legend>
          <div className="incident-action-options">
            {actions.map((action) => {
              const Icon = actionIcons[action.id] || Play;
              return (
                <label key={action.id} className={`${selected === action.id ? "selected" : ""} ${action.enabled ? "" : "disabled"}`}>
                  <input
                    type="radio"
                    name="incident-action"
                    value={action.id}
                    checked={selected === action.id}
                    onChange={() => {
                      setSelected(action.id);
                      setRequestId(null);
                      setError("");
                    }}
                    disabled={!action.enabled}
                  />
                  <i className={action.tone}><Icon size={20} weight="fill" /></i>
                  <span><strong>{action.label}</strong><small>{action.disabledReason || (action.id.includes("monitor") ? "관리자 확인 전까지 현장에서 정지합니다." : "선택 후 Robot 임무 관리자가 안전 조건을 다시 확인합니다.")}</small></span>
                </label>
              );
            })}
          </div>
        </fieldset>

        <label className="incident-admin-token">
          <span><LockKey size={16} />관리자 승인 토큰</span>
          <input
            type="password"
            value={adminToken}
            onChange={(event) => setAdminToken(event.target.value)}
            autoComplete="off"
            placeholder="Jetson 백엔드에 설정된 관리자 토큰"
            disabled={submitting}
          />
          <small>토큰은 현재 브라우저 탭에만 보관되며 서버의 운영자 계정으로 기록됩니다.</small>
        </label>

        {error && <div className="incident-dialog-error" role="alert"><Warning size={16} weight="fill" />{error}</div>}
        <div className="incident-dialog-safety"><ShieldCheck size={17} weight="fill" /><span>비콘 배출은 로봇 정지·사람 안전·BLE 배터리 조건을 Robot에서 다시 검증합니다.</span></div>
        <footer>
          <button type="button" className="button secondary" onClick={onClose} disabled={submitting}>취소</button>
          <button type="submit" className="button primary" disabled={!canSubmit}>
            {submitting ? <CircleNotch className="spin" size={17} /> : <ShieldCheck size={17} weight="fill" />}
            {submitting ? "승인 처리 중" : "관리자 확인 및 실행"}
          </button>
        </footer>
      </form>
    </div>
  );
}
