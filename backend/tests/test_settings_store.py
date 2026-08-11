import json

from app.models import ThresholdSettings
from app.settings_store import ThresholdSettingsStore


def test_threshold_settings_survive_store_recreation(tmp_path):
    path = tmp_path / "runtime" / "settings" / "thresholds.json"
    store = ThresholdSettingsStore(path)
    expected = ThresholdSettings(
        warningTemperature=58,
        criticalTemperature=78,
        clearTemperature=48,
    )

    store.save(expected)
    reloaded = ThresholdSettingsStore(path).get()

    assert reloaded == expected
    assert json.loads(path.read_text(encoding="utf-8"))["warningTemperature"] == 58
