from __future__ import annotations

import threading
import time
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
    ) -> None:
        with self._lock:
            self._items[sensor_id] = {
                "id": sensor_id,
                "label": label,
                "topic": topic,
                "required_for": list(required_for),
                "stale_after_sec": float(stale_after_sec),
                "message_count": 0,
                "last_seen": None,
                "last_seen_monotonic": None,
            }

    def mark(self, sensor_id: str) -> None:
        with self._lock:
            item = self._items.get(sensor_id)
            if item is None:
                return
            item["message_count"] += 1
            item["last_seen"] = utc_now()
            item["last_seen_monotonic"] = time.monotonic()

    def snapshot(self, *, ros_active: bool) -> dict[str, Any]:
        now = time.monotonic()
        sensors = []
        with self._lock:
            values = [dict(item) for item in self._items.values()]
        for item in values:
            last_seen = item.pop("last_seen_monotonic", None)
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
            sensors.append(item)
        return {
            "ros_active": ros_active,
            "updated_at": utc_now(),
            "sensors": sensors,
            "summary": {
                state: sum(sensor["state"] == state for sensor in sensors)
                for state in ("live", "waiting", "stale", "offline")
            },
        }
