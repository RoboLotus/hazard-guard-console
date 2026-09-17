import assert from "node:assert/strict";
import test from "node:test";
import { RgbTelemetry, parseFrameHeader } from "../src/rgbTelemetry.js";
import { startRgbPreview } from "../src/rgbPreview.js";

const frame = (n = 1) => ({ v: 1, s: "b".repeat(32), n, age_ms: 10, reference: "ingress", ros_ms: 100, capture_age_ms: null, mode: "basic" });
test("같은 프레임을 새 프레임으로 세지 않고 정지 중에도 나이가 증가", () => {
  let now = 0;
  const m = new RgbTelemetry("a".repeat(32), () => now);
  m.displayed(frame(), 0, 20);
  for (now = 100; now <= 2000; now += 100) m.sample();
  const r = m.report(2000);
  assert.equal(r.unique_frames, 1);
  assert.equal(r.age.p95_ms, 1930);
  assert.equal(r.stale_ms, 1100);
  m.displayed({ ...frame(), age_ms: 2110 }, 2100, 20);
  m.sample(true, 2200);
  assert.equal(m.report(2200).unique_frames, 0);
});
test("미수신·숨김·타이머 중단은 0ms의 좋은 결과가 아니다", () => {
  const m = new RgbTelemetry("a".repeat(32), () => 0);
  m.sample(true, 100);
  m.sample(false, 200);
  m.sample(true, 2000);
  const r = m.report(2000);
  assert.equal(r.missing_ms, 100);
  assert.equal(r.hidden_ms, 100);
  assert.equal(r.unobserved_ms, 1800);
  assert.equal(r.age.p95_ms, null);
});
test("메타데이터 없는 정상 영상은 영상 미수신과 구분", () => {
  const m = new RgbTelemetry("a".repeat(32), () => 0);
  m.displayed(null, 0, 10);
  m.sample(true, 100);
  const r = m.report(100);
  assert.equal(r.missing_ms, 0);
  assert.equal(r.metadata_errors, 1);
  assert.equal(r.unobserved_ms, 100);
});
test("촬영 시계 검증된 경우만 capture 분류; 원시 표본은 상세 모드만 50개", () => {
  const m = new RgbTelemetry("a".repeat(32), () => 0);
  m.displayed({ ...frame(), capture_age_ms: 100, mode: "detailed" }, 0, 10);
  for (let at = 100; at <= 10000; at += 100) m.sample(true, at);
  const r = m.report(10000);
  assert.equal(r.reference, "capture");
  assert.equal(r.detail_age_ms.length, 50);
  assert.equal(r.age.histogram.reduce((a, b) => a + b), r.age.samples);
});
test("서버 재시작과 메타데이터 검증", () => {
  const m = new RgbTelemetry("a".repeat(32), () => 0);
  m.displayed(frame(), 0, 10);
  m.displayed({ ...frame(), s: "c".repeat(32) }, 0, 10);
  assert.equal(m.report(100).unique_frames, 2);
  assert.equal(parseFrameHeader("not-json"), null);
  assert.equal(parseFrameHeader(JSON.stringify({ ...frame(), age_ms: -1 })), null);
  assert.equal(parseFrameHeader(JSON.stringify({ ...frame(), n: 1.5 })), null);
  assert.deepEqual(parseFrameHeader(JSON.stringify(frame())), frame());
});

test("영상 실패 후에도 마지막 세션과 상세 진단 표본을 보존", () => {
  const m = new RgbTelemetry("a".repeat(32), () => 0);
  m.displayed({ ...frame(), mode: "detailed" }, 0, 10);
  m.sample(true, 100);
  m.unavailable();
  m.sample(true, 200);
  const r = m.report(200);
  assert.equal(r.session_id, "b".repeat(32));
  assert.equal(r.detail_age_ms.length, 1);
  assert.equal(r.missing_ms, 100);
});

function harness({ slowImage = false, badReport = false, metadata = true, failImage = false } = {}) {
  let clock = 0, nextId = 0, images = 0, reports = 0, inFlight = 0, maxInFlight = 0;
  const timers = new Map(), urls = new Set(), listeners = new Map(), bodies = [];
  const platform = {
    performance: { now: () => clock }, crypto: { randomUUID: () => "a".repeat(32) },
    document: { visibilityState: "visible", addEventListener: (k, f) => listeners.set(k, f), removeEventListener: k => listeners.delete(k) },
    setTimeout: (fn, ms) => { const id = ++nextId; timers.set(id, { fn, at: clock + ms }); return id; },
    clearTimeout: id => timers.delete(id),
    setInterval: (fn, ms) => { const id = ++nextId; timers.set(id, { fn, at: clock + ms, every: ms }); return id; },
    clearInterval: id => timers.delete(id),
    requestAnimationFrame: fn => platform.setTimeout(fn, 1), cancelAnimationFrame: id => timers.delete(id),
    URL: { createObjectURL: () => { const u = `blob:test-${++nextId}`; urls.add(u); return u; }, revokeObjectURL: u => urls.delete(u) },
    fetch: async (url, options) => {
      if (options.method === "POST") { reports++; bodies.push(JSON.parse(options.body)); return { ok: !badReport, status: badReport ? 500 : 202 }; }
      images++; inFlight++; maxInFlight = Math.max(maxInFlight, inFlight);
      if (slowImage) {
        return new Promise((resolve, reject) => options.signal.addEventListener("abort", () => { inFlight--; reject(new Error("timeout")); }, { once: true }));
      }
      inFlight--;
      return { ok: !failImage, status: failImage ? 503 : 200, headers: { get: () => metadata ? JSON.stringify(frame(images)) : null }, blob: async () => ({ size: 10 }) };
    },
  };
  const element = { hidden: false, onload: null, onerror: null, removeAttribute() {}, set src(value) { if (value?.startsWith("blob:")) platform.setTimeout(() => element.onload?.(), 1); } };
  async function tick(ms) {
    const target = clock + ms;
    await new Promise(resolve => setImmediate(resolve));
    while (true) {
      const entry = [...timers].filter(([, t]) => t.at <= target).sort((a, b) => a[1].at - b[1].at)[0];
      if (!entry) break;
      const [id, timer] = entry;
      clock = timer.at;
      if (timer.every) timer.at += timer.every; else timers.delete(id);
      timer.fn();
      await new Promise(resolve => setImmediate(resolve));
    }
    clock = target;
  }
  return { platform, element, tick, urls, timers, bodies, get counts() { return { images, reports, maxInFlight }; } };
}

test("영상 메타데이터 별도 요청 없이 5초마다 집계, URL·타이머 종료 정리", async () => {
  const h = harness();
  const stop = startRgbPreview(h.element, { endpoint: "/api/v1/media/rgb" }, h.platform);
  await h.tick(15100);
  assert.equal(h.counts.reports, 3);
  assert.equal(h.counts.maxInFlight, 1);
  assert.ok(h.urls.size <= 2);
  assert.equal(h.bodies[0].reference, "ingress");
  stop(); await h.tick(10);
  assert.equal(h.urls.size, 0);
  assert.equal(h.timers.size, 0);
});
test("느린 영상 요청이 중첩되지 않고 취소 가능", async () => {
  const h = harness({ slowImage: true });
  const stop = startRgbPreview(h.element, { endpoint: "/api/v1/media/rgb" }, h.platform);
  await h.tick(11000);
  assert.equal(h.counts.maxInFlight, 1);
  assert.equal(h.counts.images, 3);
  assert.ok(h.bodies[0].missing_ms > 0);
  stop(); await h.tick(10);
  assert.equal(h.timers.size, 0);
});
test("로그 서버 실패와 off 모드는 영상 전달을 막지 않는다", async () => {
  const h = harness({ badReport: true });
  const stop = startRgbPreview(h.element, { endpoint: "/api/v1/media/rgb" }, h.platform);
  await h.tick(30000);
  assert.ok(h.counts.images > 90);
  assert.ok(h.counts.reports < 6);
  stop(); await h.tick(10);
  const off = harness();
  const offStop = startRgbPreview(off.element, { endpoint: "/api/v1/media/rgb", observe: false }, off.platform);
  await off.tick(10000);
  assert.equal(off.counts.reports, 0);
  assert.ok(off.counts.images > 30);
  offStop();
});
test("구형 백엔드의 헤더 없는 JPEG도 표시", async () => {
  const h = harness({ metadata: false });
  const stop = startRgbPreview(h.element, { endpoint: "/api/v1/media/rgb" }, h.platform);
  await h.tick(5100);
  assert.equal(h.element.hidden, false);
  assert.ok(h.bodies[0].metadata_errors > 0);
  assert.equal(h.bodies[0].age.p95_ms, null);
  stop();
});

test("일반 HTTP 환경에서 randomUUID가 없어도 영상 표시", async () => {
  const h = harness();
  h.platform.crypto = {};
  const stop = startRgbPreview(h.element, { endpoint: "/api/v1/media/rgb" }, h.platform);
  await h.tick(5100);
  assert.match(h.bodies[0].client_id, /^[a-f0-9]{32}$/);
  assert.equal(h.element.hidden, false);
  stop();
});
