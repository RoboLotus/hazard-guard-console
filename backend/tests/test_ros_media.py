from types import SimpleNamespace

from app.ros_media import RosMediaAdapter
from app.stores import MediaStore, SpatialStore


def test_sdk_color_thermal_frame_is_stored_without_recolouring():
    import cv2
    import numpy as np

    media = MediaStore()
    adapter = RosMediaAdapter(media, SpatialStore(), lambda _message: None)
    frame = np.zeros((16, 32, 3), dtype=np.uint8)
    frame[:, :16] = (10, 20, 230)
    frame[:, 16:] = (220, 30, 5)
    bridge = SimpleNamespace(imgmsg_to_cv2=lambda *_args, **_kwargs: frame)
    adapter.configure(cv_bridge=bridge, tf_buffer=None, ros_time_type=None)

    adapter.on_thermal_color_image(SimpleNamespace(encoding="bgr8"))

    stored = media.get("thermal")
    decoded = cv2.imdecode(np.frombuffer(stored["content"], np.uint8), cv2.IMREAD_COLOR)
    assert stored["source"] == "ros:/thermal_camera/image_color"
    assert stored["width"] == 32
    assert stored["height"] == 16
    assert decoded[8, 8, 2] > decoded[8, 8, 0]
    assert decoded[8, 24, 0] > decoded[8, 24, 2]


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

    snapshot = spatial.snapshot()
    pose = snapshot["pose"]
    assert pose["mock"] is False
    assert pose["frame_id"] == "odom"
    assert pose["x"] == 1.25
    assert pose["y"] == -0.75
    assert pose["z"] == 0.0
    assert pose["yaw"] == 0.0
    assert snapshot["poses"]["odom"] == pose



def test_odometry_is_transformed_from_odom_to_map():
    import math

    spatial = SpatialStore()
    adapter = RosMediaAdapter(MediaStore(), spatial, lambda _message: None)
    half_yaw = math.pi / 4.0
    transform = SimpleNamespace(
        transform=SimpleNamespace(
            translation=SimpleNamespace(x=10.0, y=-2.0, z=0.0),
            rotation=SimpleNamespace(
                x=0.0,
                y=0.0,
                z=math.sin(half_yaw),
                w=math.cos(half_yaw),
            ),
        )
    )
    buffer = SimpleNamespace(lookup_transform=lambda *_args: transform)
    adapter.configure(cv_bridge=None, tf_buffer=buffer, ros_time_type=lambda: None)
    message = SimpleNamespace(
        header=SimpleNamespace(frame_id="odom"),
        pose=SimpleNamespace(
            pose=SimpleNamespace(
                position=SimpleNamespace(x=1.0, y=0.0),
                orientation=SimpleNamespace(x=0.0, y=0.0, z=0.0, w=1.0),
            )
        ),
    )

    adapter.on_odom(message)

    snapshot = spatial.snapshot()
    pose = snapshot["pose"]
    assert pose["frame_id"] == "map"
    assert abs(pose["x"] - 10.0) < 1e-6
    assert abs(pose["y"] + 1.0) < 1e-6
    assert abs(pose["yaw"] - math.pi / 2.0) < 1e-4
    assert snapshot["poses"]["odom"]["x"] == 1.0
    assert snapshot["poses"]["map"] == pose

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

    snapshot = spatial.snapshot()
    pose = snapshot["pose"]
    assert pose["x"] == 4.0
    assert pose["y"] == 5.0
    assert pose["yaw"] == 0.25
    assert snapshot["poses"]["odom"]["x"] == 1.25


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
                    "policy_mode": "adaptive_assisted",
                    "adaptive_threshold_enabled": True,
                    "baseline_temperature_c": 50.0,
                    "baseline_residual_c": 12.0,
                    "baseline_residual_threshold_c": 10.0,
                    "effective_adaptive_threshold_c": 70.0,
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
    assert detection["policy_mode"] == "adaptive_assisted"
    assert detection["baseline_residual_c"] == 12.0
    assert detection["effective_adaptive_threshold_c"] == 70.0

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

def test_completed_visit_uses_max_for_max_only_critical_temperature():
    import json

    spatial = SpatialStore()
    adapter = RosMediaAdapter(MediaStore(), spatial, lambda _message: None)
    adapter.on_thermal_trend(SimpleNamespace(data=json.dumps({
        "frame_id": "map",
        "trend_analysis": {"visit_index": 5},
        "equipment": [{
            "equipment_id": "motor",
            "trend_status": "critical",
            "voxels": [{
                "center": [1.1, 2.1, 0.4],
                "p95_temperature_c": 62.0,
                "max_temperature_c": 82.5,
                "trend_analysis": {
                    "status": "critical",
                    "reason": "critical_max_temperature",
                    "critical_max": True,
                },
            }],
        }],
    })))
    adapter.on_thermal_detection(SimpleNamespace(
        detection_id="thermal-motor", frame_id="map",
        x=1.0, y=2.0, z=0.4, temperature_c=62.0,
        confidence=0.9, radius_m=0.3,
        source="thermal_trend:motor:normal:within_expected_range",
        simulated=True,
    ))

    detection = spatial.snapshot()["heatmap"]["detections"][0]
    assert detection["trend_status"] == "critical"
    assert detection["trend_reason"] == "critical_max_temperature"
    assert detection["temperature_c"] == 82.5
