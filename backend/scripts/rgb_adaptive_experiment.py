"""Isolated RGB experiment. No control publishers, production app or device startup."""
import argparse
import asyncio
from contextlib import asynccontextmanager
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import threading
import time

import numpy as np
import psutil
from fastapi import FastAPI, WebSocket
import uvicorn

from app.rgb_adaptive import AdaptiveRgbSession
from app.rgb_adaptive_transport import AdaptiveHub


def create_app(mode="auto", source="synthetic", path=None, topic="/camera/color/image_raw",
               origins=("http://127.0.0.1:5173", "http://localhost:5173"), output=None):
    convert = lambda frame: frame
    if source == "ros":
        from cv_bridge import CvBridge
        bridge = CvBridge()
        convert = lambda frame: bridge.imgmsg_to_cv2(frame, desired_encoding="bgr8")
    session = AdaptiveRgbSession(mode=mode, converter=convert)
    hub = AdaptiveHub(session, origins)
    stop = threading.Event()
    source_error = {"error": None, "received": 0}
    logger = logging.getLogger("rgb-adaptive-" + session.session)
    logger.propagate = False
    logger.setLevel(logging.INFO)
    handler = None
    if output:
        folder = Path(output)
        folder.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(folder / "samples.jsonl", maxBytes=4_000_000,
                                      backupCount=2, encoding="utf-8")
        logger.addHandler(handler)

    def offer(frame):
        source_error["received"] += 1
        session.submit(frame)

    def feed():
        try:
            if source == "ros":
                import rclpy
                from rclpy.qos import qos_profile_sensor_data
                from sensor_msgs.msg import Image
                context = rclpy.context.Context()
                rclpy.init(context=context)
                node = rclpy.create_node("rgb_adaptive_readonly", context=context)
                executor = rclpy.executors.SingleThreadedExecutor(context=context)
                executor.add_node(node)
                node.create_subscription(Image, topic, offer, qos_profile_sensor_data)
                try:
                    while not stop.is_set():
                        executor.spin_once(timeout_sec=.1)
                finally:
                    executor.shutdown()
                    node.destroy_node()
                    rclpy.shutdown(context=context)
                return
            images = None
            if source == "npy":
                images = np.load(path, mmap_mode="r", allow_pickle=False)
                if images.ndim != 4 or images.shape[1:] != (480, 640, 3) or images.dtype != np.uint8 or not len(images):
                    raise ValueError("npy must contain N x 480 x 640 x 3 uint8 BGR frames")
            index = 0
            while not stop.is_set():
                started = time.monotonic()
                if images is None:
                    frame = np.full((480, 640, 3), 180, dtype=np.uint8)
                    x = (index * 11) % 560
                    frame[180:260, x:x + 80] = (20, 40, 220)
                else:
                    frame = images[index % len(images)]
                offer(frame)
                index += 1
                stop.wait(max(0, .05 - (time.monotonic() - started)))
        except Exception as exc:
            source_error["error"] = f"{type(exc).__name__}: {exc}"

    process = psutil.Process()
    async def monitor():
        psutil.cpu_percent()
        process.cpu_percent()
        while True:
            await asyncio.sleep(1)
            session.evaluate(psutil.cpu_percent())
            row = session.snapshot()
            row.update(timestamp=time.time(), source=source, source_status=dict(source_error),
                       process_cpu_one_core_percent=process.cpu_percent(), rss_bytes=process.memory_info().rss,
                       transport_timeouts=hub.timeouts, protocol_errors=hub.protocol_errors)
            # bounded in-memory history + bounded disk, one record/second
            row["windows"] = row["windows"][-1:]
            row["events"] = row["events"][-1:]
            if handler:
                logger.info(json.dumps(row, allow_nan=False))

    @asynccontextmanager
    async def lifespan(app):
        thread = threading.Thread(target=feed, daemon=True, name="rgb-input-readonly")
        thread.start()
        task = asyncio.create_task(monitor())
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            stop.set()
            await asyncio.to_thread(thread.join, 2)
            await asyncio.to_thread(session.close)
            if handler:
                logger.removeHandler(handler)
                handler.close()

    app = FastAPI(lifespan=lifespan)
    app.state.session = session
    app.state.hub = hub

    @app.get("/api/bench/rgb-adaptive/status")
    def status():
        return {**session.snapshot(), "source": source, "source_status": dict(source_error),
                "pid": os.getpid(), "transport_timeouts": hub.timeouts, "protocol_errors": hub.protocol_errors}

    @app.websocket("/ws/bench/rgb-adaptive")
    async def stream(ws: WebSocket):
        await hub.serve(ws)
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["jpeg", "h264", "auto"], default="auto")
    parser.add_argument("--source", choices=["synthetic", "npy", "ros"], default="synthetic")
    parser.add_argument("--path")
    parser.add_argument("--topic", default="/camera/color/image_raw")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8002)
    parser.add_argument("--origin", action="append", default=["http://127.0.0.1:5173", "http://localhost:5173"])
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.source == "npy" and not args.path:
        parser.error("--source npy requires --path")
    uvicorn.run(create_app(args.mode, args.source, args.path, args.topic, args.origin, args.output),
                host=args.host, port=args.port, workers=1, access_log=False,
                ws_per_message_deflate=False, ws_max_size=1024, ws_max_queue=1)
