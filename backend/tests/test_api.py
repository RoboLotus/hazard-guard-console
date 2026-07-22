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


def test_controller_command_updates_fallback_telemetry():
    response = client.post(
        "/api/v1/commands/controller", json={"enabled": True}
    )
    assert response.status_code == 200
    assert response.json()["controller_enabled"] is True
    status = client.get("/api/v1/robot/status").json()
    assert status["controller_enabled"] is True
