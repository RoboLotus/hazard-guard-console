import { useEffect, useMemo, useRef, useState } from "react";
import { CheckCircle, Warning } from "@phosphor-icons/react";
import { fallbackSpatialState, thermalDetectionsToEvents } from "./spatial.js";
import { systemModeLabels } from "./components/Common.jsx";
import Sidebar from "./components/Sidebar.jsx";
import { navigationLabels } from "./data/dashboardData.js";
import EventsPage from "./pages/EventsPage.jsx";
import HelpPage from "./pages/HelpPage.jsx";
import MapPage from "./pages/MapPage.jsx";
import Overview from "./pages/Overview.jsx";
import ReportsPage from "./pages/ReportsPage.jsx";
import Settings from "./pages/Settings.jsx";
import VideoPage from "./pages/VideoPage.jsx";
import RosbagPage from "./pages/RosbagPage.jsx";
import { mergeIncidentEvents, normalizeDispenserBattery } from "./incidents.js";

export function App() {
  const [active, setActive] = useState("overview");
  const [events, setEvents] = useState([]);
  const [toast, setToast] = useState(null);
  const [apiOnline, setApiOnline] = useState(false);
  const [telemetry, setTelemetry] = useState(null);
  const [mediaStatus, setMediaStatus] = useState(null);
  const [spatialState, setSpatialState] = useState(fallbackSpatialState);
  const [systemMode, setSystemMode] = useState({
    mode: "idle",
    state: "disabled",
    control_enabled: false,
    map_available: false,
  });
  const [modeBusy, setModeBusy] = useState(false);
  const [bagStatus, setBagStatus] = useState({ state: "offline", recording: false, control_enabled: false });
  const [bagSessions, setBagSessions] = useState([]);
  const [bagEnabled, setBagEnabled] = useState(false);
  const [incidents, setIncidents] = useState([]);
  const [dispenserBattery, setDispenserBattery] = useState({
    expected: 3,
    connected: 0,
    available_for_drop: 0,
    beacons: [],
    stale: true,
  });
  const announcedThermalLevels = useRef(new Map());

  const notify = (message, tone = "success") => {
    setToast({ message, tone, id: Date.now() });
  };
  useEffect(() => {
    let disposed = false;
    const checkHealth = async () => {
      const controller = new AbortController();
      const timer = window.setTimeout(() => controller.abort(), 1200);
      try {
        const response = await fetch("/api/health", { signal: controller.signal });
        if (!disposed) setApiOnline(response.ok);
      } catch {
        if (!disposed) setApiOnline(false);
      } finally {
        window.clearTimeout(timer);
      }
    };
    void checkHealth();
    const interval = window.setInterval(checkHealth, 5000);
    return () => { disposed = true; window.clearInterval(interval); };
  }, []);
  useEffect(() => {
    let disposed = false;
    let requestSequence = 0;
    let timer;
    let controller;
    const refreshIncidents = async () => {
      const sequence = ++requestSequence;
      controller = new AbortController();
      const requestTimeout = window.setTimeout(() => controller.abort(), 3000);
      try {
        const response = await fetch("/api/v1/incidents", {
          cache: "no-store",
          signal: controller.signal,
        });
        if (!response.ok) throw new Error(`Incident status ${response.status}`);
        const payload = await response.json();
        const battery = normalizeDispenserBattery(payload?.battery);
        if (!battery) throw new Error("Incident response is missing battery status");
        if (!disposed && sequence === requestSequence) {
          setIncidents(Array.isArray(payload.incidents) ? payload.incidents : []);
          setDispenserBattery(battery);
        }
      } catch {
        if (!disposed && sequence === requestSequence) {
          setDispenserBattery((current) => ({ ...current, stale: true, available_for_drop: 0 }));
        }
      } finally {
        window.clearTimeout(requestTimeout);
        if (!disposed) timer = window.setTimeout(refreshIncidents, 1000);
      }
    };
    void refreshIncidents();
    return () => {
      disposed = true;
      requestSequence += 1;
      controller?.abort();
      window.clearTimeout(timer);
    };
  }, []);
  useEffect(() => {
    let disposed = false;
    const refresh = async () => {
      try {
        const response = await fetch("/api/v1/rosbag/status", { cache: "no-store" });
        if (!disposed && response.ok) { const payload = await response.json(); setBagStatus(payload); setBagEnabled(Boolean(payload.recording_control_enabled)); }
      } catch { if (!disposed) setBagStatus({ state: "offline", recording: false, control_enabled: false }); }
    };
    void refresh(); const timer = window.setInterval(refresh, 1500);
    return () => { disposed = true; window.clearInterval(timer); };
  }, []);
  useEffect(() => {
    let disposed = false;
    const checkSystemMode = async () => {
      try {
        const response = await fetch("/api/v1/system/mode", { cache: "no-store" });
        if (!disposed && response.ok) setSystemMode(await response.json());
      } catch {
        if (!disposed) {
          setSystemMode((current) => ({
            ...current,
            state: "disabled",
            control_enabled: false,
          }));
        }
      }
    };
    void checkSystemMode();
    const interval = window.setInterval(checkSystemMode, 1500);
    return () => { disposed = true; window.clearInterval(interval); };
  }, []);
  useEffect(() => {
    let disposed = false;
    let socket;
    let reconnectTimer;
    const connect = () => {
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      socket = new WebSocket(`${protocol}//${window.location.host}/ws/spatial`);
      socket.onmessage = ({ data }) => {
        try { setSpatialState(JSON.parse(data)); }
        catch { /* keep the most recent valid spatial snapshot */ }
      };
      socket.onerror = () => socket.close();
      socket.onclose = () => {
        if (!disposed) reconnectTimer = window.setTimeout(connect, 1500);
      };
    };
    connect();
    return () => {
      disposed = true;
      window.clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, []);
  useEffect(() => {
    if (spatialState?.source !== "ros" || spatialState?.mock) return;
    const nextEvents = thermalDetectionsToEvents(spatialState?.heatmap?.detections);
    setEvents((current) => nextEvents.map((nextEvent) => {
      const previous = current.find((event) => event.id === nextEvent.id);
      if (!previous || previous.level !== nextEvent.level) return nextEvent;
      return {
        ...nextEvent,
        status: previous.status,
        acknowledged: previous.acknowledged,
        assignee: previous.assignee,
      };
    }));

    const newlyRaised = nextEvents.filter((event) => {
      const previousLevel = announcedThermalLevels.current.get(event.id);
      announcedThermalLevels.current.set(event.id, event.level);
      return previousLevel !== event.level;
    });
    if (newlyRaised.length > 0) {
      const criticalCount = newlyRaised.filter((event) => event.level === "critical").length;
      const warningCount = newlyRaised.filter((event) => event.level === "warning").length;
      const watchCount = newlyRaised.filter((event) => event.level === "watch").length;
      const summary = [
        criticalCount ? `위험 ${criticalCount}건` : null,
        warningCount ? `경고 ${warningCount}건` : null,
        watchCount ? `관찰 ${watchCount}건` : null,
      ].filter(Boolean).join(" · ");
      notify(`열화상 위험 이벤트가 발생했습니다: ${summary}`, criticalCount ? "warning" : "info");
    }
  }, [spatialState]);
  useEffect(() => {
    let disposed = false;
    const checkMedia = async () => {
      try {
        const response = await fetch("/api/v1/media/status", { cache: "no-store" });
        if (!disposed && response.ok) setMediaStatus(await response.json());
      } catch {
        if (!disposed) setMediaStatus(null);
      }
    };
    void checkMedia();
    const interval = window.setInterval(checkMedia, 2000);
    return () => { disposed = true; window.clearInterval(interval); };
  }, []);
  useEffect(() => {
    let disposed = false;
    let socket;
    let reconnectTimer;
    const connect = () => {
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      socket = new WebSocket(`${protocol}//${window.location.host}/ws/telemetry`);
      socket.onmessage = ({ data }) => {
        try { setTelemetry(JSON.parse(data)); }
        catch { /* ignore malformed prototype telemetry */ }
      };
      socket.onerror = () => socket.close();
      socket.onclose = () => {
        if (!disposed) reconnectTimer = window.setTimeout(connect, 1500);
      };
    };
    connect();
    return () => {
      disposed = true;
      window.clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, []);
  useEffect(() => {
    if (!toast) return undefined;
    const timer = setTimeout(() => setToast(null), 3200);
    return () => clearTimeout(timer);
  }, [toast]);

  const acknowledge = (id) => {
    setEvents((current) => current.map((event) => event.id === id ? { ...event, acknowledged: true, status: "acknowledged" } : event));
    notify("이벤트를 확인 처리했습니다.");
  };
  const updateEventStatus = (id, status) => {
    setEvents((current) => current.map((event) => event.id === id ? {
      ...event,
      status,
      acknowledged: status !== "new",
      assignee: status === "new" ? "미지정" : status === "resolved" ? "관리자" : "관리자",
    } : event));
  };
  const navigate = (id) => {
    if (["overview", "map", "events", "video", "report", "rosbag", "settings", "help"].includes(id)) setActive(id);
    else notify(`${navigationLabels[id] || "도움말"} 화면은 다음 단계에서 연결됩니다.`, "info");
  };
  const visibleEvents = useMemo(
    () => mergeIncidentEvents(events, incidents),
    [events, incidents],
  );
  const decideIncident = async ({ incident, decision, adminToken, requestId }) => {
    const response = await fetch(`/api/v1/incidents/${encodeURIComponent(incident.incident_id)}/decision`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-HazardGuard-Admin-Token": adminToken,
      },
      body: JSON.stringify({
        request_id: requestId,
        decision,
        confirmed: true,
      }),
    });
    const result = await response.json();
    if (!response.ok || result.state === "rejected") {
      const error = new Error(result.detail || result.message || "관리자 조치를 수행하지 못했습니다.");
      error.retryable = response.status >= 500;
      throw error;
    }
    notify(result.message || "관리자 조치를 Robot 임무 관리자에 전달했습니다.");
    return result;
  };
  const refreshBagSessions = async () => {
    try {
      const response = await fetch("/api/v1/rosbag/sessions", { cache: "no-store" });
      if (!response.ok) throw new Error((await response.json()).detail || "세션을 조회하지 못했습니다.");
      const result = await response.json(); setBagSessions(result.sessions || []);
      if (result.truncated) notify("최근 50개 세션만 표시합니다.", "info");
    } catch (error) { notify(error.message, "warning"); }
  };
  const controlBag = async (command, profile, sessionName) => {
    if (command === "start" && !bagEnabled) { notify("ROS Bag 기록을 ON으로 켠 뒤 시작하세요.", "info"); return; }
    if (!window.confirm(command === "start" ? "선택한 프로파일로 ROS Bag 기록을 시작할까요?" : "현재 ROS Bag 기록을 중지할까요?")) return;
    try {
      const response = await fetch("/api/v1/rosbag/control", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ command, profile, session_name: sessionName }) });
      const result = await response.json(); if (!response.ok) throw new Error(result.detail || "ROS Bag 제어에 실패했습니다.");
      setBagStatus(result.status || bagStatus); notify(result.message); if (command === "stop") void refreshBagSessions();
    } catch (error) { notify(error.message, "warning"); }
  };
  const changeBagEnabled = async (enabled) => {
    try {
      const response = await fetch("/api/v1/rosbag/enabled", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled }) });
      const result = await response.json(); if (!response.ok) throw new Error(result.detail || "ROS Bag 기록 설정을 변경하지 못했습니다.");
      setBagEnabled(Boolean(result.recording_control_enabled)); setBagStatus(result);
    } catch (error) { notify(error.message, "warning"); }
  };
  const sendCommand = async (command, enabled = false) => {
    const response = await fetch(`/api/v1/commands/${command}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    });
    if (!response.ok) throw new Error(`Command failed: ${response.status}`);
    return response.json();
  };
  const changeSystemMode = async (
    nextMode,
    mappingProfile = systemMode.mapping_profile || "toolbox",
    patrolSlam = false,
  ) => {
    if (
      systemMode.mode === nextMode
      && ["starting", "running", "external"].includes(systemMode.state)
      && (nextMode !== "mapping" || systemMode.mapping_profile === mappingProfile)
      && (nextMode !== "patrol" || Boolean(systemMode.patrol_slam) === patrolSlam)
    ) {
      notify(`이미 ${systemModeLabels[nextMode]}가 실행 중입니다.`, "info");
      return;
    }
    const confirmed = window.confirm(
      nextMode === "mapping"
        ? "현재 운용 모드를 중단하고 2D SLAM Toolbox 새 지도 세션을 시작할까요? 기존 결과는 덮어쓰지 않습니다."
        : nextMode === "rgbd_mapping"
          ? "현재 2D 지도를 저장한 뒤, 선택된 저장 지도에서 RGB-D 3D 수집을 시작할까요? RTAB-Map은 주행 좌표계를 변경하지 않습니다."
        : patrolSlam
          ? "현재 SLAM 지도를 저장한 뒤 지도 갱신 순찰(SLAM·Nav2)로 전환할까요? 빈 지도에서 새로 그립니다."
          : "현재 SLAM 지도를 저장한 뒤 AMCL·Nav2 순찰 모드로 전환할까요?",
    );
    if (!confirmed) return;
    setModeBusy(true);
    try {
      const response = await fetch("/api/v1/system/mode", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mode: nextMode,
          mapping_profile: mappingProfile,
          patrol_slam: patrolSlam,
        }),
      });
      const result = await response.json();
      if (!response.ok) {
        throw new Error(result.detail || "운용 모드를 전환하지 못했습니다.");
      }
      setSystemMode(result);
      notify(result.message || `${systemModeLabels[nextMode]} 전환을 시작했습니다.`);
    } catch (error) {
      notify(error.message || "운용 모드 전환 API에 연결하지 못했습니다.", "warning");
    } finally {
      setModeBusy(false);
    }
  };
  const saveSystemMap = async () => {
    setModeBusy(true);
    try {
      const response = await fetch("/api/v1/system/map/save", { method: "POST" });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "ROS 지도를 저장하지 못했습니다.");
      setSystemMode(result);
      notify(result.message);
      return result;
    } catch (error) {
      notify(error.message || "ROS 지도 저장 API에 연결하지 못했습니다.", "warning");
      return null;
    } finally {
      setModeBusy(false);
    }
  };
  const saveAndStopSystemMap = async () => {
    setModeBusy(true);
    try {
      const response = await fetch("/api/v1/system/map/save-and-stop", { method: "POST" });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "지도 저장 후 종료하지 못했습니다.");
      setSystemMode(result);
      notify(result.message);
      return result;
    } catch (error) {
      notify(error.message || "지도 저장·종료 API에 연결하지 못했습니다.", "warning");
      return null;
    } finally {
      setModeBusy(false);
    }
  };
  const stopSystemMode = async () => {
    setModeBusy(true);
    try {
      const response = await fetch("/api/v1/system/mode", { method: "DELETE" });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "운용 모드를 종료하지 못했습니다.");
      setSystemMode(result);
      notify(result.message || "운용 모드를 종료했습니다.");
      return result;
    } catch (error) {
      notify(error.message || "운용 모드 종료 API에 연결하지 못했습니다.", "warning");
      return null;
    } finally {
      setModeBusy(false);
    }
  };
  const initializeLocalization = async () => {
    const pose = systemMode?.localization_pose;
    if (!pose) {
      notify("저장된 초기 위치가 없습니다. 맵 생성 직후 순찰 모드로 전환하거나 RViz에서 초기 위치를 지정하세요.", "warning");
      return null;
    }
    try {
      const response = await fetch("/api/v1/system/localization/initialize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(pose),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "초기 위치를 적용하지 못했습니다.");
      notify(result.message, "info");
      return result;
    } catch (error) {
      notify(error.message || "AMCL 초기 위치 API에 연결하지 못했습니다.", "warning");
      return null;
    }
  };

  return (
    <div className="app-shell">
      <Sidebar
        active={active}
        onNavigate={navigate}
        pendingEvents={visibleEvents.filter((event) => event.status === "new").length}
      />
      <main className="main-content">
        {active === "overview" && <Overview events={visibleEvents} onAcknowledge={acknowledge} onNavigate={navigate} notify={notify} telemetry={telemetry} mediaStatus={mediaStatus} spatialState={spatialState} sendCommand={sendCommand} dispenserBattery={dispenserBattery} incidents={incidents} />}
        {active === "map" && <MapPage mediaStatus={mediaStatus} telemetry={telemetry} spatialState={spatialState} systemMode={systemMode} modeBusy={modeBusy} onModeChange={changeSystemMode} onInitializeLocalization={initializeLocalization} onSystemModeUpdate={setSystemMode} onSaveSystemMap={saveSystemMap} onSaveAndStop={saveAndStopSystemMap} onStopSystemMode={stopSystemMode} notify={notify} incidents={incidents} />}
        {active === "events" && <EventsPage events={visibleEvents} onUpdateStatus={updateEventStatus} notify={notify} onOpenVideo={() => navigate("video")} dispenserBattery={dispenserBattery} onDecideIncident={decideIncident} />}
        {active === "video" && <VideoPage mediaStatus={mediaStatus} telemetry={telemetry} events={visibleEvents} notify={notify} />}
        {active === "report" && <ReportsPage notify={notify} />}
        {active === "rosbag" && <RosbagPage status={bagStatus} enabled={bagEnabled} onEnabledChange={changeBagEnabled} sessions={bagSessions} onRefreshSessions={refreshBagSessions} onControl={controlBag} />}
        {active === "settings" && <Settings notify={notify} apiOnline={apiOnline} spatialState={spatialState} />}
        {active === "help" && <HelpPage onNavigate={navigate} />}
      </main>
      {toast && <div className={`toast ${toast.tone}`} role="status">{toast.tone === "warning" ? <Warning size={19} weight="fill" /> : <CheckCircle size={19} weight="fill" />}<span>{toast.message}</span></div>}
    </div>
  );
}
