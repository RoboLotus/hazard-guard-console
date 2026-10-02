import { useEffect, useState } from "react";
import { TELEMETRY_STALE_AFTER_MS, isLiveTelemetry } from "../telemetry.js";

export function useTelemetryStream() {
  const [telemetry, setTelemetry] = useState(null);
  const [telemetryLive, setTelemetryLive] = useState(false);
  useEffect(() => {
    let disposed = false;
    let socket;
    let reconnectTimer;
    let staleTimer;
    const connect = () => {
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      socket = new WebSocket(`${protocol}//${window.location.host}/ws/telemetry`);
      socket.onmessage = ({ data }) => {
        try {
          const payload = JSON.parse(data);
          if (disposed) return;
          setTelemetry(payload);
          setTelemetryLive(isLiveTelemetry(payload));
          window.clearTimeout(staleTimer);
          staleTimer = window.setTimeout(() => {
            if (!disposed) setTelemetryLive(false);
          }, TELEMETRY_STALE_AFTER_MS);
        }
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
      window.clearTimeout(staleTimer);
      socket?.close();
    };
  }, []);
  return { telemetry, telemetryLive };
}
