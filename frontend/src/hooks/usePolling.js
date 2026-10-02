import { useEffect, useRef } from "react";
import { fetchJson, startPolling } from "../polling.js";
import { getRecording } from "../demo/runtime.js";

export function usePolling(url, onData, onError, interval = 2000) {
  const callbacks = useRef({ onData, onError });
  callbacks.current = { onData, onError };
  useEffect(() => {
    if (getRecording()) {
      const controller = new AbortController();
      fetchJson(url, controller.signal).then(data => {
        if (!controller.signal.aborted) callbacks.current.onData(data);
      }).catch(error => { if (!controller.signal.aborted) callbacks.current.onError(error); });
      return () => controller.abort();
    }
    return startPolling(
    (signal) => fetchJson(url, signal),
    (data) => callbacks.current.onData(data),
    (error) => callbacks.current.onError(error),
    { interval },
    );
  }, [url, interval]);
}
