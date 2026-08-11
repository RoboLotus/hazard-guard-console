import json

import pytest

from app.world_catalog import WorldCatalog


def write_world(path, world_name):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'<sdf version="1.8"><world name="{world_name}" /></sdf>',
        encoding="utf-8",
    )


def test_catalog_discovers_every_repository_sdf_without_a_fixed_ui_list(tmp_path):
    worlds = tmp_path / "src" / "hazard_guard_simulation" / "worlds"
    write_world(worlds / "easy_room.sdf", "easy_room_world")
    write_world(worlds / "future_difficult_room.sdf", "future_world")
    (worlds / "world_catalog.json").write_text(
        json.dumps(
            {
                "worlds": {
                    "easy_room": {
                        "label": "쉬운 방",
                        "difficulty": "easy",
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    catalog = WorldCatalog(tmp_path)
    discovered = {world["id"]: world for world in catalog.worlds()}

    assert set(discovered) == {"easy_room", "future_difficult_room"}
    assert discovered["easy_room"]["label"] == "쉬운 방"
    assert discovered["future_difficult_room"]["difficulty"] == "unrated"
    assert discovered["future_difficult_room"]["world_name"] == "future_world"


def test_map_sessions_are_scoped_to_world_and_require_complete_map_files(tmp_path):
    worlds = tmp_path / "src" / "hazard_guard_simulation" / "worlds"
    write_world(worlds / "facility_map.sdf", "facility_map")
    write_world(worlds / "hard_map.sdf", "hard_map")
    catalog = WorldCatalog(tmp_path)
    session = catalog.begin_session("hard_map")

    assert catalog.sessions("facility_map") == []
    assert catalog.sessions("hard_map")[0]["available"] is False

    session["map_path"].write_text("image: map.pgm\nresolution: 0.05\n", encoding="utf-8")
    (session["directory"] / "map.pgm").write_bytes(b"P5\n1 1\n255\n\xff")
    catalog.update_session(session["id"], "hard_map", status="saved")
    active_path = catalog.activate_session("hard_map", session["id"])

    assert active_path == session["map_path"]
    assert catalog.sessions("hard_map")[0]["active"] is True
    assert catalog.active_map_path("hard_map") == session["map_path"]
    saved = catalog.sessions("hard_map")[0]
    assert saved["storage_directory"] == str(session["directory"])
    assert saved["map_yaml_path"] == str(session["map_path"])
    assert saved["map_image_path"] == str(session["directory"] / "map.pgm")


def test_hybrid_session_reports_persistent_rtabmap_database(tmp_path):
    worlds = tmp_path / "src" / "hazard_guard_simulation" / "worlds"
    write_world(worlds / "facility_map.sdf", "facility_map")
    catalog = WorldCatalog(tmp_path)
    session = catalog.begin_session("facility_map", "toolbox_rtabmap")
    session["map_path"].write_text(
        "image: map.pgm\nresolution: 0.05\n",
        encoding="utf-8",
    )
    (session["directory"] / "map.pgm").write_bytes(b"P5\n1 1\n255\n\xff")
    session["rtabmap_database_path"].write_bytes(b"rtabmap-database")

    result = catalog.sessions("facility_map")[0]

    assert result["mapping_profile"] == "toolbox_rtabmap"
    assert result["rtabmap_available"] is True
    assert result["rtabmap_database_bytes"] == len(b"rtabmap-database")


def test_session_can_be_named_archived_and_record_a_cloud_export(tmp_path):
    worlds = tmp_path / "src" / "hazard_guard_simulation" / "worlds"
    write_world(worlds / "facility_map.sdf", "facility_map")
    catalog = WorldCatalog(tmp_path)
    session = catalog.begin_session("facility_map", "toolbox_rtabmap")
    cloud_path = session["directory"] / "cloud.ply"
    cloud_path.write_bytes(b"ply\n")

    edited = catalog.edit_session(
        "facility_map",
        session["id"],
        name="열원 구역 1차",
        archived=True,
    )
    exported = catalog.record_cloud_export(
        "facility_map",
        session["id"],
        cloud_path,
    )

    assert edited["name"] == "열원 구역 1차"
    assert edited["archived"] is True
    assert exported["cloud_available"] is True
    assert exported["cloud_bytes"] == len(b"ply\n")


def test_catalog_rejects_unknown_or_path_like_world_ids(tmp_path):
    catalog = WorldCatalog(tmp_path)

    with pytest.raises(KeyError):
        catalog.get("../outside")


def test_empty_launch_session_can_be_discarded_without_deleting_map_data(tmp_path):
    worlds = tmp_path / "src" / "hazard_guard_simulation" / "worlds"
    write_world(worlds / "facility_map.sdf", "facility_map")
    catalog = WorldCatalog(tmp_path)
    empty = catalog.begin_session("facility_map")
    populated = catalog.begin_session("facility_map")
    populated["map_path"].write_text("map data", encoding="utf-8")

    assert catalog.discard_empty_session("facility_map", empty["id"]) is True
    assert not empty["directory"].exists()
    assert catalog.discard_empty_session("facility_map", populated["id"]) is False
    assert populated["map_path"].is_file()
