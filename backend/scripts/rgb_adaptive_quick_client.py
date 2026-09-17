"""Short headless transport probe; decode completion is NOT browser presentation."""
import argparse
import asyncio
import json
import math
from pathlib import Path
import time

import av
import cv2
import numpy as np
from websockets.asyncio.client import connect


async def run(args):
    rows, decoder, previous = [], None, None
    started = time.perf_counter()
    status_counts = {"204": 0, "503": 0}
    async with connect(args.url, origin="http://127.0.0.1:5173", max_size=4_000_000,
                       compression=None, max_queue=1) as ws:
        await ws.send(json.dumps({"h264": True}))
        ack = None
        while time.perf_counter() - started < args.warmup + args.seconds:
            if ack and args.ack_delay_ms:
                await asyncio.sleep(args.ack_delay_ms / 1000)
            request_at = time.perf_counter()
            await ws.send(json.dumps({"ack": ack} if ack else {}))
            wire = await asyncio.wait_for(ws.recv(), 3)
            n = int.from_bytes(wire[:4], 'big')
            meta = json.loads(wire[4:4+n])
            ack = None
            if meta['status'] != 200:
                status_counts[str(meta['status'])] += 1
                if meta['status'] == 503:
                    decoder = previous = None
                continue
            data = wire[4+n:]
            t = time.perf_counter()
            if meta['codec'] == 'jpeg':
                image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
                decoder = None
            else:
                identity = (meta['session'], meta['epoch'])
                if decoder is None or previous != identity:
                    assert meta['key'], 'missing recovery keyframe'
                    decoder = av.CodecContext.create('h264', 'r')
                frames = decoder.decode(av.Packet(data))
                assert len(frames) == 1, 'decode delay or missing frame'
                image = frames[0].to_ndarray(format='bgr24')
                previous = identity
            assert image is not None and image.shape == (480, 640, 3)
            finished = time.perf_counter()
            decode_ms = (finished-t)*1000
            ack = {"token": meta['token'], "decode_ms": decode_ms}
            if args.warmup <= finished-started < args.warmup + args.seconds:
                rows.append({"elapsed": finished-started-args.warmup, "epoch": meta['epoch'],
                    "codec": meta['codec'], "sequence": meta['sequence'], "key": meta['key'],
                    "wire_bytes": len(wire), "decode_ms": decode_ms,
                    "ingress_age_upper_ms": meta['age_ms'] + (finished-request_at)*1000})
    def stats(values):
        values = sorted(values)
        return {"mean": sum(values)/len(values), "p95": values[math.ceil(len(values)*.95)-1], "max": values[-1]} if values else None
    folder = Path(args.output)
    folder.mkdir(parents=True, exist_ok=True)
    result = {"scope": "headless desktop decoder; not browser FPS or capture-to-display latency",
        "label": args.label, "warmup_s": args.warmup, "measurement_s": args.seconds,
        "timer": "perf_counter; half-open measurement window",
        "artificial_ack_delay_ms": args.ack_delay_ms,
        "frames": len(rows), "decoded_fps": len(rows)/args.seconds,
        "application_kib_s": sum(r['wire_bytes'] for r in rows)/args.seconds/1024,
        "ingress_age_upper_ms": stats([r['ingress_age_upper_ms'] for r in rows]),
        "decode_ms": stats([r['decode_ms'] for r in rows]), "status_counts_including_warmup": status_counts,
        "profiles_seen": sorted(set(r['codec'] for r in rows)), "rows": rows}
    (folder / 'client.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='rows'}, indent=2), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--url', default='ws://127.0.0.1:8802/ws/bench/rgb-adaptive')
    p.add_argument('--warmup', type=float, default=10)
    p.add_argument('--seconds', type=float, default=30)
    p.add_argument('--ack-delay-ms', type=float, default=0,
                   help='Synthetic feedback pressure, NOT a bandwidth limit')
    p.add_argument('--label', required=True)
    p.add_argument('--output', required=True)
    asyncio.run(run(p.parse_args()))
