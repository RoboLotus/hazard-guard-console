"""Stationary experimental JPEG/WS vs preencoded H264/VP8 WebRTC, no control API.

Video encoding is shared once, RTP packetization/encryption per viewer. Fixed
codec settings: RTCP REMB does NOT adapt the shared encoder. Not production.
"""
import asyncio, collections, contextlib, json, os, sys, threading, time
from pathlib import Path
from contextlib import asynccontextmanager
import cv2
from fastapi import HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription, RTCRtpSender, MediaStreamTrack
from aiortc.mediastreams import MediaStreamError
import rgb_pipeline_benchmark as base
from rgb_codec_core import Encoder, PROFILES, packet, mark

raw = None
seq = 0
current_profile = 'jpeg82'
current = None
history = collections.deque(maxlen=3000)
tracks = set()
peers = set()
worker_error = None
encoder = None

def callback(msg):
    global raw
    now=time.monotonic()
    raw=(msg,now)
    base.latest,base.last_rgb=msg,now
    with base.lock: base.counts['rgb_received']+=1

base.rgb_callback=callback

def encode_one(msg, received):
    global seq
    seq+=1
    t=time.monotonic()
    f=base.CvBridge().imgmsg_to_cv2(msg,desired_encoding='bgr8')
    f=mark(f,seq)
    cv_ms=(time.monotonic()-t)*1000
    start=time.monotonic()
    force=getattr(app.state,'force_key',False)
    app.state.force_key=False
    data,key=encoder.encode(f,seq,force_key=force)
    done=time.monotonic()
    with base.lock:
        base.counts['codec_encode']+=1; base.counts['encoded_bytes']+=len(data)
        base.timings['codec_encode_ms'].append((done-start)*1000)
        base.timings['codec_convert_ms'].append(cv_ms)
    return {'seq':seq,'received':received,'encoded':done,'key':key,'data':data}

async def encode_loop():
    global current,worker_error
    last=0
    while True:
        started=time.monotonic()
        item=raw
        if item and item[1]!=last and started-item[1]<2:
            last=item[1]
            try:
                result=await asyncio.to_thread(encode_one,*item)
                current=result
                history.append({k:v for k,v in result.items() if k!='data'})
                for track in list(tracks): track.push(result)
            except Exception as e:
                worker_error=repr(e); base.errors.append(worker_error)
                return
        await asyncio.sleep(max(.001,.1-(time.monotonic()-started)))

class PacketTrack(MediaStreamTrack):
    kind='video'
    def __init__(self):
        super().__init__(); self.q=asyncio.Queue(maxsize=2); self.need_key=True
        tracks.add(self)
    def push(self,result):
        if self.readyState!='live': return
        if self.q.full():
            while not self.q.empty(): self.q.get_nowait()
            self.need_key=True
            base.counts['receiver_queue_reset']+=1
        if self.need_key and not result['key']: return
        self.need_key=False; self.q.put_nowait(result)
    async def recv(self):
        if self.readyState!='live': raise MediaStreamError
        result=await self.q.get()
        return packet(result['data'],result['seq'])
    def stop(self):
        tracks.discard(self); super().stop()

original_lifespan=base.lifespan
@asynccontextmanager
async def lifespan(app):
    global encoder
    encoder=Encoder(current_profile)
    async with original_lifespan(app):
        task=asyncio.create_task(encode_loop())
        try: yield
        finally:
            await asyncio.gather(*(p.close() for p in list(peers)))
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError): await task

app=base.app
app.router.lifespan_context=lifespan

class Profile(BaseModel):
    name:str=Field(pattern='^('+'|'.join(PROFILES)+')$')

@app.post('/api/codec/profile')
async def profile(spec:Profile):
    global encoder,current_profile,current
    if base.phase['state'] in ('warming','measuring') or peers:
        raise HTTPException(409,'phase/peers active')
    raise HTTPException(409,'Restart experiment server to change codec; fixed profile per process')

class Offer(BaseModel):
    sdp:str=Field(max_length=65536)
    type:str=Field(pattern='^offer$')

@app.post('/api/codec/offer')
async def offer(spec:Offer):
    if current_profile=='jpeg82': raise HTTPException(409,'JPEG profile')
    if len(peers)>=12: raise HTTPException(429,'12-view cap')
    pc=RTCPeerConnection(RTCConfiguration(iceServers=[])); peers.add(pc)
    @pc.on('connectionstatechange')
    async def changed():
        if pc.connectionState in ('failed','closed'):
            await pc.close(); peers.discard(pc)
    track=PacketTrack(); transceiver=pc.addTransceiver(track,direction='sendonly'); sender=transceiver.sender
    codec=PROFILES[current_profile]['codec']
    caps=[c for c in RTCRtpSender.getCapabilities('video').codecs if c.mimeType.lower()=='video/'+codec]
    if not caps: raise HTTPException(400,'Server codec unavailable')
    transceiver.setCodecPreferences(caps)
    await pc.setRemoteDescription(RTCSessionDescription(spec.sdp,spec.type))
    # PLI/FIR requests a new shared keyframe. Fixed bitrate still deliberate.
    original=sender._send_keyframe
    def force():
        global seq
        # Marking next frame through a shared flag avoids touching encoder from RTP task.
        app.state.force_key=True
        original()
    sender._send_keyframe=force
    await pc.setLocalDescription(await pc.createAnswer())
    return {'sdp':pc.localDescription.sdp,'type':pc.localDescription.type,'profile':current_profile}

@app.post('/api/codec/close')
async def close():
    await asyncio.gather(*(p.close() for p in list(peers)))
    peers.clear(); return {'closed':True}

@app.get('/api/codec/clock')
async def clock(): return {'monotonic_ms':time.monotonic()*1000}

@app.get('/api/codec/history')
async def get_history():
    return {'profile':current_profile,'frames':list(history),'worker_error':worker_error}

@app.websocket('/ws/codec/jpeg')
async def jpeg(ws:WebSocket):
    if current_profile!='jpeg82' or ws.headers.get('origin')!='http://127.0.0.1:8767':
        await ws.close(1008); return
    await ws.accept()
    try:
        while True:
            value=await asyncio.wait_for(ws.receive_json(),5)
            after=value.get('after')
            if type(after)!=int or not 0<=after<2**24: raise ValueError('invalid cursor')
            end=time.monotonic()+2
            while (not current or current['seq']<=after) and time.monotonic()<end: await asyncio.sleep(.005)
            item=current
            if not item or time.monotonic()-item['received']>2: raise TimeoutError('sensor stale')
            await asyncio.wait_for(ws.send_bytes(item['data']),2)
            base.counts['jpeg_sent_bytes']+=len(item['data'])
    except (WebSocketDisconnect,RuntimeError,ValueError,TimeoutError,asyncio.TimeoutError):
        with contextlib.suppress(Exception): await ws.close()

@app.post('/api/codec/client/{label}')
async def client(label:str,body:dict):
    import re
    if not re.fullmatch('[a-zA-Z0-9_-]{1,64}',label): raise HTTPException(400)
    if len(json.dumps(body))>5000000: raise HTTPException(413)
    directory=base.output.parent/'clients'; directory.mkdir(exist_ok=True)
    p=directory/(label+'.json')
    if p.exists(): raise HTTPException(409)
    p.write_text(json.dumps(body)); return {'saved':True}

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(); p.add_argument('--profile',choices=PROFILES,required=True); p.add_argument('--output',required=True)
    args=p.parse_args(); current_profile=args.profile
    base.output=Path(args.output); base.output.mkdir(parents=True,exist_ok=True)
    base.uvicorn.run(app,host='100.107.60.123',port=8001,access_log=False,ws_per_message_deflate=False,ws_max_size=1024,ws_max_queue=1)
