import json

import pytest
from pydantic import ValidationError

from app.models import NavigationRoute, ThermalEquipmentSettingsDocument
from app.spatial_config import MapSpatialConfigStore


def context(world="facility", session="session-a", *, ready=True):
    return {
        "world_id": world,
        "map_session_id": session,
        "frame_id": "map",
        "registration_ready": ready,
        "geometry_fingerprint": "a" * 64,
    }


def prepare_session(root, world="facility", session="session-a"):
    directory = root / world / session
    directory.mkdir(parents=True)
    (directory / "metadata.json").write_text(
        json.dumps({"id": session, "world_id": world}), encoding="utf-8"
    )


def equipment_document(world="facility", session="session-a"):
    return ThermalEquipmentSettingsDocument.model_validate(
        {
            "schema_version": 2,
            "world_id": world,
            "map_session_id": session,
            "frame_id": "map",
            "equipment": [
                {
                    "id": "motor",
                    "display_name": "Motor",
                    "critical_temperature_c": 80,
                    "adaptive_delta_c": 10,
                    "roi": {"min": [0, 0, 0], "max": [0.4, 0.4, 0.5]},
                }
            ],
        }
    )


def test_map_spatial_config_is_isolated_per_map_session(tmp_path):
    current = context()
    prepare_session(tmp_path, session="session-a")
    prepare_session(tmp_path, session="session-b")
    store = MapSpatialConfigStore(lambda: current, tmp_path)

    store.save(equipment_document())
    route = NavigationRoute.model_validate(
        {
            "name": "Route A",
            "world_id": "facility",
            "map_session_id": "session-a",
            "waypoints": [{"id": "wp-1", "name": "WP-1", "x": 1, "y": 2}],
        }
    )
    store.save_route(route)

    current = context(session="session-b")
    assert store.get().equipment == []
    assert store.get_route() is None

    current = context(session="session-a")
    assert store.get().equipment[0].id == "motor"
    assert store.get_route().route.waypoints[0].id == "wp-1"


def test_route_storage_requires_explicit_current_map_binding(tmp_path):
    prepare_session(tmp_path)
    store = MapSpatialConfigStore(lambda: context(), tmp_path)
    unbound = NavigationRoute.model_validate(
        {
            "name": "Unbound route",
            "waypoints": [{"id": "wp-1", "name": "WP-1", "x": 1, "y": 2}],
        }
    )

    with pytest.raises(RuntimeError, match="현재 선택된 지도 세션"):
        store.save_route(unbound)


def test_equipment_document_rejects_overlapping_rois():
    payload = equipment_document().model_dump(by_alias=True)
    payload["equipment"].append(
        {
            "id": "pump",
            "display_name": "Pump",
            "critical_temperature_c": 80,
            "adaptive_delta_c": 10,
            "roi": {"min": [0.39, 0, 0], "max": [0.8, 0.4, 0.5]},
        }
    )
    with pytest.raises(ValidationError, match="overlap"):
        ThermalEquipmentSettingsDocument.model_validate(payload)
