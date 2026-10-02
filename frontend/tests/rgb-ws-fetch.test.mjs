import test from 'node:test';
import assert from 'node:assert/strict';
import { unpack,websocketFetcher } from './rgb-ws-fetch.js';
function packet(){const m=new TextEncoder().encode(JSON.stringify({status:200,headers:{'x-test':'yes'}})),b=new Uint8Array(m.length+7);new DataView(b.buffer).setUint32(0,m.length);b.set(m,4);b.set([1,2,3],m.length+4);return b.buffer;}
test('packet returns exact bytes, invalid packets rejected',async()=>{
 const r=unpack(packet());assert.equal(r.headers.get('x-test'),'yes');assert.deepEqual([...new Uint8Array(await(await r.blob()).arrayBuffer())],[1,2,3]);
 assert.throws(()=>unpack(new ArrayBuffer(3)));assert.throws(()=>unpack(new Uint32Array([999999]).buffer));
});
test('one pending request, reuse connection, abort and reconnect, cleanup',async()=>{
 const made=[];class WS{constructor(){this.readyState=0;made.push(this);}send(b){this.sent=b;}close(){this.readyState=3;this.onclose?.();}open(){this.readyState=1;this.onopen();}}
 const t=websocketFetcher({WebSocket:WS},'ws://localhost/ws/bench/rgb');
 const p=t.fetch('/api/v1/media/rgb?session='+ 'a'.repeat(32)+'&after=7');
 await assert.rejects(t.fetch('/api/v1/media/rgb'),/overlapping/);
 made[0].open();assert.equal(JSON.parse(made[0].sent).after,7);made[0].onmessage({data:packet()});assert.equal((await p).status,200);
 const c=new AbortController(),p2=t.fetch('/api/v1/media/rgb',{signal:c.signal});c.abort();await assert.rejects(p2,/aborted/);
 const p3=t.fetch('/api/v1/media/rgb');assert.equal(made.length,2);made[1].open();made[1].onmessage({data:packet()});await p3;
 const p4=t.fetch('/api/v1/media/rgb');t.disconnect();await assert.rejects(p4,/disconnect/);
 t.dispose();await assert.rejects(t.fetch('/api/v1/media/rgb'),/disposed/);
});
