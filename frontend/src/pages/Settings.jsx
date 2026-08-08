import { useEffect, useState } from "react";
import {
  Check,
  CheckCircle,
  ClockCounterClockwise,
  Siren,
  Warning,
} from "@phosphor-icons/react";
import { NumberField } from "../components/Common.jsx";
import SensorDiagnostics from "../components/SensorDiagnostics.jsx";
import { initialThresholds } from "../data/dashboardData.js";

export default function Settings({ notify, apiOnline }) {
  const [values, setValues] = useState(() => {
    try { return { ...initialThresholds, ...JSON.parse(localStorage.getItem("hazardGuardThresholds") || "{}") }; }
    catch { return initialThresholds; }
  });
  const [errors, setErrors] = useState([]);
  useEffect(() => {
    if (!apiOnline) return;
    const controller = new AbortController();
    void fetch("/api/v1/settings/thresholds", { signal: controller.signal, cache: "no-store" })
      .then((response) => response.ok ? response.json() : Promise.reject())
      .then((serverValues) => {
        setValues({ ...initialThresholds, ...serverValues });
        localStorage.setItem("hazardGuardThresholds", JSON.stringify(serverValues));
      })
      .catch(() => {});
    return () => controller.abort();
  }, [apiOnline]);
  const update = ({ target }) => setValues((current) => ({ ...current, [target.name]: Number(target.value) }));
  const reset = () => { setValues(initialThresholds); setErrors([]); notify("권장값으로 되돌렸습니다."); };
  const save = async (event) => {
    event.preventDefault();
    const nextErrors = [];
    if (values.criticalTemperature <= values.warningTemperature) nextErrors.push("위험 온도는 경고 온도보다 높아야 합니다.");
    if (values.clearTemperature >= values.warningTemperature) nextErrors.push("정상 복귀 온도는 경고 온도보다 낮아야 합니다.");
    if ([values.warningDuration, values.criticalDuration, values.clearDuration].some((v) => v < 1)) nextErrors.push("지속 시간은 1초 이상이어야 합니다.");
    setErrors(nextErrors);
    if (nextErrors.length) return;
    localStorage.setItem("hazardGuardThresholds", JSON.stringify(values));
    if (apiOnline) {
      try {
        const response = await fetch("/api/v1/settings/thresholds", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(values) });
        if (!response.ok) throw new Error(`threshold save failed: ${response.status}`);
        const serverValues = await response.json();
        setValues({ ...initialThresholds, ...serverValues });
        localStorage.setItem("hazardGuardThresholds", JSON.stringify(serverValues));
      } catch {
        notify("서버 저장에 실패해 이 브라우저에 임시 저장했습니다.");
        return;
      }
      notify("화재 판정 조건을 서버에 저장했습니다.");
      return;
    }
    notify("서버가 연결되지 않아 이 브라우저에 임시 저장했습니다.");
  };
  return (
    <div className="settings-page">
      <div className="page-heading">
        <div><span className="eyebrow">SYSTEM SETTINGS</span><h1>화재 판정 설정</h1><p>열화상 센서의 온도와 지속 시간을 조합해 경고 단계를 정의합니다.</p></div>
        <span className={`api-status ${apiOnline ? "online" : ""}`}><span />{apiOnline ? "서버 연결" : "서버 미연결"}</span>
      </div>
      <form onSubmit={save} className="settings-form">
        <section className="settings-card warning-card">
          <header><div className="setting-icon"><Warning size={21} weight="fill" /></div><div><h2>경고 조건</h2><p>초기 과열 징후를 관리자에게 알립니다.</p></div></header>
          <div className="field-grid"><NumberField label="경고 온도" name="warningTemperature" value={values.warningTemperature} onChange={update} unit="°C" min={1} max={200} /><NumberField label="최소 지속 시간" name="warningDuration" value={values.warningDuration} onChange={update} unit="초" min={1} max={300} /></div>
        </section>
        <section className="settings-card critical-card">
          <header><div className="setting-icon"><Siren size={21} weight="fill" /></div><div><h2>위험 조건</h2><p>즉시 확인이 필요한 고온 상태를 판정합니다.</p></div></header>
          <div className="field-grid"><NumberField label="위험 온도" name="criticalTemperature" value={values.criticalTemperature} onChange={update} unit="°C" min={1} max={250} /><NumberField label="최소 지속 시간" name="criticalDuration" value={values.criticalDuration} onChange={update} unit="초" min={1} max={300} /></div>
        </section>
        <section className="settings-card clear-card">
          <header><div className="setting-icon"><CheckCircle size={21} weight="fill" /></div><div><h2>정상 복귀 조건</h2><p>위험 상태가 해제되었음을 판단합니다.</p></div></header>
          <div className="field-grid"><NumberField label="복귀 온도" name="clearTemperature" value={values.clearTemperature} onChange={update} unit="°C" min={0} max={200} /><NumberField label="최소 지속 시간" name="clearDuration" value={values.clearDuration} onChange={update} unit="초" min={1} max={600} /></div>
        </section>
        <section className="settings-card repeat-card">
          <header><div className="setting-icon"><ClockCounterClockwise size={21} weight="fill" /></div><div><h2>알림 반복 주기</h2><p>동일 이벤트가 계속될 때 재알림 간격을 정합니다.</p></div></header>
          <div className="field-grid"><NumberField label="경고 재알림" name="warningRepeat" value={values.warningRepeat} onChange={update} unit="초" min={10} max={3600} /><NumberField label="미확인 위험 재알림" name="criticalRepeat" value={values.criticalRepeat} onChange={update} unit="초" min={10} max={3600} /></div>
        </section>
        {errors.length > 0 && <div className="form-errors" role="alert"><Warning size={19} weight="fill" /><div>{errors.map((error) => <p key={error}>{error}</p>)}</div></div>}
        <footer className="form-footer"><button type="button" className="button ghost" onClick={reset}>권장값으로 초기화</button><button type="submit" className="button primary"><Check size={17} weight="bold" />설정 저장</button></footer>
      </form>
      <SensorDiagnostics apiOnline={apiOnline} />
    </div>
  );
}
