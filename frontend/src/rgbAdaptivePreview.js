// Shared latest-only renderer: opt-in production RGB and experiment harness.
export function unpackAdaptive(buffer) {
  if (!(buffer instanceof ArrayBuffer) || buffer.byteLength < 4 || buffer.byteLength > 4_000_000) throw Error('invalid packet');
  const length = new DataView(buffer).getUint32(0);
  if (length > 8192 || length + 4 > buffer.byteLength) throw Error('invalid metadata length');
  const meta = JSON.parse(new TextDecoder().decode(new Uint8Array(buffer, 4, length)));
  const data = new Uint8Array(buffer, 4 + length);
  if (![200, 204, 503].includes(meta.status)) throw Error('invalid status');
  if (meta.status === 200 && (!['jpeg', 'h264'].includes(meta.codec) || !data.length ||
      typeof meta.session !== 'string' || typeof meta.token !== 'string' ||
      !Number.isSafeInteger(meta.sequence) || meta.sequence < 1 ||
      !Number.isSafeInteger(meta.epoch) || meta.epoch < 1 || typeof meta.key !== 'boolean' ||
      !Number.isFinite(meta.age_ms) || meta.age_ms < 0)) throw Error('invalid frame metadata');
  return { meta, data };
}

export function requiresKey(previous, meta) {
  return !previous || previous.session !== meta.session || previous.epoch !== meta.epoch ||
    previous.sequence + 1 !== meta.sequence;
}

export function startAdaptivePreview(canvas, { endpoint = '/ws/bench/rgb-adaptive', onStatus = () => {} } = {}) {
  const ctx = canvas.getContext('2d');
  if (!ctx || typeof createImageBitmap !== 'function') throw Error('canvas image decoder unavailable');
  const metrics = { displayed: 0, discarded: 0, failures: 0, reconnects: 0, paint_pauses: 0, bytes: 0, ages: [], decode: [], errors: [] };
  let stopped = false, socket, decoder, pendingDecode, last, generation = 0, retry;
  let paintRequest, paintReject, paintWake;
  let requestedAt = 0, expiresAt = 0, busy = false, disableH264 = false;
  canvas.width = 640; canvas.height = 480;
  const clear = (message) => { ctx.clearRect(0, 0, 640, 480); onStatus({ message, ...metrics }); };
  const closeDecoder = () => {
    if (pendingDecode) { pendingDecode.reject(Error('decoder reset')); pendingDecode = null; }
    if (decoder && decoder.state !== 'closed') decoder.close();
    decoder = null; last = null;
  };
  const cancelPaint = () => {
    if (paintRequest !== undefined) cancelAnimationFrame(paintRequest);
    paintRequest = undefined;
    const reject = paintReject; paintReject = null;
    reject?.(Error('paint canceled'));
  };
  const nextPaint = () => new Promise((resolve, reject) => {
    paintReject = reject;
    paintRequest = requestAnimationFrame(() => {
      paintRequest = undefined; paintReject = null; resolve();
    });
  });
  const disconnect = () => {
    generation++; clearTimeout(retry);
    cancelPaint();
    if (paintWake !== undefined) cancelAnimationFrame(paintWake);
    paintWake = undefined;
    socket?.close(); socket = null; closeDecoder(); busy = false; expiresAt = 0;
  };
  const request = (ack) => {
    requestedAt = performance.now();
    socket.send(JSON.stringify(ack ? { ack } : {}));
  };
  const bounded = (array, value) => { array.push(value); if (array.length > 600) array.shift(); };
  const timeout = async (promise, ms) => {
    let timer;
    try {
      return await Promise.race([promise, new Promise((_, reject) => { timer = setTimeout(() => reject(Error('deadline')), ms); })]);
    } finally { clearTimeout(timer); }
  };
  async function connect() {
    if (stopped || document.hidden) return;
    disconnect();
    const run = generation;
    let h264 = false;
    if (!disableH264 && typeof VideoDecoder !== 'undefined') {
      try { h264 = (await VideoDecoder.isConfigSupported({ codec: 'avc1.42C01E', codedWidth: 640, codedHeight: 480 })).supported; } catch { /* JPEG */ }
    }
    if (stopped || run !== generation || document.hidden) return;
    const url = new URL(endpoint, location.href); url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = socket = new WebSocket(url); ws.binaryType = 'arraybuffer';
    let connectTimer = setTimeout(() => ws.close(), 2000);
    ws.onopen = () => {
      clearTimeout(connectTimer);
      if (stopped || run !== generation || document.hidden) { ws.close(); return; }
      ws.send(JSON.stringify({ h264 })); request();
    };
    ws.onmessage = async event => {
      if (run !== generation || stopped) return;
      if (busy) { ws.close(); return; }
      busy = true;
      let image, meta, phase = 'packet';
      try {
        const packet = unpackAdaptive(event.data); meta = packet.meta;
        metrics.bytes += event.data.byteLength;
        if (meta.status !== 200) {
          if (meta.status === 503) { closeDecoder(); clear('센서 프레임 대기'); }
          busy = false; request(); return;
        }
        const started = performance.now();
        phase = 'decode';
        if (meta.codec === 'jpeg') {
          closeDecoder();
          // Late bitmap completions must also release their native memory.
          const bitmap = createImageBitmap(new Blob([packet.data], { type: 'image/jpeg' }));
          let accepted = false;
          bitmap.then(value => { setTimeout(() => { if (!accepted) value.close(); }, 0); }, () => {});
          image = await timeout(bitmap, 750); accepted = true;
        } else {
          const reset = requiresKey(last, meta);
          if (reset && !meta.key) throw Error('H264 reference gap');
          if (!decoder || reset) {
            closeDecoder();
            if (!/^avc1\.[0-9A-Fa-f]{6}$/.test(meta.codec_string || '')) throw Error('missing SPS codec');
            const config = { codec: meta.codec_string, codedWidth: 640, codedHeight: 480, optimizeForLatency: true };
            if (!(await VideoDecoder.isConfigSupported(config)).supported) throw Error('AVC unsupported');
            if (stopped || run !== generation || document.hidden) return;
            decoder = new VideoDecoder({
              output(frame) { if (pendingDecode) { const p = pendingDecode; pendingDecode = null; p.resolve(frame); } else frame.close(); },
              error(error) { if (pendingDecode) { pendingDecode.reject(error); pendingDecode = null; } },
            });
            decoder.configure(config);
          }
          if (decoder.decodeQueueSize > 0) throw Error('decode backlog');
          const decoded = new Promise((resolve, reject) => { pendingDecode = { resolve, reject }; });
          decoder.decode(new EncodedVideoChunk({ type: meta.key ? 'key' : 'delta', timestamp: meta.sequence * 100000, data: packet.data }));
          image = await timeout(decoded, 750);
          if (stopped || run !== generation) return;
          last = meta;
        }
        const decodeMs = performance.now() - started;
        phase = 'paint';
        await timeout(nextPaint(), 300);
        if (stopped || run !== generation || document.hidden) return;
        // Includes request uplink + server wait: conservative INGRESS-age upper
        // estimate, not sensor capture-to-photon latency nor synchronized clocks.
        const age = meta.age_ms + performance.now() - requestedAt;
        bounded(metrics.ages, age); bounded(metrics.decode, decodeMs);
        if (age <= 500) {
          ctx.drawImage(image, 0, 0, 640, 480); metrics.displayed++;
          expiresAt = performance.now() + (500 - age);
          onStatus({ message: `${meta.codec.toUpperCase()} · 목표 ${meta.profile.fps} FPS`, profile: meta.profile, age, ...metrics });
        } else { metrics.discarded++; expiresAt = 0; clear('최신 프레임 재수신 중'); }
        busy = false;
        request({ token: meta.token, decode_ms: decodeMs });
      } catch (error) {
        if (stopped || run !== generation) return;
        metrics.errors.push({ phase, codec: meta?.codec, message: error.message, at: performance.now() });
        if (metrics.errors.length > 20) metrics.errors.shift();
        if (phase === 'paint') {
          // Occluded windows may throttle rAF without visibilitychange. Stop
          // consuming/encoding; keep only one wake callback, not reconnect loops
          // or stale decoded images. Resume with a fresh connection/keyframe.
          metrics.paint_pauses++; metrics.discarded++;
          disconnect(); clear('화면 갱신 대기');
          paintWake = requestAnimationFrame(() => {
            paintWake = undefined;
            if (!stopped && !document.hidden) connect();
          });
          return;
        }
        metrics.failures++;
        // A background/overloaded browser missing rAF is not an AVC capability
        // failure. Only failed AVC decoding negotiates permanent JPEG fallback.
        if (meta?.codec === 'h264' && phase === 'decode') disableH264 = true;
        clear(`복구 중: ${error.message}`); ws.close();
      } finally { image?.close(); }
    };
    ws.onclose = () => {
      clearTimeout(connectTimer);
      if (run !== generation || stopped) return;
      disconnect(); clear('연결 대기'); metrics.reconnects++;
      retry = setTimeout(connect, 1000);
    };
    ws.onerror = () => ws.close();
  }
  const guard = setInterval(() => {
    if (expiresAt && performance.now() >= expiresAt) { expiresAt = 0; clear('오래된 영상 숨김'); }
    if (socket?.readyState === WebSocket.OPEN && performance.now() - requestedAt > 1500) socket.close();
  }, 100);
  const visibility = () => { disconnect(); clear('일시 중지'); if (!document.hidden) connect(); };
  document.addEventListener('visibilitychange', visibility);
  connect();
  return { metrics, stop() { if (stopped) return; stopped = true; disconnect(); clearInterval(guard); document.removeEventListener('visibilitychange', visibility); clear('중지'); } };
}
