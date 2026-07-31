from __future__ import annotations

import copy
import json
import math
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
        self._source = "mock"
        self._map_id = os.getenv("HAZARD_GUARD_MAP_ID", "mock:facility-v1")
        self._map = {**self.MOCK_MAP, "map_id": self._map_id}
        self._pose = {
            "available": True,
            "frame_id": "map",
            "x": self.MOCK_ROUTE[0][0],
            "y": self.MOCK_ROUTE[0][1],
            "yaw": 0.0,
            "mock": True,
            "updated_at": utc_now(),
        }
        self._trail: list[dict[str, Any]] = []
        self._detections: dict[str, dict[str, Any]] = {}
        self._started_monotonic = time.monotonic()
        self._last_mock_update = 0.0
        self._live_initialized = False
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
                "yaw": round(float(yaw), 5),
                "mock": bool(mock),
                "updated_at": utc_now(),
            }
            self._pose = pose
            self._append_trail_locked(pose)

    def clear_trail(self) -> None:
        with self._lock:
            self._trail.clear()

    def _append_trail_locked(self, pose: dict[str, Any]) -> None:
        point = {
            "x": pose["x"],
            "y": pose["y"],
            "timestamp": pose["updated_at"],
        }
        if self._trail:
            previous = self._trail[-1]
            if math.hypot(point["x"] - previous["x"], point["y"] - previous["y"]) < 0.08:
                return
        self._trail.append(point)
        self._trail = self._trail[-240:]

    def _store_detection_locked(self, detection: dict[str, Any]) -> dict[str, Any]:
        item = {
            "detection_id": str(detection.get("detection_id") or "thermal-detection"),
            "frame_id": str(detection.get("frame_id") or "map"),
            "x": round(float(detection["x"]), 4),
            "y": round(float(detection["y"]), 4),
            "z": round(float(detection.get("z", 0.0)), 4),
            "temperature_c": round(float(detection["temperature_c"]), 2),
            "confidence": round(float(detection.get("confidence", 1.0)), 3),
            "radius_m": round(float(detection.get("radius_m", 0.35)), 3),
            "source": str(detection.get("source") or "unknown"),
            "simulated": bool(detection.get("simulated", False)),
            "updated_at": utc_now(),
            "updated_monotonic": time.monotonic(),
        }
        self._detections[item["detection_id"]] = item
        if len(self._detections) > 80:
            oldest = min(
                self._detections,
                key=lambda key: self._detections[key]["updated_monotonic"],
            )
            self._detections.pop(oldest, None)
        return dict(item)

    def add_detection(self, detection: dict[str, Any], *, live: bool = False) -> dict[str, Any]:
        with self._lock:
            if live:
                self._activate_live_locked()
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
            "yaw": round(yaw, 5),
            "mock": True,
            "updated_at": utc_now(),
        }
        self._append_trail_locked(self._pose)
        self._last_mock_update = now

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            self._advance_mock_locked()
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


class RosBridge:
    """Optional ROS 2 adapter. ROS imports happen only when explicitly enabled."""

    def __init__(
        self,
        store: TelemetryStore,
        media: MediaStore,
        navigation: NavigationStore,
        mission: RouteMissionStore,
        spatial: SpatialStore,
    ) -> None:
        self.store = store
        self.media = media
        self.navigation = navigation
        self.mission = mission
        self.spatial = spatial
        self.active = False
        self.error: str | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._context = None
        self._node = None
        self._executor = None
        self._client = None
        self._request_type = None
        self._cv_bridge = None
        self._tf_buffer = None
        self._tf_listener = None
        self._ros_time_type = None
        self._navigate_action_client = None
        self._navigate_action_type = None
        self._compute_path_action_client = None
        self._compute_path_action_type = None
        self._mission_action_client = None
        self._mission_action_type = None
        self._mission_waypoint_type = None
        self._mission_cancel_client = None
        self._mission_cancel_request_type = None
        self._mission_goal_handle = None
        self._thermal_stream_seen = False
        self._navigation_goal_handle = None
        self._navigation_result_event = threading.Event()
        self._navigation_result_status: str | None = None
        self._mission_lock = threading.RLock()
        self._last_pose_update = 0.0

    def start(self) -> None:
        if os.getenv("HAZARD_GUARD_ROS_ENABLED", "0") != "1":
            return

        try:
            import rclpy
            from cv_bridge import CvBridge
            from hazard_guard_interfaces.msg import RobotTelemetry
            from hazard_guard_interfaces.srv import RobotCommand
            from nav_msgs.msg import OccupancyGrid
            from nav2_msgs.action import ComputePathToPose, NavigateToPose
            from rclpy.action import ActionClient
            from rclpy.context import Context
            from rclpy.executors import SingleThreadedExecutor
            from rclpy.node import Node
            from rclpy.qos import (
                DurabilityPolicy,
                QoSProfile,
                ReliabilityPolicy,
                qos_profile_sensor_data,
            )
            from rclpy.time import Time
            from sensor_msgs.msg import Image
            from std_msgs.msg import String
            from std_srvs.srv import Trigger
            from tf2_ros import Buffer, TransformListener

            self._context = Context()
            rclpy.init(context=self._context)
            self._node = Node("hazard_guard_web_bridge", context=self._context)
            self._tf_buffer = Buffer()
            self._tf_listener = TransformListener(
                self._tf_buffer, self._node, spin_thread=False
            )
            self._ros_time_type = Time
            self._node.create_subscription(
                RobotTelemetry,
                "/hazard_guard/telemetry",
                self._on_telemetry,
                10,
            )
            map_qos = QoSProfile(
                depth=1,
                reliability=ReliabilityPolicy.RELIABLE,
                durability=DurabilityPolicy.TRANSIENT_LOCAL,
            )
            self._node.create_subscription(
                OccupancyGrid,
                "/map",
                self._on_map,
                map_qos,
            )
            self._cv_bridge = CvBridge()
            self._node.create_subscription(
                Image,
                os.getenv("HAZARD_GUARD_RGB_TOPIC", "/camera/image_raw"),
                self._on_rgb_image,
                qos_profile_sensor_data,
            )
            self._node.create_subscription(
                Image,
                os.getenv(
                    "HAZARD_GUARD_THERMAL_TOPIC", "/thermal_camera/image_raw"
                ),
                self._on_thermal_image,
                qos_profile_sensor_data,
            )
            try:
                from hazard_guard_interfaces.msg import HazardDetection

                self._node.create_subscription(
                    HazardDetection,
                    "/hazard_guard/thermal_detections",
                    self._on_thermal_detection,
                    qos_profile_sensor_data,
                )
            except ImportError:
                # Older interface workspaces can still provide map, pose and media.
                pass
            self._navigate_action_type = NavigateToPose
            self._navigate_action_client = ActionClient(
                self._node,
                NavigateToPose,
                "/navigate_to_pose",
            )
            self._compute_path_action_type = ComputePathToPose
            self._compute_path_action_client = ActionClient(
                self._node,
                ComputePathToPose,
                "/compute_path_to_pose",
            )
            try:
                from hazard_guard_interfaces.action import RunPatrol
                from hazard_guard_interfaces.msg import PatrolWaypoint

                self._mission_action_type = RunPatrol
                self._mission_waypoint_type = PatrolWaypoint
                self._mission_action_client = ActionClient(
                    self._node,
                    RunPatrol,
                    "/hazard_guard/run_patrol",
                )
            except ImportError:
                # Keep map, telemetry and camera bridging available while an
                # older Robot workspace is rebuilt with the mission interfaces.
                self._mission_action_type = None
                self._mission_waypoint_type = None
                self._mission_action_client = None
            self._node.create_subscription(
                String,
                "/hazard_guard/mission/status",
                self._on_mission_status,
                map_qos,
            )
            self._mission_cancel_client = self._node.create_client(
                Trigger,
                "/hazard_guard/mission/cancel",
            )
            self._mission_cancel_request_type = Trigger.Request
            self._client = self._node.create_client(
                RobotCommand, "/hazard_guard/command"
            )
            self._request_type = RobotCommand.Request
            self._executor = SingleThreadedExecutor(context=self._context)
            self._executor.add_node(self._node)
            self._thread = threading.Thread(
                target=self._spin, name="hazard-guard-ros-bridge", daemon=True
            )
            self.active = True
            self._thread.start()
        except Exception as exc:  # fallback must keep the WebUI usable
            self.error = str(exc)
            self.active = False
            self.stop()

    def _spin(self) -> None:
        while not self._stop_event.is_set():
            self._executor.spin_once(timeout_sec=0.2)
            self._update_spatial_pose()

    def capability_status(self) -> dict[str, bool]:
        """Report ROS capabilities without sending a command."""

        navigate_client = self._navigate_action_client
        path_client = self._compute_path_action_client
        mission_client = self._mission_action_client
        return {
            "navigate_to_pose": bool(
                self.active
                and navigate_client is not None
                and navigate_client.server_is_ready()
            ),
            "compute_path_to_pose": bool(
                self.active and path_client is not None and path_client.server_is_ready()
            ),
            "mission_manager": bool(
                self.active
                and mission_client is not None
                and mission_client.server_is_ready()
            ),
        }

    def _on_mission_status(self, message: Any) -> None:
        """Mirror the ROS mission manager's latched state for WebUI polling."""

        try:
            payload = json.loads(message.data)
        except (TypeError, ValueError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return
        allowed = {
            "mission_id",
            "name",
            "status",
            "accepted",
            "mock",
            "frame_id",
            "current_index",
            "total_waypoints",
            "completed_waypoints",
            "total_distance_m",
            "message",
            "waypoints",
        }
        self.mission.update(
            {key: value for key, value in payload.items() if key in allowed}
        )

    def _on_mission_feedback(self, feedback_message: Any) -> None:
        feedback = feedback_message.feedback
        index = int(feedback.current_index)
        self.mission.update(
            {
                "status": feedback.status,
                "message": feedback.message,
                "current_index": index if index >= 0 else None,
                "total_waypoints": int(feedback.total_waypoints),
                "completed_waypoints": int(feedback.completed_waypoints),
                "total_distance_m": round(float(feedback.total_distance_m), 3),
            }
        )
        if index >= 0:
            details: dict[str, Any] = {}
            if float(feedback.position_error_m) >= 0:
                details["position_error_m"] = round(
                    float(feedback.position_error_m), 3
                )
            if float(feedback.yaw_error_deg) >= 0:
                details["yaw_error_deg"] = round(
                    float(feedback.yaw_error_deg), 2
                )
            self.mission.update_waypoint(
                index,
                feedback.waypoint_status or feedback.status,
                feedback.message,
                details,
            )

    def _on_mission_goal_response(self, future: Any) -> None:
        try:
            goal_handle = future.result()
        except Exception as exc:
            self.mission.update(
                {
                    "status": "failed",
                    "accepted": False,
                    "message": f"ROS 임무 관리자 요청 오류: {exc}",
                }
            )
            return
        if not goal_handle.accepted:
            self.mission.update(
                {
                    "status": "failed",
                    "accepted": False,
                    "message": "ROS 임무 관리자가 순찰 요청을 거부했습니다.",
                }
            )
            return
        self._mission_goal_handle = goal_handle
        self.mission.update(
            {
                "status": "preparing",
                "accepted": True,
                "mock": False,
                "message": "ROS 임무 관리자가 순찰 요청을 수락했습니다.",
            }
        )
        goal_handle.get_result_async().add_done_callback(
            self._on_mission_result
        )

    def _on_mission_result(self, future: Any) -> None:
        try:
            wrapped = future.result()
            result = wrapped.result
            self.mission.update(
                {
                    "status": result.status,
                    "accepted": bool(result.success),
                    "completed_waypoints": int(result.completed_waypoints),
                    "total_distance_m": round(float(result.total_distance_m), 3),
                    "current_index": None,
                    "message": result.message,
                }
            )
        except Exception as exc:
            self.mission.update(
                {
                    "status": "failed",
                    "accepted": False,
                    "message": f"ROS 임무 결과 처리 오류: {exc}",
                }
            )
        finally:
            self._mission_goal_handle = None

    def _on_telemetry(self, message: Any) -> None:
        stamp_seconds = message.stamp.sec + message.stamp.nanosec / 1_000_000_000
        timestamp = datetime.fromtimestamp(stamp_seconds, timezone.utc).isoformat()
        self.store.update(
            {
                "timestamp": timestamp,
                "robot_id": message.robot_id,
                "mode": message.mode,
                "battery_percent": round(float(message.battery_percent), 2),
                "speed_mps": round(float(message.speed_mps), 2),
                "network_quality": message.network_quality,
                "network_rssi_dbm": int(message.network_rssi_dbm),
                "lidar_status": message.lidar_status,
                "lidar_hz": round(float(message.lidar_hz), 2),
                "max_temperature_c": round(float(message.max_temperature_c), 2),
                "alert_level": message.alert_level,
                "controller_enabled": bool(message.controller_enabled),
                "mock": bool(message.mock),
            }
        )

    def _on_map(self, message: Any) -> None:
        try:
            import cv2
            import numpy as np

            width = int(message.info.width)
            height = int(message.info.height)
            if width <= 0 or height <= 0:
                return
            occupancy = np.asarray(message.data, dtype=np.int16).reshape(height, width)
            image = np.full((height, width), 205, dtype=np.uint8)
            image[occupancy == 0] = 250
            image[(occupancy > 0) & (occupancy < 65)] = 150
            image[occupancy >= 65] = 25
            image = np.flipud(image)
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
            ok, encoded = cv2.imencode(
                ".png", image, [cv2.IMWRITE_PNG_COMPRESSION, 3]
            )
            if ok:
                self.media.update(
                    "map",
                    encoded.tobytes(),
                    "image/png",
                    width=width,
                    height=height,
                    source="ros:/map",
                    metadata={
                        "frame_id": message.header.frame_id or "map",
                        "map_id": self.spatial.snapshot()["map"]["map_id"],
                        "resolution": float(message.info.resolution),
                        "origin_x": float(message.info.origin.position.x),
                        "origin_y": float(message.info.origin.position.y),
                    },
                )
                self.spatial.update_map(
                    frame_id=message.header.frame_id or "map",
                    width=width,
                    height=height,
                    resolution=float(message.info.resolution),
                    origin_x=float(message.info.origin.position.x),
                    origin_y=float(message.info.origin.position.y),
                )
        except Exception as exc:
            self.error = f"Map conversion failed: {exc}"

    def _update_spatial_pose(self) -> None:
        if self._tf_buffer is None or self._ros_time_type is None:
            return
        now = time.monotonic()
        if now - self._last_pose_update < 0.18:
            return
        try:
            transform = self._tf_buffer.lookup_transform(
                "map", "base_footprint", self._ros_time_type()
            )
            position = transform.transform.translation
            orientation = transform.transform.rotation
            yaw = math.atan2(
                2.0 * (orientation.w * orientation.z + orientation.x * orientation.y),
                1.0 - 2.0 * (orientation.y**2 + orientation.z**2),
            )
            self.spatial.update_pose(
                x=float(position.x),
                y=float(position.y),
                yaw=yaw,
                frame_id="map",
                mock=False,
            )
            self._last_pose_update = now
        except Exception:
            # TF can be unavailable while SLAM and localization are starting.
            return

    def _on_thermal_detection(self, message: Any) -> None:
        self.spatial.add_detection(
            {
                "detection_id": message.detection_id,
                "frame_id": message.frame_id or "map",
                "x": message.x,
                "y": message.y,
                "z": message.z,
                "temperature_c": message.temperature_c,
                "confidence": message.confidence,
                "radius_m": message.radius_m,
                "source": message.source,
                "simulated": message.simulated,
            },
            live=True,
        )

    def _on_rgb_image(self, message: Any) -> None:
        try:
            import cv2

            frame = self._cv_bridge.imgmsg_to_cv2(message, desired_encoding="bgr8")
            height, width = frame.shape[:2]
            ok, encoded = cv2.imencode(
                ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 82]
            )
            if ok:
                self.media.update(
                    "rgb",
                    encoded.tobytes(),
                    "image/jpeg",
                    width=width,
                    height=height,
                    source="gazebo:/camera/image_raw",
                )

            if not self._thermal_stream_seen:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                thermal = cv2.applyColorMap(gray, cv2.COLORMAP_INFERNO)
                cv2.putText(
                    thermal,
                    "SYNTHETIC THERMAL",
                    (14, 28),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.65,
                    (255, 255, 255),
                    2,
                    cv2.LINE_AA,
                )
                ok, encoded = cv2.imencode(
                    ".jpg", thermal, [cv2.IMWRITE_JPEG_QUALITY, 82]
                )
                if ok:
                    self.media.update(
                        "thermal",
                        encoded.tobytes(),
                        "image/jpeg",
                        width=width,
                        height=height,
                        source="derived:rgb-colormap",
                    )
        except Exception as exc:
            self.error = f"Camera conversion failed: {exc}"

    def _on_thermal_image(self, message: Any) -> None:
        try:
            import cv2
            import numpy as np

            raw = self._cv_bridge.imgmsg_to_cv2(
                message, desired_encoding="passthrough"
            )
            if raw.ndim == 3:
                raw = cv2.cvtColor(raw, cv2.COLOR_BGR2GRAY)
            normalized = cv2.normalize(
                raw.astype(np.float32),
                None,
                0,
                255,
                cv2.NORM_MINMAX,
            ).astype(np.uint8)
            thermal = cv2.applyColorMap(normalized, cv2.COLORMAP_INFERNO)
            cv2.putText(
                thermal,
                "GAZEBO THERMAL - SIMULATED",
                (14, 28),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )
            height, width = thermal.shape[:2]
            ok, encoded = cv2.imencode(
                ".jpg", thermal, [cv2.IMWRITE_JPEG_QUALITY, 82]
            )
            if ok:
                self._thermal_stream_seen = True
                self.media.update(
                    "thermal",
                    encoded.tobytes(),
                    "image/jpeg",
                    width=width,
                    height=height,
                    source="gazebo:/thermal_camera/image_raw",
                )
        except Exception as exc:
            self.error = f"Thermal camera conversion failed: {exc}"

    def command(self, command: str, enabled: bool) -> dict[str, Any]:
        if not self.active or not self._client.wait_for_service(timeout_sec=0.5):
            return self.store.apply_mock_command(command, enabled)

        request = self._request_type()
        request.command = command
        request.enabled = enabled
        future = self._client.call_async(request)
        completed = threading.Event()
        future.add_done_callback(lambda _: completed.set())
        if not completed.wait(timeout=2.0):
            return {
                "command": command,
                "accepted": False,
                "mock": True,
                "message": "ROS 2 명령 응답 시간이 초과되었습니다.",
                "mode": self.store.snapshot()["mode"],
                "controller_enabled": self.store.snapshot()["controller_enabled"],
            }

        try:
            response = future.result()
            return {
                "command": command,
                "accepted": bool(response.accepted),
                "mock": bool(response.mock),
                "message": response.message,
                "mode": response.mode,
                "controller_enabled": bool(response.controller_enabled),
            }
        except Exception as exc:
            return {
                "command": command,
                "accepted": False,
                "mock": True,
                "message": f"ROS 2 명령 처리 오류: {exc}",
                "mode": self.store.snapshot()["mode"],
                "controller_enabled": self.store.snapshot()["controller_enabled"],
            }

    def navigate_to(self, x: float, y: float, yaw: float, frame_id: str) -> dict[str, Any]:
        goal = {
            "frame_id": frame_id,
            "x": round(float(x), 3),
            "y": round(float(y), 3),
            "yaw": round(float(yaw), 4),
            "distance_remaining": None,
            "navigation_time_sec": None,
        }
        self._navigation_result_status = None
        self._navigation_result_event.clear()
        if (
            not self.active
            or self._navigate_action_client is None
            or not self._navigate_action_client.wait_for_server(timeout_sec=0.75)
        ):
            return self.navigation.update(
                {
                    **goal,
                    "status": "mock",
                    "accepted": False,
                    "mock": True,
                    "goal_id": None,
                    "message": "Nav2가 연결되지 않아 목적지를 전송하지 않았습니다.",
                }
            )

        import math

        message = self._navigate_action_type.Goal()
        message.pose.header.frame_id = frame_id
        # A zero timestamp asks TF for the latest transform. This works in both
        # Gazebo simulated time and a real robot's wall/ROS time.
        message.pose.pose.position.x = float(x)
        message.pose.pose.position.y = float(y)
        message.pose.pose.orientation.z = math.sin(float(yaw) / 2.0)
        message.pose.pose.orientation.w = math.cos(float(yaw) / 2.0)

        self.navigation.update(
            {
                **goal,
                "status": "sending",
                "accepted": False,
                "mock": False,
                "goal_id": None,
                "message": "Nav2에 목적지를 전송하고 있습니다.",
            }
        )
        future = self._navigate_action_client.send_goal_async(
            message,
            feedback_callback=self._on_navigation_feedback,
        )
        completed = threading.Event()
        future.add_done_callback(lambda _: completed.set())
        if not completed.wait(timeout=3.0):
            return self.navigation.update(
                {
                    "status": "failed",
                    "accepted": False,
                    "message": "Nav2 목적지 수락 응답 시간이 초과되었습니다.",
                }
            )

        try:
            goal_handle = future.result()
            if not goal_handle.accepted:
                return self.navigation.update(
                    {
                        "status": "rejected",
                        "accepted": False,
                        "message": "Nav2가 목적지를 거부했습니다.",
                    }
                )
            self._navigation_goal_handle = goal_handle
            goal_id = bytes(goal_handle.goal_id.uuid).hex()
            result_future = goal_handle.get_result_async()
            result_future.add_done_callback(self._on_navigation_result)
            return self.navigation.update(
                {
                    "status": "accepted",
                    "accepted": True,
                    "mock": False,
                    "goal_id": goal_id,
                    "message": "Nav2가 목적지를 수락했습니다.",
                }
            )
        except Exception as exc:
            return self.navigation.update(
                {
                    "status": "failed",
                    "accepted": False,
                    "message": f"Nav2 목적지 처리 오류: {exc}",
                }
            )

    def _on_navigation_feedback(self, feedback_message: Any) -> None:
        feedback = feedback_message.feedback
        navigation_time = getattr(feedback, "navigation_time", None)
        navigation_time_sec = None
        if navigation_time is not None:
            navigation_time_sec = round(
                float(navigation_time.sec)
                + float(navigation_time.nanosec) / 1_000_000_000,
                1,
            )
        self.navigation.update(
            {
                "status": "executing",
                "accepted": True,
                "mock": False,
                "distance_remaining": round(
                    float(getattr(feedback, "distance_remaining", 0.0)), 2
                ),
                "navigation_time_sec": navigation_time_sec,
                "message": "Nav2가 목적지로 이동 중입니다.",
            }
        )

    def _on_navigation_result(self, future: Any) -> None:
        try:
            from action_msgs.msg import GoalStatus

            status = int(future.result().status)
            states = {
                GoalStatus.STATUS_SUCCEEDED: (
                    "succeeded",
                    "목적지에 도착했습니다.",
                ),
                GoalStatus.STATUS_CANCELED: (
                    "canceled",
                    "목적지 이동이 취소되었습니다.",
                ),
                GoalStatus.STATUS_ABORTED: (
                    "failed",
                    "Nav2가 목적지 이동을 중단했습니다.",
                ),
            }
            next_status, message = states.get(
                status,
                ("failed", f"Nav2 이동이 상태 코드 {status}로 종료되었습니다."),
            )
            self.navigation.update(
                {
                    "status": next_status,
                    "accepted": next_status == "succeeded",
                    "distance_remaining": 0.0
                    if next_status == "succeeded"
                    else self.navigation.snapshot()["distance_remaining"],
                    "message": message,
                }
            )
            self._navigation_result_status = next_status
        except Exception as exc:
            self.navigation.update(
                {
                    "status": "failed",
                    "accepted": False,
                    "message": f"Nav2 결과 처리 오류: {exc}",
                }
            )
            self._navigation_result_status = "failed"
        finally:
            self._navigation_goal_handle = None
            self._navigation_result_event.set()

    def cancel_navigation(self) -> dict[str, Any]:
        goal_handle = self._navigation_goal_handle
        if goal_handle is None:
            return self.navigation.update(
                {
                    "message": "취소할 활성 목적지가 없습니다.",
                }
            )
        try:
            future = goal_handle.cancel_goal_async()
            completed = threading.Event()
            future.add_done_callback(lambda _: completed.set())
            if not completed.wait(timeout=2.0):
                return self.navigation.update(
                    {
                        "message": "Nav2 취소 응답 시간이 초과되었습니다.",
                    }
                )
            response = future.result()
            accepted = bool(response.goals_canceling)
            return self.navigation.update(
                {
                    "status": "canceling" if accepted else "executing",
                    "accepted": True,
                    "message": "목적지 취소를 요청했습니다."
                    if accepted
                    else "Nav2가 취소 요청을 수락하지 않았습니다.",
                }
            )
        except Exception as exc:
            return self.navigation.update(
                {
                    "message": f"Nav2 취소 처리 오류: {exc}",
                }
            )

    def _current_map_pose(self) -> tuple[float, float] | None:
        pose = self._current_map_pose_with_yaw()
        return (pose[0], pose[1]) if pose is not None else None

    def _current_map_pose_with_yaw(self) -> tuple[float, float, float] | None:
        pose = self.spatial.snapshot().get("pose") or {}
        if not pose.get("available"):
            return None
        try:
            return float(pose["x"]), float(pose["y"]), float(pose["yaw"])
        except (KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def _euclidean_distance(
        start: tuple[float, ...],
        goal: tuple[float, ...],
    ) -> float:
        return math.hypot(goal[0] - start[0], goal[1] - start[1])

    @staticmethod
    def _normalize_angle(angle: float) -> float:
        return math.atan2(math.sin(angle), math.cos(angle))

    @classmethod
    def _pose_errors(
        cls,
        actual: tuple[float, float, float],
        goal: tuple[float, float, float],
    ) -> tuple[float, float]:
        return (
            cls._euclidean_distance(actual, goal),
            abs(cls._normalize_angle(goal[2] - actual[2])),
        )

    @staticmethod
    def _set_pose_yaw(pose: Any, yaw: float) -> None:
        pose.orientation.z = math.sin(float(yaw) / 2.0)
        pose.orientation.w = math.cos(float(yaw) / 2.0)

    def _compute_path_distance(
        self,
        start: tuple[float, float, float],
        goal: tuple[float, float, float],
        frame_id: str,
        *,
        timeout_sec: float = 4.0,
    ) -> tuple[float | None, str | None]:
        client = self._compute_path_action_client
        action_type = self._compute_path_action_type
        if (
            not self.active
            or client is None
            or action_type is None
            or not client.wait_for_server(timeout_sec=3.0)
        ):
            return None, "Nav2 경로 계획 서버에 연결할 수 없습니다."

        goal_message = action_type.Goal()
        goal_message.start.header.frame_id = frame_id
        goal_message.start.pose.position.x = float(start[0])
        goal_message.start.pose.position.y = float(start[1])
        self._set_pose_yaw(goal_message.start.pose, start[2])
        goal_message.goal.header.frame_id = frame_id
        goal_message.goal.pose.position.x = float(goal[0])
        goal_message.goal.pose.position.y = float(goal[1])
        self._set_pose_yaw(goal_message.goal.pose, goal[2])
        goal_message.use_start = True
        goal_message.planner_id = "GridBased"

        send_future = client.send_goal_async(goal_message)
        sent = threading.Event()
        send_future.add_done_callback(lambda _: sent.set())
        if not sent.wait(timeout=timeout_sec):
            return None, "Nav2 경로 요청 수락 시간이 초과됐습니다."
        try:
            goal_handle = send_future.result()
        except Exception as exc:
            return None, f"Nav2 경로 요청 오류: {exc}"
        if not goal_handle.accepted:
            return None, "Nav2가 경로 계산 요청을 거부했습니다."

        result_future = goal_handle.get_result_async()
        completed = threading.Event()
        result_future.add_done_callback(lambda _: completed.set())
        if not completed.wait(timeout=timeout_sec):
            goal_handle.cancel_goal_async()
            return None, "Nav2 경로 계산 시간이 초과됐습니다."
        try:
            wrapped_result = result_future.result()
            path = wrapped_result.result.path
            poses = path.poses
        except Exception as exc:
            return None, f"Nav2 경로 결과 오류: {exc}"
        if len(poses) < 2:
            if self._euclidean_distance(start, goal) < 0.08:
                return 0.0, None
            return None, "목적지까지 유효한 경로가 없습니다."

        distance = 0.0
        previous = poses[0].pose.position
        for pose_stamped in poses[1:]:
            position = pose_stamped.pose.position
            distance += math.hypot(
                float(position.x) - float(previous.x),
                float(position.y) - float(previous.y),
            )
            previous = position
        return round(distance, 4), None

    def recommend_route(self, route: dict[str, Any]) -> dict[str, Any]:
        waypoints = [item for item in route["waypoints"] if item.get("enabled", True)]
        current = self._current_map_pose_with_yaw()
        if current is None:
            return {
                "accepted": False,
                "mock": not self.active,
                "status": "failed",
                "message": "지도상의 현재 로봇 위치를 확인할 수 없습니다.",
                "ordered_ids": [],
                "total_distance_m": 0.0,
            }

        use_nav2 = bool(
            self.active
            and self._compute_path_action_client is not None
            and self._compute_path_action_client.wait_for_server(timeout_sec=2.0)
        )
        remaining = list(waypoints)
        ordered: list[dict[str, Any]] = []
        total_distance = 0.0
        unreachable: list[str] = []

        while remaining:
            candidates: list[tuple[float, dict[str, Any]]] = []
            for waypoint in remaining:
                target = (
                    float(waypoint["x"]),
                    float(waypoint["y"]),
                    float(waypoint.get("yaw", 0.0)),
                )
                if use_nav2:
                    distance, _ = self._compute_path_distance(
                        current,
                        target,
                        route["frame_id"],
                    )
                    if distance is None:
                        unreachable.append(waypoint["id"])
                        continue
                else:
                    distance = self._euclidean_distance(current, target)
                candidates.append((float(distance), waypoint))

            if not candidates:
                return {
                    "accepted": False,
                    "mock": not use_nav2,
                    "status": "failed",
                    "message": "남은 웨이포인트까지 유효한 경로를 찾을 수 없습니다.",
                    "ordered_ids": [item["id"] for item in ordered],
                    "unreachable_ids": sorted(set(unreachable)),
                    "total_distance_m": round(total_distance, 3),
                }

            distance, selected = min(candidates, key=lambda item: item[0])
            ordered.append(selected)
            total_distance += distance
            current = (
                float(selected["x"]),
                float(selected["y"]),
                float(selected.get("yaw", 0.0)),
            )
            remaining = [item for item in remaining if item["id"] != selected["id"]]
            unreachable.clear()

        if route.get("return_to_start") and ordered:
            start_pose = self._current_map_pose_with_yaw()
            if start_pose is not None:
                if use_nav2:
                    return_distance, _ = self._compute_path_distance(
                        current,
                        start_pose,
                        route["frame_id"],
                    )
                    if return_distance is not None:
                        total_distance += return_distance
                else:
                    total_distance += self._euclidean_distance(current, start_pose)

        return {
            "accepted": True,
            "mock": not use_nav2,
            "status": "recommended",
            "message": (
                "Nav2 실제 경로 길이로 순서를 추천했습니다."
                if use_nav2
                else "ROS 미연결 상태에서 직선거리로 순서를 추천했습니다."
            ),
            "ordered_ids": [item["id"] for item in ordered],
            "total_distance_m": round(total_distance, 3),
        }

    def start_route(self, route: dict[str, Any]) -> dict[str, Any]:
        with self._mission_lock:
            current = self.mission.snapshot()
            if current["status"] in {
                "preparing",
                "running",
                "sending",
                "executing",
                "aligning",
                "dwelling",
                "canceling",
            }:
                return {
                    **current,
                    "accepted": False,
                    "message": "이미 실행 중인 순찰 임무가 있습니다.",
                }
            if not self.active:
                return self.mission.update(
                    {
                        "status": "mock",
                        "accepted": False,
                        "mock": True,
                        "message": "ROS 2와 Nav2가 연결되지 않아 순찰을 시작하지 않았습니다.",
                    }
                )
            if (
                self._mission_action_client is None
                or self._mission_action_type is None
                or self._mission_waypoint_type is None
                or not self._mission_action_client.wait_for_server(timeout_sec=2.0)
            ):
                return self.mission.update(
                    {
                        "status": "failed",
                        "accepted": False,
                        "mock": False,
                        "message": (
                            "ROS 임무 관리자에 연결할 수 없습니다. "
                            "순찰 모드와 hazard_guard_mission_manager 노드를 확인하세요."
                        ),
                    }
                )

            self.spatial.clear_trail()
            snapshot = self.mission.begin(route, mock=False)
            goal = self._mission_action_type.Goal()
            goal.mission_id = str(snapshot["mission_id"])
            goal.name = str(route["name"])
            goal.frame_id = str(route["frame_id"])
            goal.return_to_start = bool(route.get("return_to_start", False))
            goal.waypoints = []
            for item in route["waypoints"]:
                if not item.get("enabled", True):
                    continue
                waypoint = self._mission_waypoint_type()
                waypoint.id = str(item["id"])
                waypoint.name = str(item["name"])
                waypoint.x = float(item["x"])
                waypoint.y = float(item["y"])
                waypoint.yaw = float(item.get("yaw", 0.0))
                waypoint.dwell_seconds = float(item.get("dwell_seconds", 0.0))
                goal.waypoints.append(waypoint)

            send_future = self._mission_action_client.send_goal_async(
                goal,
                feedback_callback=self._on_mission_feedback,
            )
            send_future.add_done_callback(self._on_mission_goal_response)
            return snapshot

    def cancel_route(self) -> dict[str, Any]:
        current = self.mission.snapshot()
        if current["status"] not in {
            "preparing",
            "running",
            "sending",
            "executing",
            "aligning",
            "dwelling",
            "canceling",
        }:
            return {
                **current,
                "message": "취소할 활성 순찰 임무가 없습니다.",
            }
        self.mission.update(
            {
                "status": "canceling",
                "message": "순찰 중단을 요청했습니다.",
            }
        )
        if self._mission_goal_handle is not None:
            self._mission_goal_handle.cancel_goal_async()
        elif (
            self._mission_cancel_client is not None
            and self._mission_cancel_request_type is not None
            and self._mission_cancel_client.service_is_ready()
        ):
            request = self._mission_cancel_request_type()
            self._mission_cancel_client.call_async(request)
        else:
            self.mission.update(
                {
                    "status": current["status"],
                    "message": (
                        "ROS 임무 관리자 취소 채널에 연결할 수 없습니다. "
                        "노드 상태를 확인하세요."
                    ),
                }
            )
        return self.mission.snapshot()

    def stop(self) -> None:
        if self._mission_goal_handle is not None:
            self._mission_goal_handle.cancel_goal_async()
        self._stop_event.set()
        if self._executor is not None:
            self._executor.wake()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2)
        if self._executor is not None:
            self._executor.shutdown(timeout_sec=1)
        if self._node is not None:
            self._node.destroy_node()
        if self._context is not None and self._context.ok():
            self._context.shutdown()
        self.active = False


telemetry_store = TelemetryStore()
media_store = MediaStore()
navigation_store = NavigationStore()
route_mission_store = RouteMissionStore()
spatial_store = SpatialStore()
ros_bridge = RosBridge(
    telemetry_store,
    media_store,
    navigation_store,
    route_mission_store,
    spatial_store,
)
