"""Loopback functional fixture for the production RGB worker/hub. No ROS/control imports."""
import asyncio
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace

import numpy as np
from fastapi import FastAPI, Response, WebSocket
import uvicorn

from app.ros_media import RosMediaAdapter
from app.rgb_stream import RgbSocketHub, fresh_rgb
from app.stores import MediaStore, SpatialStore
from app import stream_observability as obs

store, hub = MediaStore(), RgbSocketHub()
adapter = RosMediaAdapter(store, SpatialStore(), print)
adapter._thermal_stream_seen = True  # No synthetic thermal fixture work.
adapter.configure(cv_bridge=SimpleNamespace(imgmsg_to_cv2=lambda msg, **kw: msg.image), tf_buffer=None, ros_time_type=None)
mode = "live"


@asynccontextmanager
async def lifespan(app):
    async def feed():
        number = 0
        while True:
            if mode == "live":
                image = np.full((480, 640, 3), (80, 140, 200), dtype=np.uint8)
                image[:, number % 600:number % 600 + 40] = (220, 60, 60)
                adapter.on_rgb_image(SimpleNamespace(image=image))
                number += 4
            elif mode == "missing":
                store.clear("rgb")
            await asyncio.sleep(.033)
    task = asyncio.create_task(feed())
    try:
        yield
    finally:
        task.cancel()
        adapter.close()
        obs.diagnostics.close()


app = FastAPI(lifespan=lifespan)
obs.diagnostics = obs.StreamDiagnostics(persist=False)
app.include_router(obs.router)


@app.websocket("/ws/media/rgb")
async def stream(ws: WebSocket):
    await hub.serve(ws, store)


@app.get("/api/v1/media/rgb")
def image():
    item = store.get("rgb")
    if not fresh_rgb(item):
        return Response(status_code=503)
    return Response(item["content"], media_type="image/jpeg", headers={"Cache-Control": "no-store", **obs.frame_header(item)})


@app.get("/api/fixture/status")
def status():
    return {**adapter._rgb_worker.snapshot(), "clients": hub.active, "mode": mode}


@app.post("/api/fixture/{value}")
def change(value: str):
    global mode
    if value in {"live", "freeze", "missing"}:
        mode = value
    return status()


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8891)
