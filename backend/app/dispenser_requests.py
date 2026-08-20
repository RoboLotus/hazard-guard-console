"""Durable backend-side idempotency records for physical beacon requests."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TERMINAL = frozenset({
    "succeeded", "jam_suspected", "hardware_error", "canceled",
    "rejected_busy", "recovery_required", "command_completed_unverified",
    "dispatch_unavailable",
})
IN_PROGRESS = frozenset({"accepted", "dispatched", "dispensing", "waiting", "homing"})
_ORDER = {"accepted": 0, "dispatched": 1, "dispensing": 2, "waiting": 3, "homing": 4}
ROBOT_RESULT_STATES = frozenset({
    "dispensing", "waiting", "homing", "succeeded", "jam_suspected",
    "hardware_error", "canceled", "rejected_busy", "command_completed_unverified",
    "recovery_required",
})


class DispenserRequestStoreError(RuntimeError):
    pass


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


class DispenserRequestStore:
    """SQLite request ledger shared safely by all backend worker processes."""

    def __init__(self, path: str | Path | None = None) -> None:
        default_path = "~/.local/state/hazard_guard/dispenser/backend_requests.sqlite3"
        self.path = Path(
            path or os.getenv("HAZARD_GUARD_DISPENSER_REQUEST_STORE", default_path)
        ).expanduser()
        self._lock = threading.RLock()
        try:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            self._initialize()
            self.recover_interrupted()
        except (OSError, sqlite3.Error, ValueError, TypeError) as exc:
            raise DispenserRequestStoreError(
                f"디스펜서 요청 기록을 열 수 없습니다: {exc}"
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
                """CREATE TABLE IF NOT EXISTS dispenser_requests (
                    request_id TEXT PRIMARY KEY,
                    detection_id TEXT UNIQUE,
                    state TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )"""
            )

    @staticmethod
    def _validate(record: dict[str, Any]) -> dict[str, Any]:
        required = ("request_id", "command", "state", "created_at", "updated_at")
        if not all(isinstance(record.get(key), str) and record[key] for key in required):
            raise DispenserRequestStoreError("디스펜서 원장 레코드 스키마가 손상되었습니다")
        if record["state"] not in TERMINAL | IN_PROGRESS:
            raise DispenserRequestStoreError("디스펜서 원장 레코드 상태가 유효하지 않습니다")
        if record.get("detection_id") is not None and not isinstance(record["detection_id"], str):
            raise DispenserRequestStoreError("디스펜서 원장 detection_id가 손상되었습니다")
        return record

    def _decode(self, encoded: str) -> dict[str, Any]:
        try:
            value = json.loads(encoded)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise DispenserRequestStoreError("디스펜서 원장 JSON이 손상되었습니다") from exc
        if not isinstance(value, dict):
            raise DispenserRequestStoreError("디스펜서 원장 레코드가 객체가 아닙니다")
        return self._validate(value)

    def _row(self, row) -> dict[str, Any] | None:
        return self._decode(row[0]) if row is not None else None

    @staticmethod
    def _encode(record: dict[str, Any]) -> str:
        return json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _can_transition(current: str, target: str, *, from_robot: bool = False) -> bool:
        if current == target:
            return True
        if current == "recovery_required":
            return from_robot and target in TERMINAL - {"recovery_required"}
        if current in TERMINAL:
            return False
        if target in TERMINAL:
            return True
        return _ORDER.get(target, -1) >= _ORDER.get(current, -1)

    def submit(self, *, request_id: str, detection_id: str | None) -> tuple[dict[str, Any], bool]:
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT record_json FROM dispenser_requests WHERE request_id=?", (request_id,)
            ).fetchone()
            if row is None and detection_id:
                row = connection.execute(
                    "SELECT record_json FROM dispenser_requests WHERE detection_id=?", (detection_id,)
                ).fetchone()
            existing = self._row(row)
            if existing is not None:
                connection.commit()
                return existing, False
            timestamp = _timestamp()
            record = {
                "request_id": request_id, "detection_id": detection_id, "command": "drop",
                "state": "accepted", "created_at": timestamp, "updated_at": timestamp,
            }
            connection.execute(
                "INSERT INTO dispenser_requests VALUES (?, ?, ?, ?, ?, ?)",
                (request_id, detection_id, "accepted", self._encode(record), timestamp, timestamp),
            )
            connection.commit()
            return record, True

    def transition(self, request_id: str, state: str, **fields: Any) -> dict[str, Any]:
        return self._transition(request_id, state, False, **fields)

    def _transition(self, request_id: str, state: str, from_robot: bool, **fields: Any) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT record_json FROM dispenser_requests WHERE request_id=?", (request_id,)
            ).fetchone()
            record = self._row(row)
            if record is None:
                raise DispenserRequestStoreError(f"알 수 없는 request_id: {request_id}")
            if not self._can_transition(record["state"], state, from_robot=from_robot):
                connection.commit()
                return record
            record.update(fields)
            record["state"] = state
            record["updated_at"] = _timestamp()
            connection.execute(
                "UPDATE dispenser_requests SET state=?, record_json=?, updated_at=? WHERE request_id=?",
                (state, self._encode(record), record["updated_at"], request_id),
            )
            connection.commit()
            return record

    def apply_robot_result(self, result: dict[str, Any]) -> dict[str, Any] | None:
        request_id, state = result.get("request_id"), result.get("state")
        if not isinstance(request_id, str) or state not in ROBOT_RESULT_STATES:
            return None
        record = self.get(request_id)
        if record is None or result.get("command", "drop") != record["command"]:
            return None
        result_detection = result.get("detection_id")
        if result_detection is not None and result_detection != record.get("detection_id"):
            return None
        return self._transition(request_id, state, True, robot_result=result)

    def recover_interrupted(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT record_json FROM dispenser_requests WHERE state IN ('accepted','dispatched','dispensing','waiting','homing')"
            ).fetchall()
            for row in rows:
                record = self._row(row)
                record.update({
                    "state": "recovery_required", "updated_at": _timestamp(),
                    "result_detail": "backend_restarted_before_terminal_result",
                })
                connection.execute(
                    "UPDATE dispenser_requests SET state=?, record_json=?, updated_at=? WHERE request_id=?",
                    (record["state"], self._encode(record), record["updated_at"], record["request_id"]),
                )
            connection.commit()

    def get(self, request_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT record_json FROM dispenser_requests WHERE request_id=?", (request_id,)
            ).fetchone()
            return self._row(row)
