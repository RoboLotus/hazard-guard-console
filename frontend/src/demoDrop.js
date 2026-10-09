// Exhibition-only manual beacon drop.
//
// This replaces the trigger (a latched thermal incident) with a button. Every
// safety gate still lives on the robot: signature, full stop against odometry,
// servo reachability, and at least one cube armed over BLE. The button only has
// to avoid two booth failures — pressing it while no cube is connected, and
// pressing it again while a drop is already in flight.

const TERMINAL_STATES = new Set([
  "succeeded",
  "jam_suspected",
  "hardware_error",
  "canceled",
  "rejected_busy",
  "recovery_required",
  "command_completed_unverified",
  "dispatch_unavailable",
  "hardware_unavailable",
  "rejected_no_confirmation",
  "safety_interlock",
]);

export function isTerminalDropState(state) {
  return TERMINAL_STATES.has(String(state || ""));
}

// A missing cube is reported, not blocked. The robot owns that decision: with
// require_cube_confirmation it refuses the drop itself, and without it the
// operator is deliberately running the dispenser alone. Blocking here too
// would make the dispenser-only demo impossible.
export function demoDropAvailability({ enabled, battery, busy }) {
  if (!enabled) return { visible: false, disabled: true, reason: "" };
  if (busy) return { visible: true, disabled: true, reason: "배출 진행 중" };
  if (battery?.stale) {
    return { visible: true, disabled: false, reason: "큐브 상태 미확인" };
  }
  if (!Number(battery?.available_for_drop)) {
    return { visible: true, disabled: false, reason: "큐브 미연결 — 낙하 미확인" };
  }
  return { visible: true, disabled: false, reason: "" };
}

// A drop is only a success once a cube reports DROPPED. A moved servo is not.
export function dropResultMessage(record) {
  const state = String(record?.state || "");
  const detail = record?.result_detail ? ` (${record.result_detail})` : "";
  switch (state) {
    case "succeeded":
      return { tone: "success", text: "배출 확인 — 큐브가 낙하를 보고했습니다." };
    case "jam_suspected":
      return {
        tone: "warning",
        text: "배출 미확인 — 큐브가 걸렸을 수 있습니다. 챔버를 확인하세요.",
      };
    case "rejected_no_confirmation":
      return {
        tone: "warning",
        text: "큐브 확인 경로가 없어 배출하지 않았습니다. BLE 연결을 확인하세요.",
      };
    case "safety_interlock":
      return {
        tone: "warning",
        text: `로봇 안전 조건이 충족되지 않아 배출하지 않았습니다.${detail}`,
      };
    case "hardware_unavailable":
    case "hardware_error":
      return { tone: "warning", text: `디스펜서 하드웨어 오류입니다.${detail}` };
    case "dispatch_unavailable":
      return { tone: "warning", text: `요청을 로봇에 전달하지 못했습니다.${detail}` };
    case "command_completed_unverified":
      return {
        tone: "warning",
        text: "서보는 동작했으나 낙하 보고를 받지 못했습니다.",
      };
    case "canceled":
      return { tone: "info", text: "배출이 취소되었습니다." };
    case "rejected_busy":
      return { tone: "info", text: "이미 처리 중인 배출 요청이 있습니다." };
    case "recovery_required":
      return { tone: "warning", text: "이전 배출 기록을 복구해야 합니다." };
    case "timeout":
      return {
        tone: "warning",
        text: "결과 보고를 기다리다 시간이 초과되었습니다. 실제 배출 여부는 챔버를 확인하세요.",
      };
    default:
      return { tone: "info", text: `배출 상태: ${state || "알 수 없음"}` };
  }
}

// 한 대라도 붙어 있으면 로봇이 자동 탐색을 하지 않는다. 나중에 켠 큐브는
// 운영자가 이걸 눌러야 찾는다.
export async function requestCubeScan(fetchImpl = fetch) {
  const response = await fetchImpl("/api/v1/dispenser/scan", { method: "POST" });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(result?.detail || "큐브 탐색을 요청하지 못했습니다.");
  }
  return result;
}

export async function requestDemoDrop(fetchImpl = fetch) {
  const response = await fetchImpl("/api/v1/dispenser/demo/drop", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  const result = await response.json();
  if (!response.ok) {
    throw new Error(result?.detail || "시연용 배출을 요청하지 못했습니다.");
  }
  return result;
}

// The robot reports the outcome asynchronously; give up rather than spin
// forever, and say so instead of implying the drop failed.
export async function awaitDropResult(
  requestId,
  { fetchImpl = fetch, intervalMs = 500, timeoutMs = 20000, sleep } = {},
) {
  const wait = sleep || ((ms) => new Promise((resolve) => setTimeout(resolve, ms)));
  const deadline = Date.now() + timeoutMs;
  let last = null;
  while (Date.now() < deadline) {
    const response = await fetchImpl(
      `/api/v1/dispenser/requests/${encodeURIComponent(requestId)}`,
      { cache: "no-store" },
    );
    if (response.ok) {
      last = await response.json();
      if (isTerminalDropState(last?.state)) return last;
    }
    await wait(intervalMs);
  }
  return { ...(last || { request_id: requestId }), state: "timeout" };
}
