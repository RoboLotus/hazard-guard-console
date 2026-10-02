// One request at a time; stopping invalidates even an already-resolved response.
export function startPolling(request, onData, onError, { interval = 2000, timeout = 3000 } = {}) {
  let stopped = false;
  let timer;
  let controller;
  const run = async () => {
    controller = new AbortController();
    const deadline = setTimeout(() => controller.abort(), timeout);
    try {
      const data = await request(controller.signal);
      if (!stopped && !controller.signal.aborted) onData(data);
      else if (!stopped) onError(new Error("응답 시간이 초과되었습니다."));
    } catch (error) {
      if (!stopped) onError(error);
    } finally {
      clearTimeout(deadline);
      if (!stopped) timer = setTimeout(run, interval);
    }
  };
  void run();
  return () => { stopped = true; clearTimeout(timer); controller?.abort(); };
}

export async function fetchJson(url, signal) {
  const response = await fetch(url, { cache: "no-store", signal });
  if (!response.ok) throw new Error(`상태 조회 실패 (${response.status})`);
  const data = await response.json();
  if (!data || typeof data !== "object" || Array.isArray(data)) throw new Error("잘못된 상태 응답입니다.");
  return data;
}
