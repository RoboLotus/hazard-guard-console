from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SensorDiagnosticsStore:
    """Track the freshness of the ROS inputs needed by mapping and patrol."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._items: dict[str, dict[str, Any]] = {}

    def register(
        self,
        sensor_id: str,
        *,
        label: str,
        topic: str,
        required_for: tuple[str, ...] = (),
        stale_after_sec: float = 3.0,
        expected_min_hz: float | None = None,
    ) -> None:
        with self._lock:
            self._items[sensor_id] = {
                "id": sensor_id,
                "label": label,
                "topic": topic,
                "required_for": list(required_for),
                "stale_after_sec": float(stale_after_sec),
                "expected_min_hz": expected_min_hz,
                "message_count": 0,
                "last_seen": None,
                "last_seen_monotonic": None,
                "observed_monotonic": deque(maxlen=120),
                "frame_id": None,
            }

    def mark(self, sensor_id: str, message: Any | None = None) -> None:
        with self._lock:
            item = self._items.get(sensor_id)
            if item is None:
                return
            now = time.monotonic()
            item["message_count"] += 1
            item["last_seen"] = utc_now()
            item["last_seen_monotonic"] = now
            item["observed_monotonic"].append(now)
            frame_id = getattr(getattr(message, "header", None), "frame_id", None)
            if frame_id:
                item["frame_id"] = str(frame_id).lstrip("/")

    def snapshot(
        self,
        *,
        ros_active: bool,
        active_requirements: tuple[str, ...] = (),
        deployment_target: str | None = None,
    ) -> dict[str, Any]:
        now = time.monotonic()
        sensors = []
        with self._lock:
            values = [dict(item) for item in self._items.values()]
        for item in values:
            last_seen = item.pop("last_seen_monotonic", None)
            observations = list(item.pop("observed_monotonic", ()))
            age_sec = None if last_seen is None else round(max(0.0, now - last_seen), 1)
            if not ros_active:
                state = "offline"
            elif age_sec is None:
                state = "waiting"
            elif age_sec <= item["stale_after_sec"]:
                state = "live"
            else:
                state = "stale"
            item["age_sec"] = age_sec
            item["state"] = state
            window = max(5.0, item["stale_after_sec"] * 2.0)
            recent = [value for value in observations if now - value <= window]
            item["rate_hz"] = (
                round((len(recent) - 1) / (recent[-1] - recent[0]), 1)
                if len(recent) >= 2 and recent[-1] > recent[0]
                else None
            )
            item["required_now"] = bool(
                set(item["required_for"]).intersection(active_requirements)
            )
            sensors.append(item)
        required = [sensor for sensor in sensors if sensor["required_now"]]
        return {
            "ros_active": ros_active,
            "updated_at": utc_now(),
            "deployment_target": deployment_target,
            "active_requirements": list(active_requirements),
            "sensors": sensors,
            "summary": {
                state: sum(sensor["state"] == state for sensor in sensors)
                for state in ("live", "waiting", "stale", "offline")
            }
            | {
                "required_total": len(required),
                "required_live": sum(sensor["state"] == "live" for sensor in required),
                "optional_total": sum(not sensor["required_for"] for sensor in sensors),
            },
        }
