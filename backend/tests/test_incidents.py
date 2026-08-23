from concurrent.futures import ThreadPoolExecutor

import pytest

from app.incidents import (
    IncidentDecisionConflictError,
    IncidentStore,
    IncidentStoreError,
    sign_incident_decision,
)


def incident_payload(state: str = "approval_required") -> dict:
    return {
        "incident_id": "incident-1",
        "detection_id": "detection-1",
        "state": state,
        "severity": "critical",
        "temperature_c": 84.6,
        "message": "관리자 승인이 필요합니다.",
    }


def test_incident_upsert_preserves_creation_and_replaces_runtime_state(tmp_path):
    store = IncidentStore(tmp_path / "incidents.sqlite3")
    first = store.upsert_incident(incident_payload())
    updated = store.upsert_incident(
        {**incident_payload("dispensing"), "decision": "drop_then_monitor"}
    )

    assert updated["created_at"] == first["created_at"]
    assert updated["state"] == "dispensing"
    assert store.list()[0]["decision"] == "drop_then_monitor"


def test_decision_idempotency_and_conflict_survive_restart(tmp_path):
    path = tmp_path / "incidents.sqlite3"
    store = IncidentStore(path)
    store.upsert_incident(incident_payload())
    created, is_new = store.begin_decision(
        request_id="decision-1",
        incident_id="incident-1",
        decision="drop_then_resume",
        operator_id="operator@example.com",
    )
    replayed, replay_is_new = IncidentStore(path).begin_decision(
        request_id="decision-1",
        incident_id="incident-1",
        decision="drop_then_resume",
        operator_id="operator@example.com",
    )

    assert is_new is True
    assert replay_is_new is False
    assert replayed == created
    with pytest.raises(IncidentDecisionConflictError):
        IncidentStore(path).begin_decision(
            request_id="decision-1",
            incident_id="incident-1",
            decision="resume",
            operator_id="operator@example.com",
        )


def test_decision_requires_known_incident_and_supported_value(tmp_path):
    store = IncidentStore(tmp_path / "incidents.sqlite3")
    with pytest.raises(IncidentStoreError, match="알 수 없는"):
        store.begin_decision(
            request_id="decision-1",
            incident_id="missing",
            decision="resume",
            operator_id="operator",
        )
    store.upsert_incident(incident_payload())
    with pytest.raises(IncidentStoreError, match="지원하지 않는"):
        store.begin_decision(
            request_id="decision-2",
            incident_id="incident-1",
            decision="unsafe-auto-drop",
            operator_id="operator",
        )


def test_decision_update_is_persisted_and_auditable(tmp_path):
    store = IncidentStore(tmp_path / "incidents.sqlite3")
    store.upsert_incident(incident_payload())
    store.begin_decision(
        request_id="decision-1",
        incident_id="incident-1",
        decision="resume",
        operator_id="operator",
    )

    store.claim_dispatch("decision-1", owner_id="worker-1")
    result = store.transition_decision(
        "decision-1",
        state="accepted",
        robot_response={"state": "resuming", "incident_id": "spoofed"},
    )

    assert result["state"] == "accepted"
    assert result["incident_id"] == "incident-1"
    assert result["robot_response"]["state"] == "resuming"
    assert store.decisions_for("incident-1") == [result]


def test_concurrent_duplicate_decision_creates_one_record(tmp_path):
    path = tmp_path / "incidents.sqlite3"
    store = IncidentStore(path)
    store.upsert_incident(incident_payload())

    def submit():
        return IncidentStore(path).begin_decision(
            request_id="decision-shared",
            incident_id="incident-1",
            decision="resume",
            operator_id="operator",
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: submit(), range(8)))

    assert sum(1 for _, created in results if created) == 1
    assert len(store.decisions_for("incident-1")) == 1


def test_dispatch_claim_can_be_replayed_after_crash_but_terminal_cannot(tmp_path):
    path = tmp_path / "incidents.sqlite3"
    store = IncidentStore(path)
    store.upsert_incident(incident_payload())
    store.begin_decision(
        request_id="decision-1",
        incident_id="incident-1",
        decision="resume",
        operator_id="operator",
    )
    store.claim_dispatch("decision-1", owner_id="worker-1")

    restarted = IncidentStore(path)
    record, claimed = restarted.claim_dispatch(
        "decision-1", owner_id="worker-2", lease_sec=0.000001
    )
    assert claimed is True
    assert record["state"] == "dispatching"
    restarted.transition_decision(
        "decision-1", state="accepted", robot_response={"accepted": True}
    )
    with pytest.raises(IncidentDecisionConflictError):
        restarted.claim_dispatch("decision-1", owner_id="worker-3")


def test_decision_state_regression_and_unknown_state_are_rejected(tmp_path):
    store = IncidentStore(tmp_path / "incidents.sqlite3")
    store.upsert_incident(incident_payload())
    store.begin_decision(
        request_id="decision-1",
        incident_id="incident-1",
        decision="resume",
        operator_id="operator",
    )
    with pytest.raises(IncidentDecisionConflictError):
        store.transition_decision("decision-1", state="accepted")
    with pytest.raises(IncidentStoreError):
        store.transition_decision("decision-1", state="made-up")


def test_live_dispatch_lease_suppresses_concurrent_service_call(tmp_path):
    path = tmp_path / "incidents.sqlite3"
    store = IncidentStore(path)
    store.upsert_incident(incident_payload())
    store.begin_decision(
        request_id="decision-1",
        incident_id="incident-1",
        decision="resume",
        operator_id="operator",
    )

    first, first_claimed = IncidentStore(path).claim_dispatch(
        "decision-1", owner_id="worker-1"
    )
    second, second_claimed = IncidentStore(path).claim_dispatch(
        "decision-1", owner_id="worker-2"
    )

    assert first_claimed is True
    assert second_claimed is False
    assert second["dispatch_owner_id"] == first["dispatch_owner_id"]


@pytest.mark.parametrize(
    ("field", "value"),
    [("request_id", "space is invalid"), ("incident_id", ""), ("operator_id", "한글")],
)
def test_decision_identifiers_are_validated(tmp_path, field, value):
    store = IncidentStore(tmp_path / "incidents.sqlite3")
    store.upsert_incident(incident_payload())
    values = {
        "request_id": "decision-1",
        "incident_id": "incident-1",
        "decision": "resume",
        "operator_id": "operator",
    }
    values[field] = value
    with pytest.raises(IncidentStoreError):
        store.begin_decision(**values)


def test_signature_matches_robot_contract():
    assert sign_incident_decision(
        secret="shared-secret",
        incident_id="incident-1",
        request_id="decision-1",
        decision="drop_then_monitor",
        operator_id="operator",
    ) == "1368d78ac5695945053106ba874efda8bc1b5f3185299a835dc3c922f3c29d60"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("incident_id", "incident-2"),
        ("request_id", "decision-2"),
        ("decision", "resume"),
        ("operator_id", "another-operator"),
    ],
)
def test_signature_binds_every_decision_field(field, value):
    values = {
        "secret": "shared-secret",
        "incident_id": "incident-1",
        "request_id": "decision-1",
        "decision": "drop_then_monitor",
        "operator_id": "operator",
    }
    original = sign_incident_decision(**values)
    values[field] = value
    assert sign_incident_decision(**values) != original
