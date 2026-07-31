import { useEffect, useState } from "react";
import { CheckCircle } from "@phosphor-icons/react";
import { fallbackSpatialState } from "./spatial.js";
import { systemModeLabels } from "./components/Common.jsx";
import Sidebar from "./components/Sidebar.jsx";
import { initialEvents, navigationLabels } from "./data/dashboardData.js";
import EventsPage from "./pages/EventsPage.jsx";
import MapPage from "./pages/MapPage.jsx";
import Overview from "./pages/Overview.jsx";
import ReportsPage from "./pages/ReportsPage.jsx";
import Settings from "./pages/Settings.jsx";
import VideoPage from "./pages/VideoPage.jsx";

export function App() {
  const [active, setActive] = useState("overview");
  const [events, setEvents] = useState(initialEvents);
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
    if (["overview", "map", "events", "video", "report", "settings"].includes(id)) setActive(id);
    else notify(`${navigationLabels[id] || "도움말"} 화면은 다음 단계에서 연결됩니다.`, "info");
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
  const changeSystemMode = async (nextMode) => {
    if (
      systemMode.mode === nextMode
      && ["starting", "running", "external"].includes(systemMode.state)
    ) {
      notify(`이미 ${systemModeLabels[nextMode]}가 실행 중입니다.`, "info");
      return;
    }
    const confirmed = window.confirm(
      nextMode === "mapping"
        ? "현재 순찰과 Nav2를 중단하고 SLAM 맵 생성 모드로 전환할까요?"
        : "현재 SLAM 지도를 저장한 뒤 AMCL·Nav2 순찰 모드로 전환할까요?",
    );
    if (!confirmed) return;
    setModeBusy(true);
    try {
      const response = await fetch("/api/v1/system/mode", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: nextMode }),
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
    } catch (error) {
      notify(error.message || "ROS 지도 저장 API에 연결하지 못했습니다.", "warning");
    } finally {
      setModeBusy(false);
    }
  };

  return (
    <div className="app-shell">
      <Sidebar
        active={active}
        onNavigate={navigate}
        pendingEvents={events.filter((event) => event.status === "new").length}
      />
      <main className="main-content">
        {active === "overview" && <Overview events={events} onAcknowledge={acknowledge} onNavigate={navigate} notify={notify} telemetry={telemetry} mediaStatus={mediaStatus} spatialState={spatialState} sendCommand={sendCommand} />}
        {active === "map" && <MapPage mediaStatus={mediaStatus} telemetry={telemetry} spatialState={spatialState} systemMode={systemMode} modeBusy={modeBusy} onModeChange={changeSystemMode} onSaveSystemMap={saveSystemMap} notify={notify} />}
        {active === "events" && <EventsPage events={events} onUpdateStatus={updateEventStatus} notify={notify} onOpenVideo={() => navigate("video")} />}
        {active === "video" && <VideoPage mediaStatus={mediaStatus} telemetry={telemetry} events={events} notify={notify} />}
        {active === "report" && <ReportsPage events={events} notify={notify} />}
        {active === "settings" && <Settings notify={notify} apiOnline={apiOnline} />}
      </main>
      {toast && <div className={`toast ${toast.tone}`} role="status"><CheckCircle size={19} weight="fill" /><span>{toast.message}</span></div>}
    </div>
  );
}
