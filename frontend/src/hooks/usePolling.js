import { useEffect, useRef } from "react";
import { fetchJson, startPolling } from "../polling.js";

export function usePolling(url, onData, onError, interval = 2000) {
  const callbacks = useRef({ onData, onError });
  callbacks.current = { onData, onError };
  useEffect(() => startPolling(
    (signal) => fetchJson(url, signal),
    (data) => callbacks.current.onData(data),
    (error) => callbacks.current.onError(error),
    { interval },
  ), [url, interval]);
}
