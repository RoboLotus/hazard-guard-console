from app import main as main_module
import pytest
from concurrent.futures import ThreadPoolExecutor

from app.dispenser_requests import DispenserRequestStore, DispenserRequestStoreError
from app.main import app
from fastapi.testclient import TestClient


def test_same_http_request_is_published_once_and_restored(monkeypatch, tmp_path):
    store = DispenserRequestStore(tmp_path / "backend-requests.json")
    calls = []
    monkeypatch.setattr(main_module, "dispenser_request_store", store)
    monkeypatch.setattr(
        main_module.ros_bridge,
        "publish_dispenser_drop",
        lambda request: calls.append(request) or {"accepted": True, "message": "sent"},
    )

    client = TestClient(app)
    payload = {"request_id": "beacon-request-1", "detection_id": "thermal-1"}
    first = client.post("/api/v1/dispenser/requests/drop", json=payload)
    replay = client.post("/api/v1/dispenser/requests/drop", json=payload)

    assert first.status_code == 202
    assert first.json()["dispatched"] is True
    assert replay.status_code == 202
    assert replay.json()["replayed"] is True
    assert replay.json()["dispatched"] is False
    assert len(calls) == 1

    reloaded = DispenserRequestStore(tmp_path / "backend-requests.json")
    restored = reloaded.get("beacon-request-1")
    assert restored["state"] == "recovery_required"


def test_detection_id_blocks_a_new_network_request_id(monkeypatch, tmp_path):
    store = DispenserRequestStore(tmp_path / "backend-requests.json")
    calls = []
    monkeypatch.setattr(main_module, "dispenser_request_store", store)
    monkeypatch.setattr(
        main_module.ros_bridge,
        "publish_dispenser_drop",
        lambda request: calls.append(request) or {"accepted": True, "message": "sent"},
    )
    client = TestClient(app)

    client.post(
        "/api/v1/dispenser/requests/drop",
        json={"request_id": "beacon-request-1", "detection_id": "thermal-1"},
    )
    duplicate = client.post(
        "/api/v1/dispenser/requests/drop",
        json={"request_id": "beacon-request-2", "detection_id": "thermal-1"},
    )

    assert duplicate.status_code == 202
    assert duplicate.json()["request_id"] == "beacon-request-1"
    assert duplicate.json()["replayed"] is True
    assert len(calls) == 1


def test_backend_restart_never_republishes_an_interrupted_request(tmp_path):
    path = tmp_path / "backend-requests.json"
    initial = DispenserRequestStore(path)
    initial.submit(request_id="beacon-request-1", detection_id="thermal-1")
    initial.transition("beacon-request-1", "dispatched")

    restarted = DispenserRequestStore(path)
    restored, created = restarted.submit(
        request_id="beacon-request-1", detection_id="thermal-1"
    )

    assert created is False
    assert restored["state"] == "recovery_required"


def test_completed_robot_result_survives_a_backend_restart(tmp_path):
    path = tmp_path / "backend-requests.json"
    store = DispenserRequestStore(path)
    store.submit(request_id="beacon-request-1", detection_id="thermal-1")
    store.apply_robot_result(
        {
            "request_id": "beacon-request-1",
            "state": "succeeded",
            "result_detail": "ble_drop_confirmed",
        }
    )

    restarted = DispenserRequestStore(path)
    restored = restarted.get("beacon-request-1")

    assert restored["state"] == "succeeded"
    assert restored["robot_result"]["result_detail"] == "ble_drop_confirmed"


def test_fast_robot_result_cannot_be_downgraded_by_late_dispatch(tmp_path):
    store = DispenserRequestStore(tmp_path / "backend.sqlite3")
    store.submit(request_id="beacon-request-1", detection_id="thermal-1")
    store.apply_robot_result(
        {"request_id": "beacon-request-1", "state": "succeeded"}
    )

    result = store.transition("beacon-request-1", "dispatched")

    assert result["state"] == "succeeded"


def test_corrupt_sqlite_ledger_fails_closed(tmp_path):
    path = tmp_path / "backend.sqlite3"
    path.write_text("not a sqlite database", encoding="utf-8")

    with pytest.raises(DispenserRequestStoreError):
        DispenserRequestStore(path)


def test_two_backend_process_connections_claim_only_once(tmp_path):
    path = tmp_path / "backend.sqlite3"
    first = DispenserRequestStore(path)
    second = DispenserRequestStore(path)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda store: store.submit(
                    request_id="beacon-request-1", detection_id="thermal-1"
                ),
                (first, second),
            )
        )

    assert sum(created for _, created in results) == 1
