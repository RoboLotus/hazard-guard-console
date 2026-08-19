from unittest.mock import patch

from app.sensor_diagnostics import SensorDiagnosticsStore


class Header:
    frame_id = "/camera_link"


class Message:
    header = Header()


def test_sensor_diagnostics_distinguishes_live_and_offline():
    store = SensorDiagnosticsStore()
    store.register(
        "depth",
        label="Depth",
        topic="/depth/image_raw",
        required_for=("3d",),
        expected_min_hz=5.0,
    )
    with patch(
        "app.sensor_diagnostics.time.monotonic",
        side_effect=(10.0, 10.1, 10.2, 10.3),
    ):
        store.mark("depth", Message())
        store.mark("depth", Message())

        snapshot = store.snapshot(
            ros_active=True,
            active_requirements=("3d",),
            deployment_target="physical",
        )
        live = snapshot["sensors"][0]
        offline = store.snapshot(ros_active=False)["sensors"][0]

    assert live["state"] == "live"
    assert live["required_for"] == ["3d"]
    assert live["required_now"] is True
    assert live["frame_id"] == "camera_link"
    assert live["rate_hz"] is not None
    assert snapshot["summary"]["required_live"] == 1
    assert snapshot["deployment_target"] == "physical"
    assert offline["state"] == "offline"
