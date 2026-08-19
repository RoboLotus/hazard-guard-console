from __future__ import annotations

import json
import math
import time
from collections.abc import Callable
from typing import Any

from .stores import MediaStore, SpatialStore
from .thermal import calibrated_thermal_u8


class RosMediaAdapter:
    """Convert ROS maps and images into browser media and spatial snapshots."""

    def __init__(
        self,
        media: MediaStore,
        spatial: SpatialStore,
        on_error: Callable[[str], None],
    ) -> None:
        self.media = media
        self.spatial = spatial
        self._on_error = on_error
        self._cv_bridge: Any | None = None
        self._tf_buffer: Any | None = None
        self._ros_time_type: Any | None = None
        self._thermal_stream_seen = False
        self._last_pose_update = 0.0
        self._last_odom_update = 0.0
        self._latest_thermal_detections: dict[str, dict[str, Any]] = {}
        self._completed_thermal_trends: dict[str, dict[str, Any]] = {}

    def configure(
        self,
        *,
        cv_bridge: Any,
        tf_buffer: Any,
        ros_time_type: Any,
    ) -> None:
        self._cv_bridge = cv_bridge
        self._tf_buffer = tf_buffer
        self._ros_time_type = ros_time_type

    def on_map(self, message: Any) -> None:
        try:
            import cv2
            import numpy as np

            width = int(message.info.width)
            height = int(message.info.height)
            if width <= 0 or height <= 0:
                return
            occupancy = np.asarray(
                message.data,
                dtype=np.int16,
            ).reshape(height, width)
            image = np.full((height, width), 205, dtype=np.uint8)
            image[occupancy == 0] = 250
            image[(occupancy > 0) & (occupancy < 65)] = 150
            image[occupancy >= 65] = 25
            image = cv2.cvtColor(
                np.flipud(image),
                cv2.COLOR_GRAY2BGR,
            )
            ok, encoded = cv2.imencode(
                ".png",
                image,
                [cv2.IMWRITE_PNG_COMPRESSION, 3],
            )
            if not ok:
                return
            metadata = {
                "frame_id": message.header.frame_id or "map",
                "map_id": self.spatial.snapshot()["map"]["map_id"],
                "resolution": float(message.info.resolution),
                "origin_x": float(message.info.origin.position.x),
                "origin_y": float(message.info.origin.position.y),
            }
            self.media.update(
                "map",
                encoded.tobytes(),
                "image/png",
                width=width,
                height=height,
                source="ros:/map",
                metadata=metadata,
            )
            self.spatial.update_map(
                frame_id=metadata["frame_id"],
                width=width,
                height=height,
                resolution=metadata["resolution"],
                origin_x=metadata["origin_x"],
                origin_y=metadata["origin_y"],
            )
        except Exception as exc:
            self._on_error(f"Map conversion failed: {exc}")

    def update_spatial_pose(self) -> None:
        if self._tf_buffer is None or self._ros_time_type is None:
            return
        now = time.monotonic()
        if now - self._last_pose_update < 0.18:
            return
        try:
            transform = self._tf_buffer.lookup_transform(
                "map",
                "base_footprint",
                self._ros_time_type(),
            )
            position = transform.transform.translation
            orientation = transform.transform.rotation
            yaw = math.atan2(
                2.0 * (
                    orientation.w * orientation.z
                    + orientation.x * orientation.y
                ),
                1.0 - 2.0 * (orientation.y**2 + orientation.z**2),
            )
            self.spatial.update_pose(
                x=float(position.x),
                y=float(position.y),
                z=float(getattr(position, "z", 0.0)),
                yaw=yaw,
                frame_id="map",
                mock=False,
            )
            self._last_pose_update = now
        except Exception:
            return

    def on_odom(self, message: Any) -> None:
        """Keep the browser pose live while SLAM is still stabilizing map TF."""
        now = time.monotonic()
        if now - self._last_odom_update < 0.08:
            return
        try:
            pose = message.pose.pose
            orientation = pose.orientation
            yaw = math.atan2(
                2.0 * (
                    orientation.w * orientation.z
                    + orientation.x * orientation.y
                ),
                1.0 - 2.0 * (orientation.y**2 + orientation.z**2),
            )
            source_frame = str(
                getattr(getattr(message, "header", None), "frame_id", "")
                or "odom"
            )
            x = float(pose.position.x)
            y = float(pose.position.y)
            z = float(getattr(pose.position, "z", 0.0))
            self.spatial.update_frame_pose(
                x=x,
                y=y,
                z=z,
                yaw=yaw,
                frame_id=source_frame,
                mock=False,
            )
            self._last_odom_update = now
            if now - self._last_pose_update < 0.5:
                return
            frame_id = source_frame
            if (
                source_frame != "map"
                and self._tf_buffer is not None
                and self._ros_time_type is not None
            ):
                try:
                    stamp = getattr(
                        getattr(message, "header", None), "stamp", None
                    )
                    if stamp is not None and hasattr(
                        self._ros_time_type, "from_msg"
                    ):
                        lookup_time = self._ros_time_type.from_msg(stamp)
                    else:
                        lookup_time = self._ros_time_type()
                    transform = self._tf_buffer.lookup_transform(
                        "map", source_frame, lookup_time
                    ).transform
                    q = transform.rotation
                    transform_yaw = math.atan2(
                        2.0 * (q.w * q.z + q.x * q.y),
                        1.0 - 2.0 * (q.y**2 + q.z**2),
                    )
                    cos_yaw = math.cos(transform_yaw)
                    sin_yaw = math.sin(transform_yaw)
                    x, y = (
                        float(transform.translation.x)
                        + cos_yaw * x
                        - sin_yaw * y,
                        float(transform.translation.y)
                        + sin_yaw * x
                        + cos_yaw * y,
                    )
                    z += float(transform.translation.z)
                    yaw += transform_yaw
                    frame_id = "map"
                except Exception:
                    pass
            self.spatial.update_pose(
                x=x,
                y=y,
                z=z,
                yaw=yaw,
                frame_id=frame_id,
                mock=False,
            )
        except Exception as exc:
            self._on_error(f"Odometry conversion failed: {exc}")

    def on_thermal_detection(self, message: Any) -> None:
        frame_id = message.frame_id or "map"
        x = float(message.x)
        y = float(message.y)
        z = float(message.z)
        if frame_id != "map" and self._tf_buffer is not None and self._ros_time_type is not None:
            try:
                transform = self._tf_buffer.lookup_transform(
                    "map", frame_id, self._ros_time_type()
                ).transform
                q = transform.rotation
                yaw = math.atan2(
                    2.0 * (q.w * q.z + q.x * q.y),
                    1.0 - 2.0 * (q.y**2 + q.z**2),
                )
                cos_yaw = math.cos(yaw)
                sin_yaw = math.sin(yaw)
                x, y = (
                    float(transform.translation.x) + cos_yaw * x - sin_yaw * y,
                    float(transform.translation.y) + sin_yaw * x + cos_yaw * y,
                )
                z += float(transform.translation.z)
                frame_id = "map"
            except Exception:
                pass

        source = str(message.source)
        equipment_id = None
        trend_status = None
        trend_reason = None
        visit_index = None
        if source.startswith("thermal_trend:"):
            parts = source.split(":")
            if len(parts) >= 3:
                equipment_id = parts[1]
                trend_status = parts[2]
                trend_reason = parts[3] if len(parts) >= 4 else None
                if len(parts) >= 5 and parts[4].startswith("visit-"):
                    try:
                        visit_index = int(parts[4].removeprefix("visit-"))
                    except ValueError:
                        visit_index = None
        detection = {
            "detection_id": message.detection_id,
            "frame_id": frame_id,
            "x": x,
            "y": y,
            "z": z,
            "temperature_c": message.temperature_c,
            "confidence": message.confidence,
            "radius_m": message.radius_m,
            "source": source,
            "equipment_id": equipment_id,
            "trend_status": trend_status,
            "trend_reason": trend_reason,
            "visit_index": visit_index,
            "simulated": message.simulated,
        }
        completed = None
        if equipment_id:
            self._latest_thermal_detections[equipment_id] = dict(detection)
            completed = self._completed_thermal_trends.get(equipment_id)
            if completed:
                detection.update(completed)
        self.spatial.add_detection(
            detection,
            live=True,
            completed_visit=completed is not None,
        )

    def on_thermal_trend(self, message: Any) -> None:
        """Attach one completed-visit decision to each live map detection."""

        try:
            payload = json.loads(message.data)
        except (AttributeError, json.JSONDecodeError, TypeError):
            return
        trend = payload.get("trend_analysis", {})
        visit_index = trend.get("visit_index")
        if not isinstance(visit_index, int):
            return
        severity = {"normal": 0, "watch": 1, "warning": 2, "critical": 3}
        for equipment in payload.get("equipment", []):
            if not isinstance(equipment, dict):
                continue
            equipment_id = str(equipment.get("equipment_id", ""))
            equipment_name = str(equipment.get("display_name") or equipment_id)
            live = self._latest_thermal_detections.get(equipment_id)
            completed = dict(live) if live else {
                "detection_id": f"thermal-{equipment_id}",
                "frame_id": str(payload.get("frame_id") or "map"),
                "x": 0.0,
                "y": 0.0,
                "z": 0.0,
                "temperature_c": 0.0,
                "confidence": 0.0,
                "radius_m": 0.04,
                "equipment_id": equipment_id,
                "equipment_name": equipment_name,
                "simulated": True,
            }
            status = str(equipment.get("trend_status", "normal"))
            decisions = []
            candidates = []
            for voxel in equipment.get("voxels", []):
                if not isinstance(voxel, dict):
                    continue
                decision = voxel.get("trend_analysis", {})
                if not isinstance(decision, dict):
                    continue
                reason = str(decision.get("reason", "within_expected_range"))
                voxel_status = str(decision.get("status", "normal"))
                decisions.append((voxel_status, reason))
                p95 = float(voxel.get("p95_temperature_c", 0.0))
                peak = float(voxel.get("max_temperature_c", p95))
                reported_temperature = (
                    peak if bool(decision.get("critical_max")) else p95
                )
                candidates.append((
                    severity.get(voxel_status, 0),
                    reported_temperature,
                    voxel,
                ))
            if candidates:
                _severity, temperature, hottest = max(
                    candidates, key=lambda item: (item[0], item[1])
                )
                completed["temperature_c"] = temperature
                hottest_decision = hottest.get("trend_analysis", {})
                if isinstance(hottest_decision, dict):
                    completed.update(
                        policy_mode=hottest_decision.get("policy_mode"),
                        adaptive_threshold_enabled=hottest_decision.get(
                            "adaptive_threshold_enabled"
                        ),
                        baseline_temperature_c=hottest_decision.get(
                            "baseline_temperature_c"
                        ),
                        baseline_residual_c=hottest_decision.get(
                            "baseline_residual_c"
                        ),
                        baseline_residual_threshold_c=hottest_decision.get(
                            "baseline_residual_threshold_c"
                        ),
                        effective_adaptive_threshold_c=hottest_decision.get(
                            "effective_adaptive_threshold_c"
                        ),
                    )
                center = hottest.get("center", [])
                equipment_name=equipment_name,
                if len(center) >= 3:
                    completed.update(x=center[0], y=center[1], z=center[2])
            reason = "within_expected_range"
            matching = [item for item in decisions if item[0] == status]
            if matching:
                reason = matching[0][1]
            completed.update(
                detection_id=f"thermal-{equipment_id}",
                trend_status=status,
                trend_reason=reason,
                visit_index=visit_index,
                source=(
                    f"thermal_trend:{equipment_id}:{status}:{reason}:"
                    f"visit-{visit_index}"
                ),
            )
            self._completed_thermal_trends[equipment_id] = dict(completed)
            if live:
                self.spatial.add_detection(
                    completed, live=True, completed_visit=True
                )

    def on_rgb_image(self, message: Any) -> None:
        if self._cv_bridge is None:
            return
        try:
            import cv2

            frame = self._cv_bridge.imgmsg_to_cv2(
                message,
                desired_encoding="bgr8",
            )
            height, width = frame.shape[:2]
            self._store_jpeg(
                "rgb",
                frame,
                width,
                height,
                "gazebo:/camera/image_raw",
            )
            if self._thermal_stream_seen:
                return
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            thermal = cv2.applyColorMap(gray, cv2.COLORMAP_INFERNO)
            self._label_image(thermal, "SYNTHETIC THERMAL", 0.65)
            self._store_jpeg(
                "thermal",
                thermal,
                width,
                height,
                "derived:rgb-colormap",
            )
        except Exception as exc:
            self._on_error(f"Camera conversion failed: {exc}")

    def on_thermal_image(self, message: Any) -> None:
        if self._cv_bridge is None:
            return
        try:
            import cv2
            raw = self._cv_bridge.imgmsg_to_cv2(
                message,
                desired_encoding="passthrough",
            )
            if raw.ndim == 3:
                raw = cv2.cvtColor(raw, cv2.COLOR_BGR2GRAY)
            normalized = calibrated_thermal_u8(raw, message.encoding)
            thermal = cv2.applyColorMap(
                normalized,
                cv2.COLORMAP_INFERNO,
            )
            self._label_image(
                thermal,
                "GAZEBO THERMAL - SIMULATED",
                0.55,
            )
            height, width = thermal.shape[:2]
            self._thermal_stream_seen = True
            self._store_jpeg(
                "thermal",
                thermal,
                width,
                height,
                "gazebo:/thermal_camera/image_raw",
            )
        except Exception as exc:
            self._on_error(f"Thermal camera conversion failed: {exc}")

    def _store_jpeg(
        self,
        kind: str,
        frame: Any,
        width: int,
        height: int,
        source: str,
    ) -> None:
        import cv2

        ok, encoded = cv2.imencode(
            ".jpg",
            frame,
            [cv2.IMWRITE_JPEG_QUALITY, 82],
        )
        if ok:
            self.media.update(
                kind,
                encoded.tobytes(),
                "image/jpeg",
                width=width,
                height=height,
                source=source,
            )

    @staticmethod
    def _label_image(frame: Any, label: str, scale: float) -> None:
        import cv2

        cv2.putText(
            frame,
            label,
            (14, 28),
            cv2.FONT_HERSHEY_SIMPLEX,
            scale,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
