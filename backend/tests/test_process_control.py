from app.process_control import ProcessController


def test_last_log_line_prefers_latest_error(tmp_path):
    log_path = tmp_path / "system.log"
    log_path.write_text(
        "starting\n[ERROR] planner failed\nshutdown complete\n",
        encoding="utf-8",
    )

    assert ProcessController.last_log_line(log_path) == "[ERROR] planner failed"


def test_last_log_line_handles_missing_file(tmp_path):
    assert ProcessController.last_log_line(tmp_path / "missing.log") is None


def test_ros_nodes_returns_empty_set_when_command_is_unavailable(
    monkeypatch,
    tmp_path,
):
    controller = ProcessController(tmp_path, "facility_map.sdf")

    def fail(*_args, **_kwargs):
        raise OSError("ros2 missing")

    monkeypatch.setattr(controller, "run", fail)

    assert controller.ros_nodes() == set()
