"""Validated, byte-preserving cache for Robot thermal-map delta packets."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import os
import struct
import threading
from typing import Any


MAGIC = b"HGTD"
PROTOCOL_VERSION = 1
STATIC_THERMAL_DELTA = 1
DYNAMIC_DELTA = 2

_HEADER = struct.Struct("<4sHBBQQHH")
_COUNT = struct.Struct("<I")
_DYNAMIC_COUNTS = struct.Struct("<III")
STATIC_RECORD_SIZE = struct.calcsize("<Iff")
DYNAMIC_RECORD_SIZE = struct.calcsize("<iiiff")
DYNAMIC_DELETE_SIZE = struct.calcsize("<iii")


class ThermalDeltaError(ValueError):
    pass


@dataclass(frozen=True)
class ThermalDeltaMetadata:
    protocol_version: int
    packet_type: int
    session_id: str
    geometry_fingerprint: str
    sequence: int
    base_sequence: int
    packet_size: int


@dataclass(frozen=True)
class DeltaRecovery:
    status: str
    packets: tuple[bytes, ...] = ()
    reason: str = ""


def inspect_delta(packet: bytes) -> ThermalDeltaMetadata:
    """Validate framing and counts without unpacking individual voxel records."""
    if len(packet) < _HEADER.size:
        raise ThermalDeltaError("truncated delta header")
    values = _HEADER.unpack_from(packet)
    magic, version, packet_type, flags, sequence, base, session_len, fp_len = values
    if magic != MAGIC:
        raise ThermalDeltaError("invalid delta magic")
    if version != PROTOCOL_VERSION:
        raise ThermalDeltaError("unsupported delta protocol version")
    if packet_type not in (STATIC_THERMAL_DELTA, DYNAMIC_DELTA):
        raise ThermalDeltaError("unsupported delta packet type")
    if flags != 0:
        raise ThermalDeltaError("unsupported delta flags")
    if sequence != base + 1:
        raise ThermalDeltaError("delta sequence must equal base_sequence + 1")
    offset = _HEADER.size
    metadata_end = offset + session_len + fp_len
    if metadata_end > len(packet):
        raise ThermalDeltaError("truncated delta metadata")
    try:
        session_id = packet[offset:offset + session_len].decode("utf-8")
        offset += session_len
        fingerprint = packet[offset:offset + fp_len].decode("utf-8")
        offset += fp_len
    except UnicodeDecodeError as exc:
        raise ThermalDeltaError("invalid delta metadata UTF-8") from exc
    if packet_type == STATIC_THERMAL_DELTA:
        if offset + _COUNT.size > len(packet):
            raise ThermalDeltaError("truncated static delta count")
        (count,) = _COUNT.unpack_from(packet, offset)
        expected = offset + _COUNT.size + count * STATIC_RECORD_SIZE
    else:
        if offset + _DYNAMIC_COUNTS.size > len(packet):
            raise ThermalDeltaError("truncated dynamic delta counts")
        created, updated, deleted = _DYNAMIC_COUNTS.unpack_from(packet, offset)
        expected = (
            offset + _DYNAMIC_COUNTS.size
            + (created + updated) * DYNAMIC_RECORD_SIZE
            + deleted * DYNAMIC_DELETE_SIZE
        )
    if expected != len(packet):
        raise ThermalDeltaError("delta packet size does not match record counts")
    return ThermalDeltaMetadata(
        version, packet_type, session_id, fingerprint, sequence, base, len(packet)
    )


class ThermalDeltaStore:
    """Bounded ordered history that retains the exact received bytes object."""

    def __init__(
        self,
        *,
        maximum_packets: int | None = None,
        maximum_bytes: int | None = None,
    ) -> None:
        self.maximum_packets = max(1, maximum_packets or int(os.getenv(
            "HAZARD_GUARD_THERMAL_DELTA_HISTORY_PACKETS", "512"
        )))
        self.maximum_bytes = max(1, maximum_bytes or int(os.getenv(
            "HAZARD_GUARD_THERMAL_DELTA_HISTORY_BYTES", str(8 * 1024 * 1024)
        )))
        self._lock = threading.RLock()
        self._history: deque[tuple[ThermalDeltaMetadata, bytes]] = deque()
        self._history_bytes = 0
        self._session_id: str | None = None
        self._fingerprint: str | None = None
        self._latest_sequence = 0

    def reset(
        self,
        session_id: str | None = None,
        geometry_fingerprint: str | None = None,
    ) -> None:
        with self._lock:
            self._history.clear()
            self._history_bytes = 0
            self._session_id = session_id
            self._fingerprint = geometry_fingerprint
            self._latest_sequence = 0

    def accept(self, packet: bytes | bytearray | memoryview) -> ThermalDeltaMetadata:
        # ROS adapters pass bytes, so the common path preserves object identity.
        immutable = packet if isinstance(packet, bytes) else bytes(packet)
        metadata = inspect_delta(immutable)
        with self._lock:
            identity = (metadata.session_id, metadata.geometry_fingerprint)
            current = (self._session_id, self._fingerprint)
            if current != identity:
                if metadata.base_sequence != 0:
                    raise ThermalDeltaError(
                        "delta identity mismatch without a sequence reset"
                    )
                self.reset(*identity)
            if metadata.sequence <= self._latest_sequence:
                existing = next((
                    item for item in self._history
                    if item[0].sequence == metadata.sequence
                ), None)
                if existing is not None and existing[1] == immutable:
                    return metadata
                raise ThermalDeltaError("stale or conflicting delta sequence")
            self._history.append((metadata, immutable))
            self._history_bytes += len(immutable)
            self._latest_sequence = metadata.sequence
            while (
                len(self._history) > self.maximum_packets
                or self._history_bytes > self.maximum_bytes
            ):
                _, removed = self._history.popleft()
                self._history_bytes -= len(removed)
        return metadata

    def recover(
        self,
        *,
        session_id: str,
        geometry_fingerprint: str,
        base_sequence: int,
    ) -> DeltaRecovery:
        with self._lock:
            if session_id != self._session_id:
                return DeltaRecovery("RESYNC_REQUIRED", reason="session_id_mismatch")
            if geometry_fingerprint != self._fingerprint:
                return DeltaRecovery(
                    "RESYNC_REQUIRED", reason="geometry_fingerprint_mismatch"
                )
            if base_sequence == self._latest_sequence:
                return DeltaRecovery("UP_TO_DATE")
            if base_sequence > self._latest_sequence:
                return DeltaRecovery("RESYNC_REQUIRED", reason="sequence_ahead")
            expected_base = base_sequence
            packets = []
            for metadata, packet in self._history:
                if metadata.sequence <= base_sequence:
                    continue
                if metadata.base_sequence != expected_base:
                    return DeltaRecovery(
                        "RESYNC_REQUIRED", reason="sequence_not_in_history"
                    )
                packets.append(packet)
                expected_base = metadata.sequence
            if not packets or expected_base != self._latest_sequence:
                return DeltaRecovery(
                    "RESYNC_REQUIRED", reason="sequence_not_in_history"
                )
            return DeltaRecovery("REPLAY_AVAILABLE", tuple(packets))

    def bootstrap(self) -> dict[str, Any]:
        with self._lock:
            return {
                "available": self._session_id is not None and self._fingerprint is not None,
                "session_id": self._session_id,
                "geometry_fingerprint": self._fingerprint,
                "protocol_version": PROTOCOL_VERSION,
                "latest_sequence": self._latest_sequence,
                "history_packet_count": len(self._history),
                "history_bytes": self._history_bytes,
                "history_max_packets": self.maximum_packets,
                "history_max_bytes": self.maximum_bytes,
                "snapshot_fallback_websocket": "/ws/pointcloud/thermal",
            }


class ThermalDeltaAdapter:
    def __init__(self, store: ThermalDeltaStore, on_error) -> None:
        self.store = store
        self._on_error = on_error

    def on_message(self, message: Any) -> None:
        try:
            data = message.data
            packet = data if isinstance(data, bytes) else bytes(data)
            self.store.accept(packet)
        except (AttributeError, TypeError, ValueError, ThermalDeltaError) as exc:
            self._on_error(f"Thermal delta rejected: {exc}")
