import struct
from types import SimpleNamespace

from app.point_cloud import (
    PACKET_HEADER,
    PACKET_MAGIC,
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
    magic, version, flags, _, packet_sequence, point_count, _ = (
        PACKET_HEADER.unpack_from(packet)
    )
    assert magic == PACKET_MAGIC
    assert version == 1
    assert flags & 1
    assert packet_sequence == sequence
    assert point_count == 2
    assert POINT_RECORD.unpack_from(packet, PACKET_HEADER.size) == (
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
    point = POINT_RECORD.unpack_from(packet, PACKET_HEADER.size)
    assert point[3:6] == (75, 145, 220)
    assert store.status()["color_available"] is False
