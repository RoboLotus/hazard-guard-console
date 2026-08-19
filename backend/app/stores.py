from __future__ import annotations

import copy
import math
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _datetime_to_unix_ms(value: datetime | None) -> int:
    return int(value.timestamp() * 1000) if value is not None else 0


class MediaStore:
    """Thread-safe cache for ROS media converted to browser-ready images."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._items: dict[str, dict[str, Any]] = {}

    def update(
        self,
        kind: str,
        content: bytes,
        media_type: str,
        *,
        width: int,
        height: int,
        source: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            self._items[kind] = {
                "content": content,
                "media_type": media_type,
                "width": width,
                "height": height,
                "source": source,
                "metadata": dict(metadata or {}),
                "updated_at": utc_now(),
                "updated_monotonic": time.monotonic(),
            }

    def get(self, kind: str) -> dict[str, Any] | None:
        with self._lock:
            item = self._items.get(kind)
            return dict(item) if item is not None else None

    def clear(self, kind: str | None = None) -> None:
        with self._lock:
            if kind is None:
                self._items.clear()
            else:
                self._items.pop(kind, None)

    def status(self) -> dict[str, dict[str, Any]]:
        now = time.monotonic()
        with self._lock:
            items = {kind: dict(item) for kind, item in self._items.items()}

        result: dict[str, dict[str, Any]] = {}
        for kind in ("map", "rgb", "thermal"):
            item = items.get(kind)
            if item is None:
                result[kind] = {"available": False}
                continue
            # An occupancy map is a snapshot and may be published only once by
            # map_server. Camera frames are streams and must remain fresh.
            freshness_limit = math.inf if kind == "map" else 5.0
            result[kind] = {
                "available": now - item["updated_monotonic"] < freshness_limit,
                "updated_at": item["updated_at"],
                "width": item["width"],
                "height": item["height"],
                "source": item["source"],
            }
            if item["metadata"]:
                result[kind]["metadata"] = item["metadata"]
        return result


class NavigationStore:
    """Thread-safe snapshot of the current Nav2 goal lifecycle."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._data: dict[str, Any] = {
            "status": "idle",
            "accepted": False,
            "mock": True,
            "goal_id": None,
            "frame_id": "map",
            "x": None,
            "y": None,
            "yaw": None,
            "distance_remaining": None,
            "navigation_time_sec": None,
            "message": "아직 전송된 목적지가 없습니다.",
            "updated_at": utc_now(),
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._data)

    def update(self, values: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._data.update(values)
            self._data["updated_at"] = utc_now()
            return dict(self._data)


class RouteMissionStore:
    """Thread-safe status for a named, ordered waypoint patrol."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._data: dict[str, Any] = {
            "mission_id": None,
            "name": None,
            "status": "idle",
            "accepted": False,
            "mock": True,
            "frame_id": "map",
            "current_index": None,
            "total_waypoints": 0,
            "completed_waypoints": 0,
            "repeat_mode": "once",
            "repeat_count": 1,
            "repeat_interval_sec": 0.0,
            "current_cycle": 0,
            "total_cycles": 1,
            "completed_cycles": 0,
            "start_at_unix_ms": 0,
            "end_at_unix_ms": 0,
            "next_run_at_unix_ms": 0,
            "total_distance_m": None,
            "message": "아직 시작된 순찰 임무가 없습니다.",
            "waypoints": [],
            "updated_at": utc_now(),
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._data)

    def begin(self, route: dict[str, Any], *, mock: bool) -> dict[str, Any]:
        active = [item for item in route["waypoints"] if item.get("enabled", True)]
        with self._lock:
            self._data = {
                "mission_id": uuid.uuid4().hex,
                "name": route["name"],
                "status": "preparing",
                "accepted": True,
                "mock": mock,
                "frame_id": route["frame_id"],
                "current_index": None,
                "total_waypoints": len(active),
                "completed_waypoints": 0,
                "repeat_mode": route.get("repeat_mode", "once"),
                "repeat_count": route.get("repeat_count", 1),
                "repeat_interval_sec": route.get("repeat_interval_seconds", 0.0),
                "current_cycle": 0,
                "total_cycles": (
                    route.get("repeat_count", 1)
                    if route.get("repeat_mode") == "count"
                    else 1 if route.get("repeat_mode", "once") == "once" else 0
                ),
                "completed_cycles": 0,
                "start_at_unix_ms": _datetime_to_unix_ms(route.get("start_at")),
                "end_at_unix_ms": _datetime_to_unix_ms(route.get("end_at")),
                "next_run_at_unix_ms": _datetime_to_unix_ms(route.get("start_at")),
                "total_distance_m": None,
                "message": "웨이포인트 경로를 확인하고 있습니다.",
                "waypoints": [
                    {
                        **item,
                        "status": "pending",
                        "message": "대기 중",
                    }
                    for item in active
                ],
                "updated_at": utc_now(),
            }
            return copy.deepcopy(self._data)

    def update(self, values: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._data.update(values)
            self._data["updated_at"] = utc_now()
            return copy.deepcopy(self._data)

    def update_waypoint(
        self,
        index: int,
        status: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            if 0 <= index < len(self._data["waypoints"]):
                self._data["waypoints"][index].update(
                    {
                        "status": status,
                        "message": message,
                        "updated_at": utc_now(),
                        **(details or {}),
                    }
                )
            self._data["updated_at"] = utc_now()
            return copy.deepcopy(self._data)


class SpatialStore:
    """Live map-space state used by the 2D digital-twin overlays."""

    SENSOR_SPECS = [
        {
            "id": "depth",
            "label": "Depth",
            "display_name": "Depth",
            "model": "Nuwa-HP60C",
            "horizontal_fov_deg": 73.8,
            "range_min_m": 0.2,
            "range_max_m": 4.0,
            "range_note": "제조사 깊이 측정 범위",
            "color": "#2675d8",
        },
        {
            "id": "thermal",
            "label": "Thermal",
            "display_name": "TMC160B",
            "model": "ThermoEye TMC160B",
            "resolution": "160×120",
            "frame_rate_hz": 8.7,
            "horizontal_fov_deg": 57.0,
            "range_min_m": 0.0,
            "range_max_m": 5.0,
            "range_note": "시뮬레이션 시야 표시 범위(제조사 측정거리 아님)",
            "temperature_high_gain_c": [-10.0, 140.0],
            "temperature_low_gain_c": [-10.0, 400.0],
            "color": "#e45832",
        },
    ]
    MOCK_MAP = {
        "frame_id": "map",
        "width": 240,
        "height": 180,
        "resolution": 0.05,
        "origin_x": -6.0,
        "origin_y": -4.5,
        "source": "mock:slam-map",
    }
    MOCK_ROUTE = [
        (-2.9, -2.7),
        (-0.8, -2.7),
        (1.3, -2.2),
        (2.6, -0.4),
        (2.1, 1.8),
        (-0.4, 2.6),
        (-2.7, 1.6),
        (-3.2, -0.6),
    ]
    MOCK_HEAT_SOURCES = [
        {
            "detection_id": "mock-pump-p02",
            "x": 1.8,
            "y": 1.2,
            "temperature_c": 84.6,
            "confidence": 0.94,
            "radius_m": 0.48,
            "source": "simulation:pump_block",
        },
        {
            "detection_id": "mock-partition-p01",
            "x": -0.3,
            "y": -1.3,
            "temperature_c": 63.2,
            "confidence": 0.86,
            "radius_m": 0.38,
            "source": "simulation:center_partition",
        },
        {
            "detection_id": "mock-tank-normal",
            "x": -1.8,
            "y": 1.8,
            "temperature_c": 46.8,
            "confidence": 0.8,
            "radius_m": 0.52,
            "source": "simulation:tank_block",
        },
    ]

    def __init__(self) -> None:
        self._lock = threading.RLock()
        default_mock_enabled = (
            "0"
            if os.getenv("HAZARD_GUARD_DEPLOYMENT_TARGET", "simulation").lower()
            == "physical"
            else "1"
        )
        self._mock_enabled = os.getenv(
            "HAZARD_GUARD_MOCK_DATA_ENABLED", default_mock_enabled
        ).lower() in {"1", "true", "yes", "on"}
        self._source = "mock" if self._mock_enabled else "waiting"
        self._map_id = os.getenv(
            "HAZARD_GUARD_MAP_ID",
            "mock:facility-v1" if self._mock_enabled else "physical:pending",
        )
        self._map = {
            **self.MOCK_MAP,
            "map_id": self._map_id,
            "source": "mock:slam-map" if self._mock_enabled else "pending:/map",
        }
        self._pose = {
            "available": self._mock_enabled,
            "frame_id": "map",
            "x": self.MOCK_ROUTE[0][0],
            "y": self.MOCK_ROUTE[0][1],
            "z": 0.0,
            "yaw": 0.0,
            "mock": self._mock_enabled,
            "updated_at": utc_now(),
        }
        self._poses: dict[str, dict[str, Any]] = {
            "map": dict(self._pose),
        }
        self._trail: list[dict[str, Any]] = []
        self._detections: dict[str, dict[str, Any]] = {}
        self._started_monotonic = time.monotonic()
        self._last_mock_update = 0.0
        self._live_initialized = False
        if self._mock_enabled:
            for detection in self.MOCK_HEAT_SOURCES:
                self._store_detection_locked(
                    {
                        **detection,
                        "frame_id": "map",
                        "z": 0.0,
                        "simulated": True,
                    }
                )

    def _activate_live_locked(self) -> None:
        if self._live_initialized:
            return
        self._live_initialized = True
        self._source = "ros"
        self._trail.clear()
        self._detections.clear()

    def update_map(
        self,
        *,
        frame_id: str,
        width: int,
        height: int,
        resolution: float,
        origin_x: float,
        origin_y: float,
    ) -> None:
        with self._lock:
            self._activate_live_locked()
            self._map = {
                "map_id": self._map_id,
                "frame_id": frame_id or "map",
                "width": int(width),
                "height": int(height),
                "resolution": float(resolution),
                "origin_x": float(origin_x),
                "origin_y": float(origin_y),
                "source": "ros:/map",
            }

    def update_pose(
        self,
        *,
        x: float,
        y: float,
        z: float = 0.0,
        yaw: float,
        frame_id: str = "map",
        mock: bool = False,
    ) -> None:
        with self._lock:
            if not mock:
                self._activate_live_locked()
            pose = {
                "available": True,
                "frame_id": frame_id,
                "x": round(float(x), 4),
                "y": round(float(y), 4),
                "z": round(float(z), 4),
                "yaw": round(float(yaw), 5),
                "mock": bool(mock),
                "updated_at": utc_now(),
            }
            self._pose = pose
            self._poses[str(frame_id).lstrip("/") or "map"] = dict(pose)
            self._append_trail_locked(pose)

    def update_frame_pose(
        self,
        *,
        x: float,
        y: float,
        z: float = 0.0,
        yaw: float,
        frame_id: str,
        mock: bool = False,
    ) -> None:
        """Store a pose for 3D overlays without replacing the canonical map pose."""

        with self._lock:
            if not mock:
                self._activate_live_locked()
            normalized_frame = str(frame_id).lstrip("/") or "odom"
            self._poses[normalized_frame] = {
                "available": True,
                "frame_id": normalized_frame,
                "x": round(float(x), 4),
                "y": round(float(y), 4),
                "z": round(float(z), 4),
                "yaw": round(float(yaw), 5),
                "mock": bool(mock),
                "updated_at": utc_now(),
            }

    def clear_trail(self) -> None:
        with self._lock:
            self._trail.clear()

    def reset_for_mapping(self, map_id: str) -> None:
        """Discard overlays from the previous SLAM run while awaiting /map."""

        with self._lock:
            self._map_id = map_id
            self._map = {
                **self.MOCK_MAP,
                "map_id": map_id,
                "source": "pending:/map",
            }
            self._pose = {
                "available": False,
                "frame_id": "map",
                "x": 0.0,
                "y": 0.0,
                "z": 0.0,
                "yaw": 0.0,
                "mock": False,
                "updated_at": utc_now(),
            }
            self._poses.clear()
            self._trail.clear()
            self._detections.clear()
            self._live_initialized = False

    def reset_for_localization(self) -> None:
        """Invalidate a SLAM-era pose until AMCL publishes the patrol transform."""

        with self._lock:
            self._pose = {
                "available": False,
                "frame_id": "map",
                "x": 0.0,
                "y": 0.0,
                "z": 0.0,
                "yaw": 0.0,
                "mock": False,
                "updated_at": utc_now(),
            }
            self._poses.clear()
            self._trail.clear()

    def _append_trail_locked(self, pose: dict[str, Any]) -> None:
        point = {
            "x": pose["x"],
            "y": pose["y"],
            "frame_id": pose.get("frame_id", "map"),
            "timestamp": pose["updated_at"],
        }
        if self._trail:
            previous = self._trail[-1]
            if (
                previous.get("frame_id", "map") == point["frame_id"]
                and math.hypot(
                    point["x"] - previous["x"],
                    point["y"] - previous["y"],
                ) < 0.08
            ):
                return
        self._trail.append(point)
        self._trail = self._trail[-240:]

    def _store_detection_locked(self, detection: dict[str, Any]) -> dict[str, Any]:
        detection_id = str(detection.get("detection_id") or "thermal-detection")
        item = {
            "detection_id": detection_id,
            "frame_id": str(detection.get("frame_id") or "map"),
            "x": round(float(detection["x"]), 4),
            "y": round(float(detection["y"]), 4),
            "z": round(float(detection.get("z", 0.0)), 4),
            "temperature_c": round(float(detection["temperature_c"]), 2),
            "confidence": round(float(detection.get("confidence", 1.0)), 3),
            "radius_m": round(float(detection.get("radius_m", 0.35)), 3),
            "source": str(detection.get("source") or "unknown"),
            "equipment_id": detection.get("equipment_id"),
            "equipment_name": detection.get("equipment_name"),
            "trend_status": detection.get("trend_status"),
            "trend_reason": detection.get("trend_reason"),
            "visit_index": detection.get("visit_index"),
            "policy_mode": detection.get("policy_mode"),
            "adaptive_threshold_enabled": detection.get(
                "adaptive_threshold_enabled"
            ),
            "baseline_temperature_c": detection.get(
                "baseline_temperature_c"
            ),
            "baseline_residual_c": detection.get("baseline_residual_c"),
            "baseline_residual_threshold_c": detection.get(
                "baseline_residual_threshold_c"
            ),
            "effective_adaptive_threshold_c": detection.get(
                "effective_adaptive_threshold_c"
            ),
            "simulated": bool(detection.get("simulated", False)),
            "updated_at": utc_now(),
            "updated_monotonic": time.monotonic(),
        }
        previous = self._detections.get(detection_id)
        if (
            previous is not None
            and float(previous["temperature_c"]) > item["temperature_c"]
        ):
            # A later oblique or empty view can still produce ambient points
            # inside the equipment ROI. Keep the hottest observation for the
            # current mapping/patrol session while refreshing its last-seen
            # time. Session resets clear this peak together with all markers.
            for key in (
                "frame_id", "x", "y", "z", "temperature_c", "confidence",
                "radius_m", "simulated",
            ):
                item[key] = previous[key]
            if (
                previous.get("visit_index") is None
                and item.get("visit_index") is None
            ):
                for key in (
                    "source", "equipment_id", "equipment_name", "trend_status", "trend_reason"
                ):
                    item[key] = previous.get(key)
        self._detections[item["detection_id"]] = item
        if len(self._detections) > 80:
            oldest = min(
                self._detections,
                key=lambda key: self._detections[key]["updated_monotonic"],
            )
            self._detections.pop(oldest, None)
        return dict(item)

    def add_detection(
        self,
        detection: dict[str, Any],
        *,
        live: bool = False,
        completed_visit: bool = False,
    ) -> dict[str, Any]:
        with self._lock:
            if live:
                self._activate_live_locked()
            if not completed_visit:
                previous = self._detections.get(
                    str(detection.get("detection_id") or "thermal-detection")
                )
                if previous is not None and previous.get("visit_index") is not None:
                    for key in (
                        "trend_status",
                        "trend_reason",
                        "visit_index",
                        "source",
                        "policy_mode",
                        "adaptive_threshold_enabled",
                        "baseline_temperature_c",
                        "baseline_residual_c",
                        "baseline_residual_threshold_c",
                        "effective_adaptive_threshold_c",
                    ):
                        detection[key] = previous.get(key)
            return self._store_detection_locked(detection)

    def _advance_mock_locked(self) -> None:
        if self._source != "mock":
            return
        now = time.monotonic()
        if now - self._last_mock_update < 0.18:
            return
        elapsed = (now - self._started_monotonic) % 48.0
        segment_duration = 48.0 / len(self.MOCK_ROUTE)
        segment = int(elapsed // segment_duration)
        progress = (elapsed % segment_duration) / segment_duration
        start = self.MOCK_ROUTE[segment]
        end = self.MOCK_ROUTE[(segment + 1) % len(self.MOCK_ROUTE)]
        x = start[0] + (end[0] - start[0]) * progress
        y = start[1] + (end[1] - start[1]) * progress
        yaw = math.atan2(end[1] - start[1], end[0] - start[0])
        self._pose = {
            "available": True,
            "frame_id": "map",
            "x": round(x, 4),
            "y": round(y, 4),
            "z": 0.0,
            "yaw": round(yaw, 5),
            "mock": True,
            "updated_at": utc_now(),
        }
        self._append_trail_locked(self._pose)
        self._last_mock_update = now

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            self._advance_mock_locked()
            poses = {key: dict(value) for key, value in self._poses.items()}
            pose_frame = str(self._pose.get("frame_id") or "map").lstrip("/")
            poses[pose_frame] = dict(self._pose)
            now = time.monotonic()
            detections = []
            for item in self._detections.values():
                public = {
                    key: value
                    for key, value in item.items()
                    if key != "updated_monotonic"
                }
                public["age_sec"] = round(max(0.0, now - item["updated_monotonic"]), 1)
                detections.append(public)
            detections.sort(key=lambda item: item["temperature_c"], reverse=True)
            return {
                "source": self._source,
                "mock": self._source == "mock",
                "map": dict(self._map),
                "pose": dict(self._pose),
                "poses": poses,
                "trail": [dict(point) for point in self._trail],
                "sensors": [dict(sensor) for sensor in self.SENSOR_SPECS],
                "heatmap": {
                    "available": bool(detections),
                    "simulated": all(item["simulated"] for item in detections)
                    if detections
                    else self._source == "mock",
                    "minimum_c": 20.0,
                    "maximum_c": max(
                        [item["temperature_c"] for item in detections],
                        default=20.0,
                    ),
                    "detections": detections,
                },
                "updated_at": utc_now(),
            }


class TelemetryStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._data: dict[str, Any] = {
            "timestamp": utc_now(),
            "robot_id": "rosmaster-m1-mock",
            "mode": "patrol",
            "battery_percent": 78.0,
            "speed_mps": 0.32,
            "network_quality": "good",
            "network_rssi_dbm": -48,
            "lidar_status": "normal",
            "lidar_hz": 10.2,
            "max_temperature_c": 63.0,
            "alert_level": "warning",
            "controller_enabled": False,
            "mock": True,
            "person_safety": {
                "state": 0,
                "state_name": "CLEAR",
                "person_count": 0,
                "nearest_distance_m": None,
                "distance_valid": False,
                "detector_stale": False,
                "reason": "사람 안전 기능이 아직 연결되지 않았습니다.",
                "updated_at": None,
            },
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            result = dict(self._data)
        result["timestamp"] = utc_now()
        return result

    def update(self, values: dict[str, Any]) -> None:
        with self._lock:
            self._data.update(values)

    def apply_mock_command(self, command: str, enabled: bool) -> dict[str, Any]:
        normalized = command.strip().lower()
        with self._lock:
            mode = self._data["mode"]
            accepted = True

            if normalized == "pause":
                if mode == "stopped":
                    accepted = False
                    message = "정지 상태에서는 순찰을 일시정지할 수 없습니다."
                else:
                    mode = "paused"
                    message = "순찰을 일시정지했습니다."
            elif normalized == "resume":
                if mode == "stopped":
                    accepted = False
                    message = "정지 상태는 안전 확인 없이 해제할 수 없습니다."
                else:
                    mode = "patrol"
                    message = "순찰을 재개했습니다."
            elif normalized == "stop":
                mode = "stopped"
                self._data["controller_enabled"] = False
                message = "mock robot을 정지 상태로 전환했습니다."
            elif normalized in {"controller", "controller_on", "controller_off"}:
                if normalized == "controller_on":
                    enabled = True
                elif normalized == "controller_off":
                    enabled = False
                self._data["controller_enabled"] = enabled
                label = "활성화" if enabled else "비활성화"
                message = f"컨트롤러 입력을 {label}했습니다."
            else:
                accepted = False
                message = f"지원하지 않는 mock 명령입니다: {command}"

            self._data["mode"] = mode
            self._data["speed_mps"] = 0.32 if mode == "patrol" else 0.0
            return {
                "command": command,
                "accepted": accepted,
                "mock": True,
                "message": message,
                "mode": mode,
                "controller_enabled": self._data["controller_enabled"],
            }
