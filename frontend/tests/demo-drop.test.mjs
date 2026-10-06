import test from "node:test";
import assert from "node:assert/strict";
import {
  awaitDropResult,
  demoDropAvailability,
  dropResultMessage,
  isTerminalDropState,
  requestDemoDrop,
} from "../src/demoDrop.js";

const connected = { stale: false, available_for_drop: 2, connected: 2, expected: 3 };

test("버튼은 데모 플래그가 꺼져 있으면 아예 보이지 않는다", () => {
  const state = demoDropAvailability({ enabled: false, battery: connected, busy: false });
  assert.equal(state.visible, false);
});

test("큐브가 없거나 상태를 모르면 누를 수 없다", () => {
  const stale = demoDropAvailability({
    enabled: true,
    battery: { ...connected, stale: true },
    busy: false,
  });
  assert.equal(stale.disabled, true);
  assert.match(stale.reason, /미확인/);

  const none = demoDropAvailability({
    enabled: true,
    battery: { ...connected, available_for_drop: 0 },
    busy: false,
  });
  assert.equal(none.disabled, true);
  assert.match(none.reason, /큐브/);

  // 부스에서 제일 흔한 실패: BLE가 끊긴 줄 모르고 누르는 것
  for (const battery of [null, undefined, {}, { available_for_drop: null }]) {
    assert.equal(
      demoDropAvailability({ enabled: true, battery, busy: false }).disabled,
      true,
    );
  }
});

test("배출 진행 중에는 연타가 막힌다", () => {
  const state = demoDropAvailability({ enabled: true, battery: connected, busy: true });
  assert.equal(state.disabled, true);
  assert.match(state.reason, /진행 중/);
});

test("조건이 갖춰지면 누를 수 있다", () => {
  const state = demoDropAvailability({ enabled: true, battery: connected, busy: false });
  assert.deepEqual(state, { visible: true, disabled: false, reason: "" });
});

test("서보만 움직인 것은 성공으로 표시하지 않는다", () => {
  assert.equal(dropResultMessage({ state: "succeeded" }).tone, "success");
  for (const state of [
    "jam_suspected",
    "command_completed_unverified",
    "rejected_no_confirmation",
    "safety_interlock",
    "hardware_error",
    "timeout",
  ]) {
    assert.notEqual(
      dropResultMessage({ state }).tone,
      "success",
      `${state}를 성공으로 표시하면 안 된다`,
    );
  }
});

test("안전 차단 사유는 화면에 그대로 전달된다", () => {
  const message = dropResultMessage({
    state: "safety_interlock",
    result_detail: "robot_not_stably_stopped",
  });
  assert.match(message.text, /robot_not_stably_stopped/);
});

test("종료 상태 판정", () => {
  assert.equal(isTerminalDropState("succeeded"), true);
  assert.equal(isTerminalDropState("dispensing"), false);
  assert.equal(isTerminalDropState(undefined), false);
});

test("요청 실패 시 서버가 준 사유를 그대로 던진다", async () => {
  const fetchImpl = async () => ({
    ok: false,
    json: async () => ({ detail: "시연용 수동 배출이 비활성화되어 있습니다." }),
  });
  await assert.rejects(() => requestDemoDrop(fetchImpl), /비활성화/);
});

test("폴링은 종료 상태에서 멈춘다", async () => {
  const states = ["accepted", "dispensing", "waiting", "succeeded", "succeeded"];
  let calls = 0;
  const fetchImpl = async () => ({
    ok: true,
    json: async () => ({ request_id: "demo:1", state: states[calls++] }),
  });
  const result = await awaitDropResult("demo:1", { fetchImpl, sleep: async () => {} });
  assert.equal(result.state, "succeeded");
  assert.equal(calls, 4);
});

test("응답이 끊겨도 영원히 돌지 않고 timeout을 돌려준다", async () => {
  let now = 0;
  const realNow = Date.now;
  Date.now = () => now;
  try {
    const fetchImpl = async () => ({
      ok: true,
      json: async () => ({ request_id: "demo:1", state: "dispensing" }),
    });
    const result = await awaitDropResult("demo:1", {
      fetchImpl,
      timeoutMs: 1000,
      sleep: async () => {
        now += 500;
      },
    });
    assert.equal(result.state, "timeout");
  } finally {
    Date.now = realNow;
  }
});
