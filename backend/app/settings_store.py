from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .models import ThermalEquipmentSettingsDocument, ThresholdSettings


LEGACY_WASTE_CRITICAL_TEMPERATURE_C = 49.0
DEFAULT_WASTE_CRITICAL_TEMPERATURE_C = 60.0


def migrate_legacy_equipment_defaults(
    value: ThermalEquipmentSettingsDocument,
) -> ThermalEquipmentSettingsDocument:
    """Replace only the superseded waste-pile default, preserving custom values."""

    migrated = value.model_copy(deep=True)
    for equipment in migrated.equipment:
        if (
            equipment.id == "bunker_waste_pile"
            and equipment.critical_temperature_c
            == LEGACY_WASTE_CRITICAL_TEMPERATURE_C
        ):
            equipment.critical_temperature_c = (
                DEFAULT_WASTE_CRITICAL_TEMPERATURE_C
            )
    return migrated


class ThresholdSettingsStore:
    """Persist validated fire thresholds outside of the Git worktree."""

    def __init__(self, path: Path | None = None) -> None:
        workspace = Path(
            os.getenv("HAZARD_GUARD_WORKSPACE", os.getcwd())
        ).expanduser().resolve()
        self.path = (
            path
            or Path(
                os.getenv(
                    "HAZARD_GUARD_THRESHOLD_SETTINGS_PATH",
                    workspace / "runtime" / "settings" / "thresholds.json",
                )
            )
        ).expanduser().resolve()
        self._lock = threading.RLock()
        self._value = self._load()

    def _load(self) -> ThresholdSettings:
        try:
            return ThresholdSettings.model_validate_json(
                self.path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError, TypeError):
            return ThresholdSettings()

    def get(self) -> ThresholdSettings:
        with self._lock:
            return self._value.model_copy(deep=True)

    def save(self, value: ThresholdSettings) -> ThresholdSettings:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
            temporary.write_text(
                json.dumps(value.model_dump(), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.path)
            self._value = value.model_copy(deep=True)
            return self.get()

def default_thermal_equipment_settings() -> ThermalEquipmentSettingsDocument:
    return ThermalEquipmentSettingsDocument.model_validate(
        {
            "schema_version": 1,
            "equipment": [
                {
                    "id": "bunker_waste_pile",
                    "display_name": "폐기물 적치 구역",
                    "enabled": True,
                    "critical_temperature_c": DEFAULT_WASTE_CRITICAL_TEMPERATURE_C,
                    "adaptive_delta_c": 10.0,
                    "adaptive_threshold_enabled": True,
                    "roi": {
                        "min": [-1.95, -0.95, 0.02],
                        "max": [-1.45, -0.45, 0.35],
                    },
                },
                {
                    "id": "primary_shredder_motor",
                    "display_name": "1차 파쇄기 모터",
                    "enabled": True,
                    "critical_temperature_c": 110.0,
                    "adaptive_delta_c": 10.0,
                    "adaptive_threshold_enabled": True,
                    "roi": {
                        "min": [-1.25, 0.0, 0.02],
                        "max": [-0.78, 0.5, 0.42],
                    },
                },
                {
                    "id": "secondary_processor_pump",
                    "display_name": "2차 처리기 펌프",
                    "enabled": True,
                    "critical_temperature_c": 105.0,
                    "adaptive_delta_c": 10.0,
                    "adaptive_threshold_enabled": True,
                    "roi": {
                        "min": [0.95, 0.53, 0.02],
                        "max": [1.32, 0.86, 0.42],
                    },
                },
                {
                    "id": "baler_hydraulic_tank",
                    "display_name": "베일러 유압 탱크",
                    "enabled": True,
                    "critical_temperature_c": 82.0,
                    "adaptive_delta_c": 10.0,
                    "adaptive_threshold_enabled": True,
                    "roi": {
                        "min": [0.94, 0.2, 0.02],
                        "max": [1.34, 0.5, 0.3],
                    },
                },
            ],
        }
    )


class ThermalEquipmentSettingsStore:
    """Persist validated per-equipment thermal settings outside the worktree."""

    def __init__(self, path: Path | None = None) -> None:
        workspace = Path(
            os.getenv("HAZARD_GUARD_WORKSPACE", os.getcwd())
        ).expanduser().resolve()
        self.path = (
            path
            or Path(
                os.getenv(
                    "HAZARD_GUARD_EQUIPMENT_SETTINGS_PATH",
                    workspace / "runtime" / "settings" / "equipment.json",
                )
            )
        ).expanduser().resolve()
        self._lock = threading.RLock()
        self._value = self._load()
        self.history_path = self.path.parent / "equipment-history"

    def _load(self) -> ThermalEquipmentSettingsDocument:
        try:
            document = ThermalEquipmentSettingsDocument.model_validate_json(
                self.path.read_text(encoding="utf-8")
            )
            return migrate_legacy_equipment_defaults(document)
        except (OSError, ValueError, TypeError):
            return default_thermal_equipment_settings()

    def get(self) -> ThermalEquipmentSettingsDocument:
        with self._lock:
            return self._value.model_copy(deep=True)

    def save(
        self,
        value: ThermalEquipmentSettingsDocument,
        *,
        reason: str = "manual",
    ) -> ThermalEquipmentSettingsDocument:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
            temporary.write_text(
                json.dumps(
                    value.model_dump(by_alias=True),
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.path)
            self._value = value.model_copy(deep=True)
            self._record_revision(value, reason=reason)
            return self.get()

    def reset_defaults(self) -> ThermalEquipmentSettingsDocument:
        return self.save(default_thermal_equipment_settings(), reason="defaults")

    def metadata(self) -> dict[str, Any]:
        with self._lock:
            updated_at = None
            if self.path.exists():
                updated_at = datetime.fromtimestamp(
                    self.path.stat().st_mtime,
                    timezone.utc,
                ).isoformat()
            revisions = self.history(limit=1)
            return {
                "updated_at": updated_at,
                "revision_id": revisions[0]["revision_id"] if revisions else None,
            }

    def history(self, *, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            if not self.history_path.exists():
                return []
            revisions: list[dict[str, Any]] = []
            for path in self.history_path.glob("*.json"):
                try:
                    if path.is_symlink() or path.resolve().parent != self.history_path.resolve():
                        continue
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    settings = ThermalEquipmentSettingsDocument.model_validate(
                        payload["settings"]
                    )
                    revision_id = str(payload["revision_id"])
                    if revision_id != path.stem:
                        continue
                    revisions.append(
                        {
                            "revision_id": revision_id,
                            "created_at": str(payload["created_at"]),
                            "reason": str(payload.get("reason", "manual")),
                            "equipment_count": len(settings.equipment),
                        }
                    )
                except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                    continue
            revisions.sort(key=lambda item: item["created_at"], reverse=True)
            return revisions[: max(1, min(limit, 50))]

    def restore(self, revision_id: str) -> ThermalEquipmentSettingsDocument:
        if not re.fullmatch(r"[0-9]{8}T[0-9]{6}Z[0-9a-f]{6}", revision_id):
            raise KeyError(revision_id)
        with self._lock:
            path = self.history_path / f"{revision_id}.json"
            try:
                if (
                    path.is_symlink()
                    or path.parent.resolve() != self.history_path.resolve()
                    or path.resolve().parent != self.history_path.resolve()
                ):
                    raise KeyError(revision_id)
                payload = json.loads(path.read_text(encoding="utf-8"))
                if str(payload["revision_id"]) != revision_id:
                    raise KeyError(revision_id)
                settings = ThermalEquipmentSettingsDocument.model_validate(
                    payload["settings"]
                )
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                raise KeyError(revision_id) from None
            return self.save(settings, reason=f"restore:{revision_id}")

    def _record_revision(
        self,
        value: ThermalEquipmentSettingsDocument,
        *,
        reason: str,
    ) -> None:
        now = datetime.now(timezone.utc)
        revision_id = f"{now.strftime('%Y%m%dT%H%M%SZ')}{uuid4().hex[:6]}"
        self.history_path.mkdir(parents=True, exist_ok=True)
        if (
            self.history_path.is_symlink()
            or self.history_path.resolve().parent != self.path.parent.resolve()
        ):
            raise OSError("unsafe equipment history path")
        target = self.history_path / f"{revision_id}.json"
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(
                {
                    "revision_id": revision_id,
                    "created_at": now.isoformat(),
                    "reason": reason,
                    "settings": value.model_dump(by_alias=True),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(target)
        revisions = sorted(self.history_path.glob("*.json"), reverse=True)
        for stale in revisions[50:]:
            stale.unlink(missing_ok=True)
