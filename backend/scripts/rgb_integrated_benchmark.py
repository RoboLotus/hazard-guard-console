"""Stationary Jetson check of production RGB worker + WS, no main/robot controls."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import time

from fastapi import Response, WebSocket
import uvicorn
import rgb_pipeline_benchmark as base
from app.rgb_stream import RgbSocketHub, fresh_rgb
from app.stream_observability import frame_header

hub = RgbSocketHub()
pause_until = 0.0
original_sample = base.sample


def callback(message):
    base.latest = message
    base.last_rgb = time.monotonic()
    with base.lock:
        base.counts["rgb_received"] += 1
    if time.monotonic() >= pause_until:
        base.adapter.on_rgb_image(message)


base.rgb_callback = callback


def sample(spec):
    original_sample(spec)
    (base.output / (spec.label + ".worker.json")).write_text(json.dumps({
        "worker": base.adapter._rgb_worker.snapshot(), "clients": hub.active,
        "scope": "production RGB worker/hub/preview, sensor-only, synthetic thermal excluded",
    }), encoding="utf-8")


base.sample = sample
app = base.app
# Use the production response/cache rules; retain the existing resource collector.
app.router.routes = [r for r in app.router.routes if getattr(r, "path", "") != "/api/v1/media/rgb"]


@app.get("/api/v1/media/rgb")
def image():
    item = base.store.get("rgb")
    if not fresh_rgb(item):
        return Response(status_code=503)
    return Response(item["content"], media_type="image/jpeg", headers={"Cache-Control": "no-store", **frame_header(item)})


@app.websocket("/ws/media/rgb")
async def stream(ws: WebSocket):
    await hub.serve(ws, base.store)


@app.get("/api/integrated/status")
def status():
    return {"worker": base.adapter._rgb_worker.snapshot(), "clients": hub.active,
            "sensor_age_s": time.monotonic() - base.last_rgb,
            "stream": base.store.status()["rgb"], "pid": os.getpid()}


@app.post("/api/integrated/pause")
def pause():
    # Only suppress this test adapter's input for four seconds; camera untouched.
    global pause_until
    pause_until = time.monotonic() + 4
    return {"scope": "display-input-only", "seconds": 4}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    base.output = Path(args.output)
    base.output.mkdir(parents=True, exist_ok=True)
    try:
        uvicorn.run(app, host="100.107.60.123", port=8001, access_log=False,
                    ws_per_message_deflate=False, ws_max_size=1024, ws_max_queue=1)
    finally:
        base.adapter.close()
