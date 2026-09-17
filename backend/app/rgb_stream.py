"""Display-only bounded RGB work and pull-based JPEG transport."""
from __future__ import annotations

import asyncio
import json
import math
import os
import re
import struct
import threading
import time
from urllib.parse import urlsplit

from fastapi import WebSocketDisconnect
from .stream_observability import frame_header


def display_fps():
    try:
        value = float(os.getenv("HAZARD_GUARD_RGB_DISPLAY_FPS", "10"))
        return value if math.isfinite(value) and 1 <= value <= 30 else 10.0
    except ValueError:
        return 10.0


class LatestRgbWorker:
    """One converting frame + one replaceable raw frame, never a FIFO backlog."""
    def __init__(self, encode, fps=None):
        self.encode = encode
        self.period = 1 / (fps or display_fps())
        self.condition = threading.Condition()
        self.pending = None
        self.stopped = False
        self.thread = None
        self.received = self.replaced = self.processed = self.errors = 0

    def submit(self, message, metadata):
        with self.condition:
            if self.stopped:
                return
            self.received += 1
            if self.pending is not None:
                self.replaced += 1
            self.pending = (message, metadata)
            if self.thread is None:
                self.thread = threading.Thread(target=self._run, daemon=True, name="rgb-preview")
                self.thread.start()
            self.condition.notify()

    def _run(self):
        next_at = 0.0
        while True:
            with self.condition:
                while not self.stopped:
                    delay = next_at - time.monotonic()
                    if self.pending is not None and delay <= 0:
                        break
                    self.condition.wait(max(0.001, delay) if self.pending is not None else None)
                if self.stopped:
                    return
                item, self.pending = self.pending, None
            next_at = time.monotonic() + self.period
            try:
                self.encode(*item)
                self.processed += 1
            except Exception:
                self.errors += 1

    def close(self):
        with self.condition:
            self.stopped = True
            self.pending = None
            self.condition.notify_all()
        if self.thread:
            self.thread.join(timeout=2)

    def snapshot(self):
        with self.condition:
            return {"target_fps": 1 / self.period, "received_frames": self.received,
                    "replaced_pending_frames": self.replaced, "completed_display_jobs": self.processed,
                    "failed_display_jobs": self.errors, "pending_frames": int(self.pending is not None),
                    "worker_alive": bool(self.thread and self.thread.is_alive())}


def fresh_rgb(item, now=None):
    if item is None:
        return False
    received = item.get("metadata", {}).get("received_monotonic", item["updated_monotonic"])
    return 0 <= (time.monotonic() if now is None else now) - received < 2.0


def parse_cursor(text):
    if len(text) > 512:
        raise ValueError("oversized cursor")
    value = json.loads(text)
    if not isinstance(value, dict) or set(value) != {"session", "after"}:
        raise ValueError("invalid cursor")
    if not isinstance(value["session"], str) or not re.fullmatch(r"(?:[a-f0-9]{32})?", value["session"]):
        raise ValueError("invalid session")
    if type(value["after"]) is not int or not 0 <= value["after"] <= 9007199254740991:
        raise ValueError("invalid sequence")
    return value["session"], value["after"]


def origin_allowed(ws):
    origin = ws.headers.get("origin", "")
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    allowed = {"http://localhost:5173", "http://127.0.0.1:5173"}
    allowed.update(x.strip() for x in os.getenv("HAZARD_GUARD_RGB_WS_ORIGINS", "").split(",") if x.strip())
    return origin in allowed or (parsed.scheme in {"http", "https"} and parsed.netloc == ws.headers.get("host"))


class RgbSocketHub:
    """Per-process cap; next frame is selected only on the next display ACK/pull."""
    def __init__(self, limit=16):
        self.active = 0
        self.limit = limit

    async def serve(self, ws, store, on_demand=None):
        if os.getenv("HAZARD_GUARD_RGB_WS", "on") == "off" or not origin_allowed(ws) or self.active >= self.limit:
            await ws.close(code=1008)
            return
        self.active += 1
        try:
            await ws.accept()
            next_at = 0.0
            while True:
                session, after = parse_cursor(await asyncio.wait_for(ws.receive_text(), 10))
                if on_demand:
                    on_demand()
                # Enforce server cadence even if a client ignores the browser's cadence.
                await asyncio.sleep(max(0, next_at - time.monotonic()))
                next_at = time.monotonic() + 1 / display_fps()
                item = store.get("rgb")
                status = 200 if fresh_rgb(item) else 503
                if status == 200 and item["stream_session"] == session and item["frame_sequence"] <= after:
                    status = 204
                headers = frame_header(item) if status == 200 else {}
                meta = {"status": status, "headers": headers}
                if status == 200:
                    meta.update(session=item["stream_session"], sequence=item["frame_sequence"])
                encoded = json.dumps(meta, separators=(",", ":")).encode()
                body = item["content"] if status == 200 else b""
                await asyncio.wait_for(ws.send_bytes(struct.pack("!I", len(encoded)) + encoded + body), 2)
        except (ValueError, asyncio.TimeoutError):
            try:
                await ws.close(code=1008)
            except RuntimeError:
                pass
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            self.active -= 1
