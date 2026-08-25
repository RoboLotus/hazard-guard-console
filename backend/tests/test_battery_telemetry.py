from types import SimpleNamespace

import pytest

from app import stores
from app.bridge import battery_state_payload
from app.stores import TelemetryStore


def test_battery_state_payload_converts_standard_fraction_to_percent():
    payload = battery_state_payload(
        SimpleNamespace(voltage=11.84, percentage=0.64, present=True)
    )

    assert payload == {"voltage": 11.84, "percent": 64.0}


@pytest.mark.parametrize(
    "message",
    [
        SimpleNamespace(voltage=0.0, percentage=0.5, present=True),
        SimpleNamespace(voltage=11.8, percentage=-1.0, present=True),
        SimpleNamespace(voltage=11.8, percentage=0.5, present=False),
    ],
)
def test_battery_state_payload_rejects_unavailable_measurements(message):
    with pytest.raises(ValueError):
        battery_state_payload(message)


def test_telemetry_store_marks_battery_stale_after_timeout(monkeypatch):
    now = {"value": 10.0}
    monkeypatch.setattr(stores.time, "monotonic", lambda: now["value"])
    store = TelemetryStore()

    assert store.snapshot()["battery_stale"] is True

    store.update_battery(percent=64.0, voltage=11.84, source="physical")
    current = store.snapshot()
    assert current["battery_percent"] == 64.0
    assert current["battery_voltage"] == 11.84
    assert current["battery_source"] == "physical"
    assert current["battery_stale"] is False

    now["value"] = 15.1
    stale = store.snapshot()
    assert stale["battery_stale"] is True
    assert stale["battery_age_sec"] == 5.1


def test_telemetry_store_clamps_reference_percentage():
    store = TelemetryStore()

    store.update_battery(percent=101.0, voltage=12.7, source="physical")

    assert store.snapshot()["battery_percent"] == 100.0
