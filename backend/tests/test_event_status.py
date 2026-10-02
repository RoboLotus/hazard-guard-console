from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.event_status import EventStatusStore, event_status_router


def make_client(tmp_path):
    class Spatial:
        def snapshot(self):
            return {"map": {"map_id": "map-a"}, "heatmap": {"detections": [
                {"detection_id": "motor", "visit_index": 2, "trend_status": "critical", "temperature_c": 35}
            ]}}
    store = EventStatusStore(tmp_path / "states.sqlite3")
    app = FastAPI()
    app.include_router(event_status_router(Spatial(), store))
    return TestClient(app), store


def test_status_survives_restart_and_preserves_map_and_severity_scope(tmp_path):
    client, store = make_client(tmp_path)
    request = {"map_id": "map-a", "level": "critical", "status": "working"}
    result = client.put("/api/v1/events/motor-visit-2/status", json=request)
    assert result.status_code == 200
    assert result.json()["revision"] == 1
    assert client.put("/api/v1/events/motor-visit-2/status", json=request).json()["revision"] == 2
    reopened = EventStatusStore(store.path)
    assert reopened.get("map-a")[0]["status"] == "working"
    assert reopened.get("map-b") == []
    assert client.get("/api/v1/events/statuses").json()["statuses"][0]["level"] == "critical"


def test_rejects_changed_map_level_unknown_event_and_invalid_status(tmp_path):
    client, _ = make_client(tmp_path)
    payload = {"map_id": "map-a", "level": "critical", "status": "working"}
    for patch in [{"map_id": "old-map"}, {"level": "warning"}]:
        assert client.put("/api/v1/events/motor-visit-2/status", json={**payload, **patch}).status_code == 409
    assert client.put("/api/v1/events/incident-secret/status", json=payload).status_code == 409
    assert client.put("/api/v1/events/motor-visit-2/status", json={**payload, "status": "drop"}).status_code == 422


def test_storage_failure_is_not_success(tmp_path):
    client, store = make_client(tmp_path)
    store.path = tmp_path  # A directory is not a database.
    assert client.get("/api/v1/events/statuses").status_code == 503
