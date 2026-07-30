from app.mode_manager import SystemModeManager


def test_patrol_mode_requires_saved_map(monkeypatch, tmp_path):
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    monkeypatch.setenv(
        "HAZARD_GUARD_MAP_PATH",
        str(tmp_path / "runtime" / "maps" / "facility.yaml"),
    )
    manager = SystemModeManager()
    monkeypatch.setattr(manager, "_detect_external_mode", lambda: None)

    result = manager.switch_mode("patrol")

    assert result["accepted"] is False
    assert result["state"] == "failed"
    assert "저장 지도" in result["message"]


def test_saved_map_requires_yaml_and_referenced_image(monkeypatch, tmp_path):
    map_dir = tmp_path / "runtime" / "maps"
    map_dir.mkdir(parents=True)
    map_yaml = map_dir / "facility.yaml"
    map_yaml.write_text("image: facility.pgm\nresolution: 0.05\n", encoding="utf-8")
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("HAZARD_GUARD_MAP_PATH", str(map_yaml))
    manager = SystemModeManager()

    assert manager.snapshot(detect_external=False)["map_available"] is False

    (map_dir / "facility.pgm").write_bytes(b"P5\n1 1\n255\n\xff")

    assert manager.snapshot(detect_external=False)["map_available"] is True


def test_mode_launch_arguments_are_shell_free_and_mode_specific(monkeypatch, tmp_path):
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("HAZARD_GUARD_MAP_PATH", "runtime/maps/facility.yaml")
    manager = SystemModeManager()

    mapping = manager._launch_arguments("mapping")
    patrol = manager._launch_arguments("patrol")

    assert mapping[:4] == [
        "ros2",
        "launch",
        "hazard_guard_simulation",
        "slam.launch.py",
    ]
    assert patrol[:4] == [
        "ros2",
        "launch",
        "hazard_guard_simulation",
        "localization.launch.py",
    ]
    assert "start_simulation:=false" in mapping
    assert "start_simulation:=false" in patrol
    assert any(argument.startswith("map:=") for argument in patrol)
    assert all(";" not in argument for argument in mapping + patrol)


def test_simulation_launch_arguments_are_separate_from_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    manager = SystemModeManager()

    command = manager._simulation_launch_arguments()

    assert command[:4] == [
        "ros2",
        "launch",
        "hazard_guard_simulation",
        "simulation.launch.py",
    ]
    assert "simulation_mode:=kinematic" in command
    assert all(";" not in argument for argument in command)


def test_existing_simulator_is_reused_without_starting_duplicate(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    manager = SystemModeManager()
    monkeypatch.setattr(manager, "_detect_external_simulation", lambda: True)
    monkeypatch.setattr(
        manager,
        "_cleanup_orphaned_simulators",
        lambda: (_ for _ in ()).throw(AssertionError("must not clean")),
    )

    assert manager._ensure_simulation() is True
    snapshot = manager.snapshot(detect_external=False)
    assert snapshot["simulation_state"] == "external"
    assert snapshot["simulation_managed"] is False
