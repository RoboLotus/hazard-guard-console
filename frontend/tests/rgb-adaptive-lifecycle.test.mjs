import test from 'node:test';
import assert from 'node:assert/strict';
import { startAdaptivePreview } from '../src/rgbAdaptivePreview.js';

const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
function packet(meta) {
  const header = new TextEncoder().encode(JSON.stringify(meta));
  const bytes = new Uint8Array(5 + header.length);
  new DataView(bytes.buffer).setUint32(0, header.length);
  bytes.set(header, 4); bytes[bytes.length - 1] = 1;
  return bytes.buffer;
}
const frame = { status: 200, session: 'run', epoch: 1, sequence: 1, token: 'ack',
  codec: 'jpeg', key: true, age_ms: 10, profile: { fps: 10 } };

function browser(t, { avc = false, bitmap, raf } = {}) {
  const sockets = [], draws = [], closed = [], messages = [], listeners = new Map();
  const time = { now: 1000 };
  const context = { drawImage: value => draws.push(value), clearRect() {} };
  const canvas = { getContext: () => context };
  const restore = [];
  function install(name, value) {
    const previous = Object.getOwnPropertyDescriptor(globalThis, name);
    Object.defineProperty(globalThis, name, { configurable: true, writable: true, value });
    restore.push(() => previous ? Object.defineProperty(globalThis, name, previous) : delete globalThis[name]);
  }
  class Socket {
    static OPEN = 1;
    constructor() { this.readyState = 1; this.sent = []; sockets.push(this); queueMicrotask(() => this.onopen?.()); }
    send(value) { this.sent.push(JSON.parse(value)); }
    close() { if (this.readyState !== 3) { this.readyState = 3; this.onclose?.(); } }
    frame(value) { return this.onmessage({ data: packet(value) }); }
  }
  const decoderInstances = [];
  class Decoder {
    static async isConfigSupported() { return { supported: true }; }
    constructor(callbacks) { this.callbacks = callbacks; this.state = 'unconfigured'; this.decodeQueueSize = 0; decoderInstances.push(this); }
    configure() { this.state = 'configured'; }
    decode(chunk) { this.callbacks.output({ chunk, close() { closed.push('avc-frame'); } }); }
    close() { this.state = 'closed'; }
  }
  install('document', { hidden: false, addEventListener: (key, value) => listeners.set(key, value), removeEventListener: key => listeners.delete(key) });
  install('location', { href: 'http://localhost:5173/' });
  install('WebSocket', Socket);
  install('performance', { now: () => time.now });
  install('requestAnimationFrame', raf || (callback => setTimeout(callback, 0)));
  install('cancelAnimationFrame', clearTimeout);
  install('createImageBitmap', bitmap || (async () => ({ close() { closed.push('jpeg-frame'); } })));
  install('VideoDecoder', avc ? Decoder : undefined);
  install('EncodedVideoChunk', class { constructor(options) { Object.assign(this, options); } });
  const player = startAdaptivePreview(canvas, { onStatus: value => messages.push(value.message) });
  t.after(() => { player.stop(); for (const reset of restore) reset(); });
  return { sockets, draws, closed, messages, listeners, player, time, decoderInstances };
}

test('JPEG-only browser ACKs after drawing, hides stale video and releases resources', async t => {
  const b = browser(t);
  await wait(5);
  const ws = b.sockets[0];
  assert.deepEqual(ws.sent[0], { h264: false });
  await ws.frame(frame);
  assert.equal(b.draws.length, 1);
  assert.equal(ws.sent.at(-1).ack.token, 'ack');
  assert.equal(b.closed.length, 1);
  b.time.now += 600;
  await wait(110);
  assert.ok(b.messages.includes('오래된 영상 숨김'));
  b.player.stop();
  assert.equal(b.listeners.size, 0);
  assert.equal(ws.readyState, 3);
});

test('expired frames are not displayed, and late image decode after unmount is released', async t => {
  let resolve;
  const b = browser(t, { bitmap: () => new Promise(done => { resolve = done; }) });
  await wait(5);
  const operation = b.sockets[0].frame({ ...frame, age_ms: 600 });
  resolve({ close() { b.closed.push('expired'); } });
  await operation;
  assert.equal(b.draws.length, 0);
  assert.equal(b.player.metrics.discarded, 1);
  assert.equal(b.messages.at(-1), '최신 프레임 재수신 중');
  const late = b.sockets[0].frame({ ...frame, sequence: 2 });
  b.player.stop();
  resolve({ close() { b.closed.push('late'); } });
  await late;
  assert.equal(b.draws.length, 0);
  assert.ok(b.closed.includes('late'));
});

test('JPEG-H264-JPEG epoch switch and 503 reset decoder, without old-image replay', async t => {
  const b = browser(t, { avc: true });
  await wait(5);
  const ws = b.sockets[0];
  assert.deepEqual(ws.sent[0], { h264: true });
  await ws.frame(frame);
  await ws.frame({ ...frame, codec: 'h264', epoch: 2, sequence: 2, codec_string: 'avc1.42C01E' });
  await ws.frame({ ...frame, codec: 'h264', epoch: 2, sequence: 3, key: false });
  assert.equal(b.decoderInstances.length, 1);
  await ws.frame({ status: 503 });
  assert.equal(b.decoderInstances[0].state, 'closed');
  await ws.frame({ ...frame, epoch: 3, sequence: 4 });
  assert.equal(b.draws.length, 4);
  assert.equal(b.player.metrics.failures, 0);
});

test('H264 reference gap closes connection instead of drawing undecodable delta', async t => {
  const b = browser(t, { avc: true });
  await wait(5);
  await b.sockets[0].frame({ ...frame, codec: 'h264', key: false });
  assert.equal(b.draws.length, 0);
  assert.equal(b.player.metrics.failures, 1);
  assert.equal(b.sockets[0].readyState, 3);
});

test('occluded rAF suspends consumption without a codec downgrade or reconnect storm', async t => {
  let wake;
  const b = browser(t, { avc: true, raf: callback => { wake = callback; return 99; } });
  await wait(5);
  await b.sockets[0].frame({ ...frame, codec: 'h264', codec_string: 'avc1.42C01E' });
  assert.equal(b.player.metrics.paint_pauses, 1);
  assert.equal(b.player.metrics.failures, 0);
  assert.equal(b.sockets.length, 1);
  assert.equal(b.sockets[0].readyState, 3);
  assert.equal(b.messages.at(-1), '화면 갱신 대기');
  wake(); // Compositor resumes; reconnect with H264 support intact.
  await wait(5);
  assert.equal(b.sockets.length, 2);
  assert.equal(b.sockets[1].sent[0].h264, true);
});
