from types import SimpleNamespace

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


def _create_saved_session(manager):
    session = manager._world_catalog.begin_session("facility_map", "toolbox")
    session["map_path"].write_text(
        "image: map.pgm\nresolution: 0.05\n",
        encoding="utf-8",
    )
    (session["directory"] / "map.pgm").write_bytes(b"P5\n1 1\n255\n\xff")
    manager._world_catalog.update_session(
        session["id"],
        "facility_map",
        status="saved",
    )
    assert manager.select_map("facility_map", session["id"])["accepted"]
    return session


def test_rgbd_mapping_requires_an_activated_saved_session(monkeypatch, tmp_path):
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    manager = SystemModeManager()
    monkeypatch.setattr(manager, "_detect_external_mode", lambda: None)

    result = manager.switch_mode("rgbd_mapping")

    assert result["accepted"] is False
    assert "2D 지도" in result["message"]


def test_rgbd_mapping_reuses_saved_session_and_dedicated_launch(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    manager = SystemModeManager()
    monkeypatch.setattr(manager, "_detect_external_mode", lambda: None)
    monkeypatch.setattr(manager, "_ensure_simulation", lambda: True)
    session = _create_saved_session(manager)

    class FakeProcess:
        pid = 456

        @staticmethod
        def poll():
            return None

    class NoopThread:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            pass

    launched = {}
    monkeypatch.setattr(
        manager._process_controller,
        "start_logged",
        lambda command, _log_path: launched.setdefault("command", command)
        and FakeProcess(),
    )
    monkeypatch.setattr("app.mode_manager.threading.Thread", NoopThread)

    result = manager.switch_mode("rgbd_mapping")
    sessions = manager._world_catalog.sessions("facility_map")

    assert result["accepted"] is True
    assert result["rgbd_session_id"] == session["id"]
    assert len(sessions) == 1
    assert sessions[0]["rgbd_status"] == "collecting"
    assert launched["command"][:4] == [
        "ros2",
        "launch",
        "hazard_guard_simulation",
        "rgbd_mapping.launch.py",
    ]
    assert f"map:={session['map_path']}" in launched["command"]
    assert any(
        item.startswith("rtabmap_database_path:=")
        for item in launched["command"]
    )


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
    assert any(argument.startswith("initial_pose_x:=") for argument in patrol)
    assert all(";" not in argument for argument in mapping + patrol)


def test_hybrid_mapping_launch_enables_rtabmap_with_session_database(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    manager = SystemModeManager()
    manager._mapping_profile = "toolbox_rtabmap"
    manager._rtabmap_database_path = tmp_path / "runtime" / "maps" / "session" / "rtabmap.db"

    command = manager._launch_arguments("mapping")

    assert "enable_rtabmap:=true" in command
    assert f"rtabmap_database_path:={manager._rtabmap_database_path}" in command
    assert all(";" not in argument for argument in command)


def test_saved_rtabmap_database_is_exported_to_stable_ply(monkeypatch, tmp_path):
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    manager = SystemModeManager()
    session = manager._world_catalog.begin_session("facility_map", "toolbox_rtabmap")
    session["rtabmap_database_path"].write_bytes(b"database")

    def fake_run(command, **_kwargs):
        output_dir = command[command.index("--output_dir") + 1]
        expected = session["directory"] / "cloud-export_cloud.ply"
        assert str(expected.parent) == output_dir
        expected.write_bytes(b"ply\n")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(manager._process_controller, "run", fake_run)

    result = manager.export_map_cloud("facility_map", session["id"])

    assert result["accepted"] is True
    assert result["path"].name == "cloud.ply"
    assert result["path"].read_bytes() == b"ply\n"


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
    assert "use_thermal_pipeline:=true" in command
    assert any(argument.startswith("world:=") for argument in command)
    assert "world_name:=facility_map" in command
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


def test_physical_mapping_profiles_use_hardware_launch_without_gazebo(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_DEPLOYMENT_TARGET", "physical")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    manager = SystemModeManager()
    manager._rtabmap_database_path = tmp_path / "runtime" / "maps" / "rtabmap.db"

    manager._mapping_profile = "toolbox"
    toolbox = manager._launch_arguments("mapping")
    manager._mapping_profile = "toolbox_rtabmap"
    hybrid = manager._launch_arguments("mapping")

    assert toolbox[:4] == [
        "ros2",
        "launch",
        "hazard_guard_simulation",
        "physical_mapping.launch.py",
    ]
    assert "enable_rtabmap:=false" in toolbox
    assert "enable_rtabmap:=true" in hybrid
    assert f"database_path:={manager._rtabmap_database_path}" in hybrid
    assert all("world:=" not in argument for argument in toolbox + hybrid)


def test_physical_patrol_passes_selected_map_to_hardware_launch(
    monkeypatch,
    tmp_path,
):
    map_path = tmp_path / "runtime" / "maps" / "facility.yaml"
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_DEPLOYMENT_TARGET", "physical")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("HAZARD_GUARD_MAP_PATH", str(map_path))
    manager = SystemModeManager()
    manager.set_localization_pose({"x": 1.25, "y": -0.4, "yaw": 0.75})

    command = manager._launch_arguments("patrol")

    assert command[:4] == [
        "ros2",
        "launch",
        "hazard_guard_simulation",
        "physical_patrol.launch.py",
    ]
    assert f"map:={map_path}" in command
    assert "enable_thermal_pipeline:=true" in command
    assert "initial_pose_x:=1.25" in command
    assert "initial_pose_y:=-0.4" in command
    assert "initial_pose_yaw:=0.75" in command
    assert "use_person_safety:=true" in command
    assert "person_device:=0" in command
    assert "enable_thermal_pipeline:=false" in command
    assert all("start_simulation" not in argument for argument in command)


def test_physical_patrol_passes_opt_in_perception_settings(
    monkeypatch,
    tmp_path,
):
    map_path = tmp_path / "runtime" / "maps" / "facility.yaml"
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_DEPLOYMENT_TARGET", "physical")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("HAZARD_GUARD_MAP_PATH", str(map_path))
    monkeypatch.setenv("HAZARD_GUARD_PERSON_SAFETY_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_PERSON_MODEL_PATH", "/models/yolo11n.pt")
    monkeypatch.setenv("HAZARD_GUARD_PERSON_DEVICE", "0")
    monkeypatch.setenv("HAZARD_GUARD_PERSON_DEPTH_REGISTERED", "true")
    monkeypatch.setenv("HAZARD_GUARD_THERMAL_PIPELINE_ENABLED", "yes")
    monkeypatch.setenv(
        "HAZARD_GUARD_THERMAL_BASELINE_PATH", "/data/motor-baseline.json"
    )
    monkeypatch.setenv("HAZARD_GUARD_THERMAL_AIR_TOPIC", "/sensors/air")
    monkeypatch.setenv("HAZARD_GUARD_THERMAL_OIL_TOPIC", "/sensors/oil")
    monkeypatch.setenv("HAZARD_GUARD_THERMAL_SENSOR_TIMEOUT_SEC", "8.0")
    monkeypatch.setenv("HAZARD_GUARD_THERMAL_SCALE", "0.01")
    monkeypatch.setenv("HAZARD_GUARD_THERMAL_OFFSET_C", "-273.15")
    manager = SystemModeManager()

    command = manager._launch_arguments("patrol")

    assert "use_person_safety:=true" in command
    assert "person_model_path:=/models/yolo11n.pt" in command
    assert "person_device:=0" in command
    assert "person_inference_rate_hz:=6.0" in command
    assert "person_depth_registration_verified:=true" in command
    assert "enable_thermal_pipeline:=true" in command
    assert "thermal_baseline_path:=/data/motor-baseline.json" in command
    assert "thermal_air_temperature_topic:=/sensors/air" in command
    assert "thermal_oil_temperature_topic:=/sensors/oil" in command
    assert "thermal_sensor_timeout_sec:=8.0" in command
    assert "thermal_scale:=0.01" in command
    assert "thermal_offset_c:=-273.15" in command


def test_physical_rgbd_mapping_disables_yolo_but_keeps_camera(
    monkeypatch,
    tmp_path,
):
    map_path = tmp_path / "runtime" / "maps" / "facility" / "map.yaml"
    map_path.parent.mkdir(parents=True)
    map_path.write_text("image: map.pgm\nresolution: 0.05\n", encoding="utf-8")
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_DEPLOYMENT_TARGET", "physical")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("HAZARD_GUARD_MAP_PATH", str(map_path))
    monkeypatch.setenv("HAZARD_GUARD_PERSON_SAFETY_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_PERSON_CAMERA_START", "1")
    manager = SystemModeManager()

    command = manager._launch_arguments("rgbd_mapping")

    assert command[:4] == [
        "ros2",
        "launch",
        "hazard_guard_simulation",
        "physical_rgbd_mapping.launch.py",
    ]
    assert command.count("use_person_safety:=false") == 1
    assert "use_person_safety:=true" not in command
    assert "start_person_camera:=true" in command


def test_physical_patrol_cannot_disable_person_safety(monkeypatch, tmp_path):
    map_path = tmp_path / "runtime" / "maps" / "facility.yaml"
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_DEPLOYMENT_TARGET", "physical")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("HAZARD_GUARD_MAP_PATH", str(map_path))
    monkeypatch.setenv("HAZARD_GUARD_PERSON_SAFETY_ENABLED", "0")
    manager = SystemModeManager()

    command = manager._launch_arguments("patrol")

    assert "use_person_safety:=true" in command


def test_physical_runtime_never_starts_gazebo(monkeypatch, tmp_path):
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_DEPLOYMENT_TARGET", "physical")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    manager = SystemModeManager()
    monkeypatch.setattr(
        manager,
        "_ensure_simulation",
        lambda: (_ for _ in ()).throw(AssertionError("must not start Gazebo")),
    )

    assert manager._ensure_runtime_environment() is True
    snapshot = manager.snapshot(detect_external=False)
    assert snapshot["deployment_target"] == "physical"
    assert snapshot["simulation_state"] == "not_applicable"


def test_physical_target_rejects_simulation_world_switch(monkeypatch, tmp_path):
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_DEPLOYMENT_TARGET", "physical")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    manager = SystemModeManager()

    result = manager.select_world("facility_map")

    assert result["accepted"] is False
    assert "simulation" in result["message"]


def test_mapping_does_not_create_session_when_simulator_is_unavailable(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    manager = SystemModeManager()
    original_map_path = manager._map_path
    monkeypatch.setattr(manager, "_detect_external_mode", lambda: None)
    monkeypatch.setattr(manager, "_ensure_simulation", lambda: False)

    result = manager.switch_mode("mapping", "toolbox_rtabmap")

    assert result["accepted"] is False
    assert manager._world_catalog.sessions("facility_map") == []
    assert manager._map_path == original_map_path
    assert manager._current_session_id is None


def test_mapping_discards_pending_session_when_ros_launch_fails(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    manager = SystemModeManager()
    original_map_path = manager._map_path
    monkeypatch.setattr(manager, "_detect_external_mode", lambda: None)
    monkeypatch.setattr(manager, "_ensure_simulation", lambda: True)

    def fail_launch(*_args, **_kwargs):
        raise OSError("ros2 not found")

    monkeypatch.setattr(manager._process_controller, "start_logged", fail_launch)

    result = manager.switch_mode("mapping", "toolbox_rtabmap")

    assert result["accepted"] is False
    assert manager._world_catalog.sessions("facility_map") == []
    assert manager._map_path == original_map_path
    assert manager._current_session_id is None
    assert manager._mapping_profile == "toolbox"


def test_mapping_commits_session_after_ros_launch_starts(monkeypatch, tmp_path):
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    manager = SystemModeManager()
    monkeypatch.setattr(manager, "_detect_external_mode", lambda: None)
    monkeypatch.setattr(manager, "_ensure_simulation", lambda: True)

    class FakeProcess:
        pid = 123

        @staticmethod
        def poll():
            return None

    class NoopThread:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            pass

    launched = {}

    def start_launch(command, _log_path):
        launched["command"] = command
        return FakeProcess()

    monkeypatch.setattr(manager._process_controller, "start_logged", start_launch)
    monkeypatch.setattr("app.mode_manager.threading.Thread", NoopThread)

    result = manager.switch_mode("mapping", "toolbox_rtabmap")
    sessions = manager._world_catalog.sessions("facility_map")

    assert result["accepted"] is True
    assert len(sessions) == 1
    assert result["mapping_session_id"] == sessions[0]["id"]
    assert f"rtabmap_database_path:={manager._rtabmap_database_path}" in launched[
        "command"
    ]


def test_patrol_with_slam_maps_without_a_saved_map(monkeypatch, tmp_path):
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    manager = SystemModeManager()
    monkeypatch.setattr(manager, "_detect_external_mode", lambda: None)
    monkeypatch.setattr(manager, "_ensure_simulation", lambda: True)

    class FakeProcess:
        pid = 321

        @staticmethod
        def poll():
            return None

    class NoopThread:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            pass

    launched = {}

    def start_launch(command, _log_path):
        launched["command"] = command
        return FakeProcess()

    monkeypatch.setattr(manager._process_controller, "start_logged", start_launch)
    monkeypatch.setattr("app.mode_manager.threading.Thread", NoopThread)

    # Without a saved map this request is refused; the SLAM variant builds its own.
    assert manager.switch_mode("patrol")["accepted"] is False

    result = manager.switch_mode("patrol", patrol_slam=True)
    sessions = manager._world_catalog.sessions("facility_map")

    assert result["accepted"] is True
    assert result["patrol_slam"] is True
    assert "slam:=true" in launched["command"]
    assert "auto_initial_pose:=false" in launched["command"]
    assert "localization.launch.py" in launched["command"]
    # Saving must land in a session of its own, not over the map it started from.
    assert len(sessions) == 1
    assert result["mapping_session_id"] == sessions[0]["id"]


def test_patrol_without_slam_keeps_amcl_launch_arguments(monkeypatch, tmp_path):
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    manager = SystemModeManager()

    patrol = manager._launch_arguments("patrol")

    assert "slam:=false" in patrol
    assert "auto_initial_pose:=true" in patrol
