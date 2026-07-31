from __future__ import annotations

import math
import time
from collections.abc import Callable
from typing import Any

from .stores import MediaStore, SpatialStore


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
                yaw=yaw,
                frame_id="map",
                mock=False,
            )
            self._last_pose_update = now
        except Exception:
            return

    def on_thermal_detection(self, message: Any) -> None:
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
            import numpy as np

            raw = self._cv_bridge.imgmsg_to_cv2(
                message,
                desired_encoding="passthrough",
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
