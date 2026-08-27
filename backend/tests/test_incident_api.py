from types import SimpleNamespace
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app import bridge as bridge_module
from app import main as main_module
from app.incidents import IncidentStore, sign_incident_decision
from app.main import app


client = TestClient(app)
ADMIN_HEADERS = {"X-HazardGuard-Admin-Token": "admin-token"}


def seed(store: IncidentStore, state: str = "approval_required") -> dict:
    return store.upsert_incident(
        {
            "incident_id": "incident-1",
            "detection_id": "detection-1",
            "state": state,
            "severity": "critical",
            "temperature_c": 84.6,
            "x": 1.2,
            "y": -0.4,
            "z": 0.0,
            "message": "관리자 승인이 필요합니다.",
        }
    )


@pytest.fixture
def incident_api(monkeypatch, tmp_path):
    store = IncidentStore(tmp_path / "incidents.sqlite3")
    seed(store)
    monkeypatch.setattr(main_module, "incident_store", store)
    monkeypatch.setenv("HAZARD_GUARD_DISPENSER_APPROVAL_SECRET", "shared-secret")
    monkeypatch.setenv("HAZARD_GUARD_ADMIN_API_TOKEN", "admin-token")
    monkeypatch.setenv("HAZARD_GUARD_ADMIN_OPERATOR_ID", "operator")
    monkeypatch.setattr(
        main_module.ros_bridge,
        "dispenser_battery_status",
        lambda: {
            "expected": 3,
            "connected": 2,
            "available_for_drop": 2,
            "beacons": [],
            "stale": False,
        },
    )
    return store


def test_incident_list_and_detail_include_audit_and_battery(incident_api):
    listing = client.get("/api/v1/incidents")
    detail = client.get("/api/v1/incidents/incident-1")

    assert listing.status_code == 200
    assert listing.json()["incidents"][0]["incident_id"] == "incident-1"
    assert listing.json()["battery"]["connected"] == 2
    assert detail.status_code == 200
    assert detail.json()["decisions"] == []


def test_decision_requires_explicit_confirmation(incident_api):
    response = client.post(
        "/api/v1/incidents/incident-1/decision",
        json={"decision": "resume", "operator_id": "operator", "confirmed": False},
    )

    assert response.status_code == 403


def test_decision_requires_valid_admin_token(incident_api):
    payload = {"decision": "resume", "operator_id": "operator", "confirmed": True}

    missing = client.post("/api/v1/incidents/incident-1/decision", json=payload)
    wrong = client.post(
        "/api/v1/incidents/incident-1/decision",
        json=payload,
        headers={"X-HazardGuard-Admin-Token": "wrong"},
    )

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert incident_api.decisions_for("incident-1") == []


def test_drop_decision_is_blocked_when_no_beacon_is_available(
    monkeypatch, incident_api
):
    monkeypatch.setattr(
        main_module.ros_bridge,
        "dispenser_battery_status",
        lambda: {
            "expected": 3,
            "connected": 0,
            "available_for_drop": 0,
            "beacons": [],
            "stale": False,
        },
    )

    response = client.post(
        "/api/v1/incidents/incident-1/decision",
        json={
            "decision": "drop_then_resume",
            "operator_id": "operator",
            "confirmed": True,
        },
        headers=ADMIN_HEADERS,
    )

    assert response.status_code == 409
    assert incident_api.decisions_for("incident-1") == []


def test_decision_is_signed_dispatched_and_replayed_once(monkeypatch, incident_api):
    calls = []

    def accept(payload):
        calls.append(payload)
        return {
            "delivered": True,
            "accepted": True,
            "incident_id": payload["incident_id"],
            "request_id": payload["request_id"],
            "decision": payload["decision"],
            "state": "resuming",
            "message": "accepted",
        }

    monkeypatch.setattr(main_module.ros_bridge, "decide_incident", accept)
    payload = {
        "request_id": "decision-1",
        "decision": "resume",
        "operator_id": "operator",
        "confirmed": True,
    }
    first = client.post(
        "/api/v1/incidents/incident-1/decision", json=payload, headers=ADMIN_HEADERS
    )
    replay = client.post(
        "/api/v1/incidents/incident-1/decision", json=payload, headers=ADMIN_HEADERS
    )

    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json()["replayed"] is True
    assert len(calls) == 1
    assert calls[0]["authorization"] == sign_incident_decision(
        secret="shared-secret",
        incident_id="incident-1",
        request_id="decision-1",
        decision="resume",
        operator_id="operator",
    )
    assert "authorization" not in first.json()

    seed(incident_api, "resuming")
    replay_after_state_change = client.post(
        "/api/v1/incidents/incident-1/decision",
        json=payload,
        headers=ADMIN_HEADERS,
    )
    assert replay_after_state_change.status_code == 200
    assert replay_after_state_change.json()["replayed"] is True
    assert len(calls) == 1


def test_transport_failure_can_retry_same_request(monkeypatch, incident_api):
    calls = []

    def flaky(payload):
        calls.append(payload)
        if len(calls) == 1:
            return {"delivered": False, "accepted": False, "message": "offline"}
        return {
            "delivered": True,
            "accepted": True,
            "incident_id": payload["incident_id"],
            "request_id": payload["request_id"],
            "decision": payload["decision"],
            "state": "resuming",
            "message": "accepted",
        }

    monkeypatch.setattr(main_module.ros_bridge, "decide_incident", flaky)
    payload = {
        "request_id": "decision-retry",
        "decision": "resume",
        "operator_id": "operator",
        "confirmed": True,
    }

    assert client.post(
        "/api/v1/incidents/incident-1/decision", json=payload, headers=ADMIN_HEADERS
    ).status_code == 503
    retried = client.post(
        "/api/v1/incidents/incident-1/decision", json=payload, headers=ADMIN_HEADERS
    )

    assert retried.status_code == 200
    assert len(calls) == 2
    assert incident_api.get_decision("decision-retry")["state"] == "accepted"


def test_concurrent_http_replay_dispatches_robot_service_once(
    monkeypatch, incident_api
):
    calls = []

    def slow_accept(payload):
        calls.append(payload)
        time.sleep(0.1)
        return {
            "delivered": True,
            "accepted": True,
            "incident_id": payload["incident_id"],
            "request_id": payload["request_id"],
            "decision": payload["decision"],
            "state": "resuming",
            "message": "accepted",
        }

    monkeypatch.setattr(main_module.ros_bridge, "decide_incident", slow_accept)
    payload = {
        "request_id": "decision-concurrent",
        "decision": "resume",
        "operator_id": "operator",
        "confirmed": True,
    }

    def submit():
        return client.post(
            "/api/v1/incidents/incident-1/decision",
            json=payload,
            headers=ADMIN_HEADERS,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: submit(), range(2)))

    assert [response.status_code for response in responses] == [200, 200]
    assert len(calls) == 1


def test_monitoring_requires_explicit_completion_decision(
    monkeypatch, incident_api
):
    seed(incident_api, "monitoring")
    monkeypatch.setattr(
        main_module.ros_bridge,
        "decide_incident",
        lambda payload: {
            "delivered": True,
            "accepted": True,
            "incident_id": payload["incident_id"],
            "request_id": payload["request_id"],
            "decision": payload["decision"],
            "state": "resuming",
            "message": "accepted",
        },
    )

    invalid = client.post(
        "/api/v1/incidents/incident-1/decision",
        json={"decision": "resume", "operator_id": "operator", "confirmed": True},
        headers=ADMIN_HEADERS,
    )
    premature = client.post(
        "/api/v1/incidents/incident-1/decision",
        json={
            "decision": "complete_monitoring",
            "operator_id": "operator",
            "confirmed": True,
        },
        headers=ADMIN_HEADERS,
    )

    assert invalid.status_code == 409
    assert premature.status_code == 409

    seed(incident_api, "admin_release_required")
    valid = client.post(
        "/api/v1/incidents/incident-1/decision",
        json={
            "decision": "complete_monitoring",
            "operator_id": "operator",
            "confirmed": True,
        },
        headers=ADMIN_HEADERS,
    )
    assert valid.status_code == 200


def test_rejected_decision_replay_remains_a_conflict(monkeypatch, incident_api):
    calls = []

    def reject(payload):
        calls.append(payload)
        return {
            "delivered": True,
            "accepted": False,
            "incident_id": payload["incident_id"],
            "request_id": payload["request_id"],
            "decision": payload["decision"],
            "state": "approval_required",
            "message": "safety guard rejected",
        }

    monkeypatch.setattr(main_module.ros_bridge, "decide_incident", reject)
    payload = {
        "request_id": "decision-rejected",
        "decision": "resume",
        "operator_id": "operator",
        "confirmed": True,
    }

    first = client.post(
        "/api/v1/incidents/incident-1/decision", json=payload, headers=ADMIN_HEADERS
    )
    replay = client.post(
        "/api/v1/incidents/incident-1/decision", json=payload, headers=ADMIN_HEADERS
    )

    assert first.status_code == 409
    assert replay.status_code == 409
    assert len(calls) == 1


def test_bridge_normalizes_incident_message_and_battery_fails_closed(monkeypatch):
    captured = []
    main_module.ros_bridge.set_incident_handler(captured.append)
    message = SimpleNamespace(
        stamp=SimpleNamespace(sec=1_750_000_000, nanosec=500_000_000),
        incident_id="incident-1",
        detection_id="detection-1",
        mission_id="mission-1",
        equipment_id="motor-1",
        source="thermal",
        severity="critical",
        state="approval_required",
        decision="",
        frame_id="map",
        x=1.0,
        y=2.0,
        z=0.0,
        temperature_c=84.6,
        confidence=0.9,
        simulated=False,
        message="approval needed",
        beacon_pose_available=True,
        beacon_frame_id="map",
        beacon_x=0.8,
        beacon_y=1.7,
        beacon_z=0.0,
        beacon_yaw=0.2,
    )
    main_module.ros_bridge._persist_incident_status(
        captured.append, main_module.ros_bridge._incident_payload(message)
    )

    assert captured[0]["incident_id"] == "incident-1"
    assert captured[0]["decision"] is None
    assert captured[0]["beacon_pose_available"] is True
    assert captured[0]["beacon_x"] == pytest.approx(0.8)
    assert captured[0]["observed_at"].startswith("2025-")
    main_module.ros_bridge._on_dispenser_battery(
        SimpleNamespace(
            data=(
                '{"enabled":true,"expected":3,"connected":1,'
                '"available_for_drop":1,"beacons":[],"updated_at_unix_ms":'
                f'{int(time.time() * 1000)}}}'
            )
        )
    )
    assert main_module.ros_bridge.dispenser_battery_status()["available_for_drop"] == 1
    received_at = main_module.ros_bridge._dispenser_battery_monotonic
    monkeypatch.setattr(
        bridge_module.time, "monotonic", lambda: received_at + 181.0
    )
    assert main_module.ros_bridge.dispenser_battery_status()["available_for_drop"] == 0


@pytest.mark.parametrize(
    "payload",
    [
        {
            "enabled": False,
            "expected": 3,
            "connected": 1,
            "available_for_drop": 1,
            "beacons": [],
            "updated_at_unix_ms": lambda: int(time.time() * 1000),
        },
        {
            "enabled": True,
            "expected": 3,
            "connected": 1,
            "available_for_drop": 1,
            "beacons": [],
            "updated_at_unix_ms": lambda: int((time.time() - 181) * 1000),
        },
    ],
)
def test_battery_disabled_or_source_stale_is_fail_closed(payload):
    import json

    resolved = {
        key: value() if callable(value) else value for key, value in payload.items()
    }
    main_module.ros_bridge._on_dispenser_battery(
        SimpleNamespace(data=json.dumps(resolved))
    )

    status = main_module.ros_bridge.dispenser_battery_status()
    assert status["available_for_drop"] == 0


class ImmediateFuture:
    def __init__(self, response):
        self.response = response

    def add_done_callback(self, callback):
        callback(self)

    def result(self):
        return self.response


class ImmediateClient:
    def __init__(self, response):
        self.response = response

    def wait_for_service(self, timeout_sec):
        return True

    def call_async(self, request):
        return ImmediateFuture(self.response)


def test_bridge_treats_mismatched_decision_response_as_retryable(monkeypatch):
    bridge = main_module.ros_bridge
    monkeypatch.setattr(bridge, "active", True)
    monkeypatch.setattr(bridge, "_incident_decision_request_type", type("Request", (), {}))
    monkeypatch.setattr(
        bridge,
        "_incident_decision_client",
        ImmediateClient(
            SimpleNamespace(
                accepted=True,
                incident_id="another-incident",
                request_id="decision-1",
                decision="resume",
                state="resuming",
                message="accepted",
            )
        ),
    )

    result = bridge.decide_incident(
        {
            "incident_id": "incident-1",
            "request_id": "decision-1",
            "decision": "resume",
            "operator_id": "operator",
            "authorization": "signed",
        }
    )

    assert result["delivered"] is False
    assert result["accepted"] is False


def test_dispenser_recovery_rejects_mismatched_record_json(monkeypatch):
    bridge = main_module.ros_bridge
    monkeypatch.setattr(bridge, "active", True)
    monkeypatch.setattr(bridge, "_dispenser_status_request_type", type("Request", (), {}))
    monkeypatch.setattr(
        bridge,
        "_dispenser_status_client",
        ImmediateClient(
            SimpleNamespace(
                found=True,
                fingerprint_matches=True,
                record_json=(
                    '{"request_id":"another-request",'
                    '"detection_id":"detection-1","state":"succeeded"}'
                ),
            )
        ),
    )

    assert bridge.lookup_dispenser_request("request-1", "detection-1") is None
