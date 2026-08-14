from fastapi.testclient import TestClient

from app import main as main_module
from app.main import app


client = TestClient(app)


def managed_mapping_status():
    return {
        "mode": "mapping",
        "state": "running",
        "accepted": True,
        "managed": True,
        "control_enabled": True,
        "simulation_state": "running",
        "simulation_managed": True,
        "map_available": False,
    }


def test_teleop_websocket_forwards_bounded_direction_in_managed_mapping(monkeypatch):
    published = []
    stopped = []
    monkeypatch.setattr(
        main_module.system_mode_manager,
        "snapshot",
        lambda: managed_mapping_status(),
    )
    monkeypatch.setattr(main_module.ros_bridge, "active", True)
    monkeypatch.setattr(
        main_module.ros_bridge,
        "publish_simulation_teleop",
        lambda direction: published.append(direction) or {
            "accepted": True,
            "direction": direction,
            "linear_x": 0.15,
            "angular_z": 0.0,
        },
    )
    monkeypatch.setattr(
        main_module.ros_bridge,
        "stop_simulation_teleop",
        lambda: stopped.append(True) or {"accepted": True, "direction": "stop"},
    )

    with client.websocket_connect("/ws/teleop") as websocket:
        assert websocket.receive_json()["accepted"] is True
        websocket.send_json({"direction": "forward"})
        response = websocket.receive_json()
        assert response["accepted"] is True
        assert response["direction"] == "forward"

    assert published == ["forward"]
    assert stopped


def test_teleop_websocket_rejects_idle_mode(monkeypatch):
    status = managed_mapping_status()
    status["mode"] = "idle"
    monkeypatch.setattr(main_module.system_mode_manager, "snapshot", lambda: status)
    monkeypatch.setattr(main_module.ros_bridge, "active", True)

    with client.websocket_connect("/ws/teleop") as websocket:
        response = websocket.receive_json()
        assert response["accepted"] is False
        assert "맵 생성 또는 순찰 모드" in response["message"]


def test_teleop_in_patrol_takes_the_wheel_from_nav2(monkeypatch):
    status = managed_mapping_status()
    status["mode"] = "patrol"
    cancelled = []
    monkeypatch.setattr(main_module.system_mode_manager, "snapshot", lambda: status)
    monkeypatch.setattr(main_module.ros_bridge, "active", True)
    monkeypatch.setattr(
        main_module.ros_bridge,
        "cancel_route",
        lambda: cancelled.append("route") or {"accepted": True},
    )
    monkeypatch.setattr(
        main_module.ros_bridge,
        "cancel_navigation",
        lambda: cancelled.append("navigation") or {"accepted": True},
    )
    monkeypatch.setattr(
        main_module.ros_bridge,
        "publish_simulation_teleop",
        lambda direction: {
            "accepted": True,
            "direction": direction,
            "linear_x": 0.15,
            "angular_z": 0.0,
        },
    )
    monkeypatch.setattr(
        main_module.ros_bridge,
        "stop_simulation_teleop",
        lambda: {"accepted": True, "direction": "stop"},
    )

    with client.websocket_connect("/ws/teleop") as websocket:
        assert websocket.receive_json()["accepted"] is True
        websocket.send_json({"direction": "forward"})
        assert websocket.receive_json()["direction"] == "forward"
        # Already driving: the running mission is cancelled once, not per key.
        websocket.send_json({"direction": "forward"})
        assert websocket.receive_json()["direction"] == "forward"

    assert cancelled == ["route", "navigation"]
