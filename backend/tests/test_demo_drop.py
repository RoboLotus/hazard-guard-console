"""Exhibition-only manual drop button.

The trigger moves from a latched thermal incident to an operator button; the
robot-side safety chain is untouched. These tests pin the two things that can
silently break it: the HMAC payload layout shared with the dispenser node, and
the fail-closed behaviour when the demo flag or the signing key is absent.
"""

import hashlib
import hmac
import json

from app import main as main_module
from app.dispenser_requests import DispenserRequestStore, command_authorization
from app.main import app
from fastapi.testclient import TestClient


def robot_side_verify(secret, *, request_id, detection_id, authorization):
    """Re-implementation of hazard_guard_dispenser.approval_auth.

    Deliberately not imported from the robot package: this test exists to catch
    the two repositories drifting apart, so it has to spell the contract out.
    """

    payload = f"drop\n{request_id}\n{detection_id or ''}".encode("utf-8")
    expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, authorization)


class FakePublisher:
    def __init__(self):
        self.messages = []

    def publish(self, message):
        self.messages.append(message)


class FakeString:
    def __init__(self):
        self.data = ""


def attach_fake_bridge(monkeypatch):
    """Make ros_bridge.publish_dispenser_drop reach a capturable publisher."""

    publisher = FakePublisher()
    bridge = main_module.ros_bridge
    monkeypatch.setattr(bridge, "active", True, raising=False)
    monkeypatch.setattr(bridge, "_dispenser_command_publisher", publisher, raising=False)
    monkeypatch.setattr(bridge, "_dispenser_string_type", FakeString, raising=False)
    return publisher


def test_signature_matches_what_the_robot_verifies(monkeypatch):
    publisher = attach_fake_bridge(monkeypatch)
    monkeypatch.setenv("HAZARD_GUARD_DISPENSER_APPROVAL_SECRET", "booth-secret")

    result = main_module.ros_bridge.publish_dispenser_drop(
        {"request_id": "demo:abc123", "detection_id": None}
    )

    assert result["accepted"] is True
    payload = json.loads(publisher.messages[0].data)
    assert payload["command"] == "drop"
    assert robot_side_verify(
        "booth-secret",
        request_id="demo:abc123",
        detection_id=None,
        authorization=payload["authorization"],
    )


def test_signature_covers_detection_id(monkeypatch):
    publisher = attach_fake_bridge(monkeypatch)
    monkeypatch.setenv("HAZARD_GUARD_DISPENSER_APPROVAL_SECRET", "booth-secret")

    main_module.ros_bridge.publish_dispenser_drop(
        {"request_id": "demo:abc123", "detection_id": "thermal-7"}
    )

    payload = json.loads(publisher.messages[0].data)
    # A signature made without the detection id must not satisfy the robot.
    assert not robot_side_verify(
        "booth-secret",
        request_id="demo:abc123",
        detection_id=None,
        authorization=payload["authorization"],
    )
    assert robot_side_verify(
        "booth-secret",
        request_id="demo:abc123",
        detection_id="thermal-7",
        authorization=payload["authorization"],
    )


def test_publish_refuses_without_signing_key(monkeypatch):
    publisher = attach_fake_bridge(monkeypatch)
    monkeypatch.delenv("HAZARD_GUARD_DISPENSER_APPROVAL_SECRET", raising=False)

    result = main_module.ros_bridge.publish_dispenser_drop(
        {"request_id": "demo:abc123", "detection_id": None}
    )

    assert result["accepted"] is False
    assert publisher.messages == []


def test_demo_drop_is_disabled_by_default(tmp_path, monkeypatch):
    store = DispenserRequestStore(tmp_path / "backend.sqlite3")
    monkeypatch.setattr(main_module, "dispenser_request_store", store)
    monkeypatch.delenv("HAZARD_GUARD_DISPENSER_DEMO_DROP", raising=False)
    calls = []
    monkeypatch.setattr(
        main_module.ros_bridge,
        "publish_dispenser_drop",
        lambda request: calls.append(request) or {"accepted": True},
    )

    response = TestClient(app).post("/api/v1/dispenser/demo/drop")

    assert response.status_code == 503
    assert calls == []


def test_demo_drop_dispatches_and_records_the_request(tmp_path, monkeypatch):
    store = DispenserRequestStore(tmp_path / "backend.sqlite3")
    monkeypatch.setattr(main_module, "dispenser_request_store", store)
    monkeypatch.setenv("HAZARD_GUARD_DISPENSER_DEMO_DROP", "1")
    calls = []
    monkeypatch.setattr(
        main_module.ros_bridge,
        "publish_dispenser_drop",
        lambda request: calls.append(request) or {"accepted": True, "message": "sent"},
    )

    response = TestClient(app).post("/api/v1/dispenser/demo/drop")

    assert response.status_code == 202
    record = response.json()
    assert record["state"] == "dispatched"
    assert record["request_id"].startswith("demo:")
    assert record["audit_context"]["source"] == "exhibition_demo"
    assert len(calls) == 1
    # Each press is its own ledger entry; nothing is replayed onto the last one.
    assert store.get(record["request_id"])["state"] == "dispatched"


def test_demo_drop_marks_the_request_unavailable_when_the_bridge_refuses(
    tmp_path, monkeypatch
):
    store = DispenserRequestStore(tmp_path / "backend.sqlite3")
    monkeypatch.setattr(main_module, "dispenser_request_store", store)
    monkeypatch.setenv("HAZARD_GUARD_DISPENSER_DEMO_DROP", "1")
    monkeypatch.setattr(
        main_module.ros_bridge,
        "publish_dispenser_drop",
        lambda request: {"accepted": False, "message": "브리지 미연결"},
    )

    response = TestClient(app).post("/api/v1/dispenser/demo/drop")

    assert response.status_code == 503
    records = [store.get(r) for r in [response.json().get("request_id")] if r]
    # The ledger must not be left claiming a drop was dispatched.
    assert all(r is None or r["state"] == "dispatch_unavailable" for r in records)


def test_each_press_is_a_distinct_request(tmp_path, monkeypatch):
    store = DispenserRequestStore(tmp_path / "backend.sqlite3")
    monkeypatch.setattr(main_module, "dispenser_request_store", store)
    monkeypatch.setenv("HAZARD_GUARD_DISPENSER_DEMO_DROP", "1")
    monkeypatch.setattr(
        main_module.ros_bridge,
        "publish_dispenser_drop",
        lambda request: {"accepted": True},
    )
    client = TestClient(app)

    first = client.post("/api/v1/dispenser/demo/drop").json()["request_id"]
    second = client.post("/api/v1/dispenser/demo/drop").json()["request_id"]

    assert first != second


def test_status_reports_whether_the_demo_button_is_available(monkeypatch):
    monkeypatch.setenv("HAZARD_GUARD_DISPENSER_DEMO_DROP", "1")
    client = TestClient(app)

    assert client.get("/api/v1/dispenser/status").json()["demo_drop_enabled"] is True

    monkeypatch.setenv("HAZARD_GUARD_DISPENSER_DEMO_DROP", "0")
    assert client.get("/api/v1/dispenser/status").json()["demo_drop_enabled"] is False


def test_signing_helper_rejects_a_tampered_request_id():
    signature = command_authorization(
        "booth-secret", request_id="demo:abc123", detection_id=None
    )

    assert not robot_side_verify(
        "booth-secret",
        request_id="demo:abc124",
        detection_id=None,
        authorization=signature,
    )
