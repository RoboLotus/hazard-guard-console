"""Durable incident and operator-decision audit records."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import threading
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DECISIONS = frozenset({
    "resume",
    "drop_then_resume",
    "drop_then_monitor",
    "complete_monitoring",
    "acknowledge_field_check",
})
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,96}$")
OPERATOR_PATTERN = re.compile(r"^[A-Za-z0-9_.:@-]{1,80}$")
DECISION_STATES = frozenset({
    "recorded", "dispatching", "accepted", "rejected", "transport_unavailable"
})
_DECISION_TRANSITIONS = {
    "recorded": frozenset({"dispatching"}),
    # A dispatching request is safe to resend after a process crash because the
    # Robot service enforces the same request_id idempotency contract.
    "dispatching": frozenset(
        {"dispatching", "accepted", "rejected", "transport_unavailable"}
    ),
    "transport_unavailable": frozenset({"dispatching"}),
    "accepted": frozenset(),
    "rejected": frozenset(),
}


class IncidentStoreError(RuntimeError):
    pass


class IncidentDecisionConflictError(IncidentStoreError):
    """An idempotency key was reused with different decision content."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def decision_fingerprint(
    incident_id: str,
    decision: str,
    operator_id: str,
) -> str:
    canonical = json.dumps(
        {
            "incident_id": incident_id,
            "decision": decision,
            "operator_id": operator_id,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def sign_incident_decision(
    *,
    secret: str,
    incident_id: str,
    request_id: str,
    decision: str,
    operator_id: str,
) -> str:
    """Produce the exact signature verified by the Robot mission manager."""

    if not secret:
        raise ValueError("approval secret is required")
    payload = "\n".join(
        ("decision", incident_id, request_id, decision, operator_id)
    )
    return hmac.new(
        secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()


class IncidentStore:
    """SQLite ledger that survives backend restarts and worker concurrency."""

    def __init__(self, path: str | Path | None = None) -> None:
        default_path = "~/.local/state/hazard_guard/incidents/incidents.sqlite3"
        self.path = Path(
            path or os.getenv("HAZARD_GUARD_INCIDENT_STORE", default_path)
        ).expanduser()
        self._lock = threading.RLock()
        try:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            self._initialize()
            if os.name != "nt":
                os.chmod(self.path, 0o600)
        except (OSError, sqlite3.Error, ValueError, TypeError) as exc:
            raise IncidentStoreError(
                f"위험 이벤트 기록을 열 수 없습니다: {exc}"
            ) from exc

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS incidents (
                    incident_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS incident_decisions (
                    request_id TEXT PRIMARY KEY,
                    incident_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    state TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )"""
            )
            connection.execute(
                """CREATE INDEX IF NOT EXISTS idx_incidents_updated
                   ON incidents(updated_at DESC)"""
            )
            connection.execute(
                """CREATE INDEX IF NOT EXISTS idx_decisions_incident
                   ON incident_decisions(incident_id, updated_at DESC)"""
            )

    @staticmethod
    def _encode(record: dict[str, Any]) -> str:
        return json.dumps(
            record,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

    @staticmethod
    def _decode(encoded: str) -> dict[str, Any]:
        try:
            value = json.loads(encoded)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise IncidentStoreError("위험 이벤트 원장 JSON이 손상되었습니다") from exc
        if not isinstance(value, dict):
            raise IncidentStoreError("위험 이벤트 원장 레코드가 객체가 아닙니다")
        return value

    def upsert_incident(self, payload: dict[str, Any]) -> dict[str, Any]:
        incident_id = str(payload.get("incident_id") or "").strip()
        state = str(payload.get("state") or "").strip()
        if not incident_id or not state:
            raise IncidentStoreError("incident_id와 state가 필요합니다")
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT record_json, created_at FROM incidents WHERE incident_id=?",
                (incident_id,),
            ).fetchone()
            timestamp = utc_now()
            if row is None:
                created_at = timestamp
                record: dict[str, Any] = {}
            else:
                record = self._decode(row[0])
                created_at = row[1]
            record.update(payload)
            record.update(
                incident_id=incident_id,
                state=state,
                created_at=created_at,
                updated_at=timestamp,
            )
            connection.execute(
                """INSERT INTO incidents
                   (incident_id, state, record_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(incident_id) DO UPDATE SET
                       state=excluded.state,
                       record_json=excluded.record_json,
                       updated_at=excluded.updated_at""",
                (incident_id, state, self._encode(record), created_at, timestamp),
            )
            connection.commit()
            return record

    def get(self, incident_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT record_json FROM incidents WHERE incident_id=?",
                (incident_id,),
            ).fetchone()
            return self._decode(row[0]) if row is not None else None

    def list(self, *, limit: int = 100) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(int(limit), 500))
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT record_json FROM incidents ORDER BY updated_at DESC LIMIT ?",
                (bounded_limit,),
            ).fetchall()
            return [self._decode(row[0]) for row in rows]

    def begin_decision(
        self,
        *,
        request_id: str,
        incident_id: str,
        decision: str,
        operator_id: str,
    ) -> tuple[dict[str, Any], bool]:
        request_id = str(request_id).strip()
        incident_id = str(incident_id).strip()
        operator_id = str(operator_id).strip()
        if not IDENTIFIER_PATTERN.fullmatch(request_id):
            raise IncidentStoreError("request_id 형식이 올바르지 않습니다")
        if not IDENTIFIER_PATTERN.fullmatch(incident_id):
            raise IncidentStoreError("incident_id 형식이 올바르지 않습니다")
        if not OPERATOR_PATTERN.fullmatch(operator_id):
            raise IncidentStoreError("operator_id 형식이 올바르지 않습니다")
        if decision not in DECISIONS:
            raise IncidentStoreError(f"지원하지 않는 관리자 결정입니다: {decision}")
        fingerprint = decision_fingerprint(incident_id, decision, operator_id)
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            incident_row = connection.execute(
                "SELECT 1 FROM incidents WHERE incident_id=?", (incident_id,)
            ).fetchone()
            if incident_row is None:
                connection.rollback()
                raise IncidentStoreError("알 수 없는 위험 이벤트입니다")
            row = connection.execute(
                "SELECT fingerprint, record_json FROM incident_decisions WHERE request_id=?",
                (request_id,),
            ).fetchone()
            if row is not None:
                if not hmac.compare_digest(row[0], fingerprint):
                    connection.rollback()
                    raise IncidentDecisionConflictError(
                        "request_id가 다른 관리자 결정에 재사용되었습니다"
                    )
                connection.commit()
                return self._decode(row[1]), False
            timestamp = utc_now()
            record = {
                "request_id": request_id,
                "incident_id": incident_id,
                "decision": decision,
                "operator_id": operator_id,
                "state": "recorded",
                "created_at": timestamp,
                "updated_at": timestamp,
            }
            connection.execute(
                "INSERT INTO incident_decisions VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    request_id,
                    incident_id,
                    fingerprint,
                    record["state"],
                    self._encode(record),
                    timestamp,
                    timestamp,
                ),
            )
            connection.commit()
            return record, True

    def transition_decision(
        self,
        request_id: str,
        *,
        state: str,
        robot_response: dict[str, Any] | None = None,
        message: str | None = None,
    ) -> dict[str, Any]:
        if state not in DECISION_STATES:
            raise IncidentStoreError("관리자 결정 상태가 유효하지 않습니다")
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT record_json FROM incident_decisions WHERE request_id=?",
                (request_id,),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise IncidentStoreError("알 수 없는 관리자 결정 요청입니다")
            record = self._decode(row[0])
            current = str(record.get("state") or "")
            if state not in _DECISION_TRANSITIONS.get(current, frozenset()):
                connection.rollback()
                raise IncidentDecisionConflictError(
                    f"관리자 결정 상태를 {current}에서 {state}(으)로 변경할 수 없습니다"
                )
            if robot_response is not None:
                if not isinstance(robot_response, dict):
                    connection.rollback()
                    raise IncidentStoreError("Robot 응답은 객체여야 합니다")
                # Keep external fields nested so request audit identity cannot
                # diverge from the indexed SQLite columns.
                record["robot_response"] = json.loads(self._encode(robot_response))
            if message is not None:
                record["message"] = str(message)
            record.update(state=state, updated_at=utc_now())
            connection.execute(
                """UPDATE incident_decisions
                   SET state=?, record_json=?, updated_at=? WHERE request_id=?""",
                (state, self._encode(record), record["updated_at"], request_id),
            )
            connection.commit()
            return record

    def claim_dispatch(
        self,
        request_id: str,
        *,
        owner_id: str,
        lease_sec: float = 5.0,
    ) -> tuple[dict[str, Any], bool]:
        """Atomically claim one Robot call across backend workers.

        A live lease suppresses concurrent duplicate service calls. An expired
        lease can be reclaimed after a worker crash because Robot enforces the
        same request_id idempotency contract.
        """

        if not IDENTIFIER_PATTERN.fullmatch(str(owner_id)):
            raise IncidentStoreError("dispatch owner_id 형식이 올바르지 않습니다")
        if lease_sec <= 0:
            raise IncidentStoreError("dispatch lease는 0보다 커야 합니다")
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT record_json FROM incident_decisions WHERE request_id=?",
                (request_id,),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise IncidentStoreError("알 수 없는 관리자 결정 요청입니다")
            record = self._decode(row[0])
            current = str(record.get("state") or "")
            if current == "dispatching":
                try:
                    updated_at = datetime.fromisoformat(record["updated_at"])
                    lease_age = (
                        datetime.now(timezone.utc) - updated_at
                    ).total_seconds()
                except (KeyError, TypeError, ValueError):
                    lease_age = lease_sec + 1.0
                if lease_age < lease_sec:
                    connection.commit()
                    return record, False
            elif current not in {"recorded", "transport_unavailable"}:
                connection.rollback()
                raise IncidentDecisionConflictError(
                    f"{current} 상태의 결정은 전송할 수 없습니다"
                )
            record.update(
                state="dispatching",
                dispatch_owner_id=owner_id,
                updated_at=utc_now(),
            )
            connection.execute(
                """UPDATE incident_decisions
                   SET state=?, record_json=?, updated_at=? WHERE request_id=?""",
                (
                    record["state"],
                    self._encode(record),
                    record["updated_at"],
                    request_id,
                ),
            )
            connection.commit()
            return record, True

    def get_decision(self, request_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT record_json FROM incident_decisions WHERE request_id=?",
                (request_id,),
            ).fetchone()
            return self._decode(row[0]) if row is not None else None

    def decisions_for(self, incident_id: str) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """SELECT record_json FROM incident_decisions
                   WHERE incident_id=? ORDER BY updated_at DESC""",
                (incident_id,),
            ).fetchall()
            return [self._decode(row[0]) for row in rows]
