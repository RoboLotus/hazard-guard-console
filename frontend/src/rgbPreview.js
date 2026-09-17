import { parseFrameHeader, RgbTelemetry } from "./rgbTelemetry.js";
import { createRgbTransport } from "./rgbTransport.js";

// One outstanding image request per view. Reporting never blocks the image loop.
export function startRgbPreview(element, {
  endpoint, interval = 100, fallback,
  websocket = import.meta.env?.VITE_HAZARD_GUARD_RGB_TRANSPORT !== "http",
  observe = import.meta.env?.VITE_HAZARD_GUARD_STREAM_DIAGNOSTICS !== "off",
}, platform = globalThis) {
  const now = () => platform.performance.now();
  // This is correlation, not authentication. randomUUID requires a secure context.
  const clientId = platform.crypto?.randomUUID?.()
    ?? Array.from({ length: 32 }, () => Math.floor(Math.random() * 16).toString(16)).join("");
  const meter = new RgbTelemetry(clientId, now);
  const transport = createRgbTransport(platform, endpoint, { enabled: websocket });
  let lastDisplayedAt = -Infinity;
  let active = true, revision = 0, imageTimer, requestController, reportController;
  let currentUrl = null, pendingUrl = null, nextReportAt = 0, backoffMs = 5000;
  let reportingSupported = true;
  const timers = new Set();
  const schedule = (fn, ms) => {
    const timer = platform.setTimeout(() => { timers.delete(timer); fn(); }, ms);
    timers.add(timer);
    return timer;
  };
  const revoke = url => { if (url) platform.URL.revokeObjectURL(url); };

  async function load() {
    if (!active) return;
    if (platform.document.visibilityState === "hidden") {
      imageTimer = schedule(load, 1000);
      return;
    }
    const started = now();
    const controller = new AbortController();
    requestController = controller;
    const timeout = schedule(() => controller.abort(), 5000);
    let candidate = null;
    try {
      const separator = endpoint.includes("?") ? "&" : "?";
      const response = await transport.fetch(`${endpoint}${separator}frame=${revision++}`, {
        cache: "no-store", signal: controller.signal,
      });
      if (response.status === 204 && now() - lastDisplayedAt < 2000) return;
      if (!response.ok) throw new Error("media unavailable");
      const frame = observe ? parseFrameHeader(response.headers.get("X-HazardGuard-Frame")) : null;
      const blob = await response.blob();
      if (!active || controller.signal.aborted) return;
      const receivedAt = now();
      candidate = pendingUrl = platform.URL.createObjectURL(blob);
      await new Promise((resolve, reject) => {
        let paint;
        const cleanup = () => {
          element.onload = element.onerror = null;
          controller.signal.removeEventListener("abort", aborted);
          if (paint !== undefined) platform.cancelAnimationFrame(paint);
        };
        const aborted = () => { cleanup(); reject(new Error("aborted")); };
        element.onerror = () => { cleanup(); reject(new Error("decode failed")); };
        element.onload = () => {
          const commit = () => {
            if (!active || controller.signal.aborted) { aborted(); return; }
            cleanup();
            element.hidden = false;
            lastDisplayedAt = now();
            if (observe) meter.displayed(frame, receivedAt, receivedAt - started);
            resolve();
          };
          // rAF is a display proxy, not the physical panel's presentation time.
          if (platform.document.visibilityState === "hidden") commit();
          else paint = platform.requestAnimationFrame(commit);
        };
        controller.signal.addEventListener("abort", aborted, { once: true });
        element.src = candidate;
      });
      revoke(currentUrl);
      currentUrl = candidate;
      pendingUrl = null;
      candidate = null;
    } catch {
      if (active) {
        if (observe) meter.unavailable();
        if (fallback) { element.src = fallback; element.hidden = false; }
        else element.hidden = true;
      }
    } finally {
      platform.clearTimeout(timeout); timers.delete(timeout);
      revoke(candidate);
      pendingUrl = null;
      if (requestController === controller) requestController = null;
      if (active) imageTimer = schedule(load, Math.max(0, interval - (now() - started)));
    }
  }

  async function flush() {
    if (!active || !observe || !reportingSupported || reportController || now() < nextReportAt) return;
    const report = meter.report();
    if (!report) return;
    let failed = false;
    const controller = new AbortController();
    reportController = controller;
    const timeout = schedule(() => controller.abort(), 2000);
    try {
      const response = await platform.fetch("/api/v1/stream-observability/reports", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(report), signal: controller.signal,
      });
      if (response.status === 404 || response.status === 405) reportingSupported = false;
      else if (!response.ok) throw new Error("report rejected");
      backoffMs = 5000;
    } catch {
      if (active) {
        failed = true;
        meter.reportErrors += 1;
        backoffMs = Math.min(60000, backoffMs * 2);
      }
    } finally {
      platform.clearTimeout(timeout); timers.delete(timeout);
      // setInterval itself supplies the normal cadence. A second strict 5s gate
      // can skip every other tick due to a few milliseconds of browser jitter.
      nextReportAt = failed ? now() + backoffMs : 0;
      reportController = null;
    }
  }

  const sampling = observe ? platform.setInterval(() => meter.sample(platform.document.visibilityState !== "hidden"), 100) : null;
  const reporting = observe ? platform.setInterval(flush, 5000) : null;
  // Independent watchdog also covers a stalled socket/fetch/decode promise.
  const staleCheck = platform.setInterval(() => {
    if (now() - lastDisplayedAt > 2000 && lastDisplayedAt !== -Infinity) {
      lastDisplayedAt = -Infinity;
      if (observe) meter.unavailable();
      if (fallback) { element.src = fallback; element.hidden = false; }
      else element.hidden = true;
    }
  }, 250);
  // Attribute a visibility transition to the interval that just elapsed, not the new state.
  let wasVisible = platform.document.visibilityState !== "hidden";
  const visibility = () => {
    if (observe) meter.sample(wasVisible);
    wasVisible = platform.document.visibilityState !== "hidden";
  };
  platform.document.addEventListener("visibilitychange", visibility);
  void load();
  return () => {
    active = false;
    transport.dispose();
    requestController?.abort(); reportController?.abort();
    for (const timer of timers) platform.clearTimeout(timer);
    platform.clearTimeout(imageTimer);
    if (sampling !== null) platform.clearInterval(sampling);
    if (reporting !== null) platform.clearInterval(reporting);
    platform.clearInterval(staleCheck);
    platform.document.removeEventListener("visibilitychange", visibility);
    element.onload = element.onerror = null;
    revoke(currentUrl); revoke(pendingUrl);
    element.removeAttribute("src");
  };
}
