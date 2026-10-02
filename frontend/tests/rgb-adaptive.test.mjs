import test from 'node:test';
import assert from 'node:assert/strict';
import { unpackAdaptive, requiresKey } from '../src/rgbAdaptivePreview.js';
function wire(meta,data=new Uint8Array([1])){const h=new TextEncoder().encode(JSON.stringify(meta)),b=new Uint8Array(4+h.length+data.length);new DataView(b.buffer).setUint32(0,h.length);b.set(h,4);b.set(data,4+h.length);return b.buffer;}
const frame={status:200,session:'s',token:'t',epoch:1,sequence:1,codec:'h264',key:true,age_ms:10};
test('adaptive binary envelope validates identity and age',()=>{assert.equal(unpackAdaptive(wire(frame)).meta.sequence,1);for(const m of [{...frame,age_ms:-1},{...frame,sequence:null},{...frame,codec:'vp8'}])assert.throws(()=>unpackAdaptive(wire(m)));assert.throws(()=>unpackAdaptive(new ArrayBuffer(3)));});
test('H264 reference gaps and epochs require keyframe',()=>{assert.equal(requiresKey(null,frame),true);assert.equal(requiresKey(frame,{...frame,sequence:2}),false);assert.equal(requiresKey(frame,{...frame,sequence:3}),true);assert.equal(requiresKey(frame,{...frame,sequence:2,epoch:2}),true);assert.equal(requiresKey(frame,{...frame,sequence:2,session:'restart'}),true);});
