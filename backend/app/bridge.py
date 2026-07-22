from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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

    def __init__(self, store: TelemetryStore) -> None:
        self.store = store
        self.active = False
        self.error: str | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._context = None
        self._node = None
        self._executor = None
        self._client = None
        self._request_type = None

    def start(self) -> None:
        if os.getenv("HAZARD_GUARD_ROS_ENABLED", "0") != "1":
            return

        try:
            import rclpy
            from hazard_guard_interfaces.msg import RobotTelemetry
            from hazard_guard_interfaces.srv import RobotCommand
            from rclpy.context import Context
            from rclpy.executors import SingleThreadedExecutor
            from rclpy.node import Node

            self._context = Context()
            rclpy.init(context=self._context)
            self._node = Node("hazard_guard_web_bridge", context=self._context)
            self._node.create_subscription(
                RobotTelemetry,
                "/hazard_guard/telemetry",
                self._on_telemetry,
                10,
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
ros_bridge = RosBridge(telemetry_store)
