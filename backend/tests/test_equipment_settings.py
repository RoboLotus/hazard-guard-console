import json

from fastapi.testclient import TestClient

from app import main as main_module
from app.main import app
from app.settings_store import ThermalEquipmentSettingsStore


client = TestClient(app)


def test_equipment_store_starts_with_four_defaults_and_persists(tmp_path):
    path = tmp_path / "equipment.json"
    store = ThermalEquipmentSettingsStore(path)

    settings = store.get()
    assert len(settings.equipment) == 4
    assert settings.equipment[0].display_name == "폐기물 적치 구역"
    assert settings.equipment[0].adaptive_threshold_enabled is True

    settings.equipment[0].display_name = "1번 적치 구역"
    store.save(settings)

    reloaded = ThermalEquipmentSettingsStore(path).get()
    assert reloaded.equipment[0].display_name == "1번 적치 구역"
    assert reloaded.equipment[0].roi.minimum == [-1.95, -0.95, 0.02]
    history = store.history()
    assert len(history) == 1
    assert history[0]["reason"] == "manual"
    assert store.metadata()["revision_id"] == history[0]["revision_id"]


def test_legacy_equipment_settings_default_adaptive_policy_to_enabled(
    tmp_path,
):
    path = tmp_path / "equipment.json"
    document = {
        "schema_version": 1,
        "equipment": [
            {
                "id": "motor",
                "display_name": "모터",
                "enabled": True,
                "critical_temperature_c": 100.0,
                "adaptive_delta_c": 10.0,
                "roi": {"min": [0, 0, 0], "max": [1, 1, 1]},
            }
        ],
    }
    path.write_text(json.dumps(document), encoding="utf-8")

    loaded = ThermalEquipmentSettingsStore(path).get()

    assert loaded.equipment[0].adaptive_threshold_enabled is True


def test_equipment_store_restores_a_validated_revision(tmp_path):
    store = ThermalEquipmentSettingsStore(tmp_path / "equipment.json")
    original = store.get()
    original.equipment[0].display_name = "보관 이름"
    store.save(original)
    revision_id = store.history()[0]["revision_id"]

    changed = store.get()
    changed.equipment[0].display_name = "현재 이름"
    store.save(changed)
    restored = store.restore(revision_id)

    assert restored.equipment[0].display_name == "보관 이름"
    assert store.history()[0]["reason"] == f"restore:{revision_id}"


def test_equipment_store_rejects_unsafe_or_missing_revision(tmp_path):
    store = ThermalEquipmentSettingsStore(tmp_path / "equipment.json")

    for revision_id in ("../equipment", "missing"):
        try:
            store.restore(revision_id)
        except KeyError:
            pass
        else:
            raise AssertionError("unsafe revision id should be rejected")


def test_equipment_settings_api_supports_update_and_rejects_bad_roi(
    monkeypatch, tmp_path
):
    store = ThermalEquipmentSettingsStore(tmp_path / "equipment.json")
    monkeypatch.setattr(main_module, "equipment_store", store)
    monkeypatch.setattr(
        main_module.ros_bridge,
        "publish_thermal_equipment_config",
        lambda document: {"state": "offline", "equipment": []},
    )

    response = client.get("/api/v1/settings/equipment")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["equipment"]) == 4
    payload["equipment"][0]["display_name"] = "1번 적치 구역"
    payload.pop("runtime")

    saved = client.put("/api/v1/settings/equipment", json=payload)
    assert saved.status_code == 200
    assert saved.json()["equipment"][0]["display_name"] == "1번 적치 구역"

    payload["equipment"][0]["roi"] = {
        "min": [1.0, 0.0, 0.0],
        "max": [0.0, 1.0, 1.0],
    }
    invalid = client.put("/api/v1/settings/equipment", json=payload)
    assert invalid.status_code == 422

    history = client.get("/api/v1/settings/equipment/history")
    assert history.status_code == 200
    assert history.json()["revisions"]


def test_equipment_settings_api_publishes_adaptive_policy(monkeypatch, tmp_path):
    store = ThermalEquipmentSettingsStore(tmp_path / "equipment.json")
    monkeypatch.setattr(main_module, "equipment_store", store)
    published = []
    monkeypatch.setattr(
        main_module.ros_bridge,
        "publish_thermal_equipment_config",
        lambda document: published.append(document)
        or {"state": "published", "equipment": []},
    )
    payload = store.get().model_dump(by_alias=True)
    payload["equipment"][0]["adaptive_threshold_enabled"] = False

    response = client.put("/api/v1/settings/equipment", json=payload)

    assert response.status_code == 200
    assert published[-1]["equipment"][0]["adaptive_threshold_enabled"] is False
    assert (
        response.json()["equipment"][0]["adaptive_threshold_enabled"] is False
    )


def test_equipment_settings_api_returns_robot_rejection_without_rolling_back(
    monkeypatch, tmp_path
):
    store = ThermalEquipmentSettingsStore(tmp_path / "equipment.json")
    monkeypatch.setattr(main_module, "equipment_store", store)
    monkeypatch.setattr(
        main_module.ros_bridge,
        "publish_thermal_equipment_config",
        lambda document: {
            "state": "rejected",
            "error": "baseline state could not be invalidated safely",
            "equipment": [],
        },
    )
    payload = store.get().model_dump(by_alias=True)
    payload["equipment"][0]["display_name"] = "저장된 목표 설정"

    response = client.put("/api/v1/settings/equipment", json=payload)

    assert response.status_code == 200
    assert response.json()["runtime"]["state"] == "rejected"
    assert response.json()["runtime"]["error"]
    assert store.get().equipment[0].display_name == "저장된 목표 설정"


def test_equipment_settings_apply_retries_without_creating_revision(
    monkeypatch, tmp_path
):
    store = ThermalEquipmentSettingsStore(tmp_path / "equipment.json")
    settings = store.get()
    settings.equipment[0].display_name = "재적용 대상"
    store.save(settings)
    history_count = len(store.history())
    published = []
    monkeypatch.setattr(main_module, "equipment_store", store)
    monkeypatch.setattr(
        main_module.ros_bridge,
        "publish_thermal_equipment_config",
        lambda document: published.append(document)
        or {"state": "syncing", "equipment": []},
    )

    response = client.post("/api/v1/settings/equipment/apply")

    assert response.status_code == 200
    assert response.json()["runtime"]["state"] == "syncing"
    assert published[-1]["equipment"][0]["display_name"] == "재적용 대상"
    assert len(store.history()) == history_count


def test_equipment_baseline_reset_reports_ros_result(monkeypatch):
    monkeypatch.setattr(
        main_module.ros_bridge,
        "reset_thermal_baseline_collection",
        lambda: {"accepted": True, "message": "reset"},
    )

    response = client.post("/api/v1/settings/equipment/baseline/reset")

    assert response.status_code == 200
    assert response.json() == {"accepted": True, "message": "reset"}


def test_route_rejects_unknown_equipment_id(monkeypatch, tmp_path):
    monkeypatch.setattr(
        main_module,
        "equipment_store",
        ThermalEquipmentSettingsStore(tmp_path / "equipment.json"),
    )
    route = {
        "name": "설비 연결 검증",
        "waypoints": [
            {
                "id": "wp-1",
                "name": "검사 지점",
                "equipment_id": "missing-equipment",
                "dwell_seconds": 2,
                "x": 0,
                "y": 0,
            }
        ],
    }

    response = client.post("/api/v1/navigation/route/recommend", json=route)

    assert response.status_code == 422
    assert "존재하지 않습니다" in response.json()["detail"]

