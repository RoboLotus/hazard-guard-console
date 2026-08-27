from types import SimpleNamespace
import struct

import pytest

from app.thermal_delta import (
    PROTOCOL_VERSION,
    STATIC_THERMAL_DELTA,
    ThermalDeltaAdapter,
    ThermalDeltaError,
    ThermalDeltaStore,
    inspect_delta,
)


HEADER = struct.Struct("<4sHBBQQHH")


def make_static_delta(
    sequence: int,
    *,
    base_sequence: int | None = None,
    session_id: str = "session-a",
    fingerprint: str = "fingerprint-a",
) -> bytes:
    base = sequence - 1 if base_sequence is None else base_sequence
    session = session_id.encode()
    encoded_fingerprint = fingerprint.encode()
    return (
        HEADER.pack(
            b"HGTD", PROTOCOL_VERSION, STATIC_THERMAL_DELTA, 0,
            sequence, base, len(session), len(encoded_fingerprint),
        )
        + session
        + encoded_fingerprint
        + struct.pack("<I", 1)
        + struct.pack("<Iff", sequence, 20.0 + sequence, 0.75)
    )


def test_binary_delta_is_validated_stored_and_relayed_without_reencoding() -> None:
    store = ThermalDeltaStore(maximum_packets=10, maximum_bytes=10_000)
    packet = make_static_delta(1)

    metadata = store.accept(packet)
    recovery = store.recover(
        session_id="session-a",
        geometry_fingerprint="fingerprint-a",
        base_sequence=0,
    )

    assert metadata.sequence == 1
    assert recovery.status == "REPLAY_AVAILABLE"
    assert recovery.packets[0] is packet


def test_continuous_history_replays_only_missing_sequences() -> None:
    store = ThermalDeltaStore(maximum_packets=10, maximum_bytes=10_000)
    packets = [make_static_delta(sequence) for sequence in range(1, 5)]
    for packet in packets:
        store.accept(packet)

    recovery = store.recover(
        session_id="session-a",
        geometry_fingerprint="fingerprint-a",
        base_sequence=2,
    )
    assert recovery.status == "REPLAY_AVAILABLE"
    assert recovery.packets == tuple(packets[2:])
    assert store.recover(
        session_id="session-a",
        geometry_fingerprint="fingerprint-a",
        base_sequence=4,
    ).status == "UP_TO_DATE"


def test_gap_and_evicted_history_require_resync() -> None:
    gap = ThermalDeltaStore(maximum_packets=10, maximum_bytes=10_000)
    gap.reset("session-a", "fingerprint-a")
    gap.accept(make_static_delta(1))
    gap.accept(make_static_delta(3, base_sequence=2))
    assert gap.recover(
        session_id="session-a",
        geometry_fingerprint="fingerprint-a",
        base_sequence=1,
    ).reason == "sequence_not_in_history"

    bounded = ThermalDeltaStore(maximum_packets=2, maximum_bytes=10_000)
    for sequence in range(1, 4):
        bounded.accept(make_static_delta(sequence))
    recovery = bounded.recover(
        session_id="session-a",
        geometry_fingerprint="fingerprint-a",
        base_sequence=0,
    )
    assert recovery.status == "RESYNC_REQUIRED"
    assert bounded.bootstrap()["history_packet_count"] == 2


def test_identity_mismatch_requires_resync() -> None:
    store = ThermalDeltaStore(maximum_packets=10, maximum_bytes=10_000)
    store.accept(make_static_delta(1))

    assert store.recover(
        session_id="other",
        geometry_fingerprint="fingerprint-a",
        base_sequence=0,
    ).reason == "session_id_mismatch"
    assert store.recover(
        session_id="session-a",
        geometry_fingerprint="other",
        base_sequence=0,
    ).reason == "geometry_fingerprint_mismatch"


def test_new_identity_requires_robot_sequence_reset() -> None:
    store = ThermalDeltaStore(maximum_packets=10, maximum_bytes=10_000)
    store.accept(make_static_delta(1))
    with pytest.raises(ThermalDeltaError, match="identity mismatch"):
        store.accept(make_static_delta(2, session_id="session-b"))

    packet = make_static_delta(
        1, base_sequence=0, session_id="session-b", fingerprint="fingerprint-b"
    )
    store.accept(packet)
    assert store.bootstrap()["latest_sequence"] == 1
    assert store.bootstrap()["session_id"] == "session-b"


def test_adapter_preserves_bytes_object_and_reports_invalid_packet() -> None:
    store = ThermalDeltaStore(maximum_packets=10, maximum_bytes=10_000)
    errors = []
    adapter = ThermalDeltaAdapter(store, errors.append)
    packet = make_static_delta(1)
    adapter.on_message(SimpleNamespace(data=packet))
    recovery = store.recover(
        session_id="session-a",
        geometry_fingerprint="fingerprint-a",
        base_sequence=0,
    )
    assert recovery.packets[0] is packet

    adapter.on_message(SimpleNamespace(data=b"invalid"))
    assert errors and "rejected" in errors[-1]


def test_inspector_rejects_bad_sequence_and_record_length() -> None:
    with pytest.raises(ThermalDeltaError, match="sequence"):
        inspect_delta(make_static_delta(3, base_sequence=1))
    with pytest.raises(ThermalDeltaError, match="record counts"):
        inspect_delta(make_static_delta(1)[:-1])
