import struct
from types import SimpleNamespace

from app.point_cloud import (
    PACKET_HEADER,
    PACKET_MAGIC,
    PACKET_VERSION,
    POINT_RECORD,
    PointCloudAdapter,
    PointCloudStore,
)


def field(name: str, offset: int, datatype: int) -> SimpleNamespace:
    return SimpleNamespace(name=name, offset=offset, datatype=datatype)


def test_rgb_point_cloud_is_packed_for_the_browser():
    store = PointCloudStore()
    errors = []
    adapter = PointCloudAdapter(store, errors.append)
    adapter._minimum_interval = 0
    red = (230 << 16) | (40 << 8) | 30
    green = (35 << 16) | (210 << 8) | 75
    message = SimpleNamespace(
        fields=[
            field("x", 0, 7),
            field("y", 4, 7),
            field("z", 8, 7),
            field("rgb", 12, 7),
        ],
        width=2,
        height=1,
        point_step=16,
        row_step=32,
        is_bigendian=False,
        data=(
            struct.pack("<fffI", 1.0, 2.0, 0.5, red)
            + struct.pack("<fffI", -1.0, 0.25, 1.5, green)
        ),
        header=SimpleNamespace(frame_id="map"),
    )

    adapter.on_cloud(message)

    assert errors == []
    sequence, packet = store.packet_after(None)
    magic, version, flags, frame_id_bytes, packet_sequence, point_count, _ = (
        PACKET_HEADER.unpack_from(packet)
    )
    assert magic == PACKET_MAGIC
    assert version == PACKET_VERSION == 2
    assert packet[PACKET_HEADER.size:PACKET_HEADER.size + frame_id_bytes] == b"map"
    assert flags & 1
    assert packet_sequence == sequence
    assert point_count == 2
    assert POINT_RECORD.unpack_from(
        packet, PACKET_HEADER.size + frame_id_bytes
    ) == (
        1.0,
        2.0,
        0.5,
        230,
        40,
        30,
        255,
    )
    assert store.status()["color_available"] is True


def test_cloud_without_rgb_uses_a_clear_fallback_color():
    store = PointCloudStore()
    adapter = PointCloudAdapter(store, lambda _message: None)
    adapter._minimum_interval = 0
    message = SimpleNamespace(
        fields=[field("x", 0, 7), field("y", 4, 7), field("z", 8, 7)],
        width=1,
        height=1,
        point_step=12,
        row_step=12,
        is_bigendian=False,
        data=struct.pack("<fff", 0.0, 0.0, 0.0),
        header=SimpleNamespace(frame_id="map"),
    )

    adapter.on_cloud(message)

    _, packet = store.packet_after(None)
    frame_id_bytes = PACKET_HEADER.unpack_from(packet)[3]
    point = POINT_RECORD.unpack_from(
        packet, PACKET_HEADER.size + frame_id_bytes
    )
    assert point[3:6] == (75, 145, 220)
    assert store.status()["color_available"] is False


def test_packet_rejects_an_unbounded_frame_id():
    store = PointCloudStore()

    try:
        store.update(
            b"",
            point_count=0,
            color_available=False,
            frame_id="m" * 256,
            source="test:/cloud",
        )
    except ValueError as error:
        assert "frame_id" in str(error)
    else:
        raise AssertionError("oversized frame_id must be rejected")
