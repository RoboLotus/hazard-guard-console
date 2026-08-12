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


def test_thermal_detection_keeps_session_peak_from_cooler_later_view():
    spatial = SpatialStore()
    adapter = RosMediaAdapter(MediaStore(), spatial, lambda _message: None)
    hot = SimpleNamespace(
        detection_id="thermal-motor", frame_id="map",
        x=1.0, y=2.0, z=0.4, temperature_c=64.5,
        confidence=0.9, radius_m=0.3,
        source="thermal_trend:motor:warning", simulated=True,
    )
    cool = SimpleNamespace(
        detection_id="thermal-motor", frame_id="map",
        x=1.4, y=2.3, z=0.1, temperature_c=15.0,
        confidence=0.4, radius_m=0.04,
        source="thermal_trend:motor:normal", simulated=True,
    )

    adapter.on_thermal_detection(hot)
    adapter.on_thermal_detection(cool)

    detection = spatial.snapshot()["heatmap"]["detections"][0]
    assert detection["temperature_c"] == 64.5
    assert detection["x"] == 1.0
    assert detection["y"] == 2.0
    assert detection["trend_status"] == "warning"


def test_physical_target_waits_for_ros_without_animating_mock_data(monkeypatch):
    monkeypatch.setenv("HAZARD_GUARD_DEPLOYMENT_TARGET", "physical")

    snapshot = SpatialStore().snapshot()

    assert snapshot["source"] == "waiting"
    assert snapshot["mock"] is False
    assert snapshot["pose"]["available"] is False
    assert snapshot["trail"] == []
    assert snapshot["heatmap"]["detections"] == []
    assert snapshot["map"]["source"] == "pending:/map"


def test_odometry_updates_live_browser_pose_without_tf():
    spatial = SpatialStore()
    adapter = RosMediaAdapter(MediaStore(), spatial, lambda _message: None)
    message = SimpleNamespace(
        header=SimpleNamespace(frame_id="odom"),
        pose=SimpleNamespace(
            pose=SimpleNamespace(
                position=SimpleNamespace(x=1.25, y=-0.75),
                orientation=SimpleNamespace(x=0.0, y=0.0, z=0.0, w=1.0),
            )
        ),
    )

    adapter.on_odom(message)

    pose = spatial.snapshot()["pose"]
    assert pose["mock"] is False
    assert pose["frame_id"] == "map"
    assert pose["x"] == 1.25
    assert pose["y"] == -0.75
    assert pose["yaw"] == 0.0


def test_recent_map_tf_pose_is_not_overwritten_by_raw_odometry():
    spatial = SpatialStore()
    adapter = RosMediaAdapter(MediaStore(), spatial, lambda _message: None)
    spatial.update_pose(
        x=4.0, y=5.0, yaw=0.25, frame_id="map", mock=False
    )
    adapter._last_pose_update = __import__("time").monotonic()
    message = SimpleNamespace(
        pose=SimpleNamespace(
            pose=SimpleNamespace(
                position=SimpleNamespace(x=1.25, y=-0.75),
                orientation=SimpleNamespace(x=0.0, y=0.0, z=0.0, w=1.0),
            )
        ),
    )

    adapter.on_odom(message)

    pose = spatial.snapshot()["pose"]
    assert pose["x"] == 4.0
    assert pose["y"] == 5.0
    assert pose["yaw"] == 0.25


def test_trend_metadata_is_forwarded_to_browser():
    spatial = SpatialStore()
    adapter = RosMediaAdapter(MediaStore(), spatial, lambda _message: None)
    message = SimpleNamespace(
        detection_id="thermal-motor",
        frame_id="map",
        x=1.0,
        y=2.0,
        z=0.4,
        temperature_c=52.5,
        confidence=0.9,
        radius_m=0.3,
        source="thermal_trend:motor:warning",
        simulated=True,
    )

    adapter.on_thermal_detection(message)

    detection = spatial.snapshot()["heatmap"]["detections"][0]
    assert detection["equipment_id"] == "motor"
    assert detection["trend_status"] == "warning"


def test_thermal_detection_is_transformed_from_odom_to_map():
    spatial = SpatialStore()
    adapter = RosMediaAdapter(MediaStore(), spatial, lambda _message: None)
    transform = SimpleNamespace(
        transform=SimpleNamespace(
            translation=SimpleNamespace(x=10.0, y=-2.0, z=0.0),
            rotation=SimpleNamespace(x=0.0, y=0.0, z=0.0, w=1.0),
        )
    )
    buffer = SimpleNamespace(lookup_transform=lambda *_args: transform)
    adapter.configure(cv_bridge=None, tf_buffer=buffer, ros_time_type=lambda: None)
    message = SimpleNamespace(
        detection_id="thermal-motor",
        frame_id="odom",
        x=1.0,
        y=2.0,
        z=0.4,
        temperature_c=52.5,
        confidence=0.9,
        radius_m=0.3,
        source="thermal_trend:motor:normal",
        simulated=True,
    )

    adapter.on_thermal_detection(message)

    detection = spatial.snapshot()["heatmap"]["detections"][0]
    assert detection["frame_id"] == "map"
    assert detection["x"] == 11.0
    assert detection["y"] == 0.0


def test_completed_visit_trend_is_not_overwritten_by_live_frame():
    import json

    spatial = SpatialStore()
    adapter = RosMediaAdapter(MediaStore(), spatial, lambda _message: None)
    live = SimpleNamespace(
        detection_id="thermal-motor", frame_id="map",
        x=1.0, y=2.0, z=0.4, temperature_c=64.5,
        confidence=0.9, radius_m=0.3,
        source="thermal_trend:motor:watch:environment_adjusted_anomaly_only",
        simulated=True,
    )
    adapter.on_thermal_detection(live)
    adapter.on_thermal_trend(SimpleNamespace(data=json.dumps({
        "trend_analysis": {"visit_index": 3},
        "equipment": [{
            "equipment_id": "motor",
            "trend_status": "warning",
            "voxels": [{
                "center": [1.1, 2.1, 0.4],
                "p95_temperature_c": 62.0,
                "trend_analysis": {
                    "status": "warning",
                    "reason": "persistent_trend_and_environment_adjusted_anomaly",
                },
            }],
        }],
    })))
    later = SimpleNamespace(
        detection_id="thermal-motor", frame_id="map",
        x=1.3, y=2.3, z=0.4, temperature_c=50.0,
        confidence=0.8, radius_m=0.3,
        source="thermal_trend:motor:watch:environment_adjusted_anomaly_only",
        simulated=True,
    )
    adapter.on_thermal_detection(later)

    detection = spatial.snapshot()["heatmap"]["detections"][0]
    assert detection["visit_index"] == 3
    assert detection["trend_status"] == "warning"
    assert detection["trend_reason"] == (
        "persistent_trend_and_environment_adjusted_anomaly"
    )
    assert detection["source"].endswith(":visit-3")

def test_completed_visit_before_live_frame_restores_visit_metadata():
    import json

    spatial = SpatialStore()
    adapter = RosMediaAdapter(MediaStore(), spatial, lambda _message: None)
    adapter.on_thermal_trend(SimpleNamespace(data=json.dumps({
        "frame_id": "map",
        "trend_analysis": {"visit_index": 4},
        "equipment": [{
            "equipment_id": "motor",
            "trend_status": "warning",
            "voxels": [{
                "center": [1.1, 2.1, 0.4],
                "p95_temperature_c": 63.0,
                "trend_analysis": {
                    "status": "warning",
                    "reason": "persistent_trend_only",
                },
            }],
        }],
    })))
    adapter.on_thermal_detection(SimpleNamespace(
        detection_id="thermal-motor", frame_id="map",
        x=1.0, y=2.0, z=0.4, temperature_c=61.0,
        confidence=0.9, radius_m=0.3,
        source="thermal_trend:motor:watch:environment_adjusted_anomaly_only",
        simulated=True,
    ))

    detection = spatial.snapshot()["heatmap"]["detections"][0]
    assert detection["visit_index"] == 4
    assert detection["trend_status"] == "warning"
    assert detection["trend_reason"] == "persistent_trend_only"
    assert detection["temperature_c"] == 63.0