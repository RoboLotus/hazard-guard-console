// Display transport only. One request in flight, shared server JPEG, HTTP rollback.
export function unpackRgbPacket(buffer) {
  if (!(buffer instanceof ArrayBuffer) || buffer.byteLength < 4 || buffer.byteLength > 16 * 1024 * 1024) throw Error("invalid RGB packet");
  const length = new DataView(buffer).getUint32(0);
  if (length > 8192 || length + 4 > buffer.byteLength) throw Error("invalid RGB metadata");
  const meta = JSON.parse(new TextDecoder().decode(new Uint8Array(buffer, 4, length)));
  if (![200, 204, 503].includes(meta.status) || !meta.headers || typeof meta.headers !== "object") throw Error("invalid RGB status");
  if (meta.status === 200 && (!/^[a-f0-9]{32}$/.test(meta.session) || !Number.isSafeInteger(meta.sequence) || meta.sequence < 1)) throw Error("invalid RGB cursor");
  return { ok: meta.status === 200, status: meta.status, session: meta.session, sequence: meta.sequence,
    headers: new Headers(meta.headers), blob: async () => new Blob([buffer.slice(4 + length)], { type: "image/jpeg" }) };
}

export function createRgbTransport(platform, endpoint, { enabled = true } = {}) {
  let socket = null, pending = null, disposed = false, fetching = false, cooldown = 0, session = "", after = 0;
  const now = () => platform.performance.now();
  const fail = error => { const p = pending; pending = null; if (p) { p.cleanup(); p.reject(error); } };
  const close = () => { const old = socket; socket = null; old?.close(); };
  function request(signal) {
    if (signal?.aborted) return Promise.reject(Error("aborted"));
    if (pending) return Promise.reject(Error("overlapping RGB request"));
    return new Promise((resolve, reject) => {
      const abort = () => { fail(Error("aborted")); close(); };
      const timeout = platform.setTimeout(() => { fail(Error("RGB timeout")); close(); }, 1500);
      pending = { resolve, reject, cleanup() { platform.clearTimeout(timeout); signal?.removeEventListener("abort", abort); } };
      signal?.addEventListener("abort", abort, { once: true });
      const send = () => socket.send(JSON.stringify({ session, after }));
      try {
        if (!socket) {
          const url = new URL("/ws/media/rgb", platform.location.href);
          url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
          const ws = socket = new platform.WebSocket(url.href);
          ws.binaryType = "arraybuffer";
          ws.onopen = () => { if (ws === socket && pending) send(); };
          ws.onmessage = event => {
            if (ws !== socket || !pending) return;
            try {
              const response = unpackRgbPacket(event.data);
              if (response.ok) { session = response.session; after = response.sequence; }
              const p = pending; pending = null; p.cleanup(); p.resolve(response);
            } catch (error) { fail(error); close(); }
          };
          ws.onerror = () => { if (ws === socket) { fail(Error("RGB socket error")); close(); } };
          ws.onclose = () => { if (ws === socket) { socket = null; fail(Error("RGB socket closed")); } };
        } else if (socket.readyState === 1) send();
        else throw Error("RGB socket not ready");
      } catch (error) { fail(error); close(); }
    });
  }
  return {
    async fetch(url, options = {}) {
      if (disposed) throw Error("disposed");
      if (fetching) throw Error("overlapping RGB request");
      fetching = true;
      try {
        if (enabled && platform.WebSocket && platform.location && now() >= cooldown) {
          try { return await request(options.signal); }
          catch (error) {
            if (disposed || options.signal?.aborted) throw error;
            cooldown = now() + 30000;
            session = ""; after = 0;
          }
        }
        return await platform.fetch(url, options);
      } finally {
        fetching = false;
      }
    },
    dispose() { disposed = true; fail(Error("disposed")); close(); },
  };
}
