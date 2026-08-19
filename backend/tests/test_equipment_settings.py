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

    settings.equipment[0].display_name = "1번 적치 구역"
    store.save(settings)

    reloaded = ThermalEquipmentSettingsStore(path).get()
    assert reloaded.equipment[0].display_name == "1번 적치 구역"
    assert reloaded.equipment[0].roi.minimum == [-1.95, -0.95, 0.02]


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

