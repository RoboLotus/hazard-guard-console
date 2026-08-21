from app.stores import SpatialStore


def test_spatial_store_keeps_non_normal_gas_transitions() -> None:
    store = SpatialStore()
    store.update_gas_status(
        {
            "event_id": "gas-bunker-voc_watch",
            "state": "voc_watch",
            "level": "watch",
            "voc_index": 148.0,
            "co_ppm": 0.4,
        }
    )
    snapshot = store.snapshot()

    assert snapshot["gas_status"]["state"] == "voc_watch"
    assert snapshot["gas_events"][0]["event_id"] == "gas-bunker-voc_watch"


def test_normal_status_does_not_create_a_risk_event() -> None:
    store = SpatialStore()
    store.update_gas_status(
        {
            "event_id": "gas-bunker-normal",
            "state": "normal",
            "level": "info",
        }
    )

    assert store.snapshot()["gas_events"] == []
