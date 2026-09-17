"""Display-only integration. No ROS subscriptions or control publishers here."""
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import threading
import time
from datetime import datetime, timezone

from .rgb_adaptive import AdaptiveRgbSession
from .rgb_adaptive_transport import AdaptiveHub
from .rgb_stream import origin_allowed


class AdaptiveRgbRuntime:
    def __init__(self, converter):
        self.enabled = os.getenv("HAZARD_GUARD_RGB_ADAPTIVE", "off").lower() == "on"
        self.session = AdaptiveRgbSession(converter=converter) if self.enabled else None
        self.hub = AdaptiveHub(self.session, origin_check=origin_allowed) if self.session else None
        self.lock = threading.RLock()
        self.input = None
        self.legacy_until = 0.0
        self.monitor = None
        self.stop_event = threading.Event()
        self.monitor_error = None

    def demand_legacy(self):
        with self.lock:
            self.legacy_until = time.monotonic() + 1

    def needs_legacy(self):
        with self.lock:
            # Unsupported geometry uses the existing JPEG path, never resize
            # the analysis input or silently advertise an unusable AVC stream.
            return (not self.enabled or self.input is None
                    or not self.input["compatible"] or time.monotonic() < self.legacy_until)

    def offer(self, message, received, source):
        if not self.enabled or self.stop_event.is_set():
            return
        width, height = int(message.width), int(message.height)
        with self.lock:
            self.input = {"width": width, "height": height, "source": source,
                          "compatible": (width, height) == (640, 480),
                          "updated_at": datetime.now(timezone.utc).isoformat(),
                          "received": received}
            if self.monitor is None:
                self.monitor = threading.Thread(target=self._monitor, daemon=True, name="rgb-adaptive-metrics")
                self.monitor.start()
        if (width, height) == (640, 480):
            self.session.submit(message, received)

    def media_status(self):
        with self.lock:
            item = dict(self.input) if self.input else None
        if not self.enabled or item is None:
            return None
        age = time.monotonic() - item.pop("received")
        compatible = item.pop("compatible")
        return {**item, "available": not self.stop_event.is_set() and 0 <= age < 2,
                "adaptive": compatible, "transport": "adaptive" if compatible else "jpeg"}

    def status(self):
        return {"enabled": self.enabled, "endpoint": "/ws/media/rgb/adaptive",
                "freshness_budget_ms": 500, "monitor_error": self.monitor_error,
                **(self.session.snapshot() if self.session else {})}

    def _monitor(self):
        logger = logging.getLogger("rgb-adaptive-runtime-" + self.session.session)
        logger.propagate = False
        logger.setLevel(logging.INFO)
        handler = None
        try:
            path = os.getenv("HAZARD_GUARD_RGB_ADAPTIVE_LOG", "runtime/rgb-adaptive.jsonl")
            if path.lower() != "off":
                try:
                    target = Path(path)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    handler = RotatingFileHandler(target, maxBytes=4_000_000, backupCount=2, encoding="utf-8")
                    logger.addHandler(handler)
                except OSError as exc:
                    self.monitor_error = f"log: {type(exc).__name__}"
            try:
                import psutil
                psutil.cpu_percent()
                process = psutil.Process()
                process.cpu_percent()
            except ImportError:
                psutil = process = None
                self.monitor_error = "psutil unavailable: automatic H264 trial disabled"
            while not self.stop_event.wait(1):
                try:
                    cpu = psutil.cpu_percent() if psutil else None
                    self.session.evaluate(cpu)
                    row = self.session.snapshot()
                    row.update(timestamp=time.time(), source="production_rgb_display",
                               process_cpu_one_core_percent=process.cpu_percent() if process else None,
                               rss_bytes=process.memory_info().rss if process else None,
                               transport_timeouts=self.hub.timeouts, protocol_errors=self.hub.protocol_errors)
                    row["windows"], row["events"] = row["windows"][-1:], row["events"][-1:]
                    if handler:
                        logger.info(json.dumps(row, allow_nan=False))
                except Exception as exc:
                    # Monitoring must not kill RGB, ROS, or the backend.
                    self.monitor_error = type(exc).__name__
        finally:
            if handler:
                logger.removeHandler(handler)
                handler.close()

    def close(self):
        self.stop_event.set()
        if self.monitor:
            self.monitor.join(2)
        if self.session:
            self.session.close()
