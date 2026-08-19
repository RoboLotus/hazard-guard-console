from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from .models import ThermalEquipmentSettingsDocument, ThresholdSettings


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
                    "critical_temperature_c": 49.0,
                    "adaptive_delta_c": 10.0,
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

    def _load(self) -> ThermalEquipmentSettingsDocument:
        try:
            return ThermalEquipmentSettingsDocument.model_validate_json(
                self.path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError, TypeError):
            return default_thermal_equipment_settings()

    def get(self) -> ThermalEquipmentSettingsDocument:
        with self._lock:
            return self._value.model_copy(deep=True)

    def save(
        self, value: ThermalEquipmentSettingsDocument
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
            return self.get()

    def reset_defaults(self) -> ThermalEquipmentSettingsDocument:
        return self.save(default_thermal_equipment_settings())
