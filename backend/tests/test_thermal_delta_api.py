from fastapi.testclient import TestClient

from app import main as main_module
from app.main import app
from app.thermal_delta import ThermalDeltaStore
from test_thermal_delta import make_static_delta


client = TestClient(app)


def test_thermal_delta_bootstrap_resync_and_websocket_relay(monkeypatch):
    store = ThermalDeltaStore(maximum_packets=10, maximum_bytes=10_000)
    packets = (make_static_delta(1), make_static_delta(2))
    for packet in packets:
        store.accept(packet)
    monkeypatch.setattr(main_module, "thermal_delta_store", store)

    bootstrap = client.get(
        "/api/v1/spatial/cloud/thermal/delta/bootstrap"
    ).json()
    assert bootstrap["session_id"] == "session-a"
    assert bootstrap["geometry_fingerprint"] == "fingerprint-a"
    assert bootstrap["latest_sequence"] == 2

    resync = client.get(
        "/api/v1/spatial/cloud/thermal/delta/resync",
        params={
            "session_id": "session-a",
            "geometry_fingerprint": "fingerprint-a",
            "base_sequence": 1,
        },
    ).json()
    assert resync["status"] == "REPLAY_AVAILABLE"
    assert resync["replay_packet_count"] == 1

    with client.websocket_connect(
        "/ws/pointcloud/thermal/delta"
        "?session_id=session-a&geometry_fingerprint=fingerprint-a&base_sequence=1"
    ) as websocket:
        assert websocket.receive_json()["status"] == "REPLAY_AVAILABLE"
        assert websocket.receive_bytes() == packets[1]
