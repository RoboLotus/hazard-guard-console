"""Durable backend-side idempotency records for physical beacon requests."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


IN_PROGRESS = frozenset({"accepted", "dispatched", "dispensing", "waiting", "homing"})


class DispenserRequestStoreError(RuntimeError):
    pass


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


class DispenserRequestStore:
    """A local ledger that makes retrying an HTTP request physically safe."""

    def __init__(self, path: str | Path | None = None) -> None:
        default_path = "~/.local/state/hazard_guard/dispenser/backend_requests.json"
        self.path = Path(
            path or os.getenv("HAZARD_GUARD_DISPENSER_REQUEST_STORE", default_path)
        ).expanduser()
        self._lock = threading.RLock()
        self._records: dict[str, dict[str, Any]] = {}
        self._load()
        self.recover_interrupted()

    @staticmethod
    def _clone(value: dict[str, Any]) -> dict[str, Any]:
        return json.loads(json.dumps(value, ensure_ascii=False))

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            records = payload.get("records") if isinstance(payload, dict) else None
            if not isinstance(records, dict):
                raise ValueError("records must be an object")
            self._records = {
                str(key): dict(value)
                for key, value in records.items()
                if isinstance(value, dict)
            }
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise DispenserRequestStoreError(
                f"디스펜서 요청 기록을 읽을 수 없습니다: {exc}"
            ) from exc

    def _persist(self) -> None:
        try:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            with temporary.open("w", encoding="utf-8") as handle:
                json.dump(
                    {"schema_version": 1, "records": self._records},
                    handle,
                    ensure_ascii=False,
                    sort_keys=True,
                )
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            if os.name != "nt":
                self.path.chmod(0o600)
        except OSError as exc:
            raise DispenserRequestStoreError(
                f"디스펜서 요청 기록을 저장할 수 없습니다: {exc}"
            ) from exc

    def _find_detection(self, detection_id: str) -> dict[str, Any] | None:
        return next(
            (
                record
                for record in self._records.values()
                if record.get("detection_id") == detection_id
            ),
            None,
        )

    def submit(
        self, *, request_id: str, detection_id: str | None
    ) -> tuple[dict[str, Any], bool]:
        with self._lock:
            record = self._records.get(request_id)
            if record is not None:
                return self._clone(record), False
            if detection_id:
                record = self._find_detection(detection_id)
                if record is not None:
                    return self._clone(record), False
            record = {
                "request_id": request_id,
                "detection_id": detection_id,
                "state": "accepted",
                "created_at": _timestamp(),
                "updated_at": _timestamp(),
            }
            self._records[request_id] = record
            self._persist()
            return self._clone(record), True

    def transition(
        self, request_id: str, state: str, **fields: Any
    ) -> dict[str, Any]:
        with self._lock:
            record = self._records.get(request_id)
            if record is None:
                raise DispenserRequestStoreError(f"알 수 없는 request_id: {request_id}")
            record.update(fields)
            record["state"] = state
            record["updated_at"] = _timestamp()
            self._persist()
            return self._clone(record)

    def apply_robot_result(self, result: dict[str, Any]) -> dict[str, Any] | None:
        request_id = result.get("request_id")
        state = result.get("state")
        if not isinstance(request_id, str) or not isinstance(state, str):
            return None
        with self._lock:
            if request_id not in self._records:
                return None
            return self.transition(request_id, state, robot_result=self._clone(result))

    def recover_interrupted(self) -> None:
        with self._lock:
            changed = False
            for record in self._records.values():
                if record.get("state") in IN_PROGRESS:
                    record.update(
                        {
                            "state": "recovery_required",
                            "updated_at": _timestamp(),
                            "result_detail": "backend_restarted_before_terminal_result",
                        }
                    )
                    changed = True
            if changed:
                self._persist()

    def get(self, request_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._records.get(request_id)
            return self._clone(record) if record is not None else None
