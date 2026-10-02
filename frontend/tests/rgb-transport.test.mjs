import test from 'node:test';
import assert from 'node:assert/strict';
import { createRgbTransport, unpackRgbPacket } from '../src/rgbTransport.js';

function packet(status=200, sequence=1, session='a'.repeat(32)) {
  const meta = new TextEncoder().encode(JSON.stringify({status, sequence, session, headers:{}}));
  const bytes = new Uint8Array(4 + meta.length + (status===200?3:0));
  new DataView(bytes.buffer).setUint32(0, meta.length); bytes.set(meta,4);
  if(status===200) bytes.set([1,2,3],4+meta.length);
  return bytes.buffer;
}
function harness() {
  let clock=0, http=0, serial=0;
  const timers=new Map(), sockets=[];
  class WS {
    constructor() { this.readyState=0; sockets.push(this); }
    send(data) { this.sent=JSON.parse(data); }
    open() { this.readyState=1; this.onopen(); }
    close() { this.readyState=3; this.onclose?.(); }
    receive(data) { this.onmessage({data}); }
  }
  const platform={WebSocket:WS,location:{href:'http://localhost:5173/'},performance:{now:()=>clock},
    setTimeout(fn,delay){const id=++serial;timers.set(id,{fn,at:clock+delay});return id;},
    clearTimeout(id){timers.delete(id);},fetch:async()=>{http++;return {ok:true,status:200};}};
  return {platform,sockets,timers,get http(){return http;},async tick(ms){clock+=ms;for(const [id,t]of timers)if(t.at<=clock){timers.delete(id);t.fn();}await Promise.resolve();}};
}

test('production packet validation and exact JPEG bytes', async()=>{
  const result=unpackRgbPacket(packet());
  assert.deepEqual([...new Uint8Array(await(await result.blob()).arrayBuffer())],[1,2,3]);
  assert.throws(()=>unpackRgbPacket(packet(200,0)));
  assert.throws(()=>unpackRgbPacket(packet(200,1,'bad')));
  assert.throws(()=>unpackRgbPacket(packet(404)));
  assert.throws(()=>unpackRgbPacket(new ArrayBuffer(2)));
});

test('socket reuse, cursor on diagnostics-off, session change and cleanup',async()=>{
  const h=harness(),t=createRgbTransport(h.platform,'/api/v1/media/rgb');
  const p=t.fetch('/api/v1/media/rgb',{});h.sockets[0].open();
  await assert.rejects(t.fetch('/api/v1/media/rgb',{}),/overlapping/);
  assert.equal(h.http,0);
  assert.deepEqual(h.sockets[0].sent,{session:'',after:0});
  h.sockets[0].receive(packet());await p;
  const p2=t.fetch('/api/v1/media/rgb',{});
  assert.deepEqual(h.sockets[0].sent,{session:'a'.repeat(32),after:1});
  h.sockets[0].receive(packet(200,1,'b'.repeat(32)));await p2;
  const p3=t.fetch('/api/v1/media/rgb',{});
  assert.equal(h.sockets[0].sent.session,'b'.repeat(32));
  h.sockets[0].receive(packet(204));assert.equal((await p3).status,204);
  t.dispose();assert.equal(h.timers.size,0);assert.equal(h.sockets[0].readyState,3);
});

test('failed WS uses HTTP for 30 seconds, then retries once',async()=>{
  const h=harness(),t=createRgbTransport(h.platform,'/api/v1/media/rgb');
  const p=t.fetch('/api/v1/media/rgb',{});h.sockets[0].onerror();await p;
  assert.equal(h.http,1);
  await t.fetch('/api/v1/media/rgb',{});assert.equal(h.sockets.length,1);assert.equal(h.http,2);
  await h.tick(30001);
  const p2=t.fetch('/api/v1/media/rgb',{});h.sockets[1].open();h.sockets[1].receive(packet());await p2;
  t.dispose();
});

test('hung socket times out into HTTP; abort does not start fallback',async()=>{
  const h=harness(),t=createRgbTransport(h.platform,'/api/v1/media/rgb');
  const p=t.fetch('/api/v1/media/rgb',{});await h.tick(1501);await p;assert.equal(h.http,1);t.dispose();
  const h2=harness(),t2=createRgbTransport(h2.platform,'/api/v1/media/rgb'),c=new AbortController();
  const p2=t2.fetch('/api/v1/media/rgb',{signal:c.signal});c.abort();await assert.rejects(p2,/aborted/);
  assert.equal(h2.http,0);assert.equal(h2.timers.size,0);t2.dispose();
});

test('sensor unavailable is not a transport failure; HTTP rollback flag',async()=>{
  const h=harness(),t=createRgbTransport(h.platform,'/api/v1/media/rgb');
  const p=t.fetch('/api/v1/media/rgb',{});h.sockets[0].open();h.sockets[0].receive(packet(503));
  assert.equal((await p).status,503);assert.equal(h.http,0);t.dispose();
  const off=createRgbTransport(h.platform,'/api/v1/media/rgb',{enabled:false});
  await off.fetch('/api/v1/media/rgb',{});assert.equal(h.sockets.length,1);assert.equal(h.http,1);off.dispose();
});
