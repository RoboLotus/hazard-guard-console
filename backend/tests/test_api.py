from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import bridge
from app import main as main_module
from app.bridge import MediaStore
from app.point_cloud import POINT_RECORD
from app.main import app


client = TestClient(app)


def test_health_reports_mock_mode():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "mode": "mock",
        "ros_bridge": False,
        "deployment_target": "simulation",
        "capabilities": {
            "navigate_to_pose": False,
            "compute_path_to_pose": False,
            "mission_manager": False,
        },
    }


def test_thresholds_validate_temperature_order():
    response = client.put(
        "/api/v1/settings/thresholds",
        json={
            "warningTemperature": 80,
            "warningDuration": 5,
            "criticalTemperature": 70,
            "criticalDuration": 3,
            "clearTemperature": 50,
            "clearDuration": 10,
            "warningRepeat": 60,
            "criticalRepeat": 30,
        },
    )
    assert response.status_code == 422


def test_mock_command_never_claims_hardware_action():
    response = client.post("/api/v1/commands/stop")
    assert response.status_code == 200
    assert response.json()["mock"] is True


def test_robot_status_exposes_dashboard_telemetry_contract():
    response = client.get("/api/v1/robot/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["robot_id"] == "rosmaster-m1-mock"
    assert isinstance(payload["battery_percent"], float)
    assert payload["lidar_status"] == "normal"
    assert payload["person_safety"]["state_name"] == "CLEAR"


def test_person_safety_payload_normalizes_invalid_distance():
    message = SimpleNamespace(
        header=SimpleNamespace(
            stamp=SimpleNamespace(sec=1_750_000_000, nanosec=500_000_000)
        ),
        state=4,
        state_name="SENSOR_FAULT",
        person_count=1,
        nearest_distance_m=float("nan"),
        distance_valid=True,
        detector_stale=True,
        reason="depth stream stale",
    )

    payload = bridge.person_safety_payload(message)

    assert payload["state_name"] == "SENSOR_FAULT"
    assert payload["nearest_distance_m"] is None
    assert payload["distance_valid"] is False
    assert payload["detector_stale"] is True


def test_system_mode_status_exposes_webui_control_contract():
    response = client.get("/api/v1/system/mode")
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] in {"idle", "mapping", "rgbd_mapping", "patrol"}
    assert "control_enabled" in payload
    assert "map_available" in payload
    assert "managed" in payload
    assert payload["deployment_target"] == "simulation"
    assert "navigation_ready" in payload
    assert set(payload["readiness"]) == {
        "navigate_to_pose",
        "compute_path_to_pose",
        "mission_manager",
        "localized_pose",
    }


def test_system_mode_marks_stale_rtabmap_cloud_as_not_live(monkeypatch):
    monkeypatch.setattr(
        main_module.point_cloud_store,
        "status",
        lambda: {
            "available": True,
            "point_count": 42,
            "color_available": True,
            "source": "/hazard_guard/rtabmap/cloud_surface",
            "age_sec": 2.1,
        },
    )

    payload = client.get("/api/v1/system/mode").json()

    assert payload["rtabmap"]["live"] is False
    assert payload["rtabmap"]["point_count"] == 42
    assert payload["rtabmap"]["age_sec"] == 2.1


def test_system_mode_switch_routes_validated_mode_to_manager(monkeypatch):
    expected = {
        "mode": "mapping",
        "state": "starting",
        "accepted": True,
        "managed": True,
        "control_enabled": True,
        "pid": 123,
        "map_path": "runtime/maps/facility.yaml",
        "map_available": False,
        "message": "SLAM 지도 생성 모드를 시작하고 있습니다.",
        "started_at": "2026-07-30T00:00:00+00:00",
        "updated_at": "2026-07-30T00:00:00+00:00",
        "exit_code": None,
    }
    monkeypatch.setattr(
        main_module.system_mode_manager,
        "switch_mode",
        lambda mode, mapping_profile="toolbox", patrol_slam=False: {
            **expected,
            "mode": mode,
            "mapping_profile": mapping_profile,
            "patrol_slam": patrol_slam,
        },
    )

    response = client.put("/api/v1/system/mode", json={"mode": "mapping"})

    assert response.status_code == 200
    assert response.json()["mode"] == "mapping"
    assert response.json()["state"] == "starting"


def test_system_mode_rejects_unknown_mode():
    response = client.put("/api/v1/system/mode", json={"mode": "teleop"})
    assert response.status_code == 422


def test_system_mode_rejects_unknown_mapping_profile():
    response = client.put(
        "/api/v1/system/mode",
        json={"mode": "mapping", "mapping_profile": "unknown"},
    )
    assert response.status_code == 422


def test_localization_initial_pose_can_be_retried_in_running_patrol(monkeypatch):
    recorded = {}
    monkeypatch.setattr(
        main_module,
        "system_mode_status",
        lambda: {"mode": "patrol", "state": "running"},
    )
    monkeypatch.setattr(
        main_module.system_mode_manager,
        "set_localization_pose",
        lambda pose: recorded.update(pose) or pose,
    )
    monkeypatch.setattr(main_module.spatial_store, "reset_for_localization", lambda: None)
    monkeypatch.setattr(
        main_module.ros_bridge,
        "publish_initial_pose",
        lambda x, y, yaw: {
            "accepted": True,
            "pose": {"x": x, "y": y, "yaw": yaw},
            "message": "초기 위치 전송",
        },
    )

    response = client.post(
        "/api/v1/system/localization/initialize",
        json={"x": 1.2, "y": -0.4, "yaw": 0.5},
    )

    assert response.status_code == 200
    assert recorded == {"x": 1.2, "y": -0.4, "yaw": 0.5}
    assert response.json()["accepted"] is True


def test_save_and_stop_endpoint_returns_manager_result(monkeypatch):
    monkeypatch.setattr(
        main_module.system_mode_manager,
        "save_map_and_stop",
        lambda: {
            "accepted": True,
            "mode": "idle",
            "state": "stopped",
            "message": "저장 후 종료",
        },
    )

    response = client.post("/api/v1/system/map/save-and-stop")

    assert response.status_code == 200
    assert response.json()["state"] == "stopped"


def test_map_session_metadata_can_be_updated(monkeypatch):
    monkeypatch.setattr(
        main_module.system_mode_manager,
        "edit_map_session",
        lambda world_id, session_id, **values: {
            "accepted": True,
            "message": "updated",
            "session": {"id": session_id, "world_id": world_id, **values},
        },
    )

    response = client.patch(
        "/api/v1/system/maps/facility/session-1",
        json={"name": "1차 지도", "archived": True},
    )

    assert response.status_code == 200
    assert response.json()["session"]["name"] == "1차 지도"
    assert response.json()["session"]["archived"] is True


def test_saved_cloud_is_served_inline(monkeypatch, tmp_path):
    cloud = tmp_path / "cloud.ply"
    cloud.write_bytes(b"ply\n")
    monkeypatch.setattr(
        main_module.system_mode_manager,
        "export_map_cloud",
        lambda _world_id, _session_id: {
            "accepted": True,
            "path": cloud,
            "message": "ready",
        },
    )

    response = client.get("/api/v1/system/maps/facility/session-1/cloud.ply")

    assert response.status_code == 200
    assert response.content == b"ply\n"
    assert response.headers["content-disposition"].startswith("inline")


def test_media_status_is_explicit_when_ros_streams_are_unavailable():
    response = client.get("/api/v1/media/status")
    assert response.status_code == 200
    assert response.json() == {
        "map": {"available": False},
        "rgb": {"available": False},
        "thermal": {"available": False},
    }


def test_unavailable_media_uses_service_unavailable_response():
    response = client.get("/api/v1/media/map")
    assert response.status_code == 503
    assert response.json()["detail"] == "map stream is not ready"


def test_static_map_remains_available_while_camera_stream_expires(monkeypatch):
    store = MediaStore()
    store.update(
        "map",
        b"map",
        "image/png",
        width=10,
        height=10,
        source="ros:/map",
    )
    store.update(
        "rgb",
        b"rgb",
        "image/jpeg",
        width=10,
        height=10,
        source="ros:/camera",
    )
    updated_at = bridge.time.monotonic()
    monkeypatch.setattr(bridge.time, "monotonic", lambda: updated_at + 6.0)

    status = store.status()

    assert status["map"]["available"] is True
    assert status["rgb"]["available"] is False


def test_controller_command_updates_fallback_telemetry():
    response = client.post(
        "/api/v1/commands/controller", json={"enabled": True}
    )
    assert response.status_code == 200
    assert response.json()["controller_enabled"] is True
    status = client.get("/api/v1/robot/status").json()
    assert status["controller_enabled"] is True


def test_navigation_goal_never_claims_nav2_action_in_mock_mode():
    response = client.post(
        "/api/v1/navigation/goal",
        json={"x": 1.25, "y": -0.75, "yaw": 0.0, "frame_id": "map"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["accepted"] is False
    assert payload["status"] == "mock"
    assert payload["mock"] is True
    assert payload["mock"] is True
    assert payload["status"] == "mock"
    assert payload["x"] == 1.25
    assert payload["y"] == -0.75


def test_navigation_goal_validates_frame_id():
    response = client.post(
        "/api/v1/navigation/goal",
        json={"x": 0, "y": 0, "yaw": 0, "frame_id": "../map"},
    )
    assert response.status_code == 422


def test_navigation_status_and_cancel_are_safe_without_active_goal():
    cancel = client.delete("/api/v1/navigation/goal")
    assert cancel.status_code == 200
    assert "활성 목적지" in cancel.json()["message"]

    status = client.get("/api/v1/navigation/status")
    assert status.status_code == 200
    assert status.json()["mock"] is True


def test_route_recommendation_is_safe_and_deterministic_in_mock_mode():
    route = {
        "name": "테스트 순찰",
        "frame_id": "map",
        "return_to_start": False,
        "waypoints": [
            {
                "id": "wp-a",
                "name": "A",
                "x": -2.0,
                "y": -2.0,
                "yaw": 0,
                "dwell_seconds": 0,
                "enabled": True,
            },
            {
                "id": "wp-b",
                "name": "B",
                "x": 2.0,
                "y": 2.0,
                "yaw": 0,
                "dwell_seconds": 1,
                "enabled": True,
            },
        ],
    }
    response = client.post("/api/v1/navigation/route/recommend", json=route)
    assert response.status_code == 200
    payload = response.json()
    assert payload["accepted"] is True
    assert payload["mock"] is True
    assert set(payload["ordered_ids"]) == {"wp-a", "wp-b"}
    assert payload["total_distance_m"] > 0


def test_route_start_never_claims_motion_without_ros():
    response = client.post(
        "/api/v1/navigation/route",
        json={
            "name": "Mock route",
            "frame_id": "map",
            "waypoints": [
                {
                    "id": "mock-1",
                    "name": "점검구역",
                    "x": 0,
                    "y": 0,
                    "yaw": 0,
                    "dwell_seconds": 0,
                    "enabled": True,
                }
            ],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["accepted"] is False


def test_route_schedule_requires_an_end_time_for_clock_based_patrol():
    response = client.post(
        "/api/v1/navigation/route/recommend",
        json={
            "name": "Work-hours patrol",
            "frame_id": "map",
            "repeat_mode": "until_time",
            "repeat_interval_seconds": 600,
            "waypoints": [
                {
                    "id": "clock-1",
                    "name": "Clock waypoint",
                    "x": 0,
                    "y": 0,
                }
            ],
        },
    )

    assert response.status_code == 422


def test_route_schedule_accepts_timezone_aware_start_and_end_times():
    response = client.post(
        "/api/v1/navigation/route/recommend",
        json={
            "name": "Work-hours patrol",
            "frame_id": "map",
            "repeat_mode": "until_time",
            "repeat_interval_seconds": 600,
            "start_at": "2099-08-11T09:00:00+09:00",
            "end_at": "2099-08-11T18:00:00+09:00",
            "waypoints": [
                {
                    "id": "clock-1",
                    "name": "Clock waypoint",
                    "x": 0,
                    "y": 0,
                }
            ],
        },
    )

    assert response.status_code == 200


def test_route_start_rejects_mapping_mode_before_ros_motion(monkeypatch):
    monkeypatch.setattr(
        main_module.system_mode_manager,
        "snapshot",
        lambda: {
            "control_enabled": True,
            "mode": "mapping",
            "state": "running",
        },
    )

    response = client.post(
        "/api/v1/navigation/route",
        json={
            "name": "Blocked mapping route",
            "frame_id": "map",
            "waypoints": [
                {
                    "id": "mapping-1",
                    "name": "점검구역",
                    "x": 0,
                    "y": 0,
                    "yaw": 0,
                    "dwell_seconds": 0,
                    "enabled": True,
                }
            ],
        },
    )

    assert response.status_code == 409
    assert "맵 생성 모드" in response.json()["detail"]


def test_navigation_goal_waits_for_patrol_mode_to_be_ready(monkeypatch):
    monkeypatch.setattr(
        main_module.system_mode_manager,
        "snapshot",
        lambda: {
            "control_enabled": True,
            "mode": "patrol",
            "state": "starting",
        },
    )

    response = client.post(
        "/api/v1/navigation/goal",
        json={"x": 1.0, "y": 1.0, "yaw": 0.0, "frame_id": "map"},
    )

    assert response.status_code == 409
    assert "시작하고 있습니다" in response.json()["detail"]


def test_navigation_goal_waits_for_nav2_and_localization_readiness(monkeypatch):
    monkeypatch.setattr(
        main_module.system_mode_manager,
        "snapshot",
        lambda: {
            "control_enabled": True,
            "mode": "patrol",
            "state": "running",
        },
    )
    monkeypatch.setattr(
        main_module.ros_bridge,
        "capability_status",
        lambda: {
            "navigate_to_pose": False,
            "compute_path_to_pose": False,
            "mission_manager": False,
        },
    )

    response = client.post(
        "/api/v1/navigation/goal",
        json={"x": 1.0, "y": 1.0, "yaw": 0.0, "frame_id": "map"},
    )

    assert response.status_code == 409
    assert "준비를 기다리고 있습니다" in response.json()["detail"]


def test_route_rejects_duplicate_waypoint_ids():
    waypoint = {
        "id": "duplicate",
        "name": "중복",
        "x": 0,
        "y": 0,
        "yaw": 0,
        "dwell_seconds": 0,
        "enabled": True,
    }
    response = client.post(
        "/api/v1/navigation/route",
        json={
            "name": "Invalid route",
            "frame_id": "map",
            "waypoints": [waypoint, {**waypoint, "x": 1}],
        },
    )
    assert response.status_code == 422


def test_telemetry_websocket_sends_snapshot_and_closes_cleanly():
    with client.websocket_connect("/ws/telemetry") as websocket:
        payload = websocket.receive_json()
        assert payload["robot_id"] == "rosmaster-m1-mock"
        assert "timestamp" in payload


def test_spatial_status_exposes_pose_sensor_specs_and_heatmap():
    response = client.get("/api/v1/spatial/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["pose"]["available"] is True
    assert payload["poses"]["map"]["available"] is True
    assert payload["map"]["frame_id"] == "map"
    assert payload["heatmap"]["available"] is True

    sensors = {sensor["id"]: sensor for sensor in payload["sensors"]}
    assert sensors["depth"]["horizontal_fov_deg"] == 73.8
    assert sensors["depth"]["range_max_m"] == 4.0
    assert sensors["thermal"]["model"] == "ThermoEye TMC160B"
    assert sensors["thermal"]["resolution"] == "160×120"
    assert sensors["thermal"]["horizontal_fov_deg"] == 57.0
    assert sensors["thermal"]["frame_rate_hz"] == 8.7
    assert sensors["thermal"]["range_note"].startswith("시뮬레이션")
    assert sensors["thermal"]["range_max_m"] == 5.0


def test_spatial_detection_can_be_ingested_without_claiming_real_sensor_data():
    response = client.post(
        "/api/v1/spatial/detections",
        json={
            "detection_id": "api-simulation-source",
            "frame_id": "map",
            "x": 1.2,
            "y": -0.4,
            "temperature_c": 71.5,
            "confidence": 0.88,
            "radius_m": 0.3,
            "source": "test:simulation",
            "simulated": True,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["detection_id"] == "api-simulation-source"
    assert payload["temperature_c"] == 71.5
    assert payload["simulated"] is True


def test_spatial_detection_validates_temperature_and_confidence():
    response = client.post(
        "/api/v1/spatial/detections",
        json={
            "detection_id": "invalid",
            "x": 0,
            "y": 0,
            "temperature_c": 1200,
            "confidence": 2,
        },
    )
    assert response.status_code == 422


def test_spatial_websocket_sends_map_overlay_snapshot():
    with client.websocket_connect("/ws/spatial") as websocket:
        payload = websocket.receive_json()

        assert payload["source"] in {"mock", "ros"}
        assert "pose" in payload
        assert "sensors" in payload
        assert "heatmap" in payload


def test_point_cloud_websocket_sends_binary_packet():
    main_module.point_cloud_store.update(
        POINT_RECORD.pack(1.0, 2.0, 0.5, 220, 80, 35, 255),
        point_count=1,
        color_available=True,
        frame_id="map",
        source="test:/cloud",
    )

    with client.websocket_connect("/ws/pointcloud") as websocket:
        packet = websocket.receive_bytes()

    assert packet[:4] == b"HGPC"
    frame_id_bytes = int.from_bytes(packet[6:8], "little")
    assert packet[24:24 + frame_id_bytes] == b"map"
    assert len(packet) == 24 + frame_id_bytes + POINT_RECORD.size


def test_thermal_cloud_is_a_separate_stream_from_the_colour_one():
    """The two 3D views must not be able to show each other's cloud."""
    main_module.thermal_cloud_store.update(
        POINT_RECORD.pack(0.5, 0.5, 1.0, 255, 0, 0, 255),
        point_count=1,
        color_available=True,
        frame_id="map",
        source="test:/thermal_cloud",
    )

    with client.websocket_connect("/ws/pointcloud/thermal") as websocket:
        packet = websocket.receive_bytes()

    assert packet[:4] == b"HGPC"
    frame_id_bytes = int.from_bytes(packet[6:8], "little")
    assert packet[24 + frame_id_bytes:] == POINT_RECORD.pack(
        0.5, 0.5, 1.0, 255, 0, 0, 255
    )

    status = client.get("/api/v1/spatial/cloud/thermal/status").json()
    assert status["source"] == "test:/thermal_cloud"
    # The colour window the robot node paints with, so the legend can name it.
    assert status["min_temp_c"] < status["max_temp_c"]
