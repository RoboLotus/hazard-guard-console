from __future__ import annotations

import math
import os
import struct
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable


PACKET_HEADER = struct.Struct("<4sBBHIIQ")
POINT_RECORD = struct.Struct("<fffBBBB")
PACKET_MAGIC = b"HGPC"
PACKET_VERSION = 1


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PointCloudStore:
    """Thread-safe cache for a browser-ready colored point cloud packet."""

    def __init__(
        self,
        source: str = "ros:/hazard_guard/rtabmap/cloud_surface",
    ) -> None:
        self._lock = threading.RLock()
        self._sequence = 0
        self._packet: bytes | None = None
        self._metadata: dict[str, Any] = {
            "available": False,
            "point_count": 0,
            "color_available": False,
            "frame_id": "map",
            "source": source,
        }

    def update(
        self,
        records: bytes,
        *,
        point_count: int,
        color_available: bool,
        frame_id: str,
        source: str,
    ) -> None:
        timestamp_ms = int(time.time() * 1000)
        with self._lock:
            self._sequence = (self._sequence + 1) & 0xFFFFFFFF
            flags = 1 if color_available else 0
            self._packet = PACKET_HEADER.pack(
                PACKET_MAGIC,
                PACKET_VERSION,
                flags,
                0,
                self._sequence,
                int(point_count),
                timestamp_ms,
            ) + records
            self._metadata = {
                "available": point_count > 0,
                "sequence": self._sequence,
                "point_count": int(point_count),
                "color_available": bool(color_available),
                "frame_id": frame_id or "map",
                "source": source,
                "updated_at": utc_now(),
                "updated_monotonic": time.monotonic(),
            }

    def packet_after(self, sequence: int | None) -> tuple[int, bytes] | None:
        with self._lock:
            if self._packet is None or sequence == self._sequence:
                return None
            return self._sequence, self._packet

    def status(self) -> dict[str, Any]:
        with self._lock:
            metadata = dict(self._metadata)
        updated_monotonic = metadata.pop("updated_monotonic", None)
        if updated_monotonic is not None:
            metadata["age_sec"] = round(
                max(0.0, time.monotonic() - updated_monotonic),
                2,
            )
        return metadata


class PointCloudAdapter:
    """Downsample sensor_msgs/PointCloud2 into compact XYZ/RGB records."""

    _SCALAR_FORMATS = {
        1: "b",   # INT8
        2: "B",   # UINT8
        3: "h",   # INT16
        4: "H",   # UINT16
        5: "i",   # INT32
        6: "I",   # UINT32
        7: "f",   # FLOAT32
        8: "d",   # FLOAT64
    }

    def __init__(
        self,
        store: PointCloudStore,
        on_error: Callable[[str], None],
        source_env: str = "HAZARD_GUARD_POINT_CLOUD_TOPIC",
        source_default: str = "/hazard_guard/rtabmap/cloud_surface",
    ) -> None:
        self.store = store
        self._on_error = on_error
        self._source_env = source_env
        self._source_default = source_default
        self._last_update = 0.0
        self._minimum_interval = float(
            os.getenv("HAZARD_GUARD_POINT_CLOUD_INTERVAL_SEC", "0.75")
        )
        self._maximum_points = int(
            os.getenv("HAZARD_GUARD_POINT_CLOUD_MAX_POINTS", "20000")
        )

    @staticmethod
    def _unpack_scalar(
        data: memoryview,
        offset: int,
        datatype: int,
        endian: str,
    ) -> float | int:
        scalar_format = PointCloudAdapter._SCALAR_FORMATS.get(datatype)
        if scalar_format is None:
            raise ValueError(f"Unsupported PointField datatype: {datatype}")
        return struct.unpack_from(endian + scalar_format, data, offset)[0]

    @staticmethod
    def _packed_rgb(
        data: memoryview,
        offset: int,
        endian: str,
    ) -> tuple[int, int, int]:
        value = struct.unpack_from(endian + "I", data, offset)[0]
        return (value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF

    def on_cloud(self, message: Any) -> None:
        now = time.monotonic()
        if now - self._last_update < self._minimum_interval:
            return
        self._last_update = now

        try:
            fields = {field.name: field for field in message.fields}
            missing = [name for name in ("x", "y", "z") if name not in fields]
            if missing:
                raise ValueError(f"Point cloud is missing fields: {', '.join(missing)}")

            width = int(message.width)
            height = int(message.height)
            point_step = int(message.point_step)
            row_step = int(message.row_step)
            total_points = width * height
            if total_points <= 0 or point_step <= 0:
                return

            packed_color = fields.get("rgb") or fields.get("rgba")
            split_color = all(channel in fields for channel in ("r", "g", "b"))
            color_available = packed_color is not None or split_color
            endian = ">" if bool(message.is_bigendian) else "<"
            data = memoryview(message.data)
            sample_step = max(1, math.ceil(total_points / self._maximum_points))
            records = bytearray()
            point_count = 0

            for index in range(0, total_points, sample_step):
                row, column = divmod(index, width)
                base = row * row_step + column * point_step
                if base + point_step > len(data):
                    break
                x = float(self._unpack_scalar(
                    data, base + fields["x"].offset, fields["x"].datatype, endian
                ))
                y = float(self._unpack_scalar(
                    data, base + fields["y"].offset, fields["y"].datatype, endian
                ))
                z = float(self._unpack_scalar(
                    data, base + fields["z"].offset, fields["z"].datatype, endian
                ))
                if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z)):
                    continue

                if packed_color is not None:
                    red, green, blue = self._packed_rgb(
                        data,
                        base + packed_color.offset,
                        endian,
                    )
                elif split_color:
                    red, green, blue = (
                        int(self._unpack_scalar(
                            data,
                            base + fields[channel].offset,
                            fields[channel].datatype,
                            endian,
                        ))
                        for channel in ("r", "g", "b")
                    )
                else:
                    red, green, blue = 75, 145, 220

                records.extend(POINT_RECORD.pack(
                    x,
                    y,
                    z,
                    max(0, min(255, red)),
                    max(0, min(255, green)),
                    max(0, min(255, blue)),
                    255,
                ))
                point_count += 1
                if point_count >= self._maximum_points:
                    break

            self.store.update(
                bytes(records),
                point_count=point_count,
                color_available=color_available,
                frame_id=getattr(message.header, "frame_id", "map"),
                source=os.getenv(self._source_env, self._source_default),
            )
        except Exception as exc:
            self._on_error(f"Point cloud conversion failed: {exc}")
