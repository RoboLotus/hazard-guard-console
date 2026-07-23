from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_reports_mock_mode():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "mode": "mock", "ros_bridge": False}


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


def test_telemetry_websocket_sends_snapshot_and_closes_cleanly():
    with client.websocket_connect("/ws/telemetry") as websocket:
        payload = websocket.receive_json()
        assert payload["robot_id"] == "rosmaster-m1-mock"
        assert "timestamp" in payload
