from fastapi.testclient import TestClient

from app import main as main_module
from app.main import app


def test_rosbag_status_reports_offline_without_ros():
    client = TestClient(app)
    payload = client.get("/api/v1/rosbag/status").json()
    assert payload["state"] == "offline"
    assert payload["recording"] is False


def test_rosbag_control_delegates_validated_request(monkeypatch):
    monkeypatch.setattr(
        main_module.ros_bridge,
        "bag_control",
        lambda command, profile, session_name, allow_experimental: {
            "accepted": True, "message": "recording", "status": {"recording": True, "profile": profile}
        },
    )
    client = TestClient(app)
    response = client.post("/api/v1/rosbag/control", json={
        "command": "start", "profile": "patrol-core", "session_name": "patrol-01"
    })
    assert response.status_code == 200
    assert response.json()["status"]["profile"] == "patrol-core"




def test_rosbag_sessions_reads_controlled_list(monkeypatch):
    monkeypatch.setattr(
        main_module.ros_bridge,
        "bag_control",
        lambda command, *_args: {"accepted": True, "message": "sessions", "status": {"sessions": [{"session_id": "s1"}]}},
    )
    response = TestClient(app).get("/api/v1/rosbag/sessions")
    assert response.status_code == 200
    assert response.json()["sessions"][0]["session_id"] == "s1"
