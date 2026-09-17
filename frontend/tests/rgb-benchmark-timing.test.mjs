import test from 'node:test';
import assert from 'node:assert/strict';
import { timingPlatform } from './rgb-benchmark-timing.js';

test('freshness bounds remove only measured pre-age server time, not wall clock subtraction',async()=>{
 let clock=0;
 const base={performance:{now:()=>clock},setTimeout(){},clearTimeout(){},setInterval(){},clearInterval(){},cancelAnimationFrame(){},requestAnimationFrame(fn){clock=160;fn(clock);},async fetch(){clock=140;return {ok:true,status:200,headers:{get:k=>k==='X-HazardGuard-Frame'?JSON.stringify({s:'a'.repeat(32),n:1,age_ms:10}):'handler;dur=101, wait;dur=100, active;dur=1, beforeage;dur=100'},blob:async()=>{clock=150;return {};}};}};
 const p=timingPlatform(base,{add(){},fail(){}},'new-frame');await(await p.fetch('/api/v1/media/rgb')).blob();p.requestAnimationFrame(()=>{});
 assert.deepEqual(p.freshness(200),[60,110,210]);
});

test('split-origin image requests keep timing and new-frame cursor semantics', async () => {
  let seen, saved;
  const base={performance:{now:()=>1},setTimeout(){},clearTimeout(){},setInterval(){},clearInterval(){},cancelAnimationFrame(){},requestAnimationFrame(fn){fn(1);},
    async fetch(url){seen=url;return {ok:true,status:200,headers:{get:()=>null},blob:async()=>({size:1})};}};
  const p=timingPlatform(base,{add:r=>saved=r,fail:()=>assert.fail('unexpected failure')},'new-frame');
  await (await p.fetch('http://127.0.0.1:8768/api/v1/media/rgb')).blob();
  p.requestAnimationFrame(()=>{});
  assert.equal(seen,'http://127.0.0.1:8768/api/v1/media/rgb?delivery=new-frame');
  assert.equal(saved.start,1);
});

test('benchmark splits headers/body/display without changing bytes or request options', async () => {
  let clock=0, saved, failed=0, seen;
  const blob={size:123};
  const base={
    performance:{now:()=>clock},
    setTimeout(){},clearTimeout(){},setInterval(){},clearInterval(){},cancelAnimationFrame(){},
    requestAnimationFrame(fn){clock=35;fn(clock);return 1;},
    async fetch(url,options){seen={url,options};clock=10;return {ok:true,status:200,headers:{},async blob(){clock=30;return blob;}};},
  };
  const p=timingPlatform(base,{add:(r,at)=>saved={...r,at},fail:()=>failed++});
  const opts={cache:'no-store'};
  const response=await p.fetch('/api/v1/media/rgb?frame=1',opts);
  assert.equal(await response.blob(),blob);
  p.requestAnimationFrame(()=>{});
  assert.deepEqual(saved,{start:0,headersAt:10,bodyAt:30,at:35});
  assert.equal(seen.options,opts);
  assert.equal(failed,0);
});

test('failed fetch counted once; report requests are not image timing samples', async () => {
  let failed=0;
  const base={performance:{now:()=>0},setTimeout(){},clearTimeout(){},setInterval(){},clearInterval(){},cancelAnimationFrame(){},async fetch(){throw Error('network');}};
  const p=timingPlatform(base,{fail:()=>failed++});
  await assert.rejects(p.fetch('/api/v1/media/rgb'));
  assert.equal(failed,1);
  await assert.rejects(p.fetch('/api/v1/stream-observability/reports'));
  assert.equal(failed,1);
});

test('new-frame delivery advances identity only after body success and records server timings', async () => {
  let seen=[], saved, fails=0, sequence=2, breakBody=false;
  const session='a'.repeat(32);
  const base={performance:{now:()=>10},setTimeout(){},clearTimeout(){},setInterval(){},clearInterval(){},cancelAnimationFrame(){},
    requestAnimationFrame(fn){fn(10);},
    async fetch(url){seen.push(url);return {ok:true,status:200,headers:{get(key){return key==='X-HazardGuard-Frame'?JSON.stringify({s:session,n:sequence}):'handler;dur=21.4, wait;dur=21.1, active;dur=0.3';}},
      async blob(){if(breakBody)throw Error('body failed');return {};}};},
  };
  const p=timingPlatform(base,{add:r=>saved=r,fail:()=>fails++},'new-frame');
  await (await p.fetch('/api/v1/media/rgb?frame=1')).blob();
  p.requestAnimationFrame(()=>{});
  assert.deepEqual(saved.server,[21.4,21.1,.3]);
  sequence=3;breakBody=true;
  await assert.rejects((await p.fetch('/api/v1/media/rgb?frame=2')).blob());
  breakBody=false;
  await (await p.fetch('/api/v1/media/rgb?frame=3')).blob();
  assert.equal(seen[0],'/api/v1/media/rgb?frame=1&delivery=new-frame');
  assert.ok(seen[1].endsWith(`&session=${session}&after=2`));
  assert.ok(seen[2].endsWith(`&session=${session}&after=2`));
  assert.equal(fails,1);
});
