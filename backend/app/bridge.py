from __future__ import annotations

import json
import math
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

from .ros_media import RosMediaAdapter
from .point_cloud import PointCloudAdapter, PointCloudStore
from .sensor_diagnostics import SensorDiagnosticsStore
from .stores import (
    MediaStore,
    NavigationStore,
    RouteMissionStore,
    SpatialStore,
    TelemetryStore,
)


def person_safety_payload(message: Any) -> dict[str, Any]:
    stamp_seconds = message.header.stamp.sec + (
        message.header.stamp.nanosec / 1_000_000_000
    )
    distance_valid = bool(message.distance_valid)
    nearest_distance = float(message.nearest_distance_m)
    return {
        "state": int(message.state),
        "state_name": str(message.state_name),
        "person_count": int(message.person_count),
        "nearest_distance_m": (
            round(nearest_distance, 2)
            if distance_valid and math.isfinite(nearest_distance)
            else None
        ),
        "distance_valid": distance_valid and math.isfinite(nearest_distance),
        "detector_stale": bool(message.detector_stale),
        "reason": str(message.reason),
        "updated_at": datetime.fromtimestamp(
            stamp_seconds, timezone.utc
        ).isoformat(),
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
        point_cloud: PointCloudStore,
        thermal_cloud: PointCloudStore,
        diagnostics: SensorDiagnosticsStore,
    ) -> None:
        self.store = store
        self.media = media
        self.navigation = navigation
        self.mission = mission
        self.spatial = spatial
        self.point_cloud = point_cloud
        self.thermal_cloud = thermal_cloud
        self.diagnostics = diagnostics
        self._point_cloud_adapter = PointCloudAdapter(point_cloud, self._set_error)
        # The thermal map arrives already coloured by temperature, so the same
        # adapter carries it - only the topic differs.
        self._thermal_cloud_adapter = PointCloudAdapter(
            thermal_cloud,
            self._set_error,
            source_env="HAZARD_GUARD_THERMAL_CLOUD_TOPIC",
            source_default="/hazard_guard/thermal/points",
        )
        self._media_adapter = RosMediaAdapter(
            media,
            spatial,
            self._set_error,
        )
        self.active = False
        self.error: str | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._context = None
        self._node = None
        self._executor = None
        self._client = None
        self._request_type = None
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
        self._navigation_goal_handle = None
        self._teleop_publisher = None
        self._teleop_twist_type = None
        self._initial_pose_publisher = None
        self._initial_pose_type = None
        self._teleop_lock = threading.Lock()
        self._navigation_result_event = threading.Event()
        self._navigation_result_status: str | None = None
        self._mission_lock = threading.RLock()
        self._equipment_config_publisher = None
        self._equipment_config_string_type = None
        self._equipment_config_status: dict[str, Any] = {"state": "offline", "equipment": []}
        self._equipment_config_lock = threading.RLock()

        sensor_specs = [
            ("telemetry", "로봇 상태", "/hazard_guard/telemetry", ("patrol",), 3.0),
            ("map", "2D 지도", "/map", ("mapping", "patrol"), 4.0),
            ("lidar", "2D LiDAR", os.getenv("HAZARD_GUARD_SCAN_TOPIC", "/scan"), ("mapping", "patrol"), 2.0),
            ("rgb", "RGB 카메라", os.getenv("HAZARD_GUARD_RGB_TOPIC", "/camera/image_raw"), ("3d", "inspection"), 2.0),
            ("rgb_info", "RGB CameraInfo", os.getenv("HAZARD_GUARD_RGB_INFO_TOPIC", "/camera/camera_info"), ("3d",), 5.0),
            ("depth", "Depth 카메라", os.getenv("HAZARD_GUARD_DEPTH_TOPIC", "/depth_camera/image_raw"), ("3d",), 2.0),
            ("depth_info", "Depth CameraInfo", os.getenv("HAZARD_GUARD_DEPTH_INFO_TOPIC", "/depth_camera/camera_info"), ("3d",), 5.0),
            ("thermal", "열화상 카메라", os.getenv("HAZARD_GUARD_THERMAL_TOPIC", "/thermal_camera/image_raw"), ("inspection",), 2.0),
            ("imu", "IMU", os.getenv("HAZARD_GUARD_IMU_TOPIC", "/imu/data_raw"), ("mapping", "patrol"), 2.0),
            ("odom", "Odometry", os.getenv("HAZARD_GUARD_ODOM_TOPIC", "/odom"), ("mapping", "patrol", "3d"), 2.0),
            ("point_cloud", "RTAB-Map 컬러 클라우드", os.getenv("HAZARD_GUARD_POINT_CLOUD_TOPIC", "/hazard_guard/rtabmap/cloud_surface"), ("3d",), 3.0),
            ("thermal_cloud", "열화상 3D 클라우드", os.getenv("HAZARD_GUARD_THERMAL_CLOUD_TOPIC", "/hazard_guard/thermal/points"), ("3d",), 4.0),
            ("person_safety", "사람 안전 감속", "/hazard_guard/person/safety_state", (), 2.0),
        ]
        for sensor_id, label, topic, required_for, stale_after in sensor_specs:
            self.diagnostics.register(
                sensor_id,
                label=label,
                topic=topic,
                required_for=required_for,
                stale_after_sec=stale_after,
            )

    def _observe(self, sensor_id: str, callback=None):
        def observed(message):
            self.diagnostics.mark(sensor_id)
            if callback is not None:
                callback(message)
        return observed

    def _set_error(self, message: str) -> None:
        self.error = message

    def start(self) -> None:
        if os.getenv("HAZARD_GUARD_ROS_ENABLED", "0") != "1":
            return

        try:
            import rclpy
            from cv_bridge import CvBridge
            from hazard_guard_interfaces.msg import PersonSafetyState, RobotTelemetry
            from hazard_guard_interfaces.srv import RobotCommand
            from nav_msgs.msg import OccupancyGrid, Odometry
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
            from sensor_msgs.msg import CameraInfo, Image, Imu, LaserScan, PointCloud2
            from geometry_msgs.msg import PoseWithCovarianceStamped, Twist
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
            self._media_adapter.configure(
                cv_bridge=CvBridge(),
                tf_buffer=self._tf_buffer,
                ros_time_type=Time,
            )
            self._node.create_subscription(
                RobotTelemetry,
                "/hazard_guard/telemetry",
                self._observe("telemetry", self._on_telemetry),
                10,
            )
            self._node.create_subscription(
                PersonSafetyState,
                "/hazard_guard/person/safety_state",
                self._observe("person_safety", self._on_person_safety),
                10,
            )
            self._node.create_subscription(
                Odometry,
                os.getenv("HAZARD_GUARD_ODOM_TOPIC", "/odom"),
                self._media_adapter.on_odom,
                qos_profile_sensor_data,
            )
            map_qos = QoSProfile(
                depth=1,
                reliability=ReliabilityPolicy.RELIABLE,
                durability=DurabilityPolicy.TRANSIENT_LOCAL,
            )
            self._node.create_subscription(
                OccupancyGrid,
                "/map",
                self._observe("map", self._media_adapter.on_map),
                map_qos,
            )
            self._equipment_config_string_type = String
            self._equipment_config_publisher = self._node.create_publisher(
                String, "/hazard_guard/thermal/equipment_config", map_qos,
            )
            self._node.create_subscription(
                String,
                "/hazard_guard/thermal/equipment_config/status",
                self._on_equipment_config_status,
                map_qos,
            )
            self._node.create_subscription(
                String,
                "/hazard_guard/thermal/trend",
                self._media_adapter.on_thermal_trend,
                10,
            )
            self._node.create_subscription(
                Image,
                os.getenv("HAZARD_GUARD_RGB_TOPIC", "/camera/image_raw"),
                self._observe("rgb", self._media_adapter.on_rgb_image),
                qos_profile_sensor_data,
            )
            self._node.create_subscription(
                PointCloud2,
                os.getenv(
                    "HAZARD_GUARD_POINT_CLOUD_TOPIC",
                    "/hazard_guard/rtabmap/cloud_surface",
                ),
                self._observe("point_cloud", self._point_cloud_adapter.on_cloud),
                qos_profile_sensor_data,
            )
            self._node.create_subscription(
                PointCloud2,
                os.getenv(
                    "HAZARD_GUARD_THERMAL_CLOUD_TOPIC",
                    "/hazard_guard/thermal/points",
                ),
                self._observe("thermal_cloud", self._thermal_cloud_adapter.on_cloud),
                qos_profile_sensor_data,
            )
            self._node.create_subscription(
                Image,
                os.getenv(
                    "HAZARD_GUARD_THERMAL_TOPIC", "/thermal_camera/image_raw"
                ),
                self._observe("thermal", self._media_adapter.on_thermal_image),
                qos_profile_sensor_data,
            )
            diagnostic_topics = [
                (LaserScan, os.getenv("HAZARD_GUARD_SCAN_TOPIC", "/scan"), "lidar"),
                (CameraInfo, os.getenv("HAZARD_GUARD_RGB_INFO_TOPIC", "/camera/camera_info"), "rgb_info"),
                (Image, os.getenv("HAZARD_GUARD_DEPTH_TOPIC", "/depth_camera/image_raw"), "depth"),
                (CameraInfo, os.getenv("HAZARD_GUARD_DEPTH_INFO_TOPIC", "/depth_camera/camera_info"), "depth_info"),
                (Imu, os.getenv("HAZARD_GUARD_IMU_TOPIC", "/imu/data_raw"), "imu"),
                (Odometry, os.getenv("HAZARD_GUARD_ODOM_TOPIC", "/odom"), "odom"),
            ]
            for message_type, topic, sensor_id in diagnostic_topics:
                self._node.create_subscription(
                    message_type,
                    topic,
                    self._observe(sensor_id),
                    qos_profile_sensor_data,
                )
            try:
                from hazard_guard_interfaces.msg import HazardDetection

                detection_qos = QoSProfile(
                    depth=20,
                    reliability=ReliabilityPolicy.RELIABLE,
                    durability=DurabilityPolicy.VOLATILE,
                )
                self._node.create_subscription(
                    HazardDetection,
                    "/hazard_guard/thermal_detections",
                    self._media_adapter.on_thermal_detection,
                    detection_qos,
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
            self._teleop_twist_type = Twist
            self._teleop_publisher = self._node.create_publisher(
                Twist,
                os.getenv("HAZARD_GUARD_CMD_VEL_TOPIC", "/cmd_vel"),
                10,
            )
            self._initial_pose_type = PoseWithCovarianceStamped
            self._initial_pose_publisher = self._node.create_publisher(
                PoseWithCovarianceStamped,
                "/initialpose",
                10,
            )
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
            self._media_adapter.update_spatial_pose()

    def _on_equipment_config_status(self, message: Any) -> None:
        try:
            payload = json.loads(message.data)
        except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return
        with self._equipment_config_lock:
            self._equipment_config_status = payload

    def thermal_equipment_config_status(self) -> dict[str, Any]:
        with self._equipment_config_lock:
            return json.loads(json.dumps(self._equipment_config_status))

    def publish_thermal_equipment_config(
        self, document: dict[str, Any]
    ) -> dict[str, Any]:
        if (
            not self.active
            or self._equipment_config_publisher is None
            or self._equipment_config_string_type is None
        ):
            with self._equipment_config_lock:
                self._equipment_config_status = {
                    "state": "offline",
                    "equipment": [],
                }
            return self.thermal_equipment_config_status()
        message = self._equipment_config_string_type()
        message.data = json.dumps(
            document,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
        self._equipment_config_publisher.publish(message)
        with self._equipment_config_lock:
            previous = self._equipment_config_status
            self._equipment_config_status = {
                "state": "syncing",
                "equipment": previous.get("equipment", []),
            }
        return self.thermal_equipment_config_status()

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

    def publish_initial_pose(self, x: float, y: float, yaw: float) -> dict[str, Any]:
        """Publish a retry burst that lets AMCL recover after a mode switch."""

        if (
            not self.active
            or self._initial_pose_publisher is None
            or self._initial_pose_type is None
        ):
            return {
                "accepted": False,
                "message": "ROS 브리지가 준비되지 않아 초기 위치를 전송하지 못했습니다.",
            }

        # Complete the short discovery burst before returning to the WebUI.
        # This prevents an operator from starting Nav2 while a fixed pose is
        # still being replayed in the background.
        for _ in range(3):
            if self._stop_event.is_set():
                break
            message = self._initial_pose_type()
            # A zero stamp asks tf2/AMCL to use the latest available transform
            # and avoids startup-time extrapolation between odom and map clocks.
            message.header.frame_id = "map"
            message.pose.pose.position.x = float(x)
            message.pose.pose.position.y = float(y)
            message.pose.pose.orientation.z = math.sin(float(yaw) / 2.0)
            message.pose.pose.orientation.w = math.cos(float(yaw) / 2.0)
            message.pose.covariance[0] = 0.25
            message.pose.covariance[7] = 0.25
            message.pose.covariance[35] = 0.0685
            self._initial_pose_publisher.publish(message)
            time.sleep(0.25)
        return {
            "accepted": True,
            "pose": {"x": float(x), "y": float(y), "yaw": float(yaw)},
            "message": "저장된 초기 위치를 AMCL에 다시 전송하고 있습니다.",
        }

    def publish_simulation_teleop(self, direction: str) -> dict[str, Any]:
        """Publish a bounded simulator teleop command to ``/cmd_vel``.

        Access control lives in the WebSocket endpoint. Keeping the ROS adapter
        limited to a small direction vocabulary prevents browser payloads from
        selecting arbitrary velocities.
        """

        commands = {
            "forward": (0.15, 0.0),
            "backward": (-0.12, 0.0),
            "left": (0.0, 0.55),
            "right": (0.0, -0.55),
            "stop": (0.0, 0.0),
        }
        if direction not in commands:
            return {
                "accepted": False,
                "direction": "stop",
                "message": "지원하지 않는 시뮬레이션 조작 명령입니다.",
            }
        if not self.active or self._teleop_publisher is None or self._teleop_twist_type is None:
            return {
                "accepted": False,
                "direction": "stop",
                "message": "ROS 시뮬레이션 브리지가 준비되지 않았습니다.",
            }

        linear_x, angular_z = commands[direction]
        message = self._teleop_twist_type()
        message.linear.x = linear_x
        message.angular.z = angular_z
        with self._teleop_lock:
            self._teleop_publisher.publish(message)
        return {
            "accepted": True,
            "direction": direction,
            "linear_x": linear_x,
            "angular_z": angular_z,
        }

    def stop_simulation_teleop(self) -> dict[str, Any]:
        """Best-effort zero velocity used by release and dead-man handling."""

        return self.stop_motion()

    def stop_motion(self) -> dict[str, Any]:
        """Publish a best-effort zero velocity before changing ROS stacks."""

        return self.publish_simulation_teleop("stop")

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
            "repeat_mode",
            "repeat_count",
            "repeat_interval_sec",
            "current_cycle",
            "total_cycles",
            "completed_cycles",
            "start_at_unix_ms",
            "end_at_unix_ms",
            "next_run_at_unix_ms",
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
                "current_cycle": int(feedback.current_cycle),
                "total_cycles": int(feedback.total_cycles),
                "completed_cycles": int(feedback.completed_cycles),
                "next_run_at_unix_ms": int(feedback.next_run_at_unix_ms),
                "end_at_unix_ms": int(feedback.end_at_unix_ms),
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
                    "completed_cycles": int(result.completed_cycles),
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

    def _on_person_safety(self, message: Any) -> None:
        self.store.update({"person_safety": person_safety_payload(message)})

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
                "scheduled",
                "waiting",
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
            if not hasattr(goal, "repeat_mode"):
                return self.mission.update(
                    {
                        "status": "failed",
                        "accepted": False,
                        "mock": False,
                        "message": (
                            "반복 순찰 인터페이스가 설치되지 않았습니다. "
                            "Robot 워크스페이스를 다시 빌드한 뒤 백엔드를 재시작하세요."
                        ),
                    }
                )
            repeat_modes = {
                "once": 0,
                "count": 1,
                "until_time": 2,
                "forever": 3,
            }
            goal.repeat_mode = repeat_modes[route.get("repeat_mode", "once")]
            goal.repeat_count = int(route.get("repeat_count", 1))
            goal.repeat_interval_sec = float(
                route.get("repeat_interval_seconds", 0.0)
            )
            start_at = route.get("start_at")
            end_at = route.get("end_at")
            goal.start_at_unix_ms = (
                int(start_at.timestamp() * 1000) if start_at is not None else 0
            )
            goal.end_at_unix_ms = (
                int(end_at.timestamp() * 1000) if end_at is not None else 0
            )
            goal.waypoints = []
            for item in route["waypoints"]:
                if not item.get("enabled", True):
                    continue
                waypoint = self._mission_waypoint_type()
                waypoint.id = str(item["id"])
                waypoint.name = str(item["name"])
                if hasattr(waypoint, "equipment_id"):
                    waypoint.equipment_id = str(
                        item.get("equipment_id") or ""
                    )
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
            "scheduled",
            "waiting",
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
        self.stop_simulation_teleop()
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
        self._teleop_publisher = None
        self._teleop_twist_type = None
        self._initial_pose_publisher = None
        self._initial_pose_type = None


telemetry_store = TelemetryStore()
media_store = MediaStore()
navigation_store = NavigationStore()
route_mission_store = RouteMissionStore()
spatial_store = SpatialStore()
point_cloud_store = PointCloudStore()
thermal_cloud_store = PointCloudStore(source="ros:/hazard_guard/thermal/points")
sensor_diagnostics_store = SensorDiagnosticsStore()
ros_bridge = RosBridge(
    telemetry_store,
    media_store,
    navigation_store,
    route_mission_store,
    spatial_store,
    point_cloud_store,
    thermal_cloud_store,
    sensor_diagnostics_store,
)
