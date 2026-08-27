from app import main as main_module
import pytest
from concurrent.futures import ThreadPoolExecutor

from app.dispenser_requests import (
    DispenserRequestStore,
    DispenserRequestStoreError,
    IdempotencyConflictError,
)
from app.main import app
from app.models import DispenserDropRequest
from fastapi.testclient import TestClient


REAL_SAFETY_CONTEXT = main_module.dispenser_safety_context


@pytest.fixture(autouse=True)
def allow_test_dispenser_request(monkeypatch):
    monkeypatch.setattr(
        main_module,
        "dispenser_safety_context",
        lambda _request: {
            "operator_approved": True,
            "speed_mps": 0.0,
            "mission_status": "stopped",
            "person_safety_state": "CLEAR",
        },
    )


def test_direct_drop_endpoint_is_disabled(monkeypatch):
    calls = []
    monkeypatch.setattr(
        main_module.ros_bridge,
        "publish_dispenser_drop",
        lambda request: calls.append(request) or {"accepted": True, "message": "sent"},
    )

    client = TestClient(app)
    payload = {"request_id": "beacon-request-1", "detection_id": "thermal-1"}
    response = client.post("/api/v1/dispenser/requests/drop", json=payload)

    assert response.status_code == 410
    assert "위험 이벤트" in response.json()["detail"]
    assert calls == []


def test_direct_drop_endpoint_does_not_create_a_ledger_record(tmp_path, monkeypatch):
    store = DispenserRequestStore(tmp_path / "backend-requests.json")
    monkeypatch.setattr(main_module, "dispenser_request_store", store)
    client = TestClient(app)

    response = client.post(
        "/api/v1/dispenser/requests/drop",
        json={"request_id": "beacon-request-1", "detection_id": "thermal-1"},
    )

    assert response.status_code == 410
    assert store.get("beacon-request-1") is None


def test_request_id_reuse_with_different_detection_is_conflict(tmp_path):
    store = DispenserRequestStore(tmp_path / "backend.sqlite3")
    store.submit(request_id="beacon-request-1", detection_id="thermal-1")

    with pytest.raises(IdempotencyConflictError):
        store.submit(request_id="beacon-request-1", detection_id="thermal-2")


def test_detection_only_request_id_is_bounded_for_robot_validation():
    request = DispenserDropRequest(detection_id="a" * 96)

    assert len(request.request_id) <= 96
    assert request.request_id.startswith("detection:")


def test_dispatch_failure_can_retry_same_request_without_actuation(tmp_path):
    store = DispenserRequestStore(tmp_path / "backend.sqlite3")
    store.submit(request_id="beacon-request-1", detection_id="thermal-1")
    store.transition(
        "beacon-request-1",
        "dispatch_unavailable",
        actuation_started=False,
    )

    record, created = store.submit(
        request_id="beacon-request-1", detection_id="thermal-1"
    )

    assert created is True
    assert record["state"] == "accepted"


def test_real_safety_guard_requires_enablement_approval_and_full_stop(
    monkeypatch,
):
    request = DispenserDropRequest(
        request_id="beacon-request-1",
        detection_id="thermal-1",
        operator_approved=True,
    )
    monkeypatch.setenv("HAZARD_GUARD_DISPENSER_DROP_ENABLED", "1")
    monkeypatch.setattr(
        main_module.telemetry_store,
        "snapshot",
        lambda: {
            "speed_mps": 0.1,
            "person_safety": {
                "state_name": "CLEAR",
                "detector_stale": False,
            },
        },
    )
    monkeypatch.setattr(
        main_module.route_mission_store,
        "snapshot",
        lambda: {"status": "stopped"},
    )

    with pytest.raises(main_module.HTTPException) as error:
        REAL_SAFETY_CONTEXT(request)

    assert error.value.status_code == 409


def test_real_safety_guard_is_disabled_and_unapproved_by_default(monkeypatch):
    request = DispenserDropRequest(
        request_id="beacon-request-1",
        detection_id="thermal-1",
    )
    monkeypatch.delenv("HAZARD_GUARD_DISPENSER_DROP_ENABLED", raising=False)
    with pytest.raises(main_module.HTTPException) as disabled:
        REAL_SAFETY_CONTEXT(request)
    assert disabled.value.status_code == 503

    monkeypatch.setenv("HAZARD_GUARD_DISPENSER_DROP_ENABLED", "1")
    with pytest.raises(main_module.HTTPException) as unapproved:
        REAL_SAFETY_CONTEXT(request)
    assert unapproved.value.status_code == 403


def test_real_safety_guard_accepts_approved_stopped_clear_state(monkeypatch):
    request = DispenserDropRequest(
        request_id="beacon-request-1",
        detection_id="thermal-1",
        operator_approved=True,
    )
    monkeypatch.setenv("HAZARD_GUARD_DISPENSER_DROP_ENABLED", "1")
    monkeypatch.setattr(
        main_module.telemetry_store,
        "snapshot",
        lambda: {
            "speed_mps": 0.0,
            "person_safety": {
                "state_name": "CLEAR",
                "detector_stale": False,
            },
        },
    )
    monkeypatch.setattr(
        main_module.route_mission_store,
        "snapshot",
        lambda: {"status": "stopped"},
    )

    context = REAL_SAFETY_CONTEXT(request)

    assert context["operator_approved"] is True
    assert context["mission_status"] == "stopped"


def test_real_safety_guard_does_not_depend_on_optional_person_detection(
    monkeypatch,
):
    request = DispenserDropRequest(
        request_id="beacon-request-1",
        detection_id="thermal-1",
        operator_approved=True,
    )
    monkeypatch.setenv("HAZARD_GUARD_DISPENSER_DROP_ENABLED", "1")
    monkeypatch.setattr(
        main_module.telemetry_store,
        "snapshot",
        lambda: {
            "speed_mps": 0.0,
            "person_safety": {
                "state_name": "SENSOR_FAULT",
                "detector_stale": True,
            },
        },
    )
    monkeypatch.setattr(
        main_module.route_mission_store,
        "snapshot",
        lambda: {"status": "stopped"},
    )

    context = REAL_SAFETY_CONTEXT(request)

    assert context == {
        "operator_approved": True,
        "speed_mps": 0.0,
        "mission_status": "stopped",
    }


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
