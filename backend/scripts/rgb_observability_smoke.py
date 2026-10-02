"""Loopback-only functional fixture. No ROS imports, hardware or performance claims.

python -m scripts.rgb_observability_smoke --port 8891
"""
import argparse
import time
from contextlib import asynccontextmanager

import cv2
import numpy as np
import uvicorn
from fastapi import FastAPI, Response

from app import stream_observability as obs
from app.stores import MediaStore


@asynccontextmanager
async def lifespan(_app):
    yield
    obs.diagnostics.close()


app = FastAPI(lifespan=lifespan)
obs.diagnostics = obs.StreamDiagnostics(persist=False)
app.include_router(obs.router)
store = MediaStore()
frozen = False
missing = False
image = np.full((120, 160, 3), (100, 140, 200), dtype=np.uint8)
_, encoded = cv2.imencode(".jpg", image)


@app.get("/api/v1/media/rgb")
def image_response():
    if missing:
        return Response(status_code=503)
    if not frozen or store.get("rgb") is None:
        store.update("rgb", encoded.tobytes(), "image/jpeg", width=160, height=120,
                     source="fixture:no-hardware", metadata={"received_monotonic": time.monotonic()})
    item = store.get("rgb")
    return Response(item["content"], media_type="image/jpeg", headers={"Cache-Control": "no-store", **obs.frame_header(item)})


@app.post("/api/fixture/{mode}")
def state(mode: str):
    global frozen, missing
    frozen, missing = mode == "freeze", mode == "missing"
    return {"fixture_only": True, "frozen": frozen, "missing": missing}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8891)
    args = parser.parse_args()
    uvicorn.run(app, host="127.0.0.1", port=args.port)
