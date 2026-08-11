from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from .models import ThresholdSettings


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
