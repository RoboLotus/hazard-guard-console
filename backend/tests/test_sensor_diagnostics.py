from app.sensor_diagnostics import SensorDiagnosticsStore


def test_sensor_diagnostics_distinguishes_live_and_offline():
    store = SensorDiagnosticsStore()
    store.register(
        "depth",
        label="Depth",
        topic="/depth/image_raw",
        required_for=("3d",),
    )
    store.mark("depth")

    live = store.snapshot(ros_active=True)["sensors"][0]
    offline = store.snapshot(ros_active=False)["sensors"][0]

    assert live["state"] == "live"
    assert live["required_for"] == ["3d"]
    assert offline["state"] == "offline"
