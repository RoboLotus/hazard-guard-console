import { useEffect, useState } from "react";
import { fallbackSpatialState } from "../spatial.js";
import { normalizeSpatial, SPATIAL_STALE_MS } from "../spatialFreshness.js";

export function useSpatialStream() {
  const [state, setState] = useState(fallbackSpatialState);
  useEffect(() => {
    let disposed = false, socket, reconnect, stale;
    const expire = () => setState((current) => normalizeSpatial(current, false));
    const connect = () => {
      const protocol = location.protocol === "https:" ? "wss:" : "ws:";
      socket = new WebSocket(`${protocol}//${location.host}/ws/spatial`);
      socket.onmessage = ({ data }) => {
        if (disposed) return;
        try {
          const payload = JSON.parse(data);
          if (!payload || typeof payload !== "object" || !payload.pose || !payload.map) return;
          setState(normalizeSpatial(payload));
          clearTimeout(stale);
          stale = setTimeout(expire, SPATIAL_STALE_MS);
        } catch { /* malformed snapshots cannot extend freshness */ }
      };
      socket.onerror = () => socket.close();
      socket.onclose = () => {
        if (!disposed) { expire(); reconnect = setTimeout(connect, 1500); }
      };
    };
    connect();
    return () => { disposed = true; clearTimeout(reconnect); clearTimeout(stale); socket?.close(); };
  }, []);
  return state;
}
