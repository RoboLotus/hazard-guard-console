import math
from types import SimpleNamespace

import pytest

from app.bridge import RosBridge, SpatialStore


def test_pose_errors_wrap_yaw_across_pi_boundary():
    position_error, yaw_error = RosBridge._pose_errors(
        (1.0, 2.0, math.radians(179)),
        (1.03, 2.04, math.radians(-179)),
    )

    assert position_error == pytest.approx(0.05)
    assert math.degrees(yaw_error) == pytest.approx(2.0)


def test_set_pose_yaw_creates_planar_unit_quaternion():
    pose = SimpleNamespace(
        orientation=SimpleNamespace(x=0.0, y=0.0, z=0.0, w=0.0)
    )

    RosBridge._set_pose_yaw(pose, math.radians(90))

    assert pose.orientation.z == pytest.approx(math.sqrt(0.5))
    assert pose.orientation.w == pytest.approx(math.sqrt(0.5))
    assert pose.orientation.z**2 + pose.orientation.w**2 == pytest.approx(1.0)


def test_clear_trail_keeps_current_pose_but_removes_previous_mission_path():
    store = SpatialStore()
    store.update_pose(x=0.0, y=0.0, yaw=0.0, mock=False)
    store.update_pose(x=0.2, y=0.0, yaw=0.0, mock=False)

    store.clear_trail()

    snapshot = store.snapshot()
    assert snapshot["trail"] == []
    assert snapshot["pose"]["available"] is True
    assert snapshot["pose"]["x"] == 0.2
