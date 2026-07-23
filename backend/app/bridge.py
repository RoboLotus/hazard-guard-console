from __future__ import annotations

import math
import os
import threading
import time
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
            result[kind] = {
                "available": now - item["updated_monotonic"] < 5.0,
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


class SpatialStore:
    """Live map-space state used by the 2D digital-twin overlays."""

    SENSOR_SPECS = [
        {
            "id": "depth",
            "label": "Depth",
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
            "model": "TOPDON TC001",
            "horizontal_fov_deg": 56.0,
            "range_min_m": 0.1,
            "range_max_m": 5.0,
            "range_note": "제조사 권장 유효 온도 측정거리",
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
        self._map = dict(self.MOCK_MAP)
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
        spatial: SpatialStore,
    ) -> None:
        self.store = store
        self.media = media
        self.navigation = navigation
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
        self._navigation_goal_handle = None
        self._last_pose_update = 0.0

    def start(self) -> None:
        if os.getenv("HAZARD_GUARD_ROS_ENABLED", "0") != "1":
            return

        try:
            import rclpy
            from cv_bridge import CvBridge
            from hazard_guard_interfaces.msg import RobotTelemetry
            from nav_msgs.msg import OccupancyGrid
            from nav2_msgs.action import NavigateToPose
            from rclpy.action import ActionClient
            from hazard_guard_interfaces.srv import RobotCommand
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
                "/hazard_guard_rgb_camera/image_raw",
                self._on_rgb_image,
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
                    source="gazebo:/hazard_guard_rgb_camera/image_raw",
                )

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
        message.pose.header.stamp = self._node.get_clock().now().to_msg()
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
        except Exception as exc:
            self.navigation.update(
                {
                    "status": "failed",
                    "accepted": False,
                    "message": f"Nav2 결과 처리 오류: {exc}",
                }
            )
        finally:
            self._navigation_goal_handle = None

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

    def stop(self) -> None:
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
spatial_store = SpatialStore()
ros_bridge = RosBridge(
    telemetry_store,
    media_store,
    navigation_store,
    spatial_store,
)
