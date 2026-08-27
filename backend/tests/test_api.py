import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import bridge
from app import main as main_module
from app.bridge import MediaStore
from app.point_cloud import POINT_RECORD
from app.main import app


client = TestClient(app)


def test_lifespan_always_stops_bridge_when_mode_stop_raises(monkeypatch):
    events = []
    monkeypatch.setattr(
        main_module.ros_bridge,
        "start",
        lambda: events.append("bridge-start"),
    )
    monkeypatch.setattr(
        main_module.ros_bridge,
        "publish_thermal_equipment_config",
        lambda _config: events.append("equipment"),
    )
    monkeypatch.setattr(
        main_module.equipment_store,
        "get",
        lambda: SimpleNamespace(model_dump=lambda **_kwargs: {}),
    )

    def fail_mode_stop():
        events.append("mode-stop")
        raise RuntimeError("mode stop failed")

    monkeypatch.setattr(main_module.system_mode_manager, "stop", fail_mode_stop)
    monkeypatch.setattr(
        main_module.ros_bridge,
        "stop",
        lambda: events.append("bridge-stop"),
    )

    async def exercise_lifespan():
        try:
            async with main_module.lifespan(main_module.app):
                pass
        except RuntimeError as exc:
            assert str(exc) == "mode stop failed"
            events.append("error-propagated")

    asyncio.run(exercise_lifespan())

    assert events == [
        "bridge-start",
        "equipment",
        "mode-stop",
        "bridge-stop",
        "error-propagated",
    ]


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
    assert payload["battery_percent"] is None
    assert payload["battery_voltage"] is None
    assert payload["battery_stale"] is True
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


def test_rgbd_mode_disables_thermal_status_identity_until_patrol(monkeypatch):
    reset_sessions = []
    monkeypatch.setattr(
        main_module.system_mode_manager,
        "snapshot",
        lambda **_kwargs: {"mode": "idle", "pid": None},
    )
    monkeypatch.setattr(
        main_module.system_mode_manager,
        "switch_mode",
        lambda mode, **_kwargs: {
            "accepted": True,
            "mode": mode,
            "state": "starting",
            "pid": 321,
            "active_map_session_id": "session-rgbd",
            "thermal_map_session_id": "session-rgbd",
            "mapping_session_id": None,
            "patrol_slam": False,
        },
    )
    monkeypatch.setattr(
        main_module,
        "reset_thermal_map_stream",
        reset_sessions.append,
    )

    response = client.put(
        "/api/v1/system/mode",
        json={"mode": "rgbd_mapping"},
    )

    assert response.status_code == 200
    assert reset_sessions == [None]


def test_failed_patrol_resets_cache_when_geometry_was_refreshed(monkeypatch):
    reset_sessions = []
    monkeypatch.setattr(
        main_module.system_mode_manager,
        "snapshot",
        lambda **_kwargs: {"mode": "idle", "pid": None},
    )
    monkeypatch.setattr(
        main_module.system_mode_manager,
        "switch_mode",
        lambda _mode, **_kwargs: {
            "accepted": False,
            "mode": "idle",
            "state": "failed",
            "thermal_map_session_id": "session-refreshed",
            "thermal_cache_reset_required": True,
            "message": "launch failed",
        },
    )
    monkeypatch.setattr(
        main_module,
        "reset_thermal_map_stream",
        reset_sessions.append,
    )

    response = client.put("/api/v1/system/mode", json={"mode": "patrol"})

    assert response.status_code == 409
    assert reset_sessions == [None]


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
        lambda: {
            "mode": "patrol",
            "state": "running",
            "active_world_id": "facility_map",
            "active_map_session_id": "session-a",
        },
    )
    monkeypatch.setattr(
        main_module.system_mode_manager,
        "set_localization_pose",
        lambda pose: recorded.update(pose) or pose,
    )
    monkeypatch.setattr(
        main_module.spatial_store,
        "reset_for_localization",
        lambda _map_id=None: None,
    )
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
    reset_sessions = []
    monkeypatch.setattr(
        main_module.spatial_store,
        "snapshot",
        lambda: {"pose": {"available": False, "mock": False}},
    )
    monkeypatch.setattr(
        main_module.system_mode_manager,
        "save_map_and_stop",
        lambda: {
            "accepted": True,
            "mode": "idle",
            "state": "stopped",
            "managed_stop_performed": True,
            "message": "저장 후 종료",
        },
    )
    monkeypatch.setattr(
        main_module,
        "reset_thermal_map_stream",
        reset_sessions.append,
    )

    response = client.post("/api/v1/system/map/save-and-stop")

    assert response.status_code == 200
    assert response.json()["state"] == "stopped"
    assert reset_sessions == [None]


def test_save_endpoint_records_live_pose_before_manager_save(monkeypatch):
    recorded = []
    map_id = "facility_map:session-current"
    updated_at = datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr(
        main_module.system_mode_manager,
        "snapshot",
        lambda **_kwargs: {
            "mode": "mapping",
            "patrol_slam": False,
            "mapping_session_id": "session-current",
            "active_map_session_id": "session-old",
            "active_world_id": "facility_map",
        },
    )
    monkeypatch.setattr(
        main_module.spatial_store,
        "snapshot",
        lambda: {
            "map": {"map_id": map_id},
            "pose": {
                "available": True,
                "mock": False,
                "map_id": map_id,
                "frame_id": "map",
                "x": 1.2,
                "y": -0.3,
                "yaw": 0.6,
                "updated_at": updated_at,
            }
        },
    )
    monkeypatch.setattr(
        main_module.system_mode_manager,
        "set_localization_pose",
        lambda pose, **identity: recorded.append((dict(pose), identity)),
    )
    monkeypatch.setattr(
        main_module.system_mode_manager,
        "save_map",
        lambda: {"accepted": True, "message": "saved"},
    )

    response = client.post("/api/v1/system/map/save")

    assert response.status_code == 200
    assert recorded == [(
        {
            "available": True,
            "mock": False,
            "map_id": map_id,
            "frame_id": "map",
            "x": 1.2,
            "y": -0.3,
            "yaw": 0.6,
            "updated_at": updated_at,
        },
        {"world_id": "facility_map", "session_id": "session-current"},
    )]


def test_map_selection_invalidates_pose_from_previous_session(monkeypatch):
    reset = []
    monkeypatch.setattr(
        main_module.system_mode_manager,
        "select_map",
        lambda world_id, session_id: {
            "accepted": True,
            "active_world_id": world_id,
            "active_map_session_id": session_id,
            "message": "selected",
        },
    )
    monkeypatch.setattr(
        main_module.spatial_store,
        "reset_for_localization",
        lambda map_id: reset.append(map_id),
    )
    monkeypatch.setattr(main_module, "reset_thermal_map_stream", lambda _session: None)
    monkeypatch.setattr(
        main_module.ros_bridge,
        "publish_thermal_equipment_config",
        lambda _config: None,
    )

    response = client.put(
        "/api/v1/system/map/active",
        json={"world_id": "facility_map", "session_id": "session-new"},
    )

    assert response.status_code == 200
    assert reset == ["facility_map:session-new"]


def test_stop_endpoint_rejects_unmanaged_external_stack(monkeypatch):
    side_effects = []
    monkeypatch.setattr(
        main_module.system_mode_manager,
        "stop",
        lambda: {
            "accepted": False,
            "mode": "patrol",
            "state": "external",
            "message": "terminal launch",
        },
    )
    monkeypatch.setattr(
        main_module.ros_bridge,
        "cancel_route",
        lambda: side_effects.append("route"),
    )
    monkeypatch.setattr(
        main_module.ros_bridge,
        "cancel_navigation",
        lambda: side_effects.append("navigation"),
    )
    monkeypatch.setattr(
        main_module.ros_bridge,
        "stop_motion",
        lambda: side_effects.append("motion"),
    )
    monkeypatch.setattr(
        main_module,
        "reset_thermal_map_stream",
        lambda _session: side_effects.append("thermal"),
    )

    response = client.delete("/api/v1/system/mode")

    assert response.status_code == 409
    assert response.json()["detail"] == "terminal launch"
    assert side_effects == []


def test_idle_stop_endpoint_does_not_reset_thermal_cache(monkeypatch):
    side_effects = []
    monkeypatch.setattr(
        main_module.system_mode_manager,
        "stop",
        lambda: {
            "accepted": True,
            "mode": "idle",
            "state": "stopped",
            "managed_stop_performed": False,
            "message": "nothing to stop",
        },
    )
    monkeypatch.setattr(
        main_module,
        "reset_thermal_map_stream",
        lambda _session: side_effects.append("thermal"),
    )

    response = client.delete("/api/v1/system/mode")

    assert response.status_code == 200
    assert response.json()["managed_stop_performed"] is False
    assert side_effects == []


def test_managed_stop_endpoint_resets_thermal_cache(monkeypatch):
    reset_sessions = []
    monkeypatch.setattr(
        main_module.system_mode_manager,
        "stop",
        lambda: {
            "accepted": True,
            "mode": "idle",
            "state": "stopped",
            "managed_stop_performed": True,
            "message": "managed patrol stopped",
        },
    )
    monkeypatch.setattr(
        main_module,
        "reset_thermal_map_stream",
        reset_sessions.append,
    )

    response = client.delete("/api/v1/system/mode")

    assert response.status_code == 200
    assert reset_sessions == [None]


def test_managed_ros_pre_stop_hook_cancels_navigation_before_zero_velocity(
    monkeypatch,
):
    events = []
    monkeypatch.setattr(
        main_module.ros_bridge,
        "cancel_route",
        lambda: events.append("route"),
    )
    monkeypatch.setattr(
        main_module.ros_bridge,
        "cancel_navigation",
        lambda: events.append("navigation"),
    )
    monkeypatch.setattr(
        main_module.ros_bridge,
        "stop_motion",
        lambda: events.append("motion"),
    )

    result = main_module.prepare_managed_ros_stop()

    assert events == ["route", "navigation", "motion"]
    assert result == {"accepted": True, "message": None}


def test_managed_ros_pre_stop_hook_aggregates_rejection_and_exception(
    monkeypatch,
):
    events = []
    monkeypatch.setattr(
        main_module.ros_bridge,
        "cancel_route",
        lambda: events.append("route") or {
            "accepted": False,
            "message": "route rejected",
        },
    )

    def fail_navigation():
        events.append("navigation")
        raise RuntimeError("action unavailable")

    monkeypatch.setattr(
        main_module.ros_bridge,
        "cancel_navigation",
        fail_navigation,
    )
    monkeypatch.setattr(
        main_module.ros_bridge,
        "stop_motion",
        lambda: events.append("motion") or {"accepted": True},
    )

    result = main_module.prepare_managed_ros_stop()

    assert events == ["route", "navigation", "motion"]
    assert result["accepted"] is False
    assert "route rejected" in str(result["message"])
    assert "action unavailable" in str(result["message"])


def test_save_endpoint_ignores_stale_pose_from_selected_session(monkeypatch):
    persisted_pose = [{"x": 1.5, "y": -0.5, "yaw": 0.25}]
    map_id = "facility_map:session-current"
    monkeypatch.setattr(
        main_module.system_mode_manager,
        "snapshot",
        lambda **_kwargs: {
            "mode": "idle",
            "patrol_slam": False,
            "mapping_session_id": None,
            "active_map_session_id": "session-current",
            "active_world_id": "facility_map",
        },
    )
    monkeypatch.setattr(
        main_module.spatial_store,
        "snapshot",
        lambda: {
            "map": {"map_id": map_id},
            "pose": {
                "available": True,
                "mock": False,
                "map_id": map_id,
                "frame_id": "map",
                "x": 99.0,
                "y": 99.0,
                "yaw": 1.0,
                "updated_at": (
                    datetime.now(timezone.utc) - timedelta(seconds=3)
                ).isoformat(),
            },
        },
    )
    monkeypatch.setattr(
        main_module.system_mode_manager,
        "set_localization_pose",
        lambda pose, **_kwargs: persisted_pose.__setitem__(0, dict(pose)),
    )
    monkeypatch.setattr(
        main_module.system_mode_manager,
        "save_map",
        lambda: {"accepted": False, "message": "not mapping"},
    )

    response = client.post("/api/v1/system/map/save")

    assert response.status_code == 409
    assert persisted_pose == [{"x": 1.5, "y": -0.5, "yaw": 0.25}]


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


def test_refreshed_active_cloud_resets_thermal_session_cache(
    monkeypatch,
    tmp_path,
):
    cloud = tmp_path / "cloud.ply"
    cloud.write_bytes(b"ply\n")
    reset_sessions = []
    monkeypatch.setattr(
        main_module.system_mode_manager,
        "export_map_cloud",
        lambda _world_id, _session_id: {
            "accepted": True,
            "path": cloud,
            "geometry_refreshed": True,
            "message": "refreshed",
        },
    )
    monkeypatch.setattr(
        main_module.system_mode_manager,
        "snapshot",
        lambda **_kwargs: {
            "active_map_session_id": "session-1",
            "thermal_map_session_id": "session-1",
        },
    )
    monkeypatch.setattr(
        main_module,
        "reset_thermal_map_stream",
        reset_sessions.append,
    )

    response = client.get("/api/v1/system/maps/facility/session-1/cloud.ply")

    assert response.status_code == 200
    assert reset_sessions == [None]


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


def test_route_rejects_equipment_waypoint_without_measurement_dwell():
    response = client.post(
        "/api/v1/navigation/route",
        json={
            "name": "Invalid equipment route",
            "frame_id": "map",
            "waypoints": [
                {
                    "id": "equipment-without-dwell",
                    "name": "설비 측정",
                    "equipment_id": "primary_shredder_motor",
                    "x": 0,
                    "y": 0,
                    "yaw": 0,
                    "dwell_seconds": 0,
                    "enabled": True,
                }
            ],
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
    # The fixed browser packet colour window, so the legend can name it.
    assert status["min_temp_c"] == 20.0
    assert status["max_temp_c"] == 40.0


def test_thermal_cloud_status_exposes_cumulative_session_artifacts(
    monkeypatch,
    tmp_path,
):
    cloud_path = tmp_path / "cloud.ply"
    state_path = tmp_path / "thermal_layer.npz"
    cloud_path.write_bytes(b"ply\n")
    state_path.write_bytes(b"state")
    monkeypatch.setenv(
        "HAZARD_GUARD_THERMAL_CLOUD_TOPIC", "/hazard_guard/thermal/map"
    )
    monkeypatch.setattr(
        main_module.system_mode_manager,
        "snapshot",
        lambda **_kwargs: {
            "thermal_map_session_id": "session-thermal",
            "thermal_map_status": "active",
            "thermal_map_message": "ready",
            "thermal_map_cloud_path": str(cloud_path),
            "thermal_map_state_path": str(state_path),
        },
    )
    main_module.thermal_map_status_store.reset("session-thermal")
    main_module.thermal_map_status_store.update(
        SimpleNamespace(
            data='{"session_id":"session-thermal",'
            '"cumulative":true,"fixed_map_available":true,'
            '"fingerprint":"fixed-map","observed_voxel_count":77,'
            '"match_ratio":0.81,"rejected_observation_count":4,'
            '"snapshot_truncated":true,"surface_range_rejected_count":9,'
            '"dropped_pending_observation_count":2,'
            '"localization_ready":true,'
            '"localization_stable_sample_count":6,'
            '"last_observation_at":"2026-08-23T10:00:00+00:00",'
            '"persisted_at":"2026-08-23T10:00:01+00:00",'
            '"map_error":"","state_error":""}'
        )
    )

    status = client.get("/api/v1/spatial/cloud/thermal/status").json()

    assert status["cumulative"] is True
    assert status["session_id"] == "session-thermal"
    assert status["fixed_map_available"] is True
    assert status["state_available"] is True
    assert status["persisted_at"] is not None
    assert status["map_status"] == "active"
    assert status["status_available"] is True
    assert status["observed_voxel_count"] == 77
    assert status["match_ratio"] == 0.81
    assert status["rejected_observation_count"] == 4
    assert status["snapshot_truncated"] is True
    assert status["surface_range_rejected_count"] == 9
    assert status["dropped_pending_observation_count"] == 2
    assert status["localization_ready"] is True
    assert status["localization_stable_sample_count"] == 6
    assert status["observation_age_sec"] > 0
    assert status["observation_fresh"] is False


def test_cumulative_status_without_node_observation_never_uses_cache_time(
    monkeypatch,
    tmp_path,
):
    cloud_path = tmp_path / "cloud.ply"
    cloud_path.write_bytes(b"ply\n")
    monkeypatch.setenv(
        "HAZARD_GUARD_THERMAL_CLOUD_TOPIC", "/hazard_guard/thermal/map"
    )
    monkeypatch.setattr(
        main_module.system_mode_manager,
        "snapshot",
        lambda **_kwargs: {
            "thermal_map_session_id": "session-no-status",
            "thermal_map_status": "ready",
            "thermal_map_cloud_path": str(cloud_path),
            "thermal_map_state_path": str(tmp_path / "thermal_layer.npz"),
        },
    )
    main_module.thermal_map_status_store.reset("session-no-status")
    main_module.thermal_cloud_store.clear(source="/hazard_guard/thermal/map")

    status = client.get("/api/v1/spatial/cloud/thermal/status").json()

    assert status["status_available"] is False
    assert status["last_observation_at"] is None
    assert status["age_sec"] is None
    assert status["observation_fresh"] is False


def test_thermal_websocket_bridge_defaults_to_accumulated_map_topic():
    assert (
        bridge.ros_bridge._thermal_cloud_adapter._source_default
        == "/hazard_guard/thermal/map"
    )


def test_thermal_status_fingerprint_change_clears_cached_cloud():
    main_module.thermal_map_status_store.reset("session-new")
    main_module.thermal_cloud_store.update(
        POINT_RECORD.pack(1.0, 1.0, 1.0, 255, 0, 0, 255),
        point_count=1,
        color_available=True,
        frame_id="map",
        source="/hazard_guard/thermal/map",
    )
    previous_sequence, _ = main_module.thermal_cloud_store.packet_after(None)

    bridge.ros_bridge._on_thermal_map_status(
        SimpleNamespace(
            data='{"session_id":"session-new","fingerprint":"new-map"}'
        )
    )

    _, packet = main_module.thermal_cloud_store.packet_after(previous_sequence)
    point_count = int.from_bytes(packet[12:16], "little")
    assert point_count == 0
    assert main_module.thermal_cloud_store.status()["available"] is False
