"""Bounded, non-control-plane RGB diagnostics. No images or arbitrary log text."""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import queue
import threading
import time
from collections import OrderedDict
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

HEADER = "X-HazardGuard-Frame"
HISTOGRAM_BOUNDS_MS = [50, 100, 200, 300, 500, 750, 1000, 1500, 2000, 3000, 5000, 10000, 30000, 60000]


def diagnostics_mode() -> str:
    value = os.getenv("HAZARD_GUARD_STREAM_DIAGNOSTICS", "basic")
    return value if value in {"off", "basic", "detailed"} else "basic"


def rgb_receive_metadata(message) -> dict:
    if diagnostics_mode() == "off":
        return {}
    stamp = getattr(getattr(message, "header", None), "stamp", None)
    ros_ms = None
    try:
        sec, nano = int(stamp.sec), int(stamp.nanosec)
        value = sec * 1000 + nano / 1_000_000
        if sec >= 0 and 0 <= nano < 1_000_000_000 and 0 < value < 1e15:
            ros_ms = value
    except (AttributeError, ValueError, TypeError, OverflowError):
        pass
    return {
        "received_monotonic": time.monotonic(),
        "received_unix_ms": time.time() * 1000,
        "ros_stamp_ms": ros_ms,
        # Explicit operator assertion, NEVER inferred just from epoch magnitude.
        "stamp_clock_verified": os.getenv("HAZARD_GUARD_RGB_STAMP_CLOCK") == "unix_verified",
    }


def frame_header(item: dict) -> dict[str, str]:
    mode = diagnostics_mode()
    if mode == "off":
        return {}
    meta = item.get("metadata", {})
    received = meta.get("received_monotonic", item["updated_monotonic"])
    age = max(0.0, (time.monotonic() - received) * 1000)
    reference = "ingress" if "received_monotonic" in meta else "cache"
    ros_ms = meta.get("ros_stamp_ms")
    capture_age = None
    if meta.get("stamp_clock_verified") and ros_ms is not None:
        # Project the capture→ingress interval with a monotonic clock thereafter.
        capture_to_ingress = meta["received_unix_ms"] - ros_ms
        if math.isfinite(capture_to_ingress) and 0 <= capture_to_ingress <= 86_400_000:
            capture_age = age + capture_to_ingress
    payload = {
        "v": 1, "s": item["stream_session"], "n": item["frame_sequence"],
        "age_ms": round(age, 3), "reference": reference,
        "ros_ms": ros_ms,
        "capture_age_ms": round(capture_age, 3) if capture_age is not None else None,
        "mode": mode,
    }
    return {HEADER: json.dumps(payload, separators=(",", ":"), allow_nan=False)}


NonNegative = Annotated[float, Field(ge=0, le=1e12, allow_inf_nan=False)]
Count = Annotated[int, Field(strict=True, ge=0, le=1_000_000)]
Identity = Annotated[str, Field(pattern=r"^[a-f0-9-]{16,48}$")]


class WindowStats(BaseModel):
    model_config = ConfigDict(extra="forbid")
    samples: Count
    mean_ms: NonNegative | None
    p95_ms: NonNegative | None
    max_ms: NonNegative | None
    histogram: list[Count] = Field(min_length=15, max_length=15)

    @model_validator(mode="after")
    def consistent(self):
        if sum(self.histogram) != self.samples:
            raise ValueError("histogram count mismatch")
        values = [self.mean_ms, self.p95_ms, self.max_ms]
        if (self.samples == 0 and any(v is not None for v in values)) or (
            self.samples > 0 and any(v is None for v in values)
        ):
            raise ValueError("empty and measured values must be distinguished")
        if self.samples and (self.mean_ms > self.max_ms or self.p95_ms > self.max_ms):
            raise ValueError("invalid maximum")
        return self


class BrowserReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_id: Identity
    session_id: Identity | None
    sequence: Annotated[int, Field(strict=True, ge=1, le=9_000_000_000_000_000)]
    reference: Literal["ingress", "capture", "cache", "unavailable", "mixed"]
    window_ms: Annotated[float, Field(gt=0, le=600_000, allow_inf_nan=False)]
    observed_ms: NonNegative
    missing_ms: NonNegative
    stale_ms: NonNegative
    hidden_ms: NonNegative
    unobserved_ms: NonNegative
    max_gap_ms: NonNegative
    uncertainty_max_ms: NonNegative
    frames_loaded: Count
    unique_frames: Count
    request_errors: Count
    report_errors: Count
    metadata_errors: Count
    age: WindowStats
    detail_age_ms: list[NonNegative | None] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def durations(self):
        if self.observed_ms + self.hidden_ms + self.unobserved_ms > self.window_ms + 2:
            raise ValueError("window duration mismatch")
        if self.missing_ms + self.stale_ms > self.observed_ms + 2:
            raise ValueError("invalid unavailable duration")
        if self.unique_frames > self.frames_loaded:
            raise ValueError("invalid unique frame count")
        return self


class StreamDiagnostics:
    """In-memory cap + drop-on-full asynchronous rotating writer."""

    def __init__(self, *, persist=True, log_dir=None, clock=time.monotonic, max_clients=64):
        self.clock = clock
        self.max_clients = max_clients
        self.persist = persist
        self.log_dir = Path(log_dir) if log_dir else Path(__file__).resolve().parents[1] / "runtime" / "stream-observability"
        self.clients = OrderedDict()
        self.lock = threading.Lock()
        self.pending = queue.Queue(maxsize=128)
        self.stopped = threading.Event()
        self.worker = None
        self.dropped_logs = 0
        self.write_errors = 0

    def accept(self, report: BrowserReport) -> bool:
        now = self.clock()
        record = report.model_dump()
        if diagnostics_mode() != "detailed":
            record["detail_age_ms"] = []
        record["received_unix_ms"] = round(time.time() * 1000)
        with self.lock:
            for key in [k for k, v in self.clients.items() if now - v["seen"] > 300]:
                del self.clients[key]
            old = self.clients.get(report.client_id)
            if old and (now - old["seen"] < 4 or report.sequence <= old["record"]["sequence"]):
                return False
            if not old and len(self.clients) >= self.max_clients:
                return False
            record["window_state"] = (
                "unobserved" if report.observed_ms == 0 else
                "missing" if report.missing_ms > 0 else
                "stale" if report.stale_ms > 0 else
                "request_error" if report.request_errors > 0 else "fresh"
            )
            record["state_changed"] = old is None or old["record"]["window_state"] != record["window_state"]
            self.clients[report.client_id] = {"seen": now, "record": record}
            if self.persist and not self.stopped.is_set():
                try:
                    self.pending.put_nowait(record)
                except queue.Full:
                    self.dropped_logs += 1
                if self.worker is None:
                    self.worker = threading.Thread(target=self._write_loop, daemon=True, name="rgb-diagnostics")
                    self.worker.start()
        return True

    def _write_loop(self):
        handler = None
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(self.log_dir / "windows.jsonl", maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(message)s"))
            # logging's default handler suppresses IO exceptions; make failures observable.
            def on_error(_record):
                with self.lock:
                    self.write_errors += 1
            handler.handleError = on_error
            while not self.stopped.is_set():
                try:
                    record = self.pending.get(timeout=0.2)
                except queue.Empty:
                    continue
                handler.emit(logging.LogRecord("rgb", logging.INFO, "", 0, json.dumps(record, allow_nan=False), (), None))
        except Exception:
            with self.lock:
                self.write_errors += 1
        finally:
            if handler:
                handler.close()

    def snapshot(self):
        now = self.clock()
        with self.lock:
            return {
                "mode": diagnostics_mode(), "measurement": "browser_self_reported_display_proxy",
                "histogram_bounds_ms": HISTOGRAM_BOUNDS_MS,
                "clients": [
                    {**entry["record"], "report_age_ms": round((now - entry["seen"]) * 1000),
                     "report_state": "reporting" if now - entry["seen"] <= 15 else "report_missing"}
                    for entry in self.clients.values() if now - entry["seen"] <= 300
                ],
                "dropped_logs": self.dropped_logs, "write_errors": self.write_errors,
                "queue_size": self.pending.qsize(), "max_clients": self.max_clients,
            }

    def close(self):
        self.stopped.set()
        if self.worker:
            self.worker.join(timeout=1)


diagnostics = StreamDiagnostics(persist=os.getenv("HAZARD_GUARD_STREAM_LOG_PERSIST", "1") == "1", log_dir=os.getenv("HAZARD_GUARD_STREAM_LOG_DIR"))
router = APIRouter(prefix="/api/v1/stream-observability")


@router.get("")
def stream_status():
    return diagnostics.snapshot()


@router.post("/reports", status_code=202)
async def stream_report(request: Request):
    if diagnostics_mode() == "off":
        raise HTTPException(404, "Stream diagnostics disabled")
    # Bound the body before Pydantic/JSON allocation. Never echo client content.
    async def read_report():
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > 8192:
                raise HTTPException(413, "Report too large")
            body.extend(chunk)
        return body
    try:
        body = await asyncio.wait_for(read_report(), timeout=2)
        report = BrowserReport.model_validate_json(body)
    except asyncio.TimeoutError:
        raise HTTPException(408, "Report timeout") from None
    except ValidationError:
        raise HTTPException(422, "Invalid stream report") from None
    if not diagnostics.accept(report):
        raise HTTPException(429, "Report rate or client limit exceeded")
    return {"accepted": True}
