import test from "node:test";
import assert from "node:assert/strict";
import { startPolling, fetchJson } from "../src/polling.js";
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

test("HTTP 실패도 실패로 처리한다", async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () => ({ ok: false, status: 503 });
    await assert.rejects(fetchJson("/test"), /503/);
  } finally { globalThis.fetch = original; }
});

test("요청 중첩 없이 실패 후 복구하며 종료 후 결과를 버린다", { timeout: 5000 }, async (t) => {
  let count = 0, pending = 0, peak = 0;
  const received = [], errors = [];
  let recovered;
  const recovery = new Promise((resolve) => { recovered = resolve; });
  const stop = startPolling(async () => {
    pending += 1; peak = Math.max(peak, pending);
    await wait(5); pending -= 1;
    if (++count === 1) throw new Error("offline");
    return count;
  }, (data) => { received.push(data); recovered(); }, (error) => errors.push(error), { interval: 1, timeout: 1000 });
  t.after(stop);
  await recovery; stop();
  const length = received.length;
  await wait(10);
  assert.equal(peak, 1);
  assert.equal(errors.length, 1);
  assert.ok(received.length > 0);
  assert.equal(received.length, length);
});

test("타임아웃은 AbortSignal로 요청을 중단한다", async () => {
  let failed = 0;
  const stop = startPolling((signal) => new Promise((_, reject) => {
    signal.addEventListener("abort", () => reject(new Error("timeout")));
  }), () => assert.fail(), () => failed++, { timeout: 5, interval: 100 });
  await wait(20); stop();
  assert.equal(failed, 1);
});
