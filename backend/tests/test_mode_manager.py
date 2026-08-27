import threading
from types import SimpleNamespace

import numpy as np

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
    first_pass_database = session["directory"] / "rtabmap.db"
    dedicated_database = session["directory"] / "rgbd-map.db"
    first_pass_database.write_bytes(b"first-pass")
    dedicated_database.write_bytes(b"previous-second-pass")
    (session["directory"] / "cloud.ply").write_bytes(b"previous-cloud")
    (session["directory"] / "thermal_layer.npz").write_bytes(
        b"previous-thermal"
    )
    manager._world_catalog.update_session(
        session["id"],
        "facility_map",
        mapping_profile="toolbox_rtabmap",
        rtabmap_database_file="rtabmap.db",
        mapping_rtabmap_database_file="rtabmap.db",
    )

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
    assert f"rtabmap_database_path:={dedicated_database}" in launched["command"]
    assert "rtabmap_reset_database:=true" in launched["command"]
    assert first_pass_database.read_bytes() == b"first-pass"
    assert not dedicated_database.exists()
    assert len(list(session["directory"].glob("rgbd-map.stale-*.db"))) == 1
    assert len(list(session["directory"].glob("cloud.stale-*.ply"))) == 1
    assert len(
        list(session["directory"].glob("thermal_layer.stale-*.npz"))
    ) == 1
    assert sessions[0]["rtabmap_database_path"] == str(dedicated_database)
    assert sessions[0]["mapping_rtabmap_database_path"] == str(
        first_pass_database
    )


def test_second_pass_cloud_export_never_reads_first_pass_database(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    manager = SystemModeManager()
    session = manager._world_catalog.begin_session(
        "facility_map", "toolbox_rtabmap"
    )
    first_pass_database = session["directory"] / "rtabmap.db"
    first_pass_database.write_bytes(b"first-pass")
    dedicated_database = manager._prepare_rgbd_collection(session)
    dedicated_database.write_bytes(b"second-pass-map-frame")

    def fake_export(command, **_kwargs):
        assert command[-1] == str(dedicated_database)
        (session["directory"] / "cloud-export_cloud.ply").write_bytes(b"ply\n")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(manager._process_controller, "run", fake_export)

    result = manager.export_map_cloud("facility_map", session["id"])

    assert result["accepted"] is True
    assert result["geometry_refreshed"] is True
    assert first_pass_database.read_bytes() == b"first-pass"


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
    assert "enable_hazard_approval:=false" in patrol
    assert any(argument.startswith("map:=") for argument in patrol)
    assert any(argument.startswith("initial_pose_x:=") for argument in patrol)
    assert all(";" not in argument for argument in mapping + patrol)


def test_simulation_patrol_can_enable_hazard_approval(monkeypatch, tmp_path):
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("HAZARD_GUARD_MAP_PATH", "runtime/maps/facility.yaml")
    monkeypatch.setenv("HAZARD_GUARD_HAZARD_APPROVAL_ENABLED", "1")
    manager = SystemModeManager()

    patrol = manager._launch_arguments("patrol")

    assert "enable_hazard_approval:=true" in patrol


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
    saved = manager._world_catalog.sessions("facility_map")[0]
    assert saved["thermal_map_status"] == "incompatible"
    assert "provenance" in saved["thermal_map_error"]


def test_fresh_cloud_export_quarantines_previous_thermal_layer(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    manager = SystemModeManager()
    session = manager._world_catalog.begin_session("facility_map", "toolbox")
    session["rtabmap_database_path"].write_bytes(b"database")
    state_path = session["directory"] / "thermal_layer.npz"
    state_path.write_bytes(b"previous-layer")
    manager._world_catalog.update_session(
        session["id"],
        "facility_map",
        cloud_export_status="stale",
    )

    def fake_run(_command, **_kwargs):
        (session["directory"] / "cloud-export_cloud.ply").write_bytes(b"ply\n")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(manager._process_controller, "run", fake_run)

    result = manager.export_map_cloud("facility_map", session["id"])

    assert result["accepted"] is True
    assert not state_path.exists()
    quarantined = list(session["directory"].glob("thermal_layer.stale-*.npz"))
    assert len(quarantined) == 1
    assert quarantined[0].read_bytes() == b"previous-layer"
    saved = manager._world_catalog.sessions("facility_map")[0]
    assert saved["thermal_layer_status"] == "quarantined"
    assert saved["thermal_layer_quarantine_file"] == quarantined[0].name


def test_rgbd_finalize_marks_cloud_export_pending_without_blocking_shutdown(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    manager = SystemModeManager()
    session = manager._world_catalog.begin_session("facility_map", "toolbox")
    database_path = session["directory"] / "rgbd-map.db"
    database_path.write_bytes(b"database")
    (session["directory"] / "cloud.ply").write_bytes(b"old-cloud")
    manager._world_catalog.update_session(
        session["id"],
        "facility_map",
        rtabmap_database_file="rgbd-map.db",
        rgbd_database_file="rgbd-map.db",
        rgbd_status="collecting",
        rgbd_workflow=manager.RGBD_WORKFLOW,
        cloud_frame_id="map",
        cloud_export_status="stale",
    )
    manager._rgbd_session_id = session["id"]
    manager._rtabmap_database_path = database_path

    monkeypatch.setattr(
        manager._process_controller,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("shutdown must defer rtabmap-export")
        ),
    )

    manager._finalize_rgbd_session()

    saved = manager._world_catalog.sessions("facility_map")[0]
    assert saved["rgbd_status"] == "saved"
    assert saved["rgbd_workflow"] == manager.RGBD_WORKFLOW
    assert saved["cloud_frame_id"] == "map"
    assert saved["cloud_export_status"] == "stale"
    assert saved["cloud_ready"] is False
    assert saved["thermal_map_status"] == "waiting_for_cloud"
    assert (session["directory"] / "cloud.ply").read_bytes() == b"old-cloud"
    assert manager._rgbd_session_id is None


def test_rgbd_finalize_records_missing_database_without_running_export(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    manager = SystemModeManager()
    session = manager._world_catalog.begin_session("facility_map", "toolbox")
    database_path = session["directory"] / "rgbd-map.db"
    manager._world_catalog.update_session(
        session["id"],
        "facility_map",
        rtabmap_database_file="rgbd-map.db",
        rgbd_database_file="rgbd-map.db",
        cloud_export_status="stale",
    )
    manager._rgbd_session_id = session["id"]
    manager._rtabmap_database_path = database_path
    monkeypatch.setattr(
        manager._process_controller,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("missing DB must not invoke exporter")
        ),
    )

    manager._finalize_rgbd_session()

    saved = manager._world_catalog.sessions("facility_map")[0]
    assert saved["rgbd_status"] == "empty"
    assert saved["rtabmap_available"] is False
    assert saved["cloud_export_status"] == "failed"
    assert saved["cloud_ready"] is False
    assert saved["thermal_map_status"] == "failed"
    assert "RTAB-Map DB" in saved["cloud_export_error"]


def test_manual_cloud_export_waits_for_managed_rgbd_group_finalization(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    manager = SystemModeManager()
    session = manager._world_catalog.begin_session("facility_map", "toolbox")
    session["rtabmap_database_path"].write_bytes(b"database")

    class ExitedLaunchProcess:
        pid = 991

        @staticmethod
        def poll():
            return 0

    manager._process = ExitedLaunchProcess()
    manager._rgbd_session_id = session["id"]
    manager._data.update(
        mode="rgbd_mapping",
        state="running",
        rgbd_session_id=session["id"],
    )
    monkeypatch.setattr(
        manager._process_controller,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("must wait for ROS process-group cleanup")
        ),
    )

    result = manager.export_map_cloud("facility_map", session["id"])

    assert result["accepted"] is False
    assert "종료" in result["message"]

    # Explicit stop clears the process reference before metadata finalization;
    # the pending-session guard must still keep the DB closed to exporters.
    manager._process = None
    manager._rgbd_finalize_pending_id = session["id"]
    pending = manager.export_map_cloud("facility_map", session["id"])
    assert pending["accepted"] is False


def test_manual_cloud_export_rejects_external_mapping_or_patrol_stack(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    manager = SystemModeManager()
    session = manager._world_catalog.begin_session("facility_map", "toolbox")
    session["rtabmap_database_path"].write_bytes(b"database")
    monkeypatch.setattr(
        manager._process_controller,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("external stack DB must not be exported")
        ),
    )

    for mode in ("mapping", "rgbd_mapping", "patrol"):
        manager._data.update(mode=mode, state="external")
        result = manager.export_map_cloud("facility_map", session["id"])

        assert result["accepted"] is False
        assert "터미널" in result["message"]


def test_active_thermal_patrol_can_read_immutable_reference_cloud(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    manager = SystemModeManager()
    session = manager._world_catalog.begin_session("facility_map", "toolbox")
    cloud_path = manager._world_catalog.session_paths(
        "facility_map", session["id"]
    )["cloud"]
    cloud_path.write_bytes(b"ply-reference")

    class RunningProcess:
        pid = 31337

        @staticmethod
        def poll():
            return None

    manager._process = RunningProcess()
    manager._thermal_map_session_id = session["id"]
    manager._data.update(mode="patrol", state="running")
    monkeypatch.setattr(
        manager._process_controller,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("active patrol must not re-export RTAB-Map")
        ),
    )

    result = manager.export_map_cloud("facility_map", session["id"])

    assert result["accepted"] is True
    assert result["path"] == cloud_path
    assert result["geometry_refreshed"] is False


def test_status_poll_does_not_bypass_process_group_finalization(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    manager = SystemModeManager()

    class ExitedLaunchProcess:
        pid = 1991

        @staticmethod
        def poll():
            return 0

    process = ExitedLaunchProcess()
    manager._process = process
    manager._data.update(
        mode="rgbd_mapping",
        state="running",
        managed=True,
        pid=process.pid,
    )

    snapshot = manager.snapshot(detect_external=False)

    assert manager._process is process
    assert snapshot["state"] == "stopping"
    assert snapshot["managed"] is True
    assert snapshot["pid"] is not None


def test_mode_launch_waits_for_in_progress_cloud_export_transition(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    manager = SystemModeManager()
    monkeypatch.setattr(manager, "_detect_external_mode", lambda: None)
    monkeypatch.setattr(manager, "_ensure_simulation", lambda: True)
    launched = threading.Event()
    real_thread = threading.Thread

    class FakeProcess:
        pid = 419

        @staticmethod
        def poll():
            return None

    class NoopThread:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            pass

    def start_logged(_command, _log_path):
        launched.set()
        return FakeProcess()

    monkeypatch.setattr(manager._process_controller, "start_logged", start_logged)
    monkeypatch.setattr("app.mode_manager.threading.Thread", NoopThread)

    with manager._cloud_export_lock:
        worker = real_thread(target=lambda: manager.switch_mode("mapping"))
        worker.start()
        assert launched.wait(timeout=0.05) is False

    assert launched.wait(timeout=1.0) is True
    worker.join(timeout=1.0)
    assert worker.is_alive() is False


def test_stop_waits_for_in_progress_mode_transition(monkeypatch, tmp_path):
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    manager = SystemModeManager()
    stopped = threading.Event()
    real_thread = threading.Thread

    with manager._cloud_export_lock:
        worker = real_thread(
            target=lambda: (manager.stop(), stopped.set()),
        )
        worker.start()
        assert stopped.wait(timeout=0.05) is False

    assert stopped.wait(timeout=1.0) is True
    worker.join(timeout=1.0)
    assert worker.is_alive() is False
    assert manager.snapshot(detect_external=False)["mode"] == "idle"


def test_map_and_world_selection_are_rejected_during_cloud_preparation(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    manager = SystemModeManager()
    session = _create_saved_session(manager)
    manager._data.update(mode="patrol", state="preparing")

    selected_map = manager.select_map("facility_map", session["id"])
    selected_world = manager.select_world("facility_map")

    assert selected_map["accepted"] is False
    assert selected_world["accepted"] is False
    assert "종료" in selected_map["message"]
    assert "종료" in selected_world["message"]


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
    assert "initial_pose_x:=1.25" in command
    assert "initial_pose_y:=-0.4" in command
    assert "initial_pose_yaw:=0.75" in command
    assert "use_person_safety:=false" in command
    assert "use_dispenser:=false" in command
    assert "enable_physical_drop:=false" in command
    assert "person_device:=0" in command
    assert "enable_thermal_pipeline:=false" in command
    assert command.count("enable_thermal_pipeline:=false") == 1
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
    monkeypatch.setenv("HAZARD_GUARD_HAZARD_APPROVAL_ENABLED", "yes")
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
    assert "enable_hazard_approval:=true" in command
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
    assert not any(
        argument.startswith("enable_frozen_thermal_map:=true")
        for argument in command
    )


def test_physical_launch_omits_empty_optional_arguments(monkeypatch, tmp_path):
    map_path = tmp_path / "runtime" / "maps" / "facility" / "map.yaml"
    map_path.parent.mkdir(parents=True)
    map_path.write_text("image: map.pgm\nresolution: 0.05\n", encoding="utf-8")
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_DEPLOYMENT_TARGET", "physical")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("HAZARD_GUARD_MAP_PATH", str(map_path))
    for name in (
        "HAZARD_GUARD_THERMAL_ROI_CONFIG",
        "HAZARD_GUARD_THERMAL_BASELINE_PATH",
        "HAZARD_GUARD_THERMAL_AIR_TOPIC",
        "HAZARD_GUARD_THERMAL_OIL_TOPIC",
    ):
        monkeypatch.setenv(name, "  ")
    manager = SystemModeManager()

    command = manager._launch_arguments("rgbd_mapping")

    assert "thermal_roi_config:=" not in command
    assert not any(argument.endswith(":=") for argument in command)


def test_physical_patrol_uses_active_session_when_frozen_config_has_no_identity(
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
    manager = SystemModeManager()
    manager._active_map_session_id = "session-active"

    command = manager._launch_arguments(
        "patrol",
        thermal_map_config={"enabled": False, "session_id": ""},
    )

    assert "enable_frozen_thermal_map:=false" in command
    assert "thermal_map_session_id:=session-active" in command


def test_saved_mapping_session_immediately_becomes_active_transition_target(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    manager = SystemModeManager()
    old_session = _create_saved_session(manager)
    new_session = manager._world_catalog.begin_session("facility_map", "toolbox")
    manager._current_session_id = new_session["id"]
    manager._map_path = new_session["map_path"]
    manager._localization_pose = {"x": 2.5, "y": -1.0, "yaw": 0.4}
    manager._data.update(mode="mapping", state="running")

    def save_map(command, **_kwargs):
        assert command[command.index("-f") + 1] == str(
            new_session["map_path"].with_suffix("")
        )
        new_session["map_path"].write_text(
            "image: map.pgm\nresolution: 0.05\n",
            encoding="utf-8",
        )
        (new_session["directory"] / "map.pgm").write_bytes(b"P5\n1 1\n255\n\xff")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(manager._process_controller, "run", save_map)

    result = manager.save_map()
    rgbd_command = manager._launch_arguments("rgbd_mapping")

    assert result["accepted"] is True
    assert result["active_map_session_id"] == new_session["id"]
    assert result["thermal_map_session_id"] == new_session["id"]
    assert f"map:={new_session['map_path']}" in rgbd_command
    assert "initial_pose_x:=2.5" in rgbd_command
    assert old_session["id"] != result["active_map_session_id"]


def test_stop_rejects_external_stack_and_clears_managed_runtime_ids(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    manager = SystemModeManager()
    manager._data.update(mode="patrol", state="external", managed=False)

    external = manager.stop()

    assert external["accepted"] is False
    assert external["mode"] == "patrol"
    assert external["state"] == "external"

    manager._data.update(
        mode="rgbd_mapping",
        state="failed",
        mapping_session_id="stale-mapping",
        rgbd_session_id="stale-rgbd",
        rtabmap_database_path="stale.db",
    )
    manager._current_session_id = "stale-mapping"
    manager._rgbd_session_id = None
    manager._rtabmap_database_path = tmp_path / "stale.db"

    stopped = manager.stop()

    assert stopped["accepted"] is True
    assert stopped["mode"] == "idle"
    assert stopped["state"] == "stopped"
    assert stopped["mapping_session_id"] is None
    assert stopped["rgbd_session_id"] is None
    assert stopped["rtabmap_database_path"] is None


def test_stop_detects_external_stack_before_idle_early_return(monkeypatch, tmp_path):
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    manager = SystemModeManager()
    monkeypatch.setattr(manager, "_detect_external_mode", lambda: "patrol")
    side_effects = []
    manager.set_pre_stop_hook(lambda: side_effects.append("pre-stop"), grace_seconds=0)

    result = manager.stop()

    assert result["accepted"] is False
    assert result["mode"] == "patrol"
    assert result["state"] == "external"
    assert result["managed"] is False
    assert side_effects == []


def test_idle_stop_does_not_invoke_pre_stop_hook(monkeypatch, tmp_path):
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    manager = SystemModeManager()
    monkeypatch.setattr(manager, "_detect_external_mode", lambda: None)
    side_effects = []
    manager.set_pre_stop_hook(lambda: side_effects.append("pre-stop"), grace_seconds=0)

    result = manager.stop()

    assert result["accepted"] is True
    assert result["mode"] == "idle"
    assert side_effects == []


def test_managed_stop_quiesces_motion_before_process_signal(monkeypatch, tmp_path):
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    manager = SystemModeManager()
    events = []

    class FakeProcess:
        pid = 741

        @staticmethod
        def poll():
            return None

    manager._process = FakeProcess()
    manager._data.update(mode="patrol", state="running", managed=True, pid=741)

    def pre_stop():
        assert manager.snapshot(detect_external=False)["state"] == "stopping"
        events.extend(["cancel-route", "cancel-navigation", "stop-motion"])

    manager.set_pre_stop_hook(pre_stop, grace_seconds=0.2)
    monkeypatch.setattr(
        "app.mode_manager.time.sleep",
        lambda seconds: events.append(("grace", seconds)),
    )
    monkeypatch.setattr(
        manager,
        "_terminate_process_group",
        lambda *_args, **_kwargs: events.append("terminate"),
    )

    result = manager.stop()

    assert result["accepted"] is True
    assert events == [
        "cancel-route",
        "cancel-navigation",
        "stop-motion",
        ("grace", 0.2),
        "terminate",
    ]


def test_pre_stop_hook_exception_is_exposed_without_blocking_termination(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    manager = SystemModeManager()
    events = []

    class FakeProcess:
        pid = 745

    manager._process = FakeProcess()
    manager._data.update(mode="patrol", state="running", managed=True, pid=745)

    def failing_hook():
        events.append("hook")
        raise RuntimeError("bridge unavailable")

    manager.set_pre_stop_hook(failing_hook, grace_seconds=0)
    monkeypatch.setattr(
        manager,
        "_terminate_process_group",
        lambda *_args, **_kwargs: events.append("terminate"),
    )

    result = manager.stop()

    assert result["accepted"] is True
    assert result["pre_stop_warning"] == "bridge unavailable"
    assert events == ["hook", "terminate"]


def test_pre_stop_hook_rejection_is_exposed_without_blocking_termination(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    manager = SystemModeManager()
    events = []

    class FakeProcess:
        pid = 746

    manager._process = FakeProcess()
    manager._data.update(mode="patrol", state="running", managed=True, pid=746)
    manager.set_pre_stop_hook(
        lambda: {
            "accepted": False,
            "message": "zero velocity publish rejected",
        },
        grace_seconds=0,
    )
    monkeypatch.setattr(
        manager,
        "_terminate_process_group",
        lambda *_args, **_kwargs: events.append("terminate"),
    )

    result = manager.stop()

    assert result["accepted"] is True
    assert result["pre_stop_warning"] == "zero velocity publish rejected"
    assert events == ["terminate"]


def test_save_and_stop_uses_pre_stop_ordering(monkeypatch, tmp_path):
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    manager = SystemModeManager()
    events = []

    class FakeProcess:
        pid = 742

    manager._process = FakeProcess()
    manager._data.update(mode="mapping", state="running", managed=True, pid=742)
    manager.set_pre_stop_hook(
        lambda: events.extend(["cancel-route", "cancel-navigation", "stop-motion"]),
        grace_seconds=0.1,
    )
    monkeypatch.setattr(manager, "_save_map", lambda: {"accepted": True})
    monkeypatch.setattr(
        "app.mode_manager.time.sleep",
        lambda seconds: events.append(("grace", seconds)),
    )
    monkeypatch.setattr(
        manager,
        "_terminate_process_group",
        lambda *_args, **_kwargs: events.append("terminate"),
    )

    result = manager.save_map_and_stop()

    assert result["accepted"] is True
    assert events == [
        "cancel-route",
        "cancel-navigation",
        "stop-motion",
        ("grace", 0.1),
        "terminate",
    ]


def test_patrol_mode_switch_quiesces_motion_before_old_process_signal(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_DEPLOYMENT_TARGET", "physical")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    manager = SystemModeManager()
    events = []

    class OldProcess:
        pid = 743

        @staticmethod
        def poll():
            return None

    class NewProcess:
        pid = 744

        @staticmethod
        def poll():
            return None

    class NoopThread:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            pass

    manager._process = OldProcess()
    manager._data.update(mode="patrol", state="running", managed=True, pid=743)
    manager.set_pre_stop_hook(
        lambda: events.extend(["cancel-route", "cancel-navigation", "stop-motion"]),
        grace_seconds=0.05,
    )
    monkeypatch.setattr(manager, "_ensure_runtime_environment", lambda: True)
    monkeypatch.setattr(
        "app.mode_manager.time.sleep",
        lambda seconds: events.append(("grace", seconds)),
    )
    monkeypatch.setattr(
        manager,
        "_terminate_process_group",
        lambda *_args, **_kwargs: events.append("terminate-old"),
    )
    monkeypatch.setattr(
        manager._process_controller,
        "start_logged",
        lambda *_args, **_kwargs: events.append("launch-new") or NewProcess(),
    )
    monkeypatch.setattr("app.mode_manager.threading.Thread", NoopThread)

    result = manager.switch_mode("mapping")

    assert result["accepted"] is True
    assert events == [
        "cancel-route",
        "cancel-navigation",
        "stop-motion",
        ("grace", 0.05),
        "terminate-old",
        "launch-new",
    ]


def test_session_qualified_pose_loses_race_to_new_map_selection(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    manager = SystemModeManager()
    old_session = _create_saved_session(manager)
    manager._world_catalog.update_session(
        old_session["id"],
        "facility_map",
        localization_pose={"x": 1.0, "y": 1.0, "yaw": 0.1},
    )
    new_session = manager._world_catalog.begin_session("facility_map", "toolbox")
    new_session["map_path"].write_text(
        "image: map.pgm\nresolution: 0.05\n",
        encoding="utf-8",
    )
    (new_session["directory"] / "map.pgm").write_bytes(b"P5\n1 1\n255\n\xff")
    new_pose = {"x": 4.0, "y": -2.0, "yaw": 0.8}
    manager._world_catalog.update_session(
        new_session["id"],
        "facility_map",
        status="saved",
        localization_pose=new_pose,
    )
    attempted = threading.Event()
    result = []

    def store_old_pose():
        attempted.set()
        result.append(manager.set_localization_pose(
            {"x": 99.0, "y": 99.0, "yaw": 2.0},
            world_id="facility_map",
            session_id=old_session["id"],
        ))

    with manager._cloud_export_lock:
        worker = threading.Thread(target=store_old_pose)
        worker.start()
        assert attempted.wait(timeout=1.0)
        selected = manager.select_map("facility_map", new_session["id"])
    worker.join(timeout=1.0)

    assert selected["accepted"] is True
    assert result == [None]
    assert manager.snapshot(detect_external=False)["localization_pose"] == new_pose


def test_save_and_stop_are_serialized_on_one_transition_guard(monkeypatch, tmp_path):
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    manager = SystemModeManager()
    monkeypatch.setattr(manager, "_detect_external_mode", lambda: None)
    session = manager._world_catalog.begin_session("facility_map", "toolbox")
    manager._current_session_id = session["id"]
    manager._map_path = session["map_path"]
    manager._data.update(
        mode="mapping",
        state="running",
        mapping_session_id=session["id"],
    )

    class FakeProcess:
        pid = 188

        @staticmethod
        def poll():
            return None

    manager._process = FakeProcess()
    save_started = threading.Event()
    allow_save = threading.Event()
    stop_finished = threading.Event()
    results = {}

    def save_command(_command, **_kwargs):
        save_started.set()
        assert allow_save.wait(timeout=1.0)
        session["map_path"].write_text(
            "image: map.pgm\nresolution: 0.05\n",
            encoding="utf-8",
        )
        (session["directory"] / "map.pgm").write_bytes(b"P5\n1 1\n255\n\xff")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(manager._process_controller, "run", save_command)
    monkeypatch.setattr(manager, "_terminate_process_group", lambda *_args, **_kwargs: None)
    save_worker = threading.Thread(
        target=lambda: results.setdefault("save", manager.save_map())
    )
    stop_worker = threading.Thread(
        target=lambda: (results.setdefault("stop", manager.stop()), stop_finished.set())
    )

    save_worker.start()
    assert save_started.wait(timeout=1.0)
    stop_worker.start()
    assert stop_finished.wait(timeout=0.05) is False
    allow_save.set()
    save_worker.join(timeout=1.0)
    stop_worker.join(timeout=1.0)

    assert results["save"]["accepted"] is True
    assert results["save"]["active_map_session_id"] == session["id"]
    assert results["stop"]["accepted"] is True
    assert results["stop"]["mode"] == "idle"


def test_interrupted_save_generation_does_not_activate_result(monkeypatch, tmp_path):
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    manager = SystemModeManager()
    old_session = _create_saved_session(manager)
    new_session = manager._world_catalog.begin_session("facility_map", "toolbox")
    manager._current_session_id = new_session["id"]
    manager._map_path = new_session["map_path"]
    manager._data.update(mode="mapping", state="running")

    def interrupted_save(_command, **_kwargs):
        new_session["map_path"].write_text(
            "image: map.pgm\nresolution: 0.05\n",
            encoding="utf-8",
        )
        (new_session["directory"] / "map.pgm").write_bytes(b"P5\n1 1\n255\n\xff")
        with manager._lock:
            manager._generation += 1
            manager._data["state"] = "stopping"
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(manager._process_controller, "run", interrupted_save)

    result = manager.save_map()

    assert result["accepted"] is False
    assert "변경" in result["message"]
    assert manager._world_catalog.active_map_path("facility_map") == old_session["map_path"]
    metadata = manager._world_catalog.session_metadata(
        "facility_map", new_session["id"]
    )
    assert metadata["status"] == "mapping"


def test_failed_rgbd_retry_after_backend_restart_uses_active_map_pose(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_DEPLOYMENT_TARGET", "physical")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    original = SystemModeManager()
    session = _create_saved_session(original)
    expected_pose = {"x": 3.2, "y": -0.8, "yaw": 0.35}
    original._world_catalog.update_session(
        session["id"],
        "facility_map",
        localization_pose=expected_pose,
        rgbd_status="failed",
        cloud_export_status="failed",
        cloud_export_error="previous launch failed",
        thermal_map_status="failed",
        thermal_map_error="previous launch failed",
    )

    restarted = SystemModeManager()
    monkeypatch.setattr(restarted, "_detect_external_mode", lambda: None)

    class FakeProcess:
        pid = 812

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
        restarted._process_controller,
        "start_logged",
        lambda command, _log_path: launched.setdefault("command", command)
        and FakeProcess(),
    )
    monkeypatch.setattr("app.mode_manager.threading.Thread", NoopThread)

    before_retry = restarted.snapshot(detect_external=False)
    result = restarted.switch_mode("rgbd_mapping")
    metadata = restarted._world_catalog.session_metadata(
        "facility_map", session["id"]
    )

    assert before_retry["state"] == "stopped"
    assert before_retry["active_map_session_id"] == session["id"]
    assert before_retry["localization_pose"] == expected_pose
    assert result["accepted"] is True
    assert result["rgbd_session_id"] == session["id"]
    assert f"map:={session['map_path']}" in launched["command"]
    assert "initial_pose_x:=3.2" in launched["command"]
    assert "initial_pose_y:=-0.8" in launched["command"]
    assert "initial_pose_yaw:=0.35" in launched["command"]
    assert metadata["rgbd_status"] == "collecting"
    assert metadata["cloud_export_status"] == "stale"
    assert metadata["cloud_export_error"] is None
    assert metadata["thermal_map_status"] == "waiting_for_cloud"
    assert metadata["thermal_map_error"] is None


def test_physical_patrol_prepares_and_passes_frozen_thermal_session(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_DEPLOYMENT_TARGET", "physical")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    manager = SystemModeManager()
    monkeypatch.setattr(manager, "_detect_external_mode", lambda: None)
    session = _create_saved_session(manager)
    database_path = session["directory"] / "rgbd-map.db"
    database_path.write_bytes(b"database")
    manager._world_catalog.update_session(
        session["id"],
        "facility_map",
        rtabmap_database_file="rgbd-map.db",
        rgbd_database_file="rgbd-map.db",
        rgbd_status="saved",
        rgbd_workflow=manager.RGBD_WORKFLOW,
        cloud_frame_id="map",
        cloud_export_status="stale",
    )

    def fake_export(command, **_kwargs):
        preparing = manager.snapshot(detect_external=False)
        assert preparing["state"] == "preparing"
        assert preparing["thermal_map_status"] == "exporting"
        assert "내보내" in preparing["message"]
        expected = session["directory"] / "cloud-export_cloud.ply"
        assert command[-1] == str(database_path)
        expected.write_bytes(b"ply\n")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    class FakeProcess:
        pid = 741

        @staticmethod
        def poll():
            return None

    class NoopThread:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            pass

    launched = {}
    monkeypatch.setattr(manager._process_controller, "run", fake_export)
    monkeypatch.setattr(
        manager._process_controller,
        "start_logged",
        lambda command, _log_path: launched.setdefault("command", command)
        and FakeProcess(),
    )
    monkeypatch.setattr("app.mode_manager.threading.Thread", NoopThread)

    result = manager.switch_mode("patrol")

    cloud_path = session["directory"] / "cloud.ply"
    state_path = session["directory"] / "thermal_layer.npz"
    assert result["accepted"] is True
    assert result["thermal_map_enabled"] is True
    assert result["thermal_map_session_id"] == session["id"]
    assert "enable_frozen_thermal_map:=true" in launched["command"]
    assert f"thermal_map_cloud_path:={cloud_path}" in launched["command"]
    assert f"thermal_map_state_path:={state_path}" in launched["command"]
    assert f"thermal_map_session_id:={session['id']}" in launched["command"]
    saved = manager._world_catalog.sessions("facility_map")[0]
    assert saved["cloud_ready"] is True
    assert saved["thermal_map_status"] == "active"


def test_patrol_launch_failure_after_geometry_refresh_requires_cache_reset(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_DEPLOYMENT_TARGET", "physical")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    manager = SystemModeManager()
    monkeypatch.setattr(manager, "_detect_external_mode", lambda: None)
    session = _create_saved_session(manager)
    database_path = session["directory"] / "rgbd-map.db"
    database_path.write_bytes(b"database")
    manager._world_catalog.update_session(
        session["id"],
        "facility_map",
        rtabmap_database_file="rgbd-map.db",
        rgbd_database_file="rgbd-map.db",
        rgbd_status="saved",
        rgbd_workflow=manager.RGBD_WORKFLOW,
        cloud_frame_id="map",
        cloud_export_status="stale",
    )

    def fake_export(_command, **_kwargs):
        (session["directory"] / "cloud-export_cloud.ply").write_bytes(
            b"new-geometry"
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(manager._process_controller, "run", fake_export)
    monkeypatch.setattr(
        manager._process_controller,
        "start_logged",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError("launch unavailable")
        ),
    )

    result = manager.switch_mode("patrol")

    assert result["accepted"] is False
    assert result["thermal_cache_reset_required"] is True
    assert result["thermal_map_session_id"] == session["id"]
    assert (session["directory"] / "cloud.ply").read_bytes() == b"new-geometry"


def test_physical_patrol_starts_navigation_when_frozen_map_is_unavailable(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_DEPLOYMENT_TARGET", "physical")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    manager = SystemModeManager()
    monkeypatch.setattr(manager, "_detect_external_mode", lambda: None)
    session = _create_saved_session(manager)
    manager._world_catalog.update_session(
        session["id"],
        "facility_map",
        rtabmap_database_file="rgbd-map.db",
        rgbd_database_file="rgbd-map.db",
        rgbd_status="saved",
        rgbd_workflow=manager.RGBD_WORKFLOW,
        cloud_frame_id="map",
    )

    class FakeProcess:
        pid = 852

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

    result = manager.switch_mode("patrol")

    assert result["accepted"] is True
    assert result["thermal_map_enabled"] is False
    assert result["thermal_map_status"] == "failed"
    assert "enable_frozen_thermal_map:=false" in launched["command"]
    assert f"thermal_map_session_id:={session['id']}" in launched["command"]
    assert not any(
        argument.startswith("thermal_map_cloud_path:=")
        for argument in launched["command"]
    )
    assert "RTAB-Map" in str(result["thermal_map_message"])
    saved = manager._world_catalog.sessions("facility_map")[0]
    assert saved["thermal_map_status"] == "failed"


def test_physical_patrol_rejects_legacy_mixed_database_workflow(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_DEPLOYMENT_TARGET", "physical")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    manager = SystemModeManager()
    monkeypatch.setattr(manager, "_detect_external_mode", lambda: None)
    session = _create_saved_session(manager)
    (session["directory"] / "rtabmap.db").write_bytes(b"legacy-db")
    (session["directory"] / "cloud.ply").write_bytes(b"legacy-cloud")
    manager._world_catalog.update_session(
        session["id"],
        "facility_map",
        rtabmap_database_file="rtabmap.db",
        rgbd_database_file="rgbd-map.db",
        rgbd_status="saved",
        rgbd_workflow="saved-map-second-pass-v1",
        cloud_frame_id="map",
        cloud_export_status="ready",
    )

    class FakeProcess:
        pid = 963

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
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("unknown-frame legacy cloud must not be exported")
        ),
    )
    monkeypatch.setattr(
        manager._process_controller,
        "start_logged",
        lambda command, _log_path: launched.setdefault("command", command)
        and FakeProcess(),
    )
    monkeypatch.setattr("app.mode_manager.threading.Thread", NoopThread)

    result = manager.switch_mode("patrol")

    assert result["accepted"] is True
    assert result["thermal_map_enabled"] is False
    assert result["thermal_map_status"] == "failed"
    assert "map 좌표계" in str(result["thermal_map_message"])
    assert "enable_frozen_thermal_map:=false" in launched["command"]


def test_thermal_layer_persistence_is_recorded_after_patrol_stops(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_DEPLOYMENT_TARGET", "physical")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    manager = SystemModeManager()
    session = _create_saved_session(manager)
    state_path = session["directory"] / "thermal_layer.npz"
    np.savez_compressed(
        state_path,
        geometry_fingerprint=np.asarray("fixed-map-fingerprint"),
        persisted_at_ns=np.asarray(2_000_000_000, dtype=np.int64),
        last_seen_ns=np.asarray([1_000_000_000], dtype=np.int64),
    )
    manager._thermal_map_session_id = session["id"]
    manager._thermal_map_state_path = state_path
    manager._data["thermal_map_enabled"] = True
    manager.set_thermal_status_provider(
        lambda: {
            "available": True,
            "session_id": session["id"],
            "fingerprint": "fixed-map-fingerprint",
            "last_observation_at": "2026-08-23T10:00:00+00:00",
            "persisted_at": "2026-08-23T10:00:01+00:00",
            "map_error": "",
            "state_error": "",
        }
    )

    manager._finalize_thermal_map_session()
    manager._finalize_thermal_map_session()

    saved = manager._world_catalog.sessions("facility_map")[0]
    assert saved["thermal_map_status"] == "saved"
    assert saved["thermal_layer_available"] is True
    assert saved["thermal_layer_bytes"] == state_path.stat().st_size
    assert saved["thermal_layer_persisted_at"] is not None
    assert manager._data["thermal_map_enabled"] is False


def test_thermal_layer_is_not_marked_saved_without_matching_status(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    manager = SystemModeManager()
    session = _create_saved_session(manager)
    state_path = session["directory"] / "thermal_layer.npz"
    np.savez_compressed(
        state_path,
        geometry_fingerprint=np.asarray("old-fingerprint"),
        persisted_at_ns=np.asarray(2_000_000_000, dtype=np.int64),
        last_seen_ns=np.asarray([1_000_000_000], dtype=np.int64),
    )
    manager._thermal_map_session_id = session["id"]
    manager._thermal_map_state_path = state_path
    manager._data["thermal_map_enabled"] = True
    manager.set_thermal_status_provider(
        lambda: {
            "available": True,
            "session_id": session["id"],
            "fingerprint": "new-fingerprint",
            "persisted_at": "2026-08-23T10:00:01+00:00",
            "last_observation_at": "2026-08-23T10:00:00+00:00",
            "map_error": "",
            "state_error": "",
        }
    )

    manager._finalize_thermal_map_session()

    saved = manager._world_catalog.sessions("facility_map")[0]
    assert saved["thermal_map_status"] == "failed"
    assert saved["thermal_layer_status"] == "failed"
    assert "fingerprint" in str(saved["thermal_map_error"])


def test_physical_patrol_can_explicitly_disable_person_safety(monkeypatch, tmp_path):
    map_path = tmp_path / "runtime" / "maps" / "facility.yaml"
    monkeypatch.setenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "1")
    monkeypatch.setenv("HAZARD_GUARD_DEPLOYMENT_TARGET", "physical")
    monkeypatch.setenv("HAZARD_GUARD_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("HAZARD_GUARD_MAP_PATH", str(map_path))
    monkeypatch.setenv("HAZARD_GUARD_PERSON_SAFETY_ENABLED", "0")
    manager = SystemModeManager()

    command = manager._launch_arguments("patrol")

    assert "use_person_safety:=false" in command


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
