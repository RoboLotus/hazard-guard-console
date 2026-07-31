from types import SimpleNamespace

from app.ros_media import RosMediaAdapter
from app.stores import MediaStore, SpatialStore


def test_thermal_detection_is_forwarded_to_spatial_store():
    spatial = SpatialStore()
    adapter = RosMediaAdapter(MediaStore(), spatial, lambda _message: None)
    message = SimpleNamespace(
        detection_id="hot-motor",
        frame_id="map",
        x=1.0,
        y=2.0,
        z=0.4,
        temperature_c=82.5,
        confidence=0.91,
        radius_m=0.3,
        source="simulation:motor",
        simulated=True,
    )

    adapter.on_thermal_detection(message)

    detection = spatial.snapshot()["heatmap"]["detections"][0]
    assert detection["detection_id"] == "hot-motor"
    assert detection["temperature_c"] == 82.5
    assert detection["simulated"] is True
