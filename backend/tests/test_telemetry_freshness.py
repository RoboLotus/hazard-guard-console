from app import stores


def test_producer_age_is_not_refreshed_by_sending_or_other_sensors(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(stores.time, "monotonic", lambda: now[0])
    store = stores.TelemetryStore()
    assert store.snapshot()["stale"]
    store.update({"mock": False, "speed_mps": 0.0})
    received = store.snapshot()["received_at"]
    assert not store.snapshot()["stale"]
    now[0] = 6.0
    store.update({"person_safety": {"state": 0}})
    store.update_battery(percent=50, voltage=12, source="physical")
    assert store.snapshot()["stale"]
    assert store.snapshot()["age_sec"] == 6
    assert store.snapshot()["received_at"] == received
    store.update({"mock": False, "speed_mps": 0.1})
    assert not store.snapshot()["stale"]
