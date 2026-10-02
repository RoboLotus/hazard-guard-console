"""Opt-in stationary RGB-only benchmark. Never imports the robot bridge/main app.

Run on a disposable directory with ROS_DOMAIN_ID=162 ROS_LOCALHOST_ONLY=1.
Uses the actual RosMediaAdapter RGB conversion; synthetic thermal explicitly omitted.
The experiment control API cannot invoke robot actions or arbitrary shell commands.
"""
import argparse
import asyncio
import collections
import json
import hashlib
import math
import os
from pathlib import Path
import re
import statistics
import subprocess
import threading
import time
from contextlib import asynccontextmanager

import cv2
import psutil
import rclpy
from cv_bridge import CvBridge
from fastapi import FastAPI, HTTPException, Response, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from rclpy.qos import qos_profile_sensor_data
from rclpy.signals import SignalHandlerOptions
from sensor_msgs.msg import Image
import uvicorn

from app import stream_observability as obs
from app.ros_media import RosMediaAdapter
from app.stores import MediaStore, SpatialStore
from rgb_encode_gate import EncodeGate
from rgb_frame_signal import FrameSignal
from rgb_ws_transport import serve_latest

lock = threading.RLock()
counts = collections.Counter()
timings = collections.defaultdict(lambda: collections.deque(maxlen=20000))
errors = collections.deque(maxlen=20)
reports = collections.deque(maxlen=3000)
tg_lines = collections.deque(maxlen=3000)
phase = {"state": "idle"}
latest = None
last_rgb = 0.0
encode_gate = EncodeGate()
frame_signal = None
output = None
store = MediaStore()
adapter = RosMediaAdapter(store, SpatialStore(), lambda e: errors.append(str(e)))
adapter.configure(cv_bridge=CvBridge(), tf_buffer=None, ros_time_type=None)
adapter._thermal_stream_seen = True  # Scope exclusion, NOT an optimization result.


def stats(values):
    xs = sorted(values)
    return {"n": len(xs), "mean": statistics.mean(xs), "median": statistics.median(xs),
            "p95": xs[math.ceil(.95 * len(xs)) - 1], "max": xs[-1]} if xs else None


def timed(owner, name, key):
    original = getattr(owner, name)
    def wrapped(*a, **kw):
        start = time.monotonic()
        result = original(*a, **kw)
        with lock:
            counts[key] += 1
            timings[key + "_ms"].append((time.monotonic() - start) * 1000)
        return result
    setattr(owner, name, wrapped)


timed(CvBridge, "imgmsg_to_cv2", "cv_bridge")
timed(cv2, "imencode", "jpeg_encode")
original_accept = obs.diagnostics.accept
def capture_report(report):
    accepted = original_accept(report)
    if accepted:
        with lock:
            reports.append({**report.model_dump(), "server_received_monotonic": time.monotonic()})
    return accepted
obs.diagnostics.accept = capture_report


def rgb_callback(msg):
    global latest, last_rgb
    latest = msg
    last_rgb = time.monotonic()
    start = last_rgb
    with lock:
        counts["rgb_received"] += 1
        allowed = phase.get("encoding", "ingress") != "periodic" or encode_gate.allow(start, phase.get("target_fps", 10))
        if not allowed:
            counts["display_encode_skipped"] += 1
    if allowed:
        # Preserve the historical ingress-vs-periodic experimental baseline.
        # Production on_rgb_image now queues a bounded asynchronous display job.
        adapter._encode_rgb_image(msg, obs.rgb_receive_metadata(msg))
        if frame_signal is not None:
            frame_signal.notify()
    with lock:
        timings["callback_ms"].append((time.monotonic() - start) * 1000)


@asynccontextmanager
async def lifespan(_):
    global frame_signal
    if os.getenv("ROS_DOMAIN_ID") != "162" or os.getenv("ROS_LOCALHOST_ONLY") != "1":
        raise RuntimeError("Isolated domain 162 and localhost-only required")
    rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
    frame_signal = FrameSignal()
    node = rclpy.create_node("rgb_stationary_benchmark")
    node.create_subscription(Image, "/ascamera_hp60c/camera_publisher/rgb0/image", rgb_callback, qos_profile_sensor_data)
    thread = threading.Thread(target=rclpy.spin, args=(node,), daemon=True)
    thread.start()
    tg = subprocess.Popen(["tegrastats", "--interval", "1000"], stdout=subprocess.PIPE, text=True)
    def read_tg():
        for line in tg.stdout:
            tg_lines.append({"at": time.monotonic(), "text": line.strip()})
    threading.Thread(target=read_tg, daemon=True).start()
    try:
        yield
    finally:
        tg.terminate()
        tg.wait(timeout=5)
        obs.diagnostics.close()
        # SIGINT may already have shut down the ROS context before ASGI cleanup.
        rclpy.try_shutdown()
        thread.join(timeout=3)
        node.destroy_node()


app = FastAPI(lifespan=lifespan)
# Experiment-only: a second loopback proxy separates browser HTTP connection pools.
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:8767"],
                   allow_methods=["GET"], expose_headers=["X-HazardGuard-Frame", "Server-Timing"])
app.include_router(obs.router)


@app.middleware("http")
async def count_requests(request, call_next):
    response = await call_next(request)
    if request.url.path == "/api/v1/stream-observability/reports":
        with lock:
            counts["report_requests"] += 1
            counts["report_body_bytes"] += int(request.headers.get("content-length", 0))
    return response


def cached_image(item=None, request_start=None, transport="http"):
    item = item or store.get("rgb")
    if not item or time.monotonic() - item["updated_monotonic"] > 5:
        with lock:
            counts["http_503"] += 1
        return Response(status_code=503)
    before_age_ms = max(0, (time.monotonic()-request_start)*1000) if request_start is not None else 0
    headers = obs.frame_header(item)
    headers["X-Bench-Before-Age-Ms"] = str(before_age_ms)
    with lock:
        counts[transport + "_200"] += 1
        counts["jpeg_payload_bytes"] += len(item["content"])
        counts["metadata_header_bytes"] += sum(len(k) + len(v) + 4 for k, v in headers.items())
    return Response(item["content"], media_type="image/jpeg", headers={"Cache-Control": "no-store", **headers})


@app.get("/api/v1/media/rgb")
async def image(after: int = Query(default=0, ge=0), session: str = Query(default="", pattern=r"^([a-f0-9]{32})?$"), delivery: str = Query(default="poll", pattern="^(poll|new-frame)$")):
    return await frame_response(after, session, delivery)


async def frame_response(after, session, delivery, transport="http"):
    start = time.monotonic()
    wait_ms = 0.0
    if delivery == "new-frame":
        wait_start = time.monotonic()
        item = await frame_signal.newer(lambda: store.get("rgb"), session, after)
        wait_ms = (time.monotonic() - wait_start) * 1000
        if item is None:
            with lock:
                counts["new_frame_timeout"] += 1
            response = Response(status_code=503, headers={"Cache-Control": "no-store"})
        else:
            response = cached_image(item, start, transport)
    else:
        response = cached_image(request_start=start, transport=transport)
    handler_ms = (time.monotonic() - start) * 1000
    before_age_ms = response.headers.get("X-Bench-Before-Age-Ms", "0")
    if "X-Bench-Before-Age-Ms" in response.headers:
        del response.headers["X-Bench-Before-Age-Ms"]
    response.headers["Server-Timing"] = f"handler;dur={handler_ms:.3f}, wait;dur={wait_ms:.3f}, active;dur={max(0, handler_ms-wait_ms):.3f}, beforeage;dur={before_age_ms}"
    with lock:
        timings["handler_ms"].append(handler_ms)
        timings["new_frame_wait_ms"].append(wait_ms)
        timings["handler_active_ms"].append(max(0, handler_ms-wait_ms))
    return response


@app.websocket("/ws/bench/rgb")
async def rgb_socket(ws: WebSocket):
    if ws.headers.get("origin") != "http://127.0.0.1:8767":
        await ws.close(code=1008)
        return
    await ws.accept()
    with lock:
        counts["ws_connections"] += 1
    try:
        await serve_latest(ws, lambda session, after: frame_response(after, session, "new-frame", "ws"))
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        with lock:
            counts["ws_closed"] += 1


@app.get("/api/bench/reference.png")
def reference():
    msg = latest
    if msg is None or time.monotonic() - last_rgb > 5:
        raise HTTPException(503, "Camera unavailable")
    frame = CvBridge().imgmsg_to_cv2(msg, desired_encoding="bgr8")
    return Response(cv2.imencode(".png", frame)[1].tobytes(), media_type="image/png")


class Phase(BaseModel):
    label: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    mode: str = Field(pattern="^(off|basic)$")
    views: int = Field(ge=0, le=12)
    warmup: int = Field(default=15, ge=5, le=60)
    seconds: int = Field(default=60, ge=10, le=180)
    target_fps: float = Field(default=1000/300, ge=1, le=30)
    encoding: str = Field(default="ingress", pattern="^(ingress|periodic)$")
    delivery: str = Field(default="poll", pattern="^(poll|new-frame|websocket)$")


class ClientTiming(BaseModel):
    label: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    # Each row: elapsed headers, body, decode-to-rAF; successful frames only.
    rows: list[tuple[float, float, float]] = Field(max_length=25000)
    elapsed_ms: float = Field(ge=0, le=300000, allow_inf_nan=False)
    errors: int = Field(ge=0, le=100000)
    overflow: int = Field(ge=0, le=100000)
    hidden: bool
    server_rows: list[tuple[float, float, float]] = Field(default_factory=list, max_length=25000)
    # view index, relative time, lower/upper ingress age, legacy upper; every100ms.
    freshness: list[tuple[int, float, float, float, float]] = Field(default_factory=list, max_length=25000)
    frame_events: list[tuple[int, float]] = Field(default_factory=list, max_length=25000)
    freshness_missing: int = Field(default=0, ge=0)
    freshness_unobserved: int = Field(default=0, ge=0)
    injection_ms: float | None = Field(default=None, ge=0, le=55000, allow_inf_nan=False)


@app.post("/api/bench/client-timings")
def client_timings(spec: ClientTiming):
    with lock:
        if phase.get("label") != spec.label or phase.get("state") != "done":
            raise HTTPException(409, "Timing upload requires completed current phase")
    if any(not math.isfinite(x) or x < 0 or x > 300000 for row in [*spec.rows, *spec.server_rows, *spec.freshness, *spec.frame_events] for x in row):
        raise HTTPException(422, "Invalid timing value")
    directory = output.parent / "client-timings"
    directory.mkdir(exist_ok=True)
    path = directory / (spec.label + ".json")
    try:
        with path.open("x", encoding="utf-8") as file:
            json.dump(spec.model_dump(), file)
    except FileExistsError:
        raise HTTPException(409, "Timing already saved")
    return {"saved": True, "rows": len(spec.rows)}


@app.get("/api/bench/snapshot")
def snapshot(label: str = Query(pattern=r"^[a-zA-Z0-9_-]{1,64}$")):
    # Capture the already encoded JPEG, never a resized screenshot/re-encode.
    # Warmup only, so this extra HTTP request does not affect the measured phase.
    with lock:
        if phase.get("state") != "warming" or phase.get("label") != label:
            raise HTTPException(409, "Snapshot allowed only for the current warmup")
        spec = dict(phase)
    response = cached_image()
    if response.status_code != 200:
        raise HTTPException(503, "No fresh JPEG")
    directory = output.parent / "frames"
    directory.mkdir(exist_ok=True)
    path = directory / (label + ".jpg")
    if path.exists():
        raise HTTPException(409, "Snapshot already saved")
    with path.open("xb") as file:
        file.write(response.body)
    meta = {"phase": spec, "saved_unix": time.time(), "codec": "JPEG", "quality": 82,
            "width": latest.width, "height": latest.height, "bytes": len(response.body),
            "sha256": hashlib.sha256(response.body).hexdigest(),
            "frame_header": response.headers.get("X-HazardGuard-Frame"),
            "scope": "Exact encoded JPEG returned by the web media path; single static frame, not a motion-quality score"}
    (directory / (label + ".json")).write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return response


def sample(spec):
    global phase
    try:
        time.sleep(spec.warmup)
        tracked = {}
        for p in psutil.process_iter(["pid", "name"]):
            try:
                p.cpu_percent()
                tracked[p.pid] = (p, p.info["name"])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        psutil.cpu_percent(percpu=True)
        begin = time.monotonic()
        rows = []
        with lock:
            counts.clear(); timings.clear(); reports.clear(); errors.clear()
            phase = {**phase, "state": "measuring", "started_unix": time.time()}
        aborted = None
        for i in range(spec.seconds):
            time.sleep(max(0, begin + i + 1 - time.monotonic()))
            cores = psutil.cpu_percent(percpu=True)
            vm = psutil.virtual_memory()
            processes = []
            for pid, (p, name) in tracked.items():
                try:
                    with p.oneshot():
                        cpu, rss = p.cpu_percent(), p.memory_info().rss / 1048576
                    if cpu or pid == os.getpid() or "ascamera" in name:
                        processes.append({"pid": pid, "name": name, "cpu_one_core_100": cpu, "rss_mib": rss})
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            row = {"t": time.monotonic() - begin, "cores_pct": cores, "cpu_total_pct": statistics.mean(cores),
                   "ram_mib": vm.used / 1048576, "available_mib": vm.available / 1048576,
                   "swap_mib": psutil.swap_memory().used / 1048576, "rgb_age_sec": time.monotonic() - last_rgb,
                   "processes": processes}
            rows.append(row)
            thermal = tg_lines[-1]["text"] if tg_lines else ""
            cpu_temp = re.search(r"cpu@([\d.]+)C", thermal)
            if row["rgb_age_sec"] > 5 or vm.available < 500 * 1048576 or (cpu_temp and float(cpu_temp[1]) >= 85):
                aborted = "sensor_stale_or_resource_guard"
                break
        end = time.monotonic()
        with lock:
            result = {"spec": spec.model_dump(), "started_unix": phase["started_unix"], "elapsed_sec": end - begin,
                      "begin_monotonic": begin, "end_monotonic": end,
                      "pid": os.getpid(), "aborted": aborted, "counts": dict(counts),
                      "timings": {k: stats(v) for k, v in timings.items()}, "errors": list(errors),
                      "samples": rows, "reports": list(reports), "tegrastats": [x for x in tg_lines if begin <= x["at"] <= end],
                      "scope": "RGB-only RosMediaAdapter + FastAPI; no synthetic thermal, no main/bridge; one browser multi-view",
                      "dimensions": {"width": latest.width, "height": latest.height, "encoding": latest.encoding} if latest else None}
        (output / (spec.label + ".json")).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        with lock:
            phase = {**phase, "state": "aborted" if aborted else "done", "file": spec.label + ".json", "reason": aborted}
    except Exception as exc:
        with lock:
            phase = {**phase, "state": "error", "reason": str(exc)}


@app.post("/api/bench/phase")
def start_phase(spec: Phase):
    global phase
    with lock:
        if phase["state"] in {"warming", "measuring"}:
            raise HTTPException(409, "Phase running")
        if (output / (spec.label + ".json")).exists():
            raise HTTPException(409, "Result already exists; choose a new label")
        os.environ["HAZARD_GUARD_STREAM_DIAGNOSTICS"] = spec.mode
        encode_gate.reset()
        phase = {"state": "warming", **spec.model_dump()}
        threading.Thread(target=sample, args=(spec,), daemon=True).start()
        return phase


@app.get("/api/bench/status")
def status():
    with lock:
        return {"phase": dict(phase), "rgb_age_sec": time.monotonic() - last_rgb,
                "rgb_count": counts["rgb_received"], "errors": list(errors), "pid": os.getpid()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    uvicorn.run(app, host=args.host, port=args.port, access_log=False,
                ws_per_message_deflate=False, ws_max_size=1024, ws_max_queue=1)
