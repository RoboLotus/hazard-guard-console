import json
import math
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.bridge import RosBridge, SpatialStore, ThermalMapStatusStore


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


def test_thermal_map_freshness_uses_last_observation_not_status_receipt(
    monkeypatch,
):
    monkeypatch.setenv("HAZARD_GUARD_THERMAL_MAP_STALE_SEC", "5.0")
    store = ThermalMapStatusStore()
    store.reset("session-a")
    last_observation = datetime.now(timezone.utc) - timedelta(seconds=30)

    changed = store.update(
        SimpleNamespace(
            data=json.dumps(
                {
                    "session_id": "session-a",
                    "cumulative": True,
                    "fingerprint": "geometry-a",
                    "last_observation_at": last_observation.isoformat(),
                    "observed_voxel_count": 123,
                    "match_ratio": 0.72,
                    "rejected_observation_count": 8,
                }
            )
        )
    )
    snapshot = store.snapshot()

    assert changed is True
    assert snapshot["status_age_sec"] < 1.0
    assert snapshot["observation_age_sec"] >= 29.0
    assert snapshot["observation_fresh"] is False
    assert snapshot["stale_after_sec"] == 5.0
    assert snapshot["session_id"] == "session-a"
    assert snapshot["observed_voxel_count"] == 123


def test_thermal_map_status_detects_fingerprint_change_and_empty_identity():
    store = ThermalMapStatusStore()
    store.reset("session-a")

    assert store.update(
        SimpleNamespace(
            data=json.dumps(
                {"session_id": "session-a", "fingerprint": "geometry-a"}
            )
        )
    ) is True
    assert store.update(
        SimpleNamespace(
            data=json.dumps(
                {"session_id": "session-a", "fingerprint": "geometry-a"}
            )
        )
    ) is False
    assert store.update(
        SimpleNamespace(
            data=json.dumps(
                {"session_id": "session-a", "fingerprint": "geometry-b"}
            )
        )
    ) is True
    assert store.update(
        SimpleNamespace(
            data=json.dumps({"session_id": "session-a", "fingerprint": ""})
        )
    ) is True


def test_thermal_map_status_rejects_delayed_previous_session():
    store = ThermalMapStatusStore()
    store.reset("session-new")

    changed = store.update(
        SimpleNamespace(
            data=json.dumps(
                {"session_id": "session-old", "fingerprint": "old-map"}
            )
        )
    )

    assert changed is False
    assert store.snapshot()["available"] is False
    assert store.snapshot()["session_id"] == "session-new"


def test_thermal_map_status_rejects_all_updates_while_session_is_disabled():
    store = ThermalMapStatusStore()
    store.reset(None)

    changed = store.update(
        SimpleNamespace(
            data=json.dumps(
                {"session_id": "stopped-patrol", "fingerprint": "old-map"}
            )
        )
    )

    assert changed is False
    assert store.snapshot()["available"] is False
    assert store.snapshot()["session_id"] is None


def test_thermal_cloud_waits_for_matching_fixed_map_status():
    status_store = ThermalMapStatusStore()
    status_store.reset("session-new")
    received = []
    bridge = RosBridge.__new__(RosBridge)
    bridge.thermal_map_status = status_store
    bridge._thermal_cloud_adapter = SimpleNamespace(on_cloud=received.append)
    cloud_message = object()

    bridge._on_thermal_cloud(cloud_message)
    status_store.update(
        SimpleNamespace(
            data=json.dumps(
                {
                    "session_id": "session-old",
                    "fixed_map_available": True,
                    "fingerprint": "old-map",
                }
            )
        )
    )
    bridge._on_thermal_cloud(cloud_message)

    assert received == []

    status_store.update(
        SimpleNamespace(
            data=json.dumps(
                {
                    "session_id": "session-new",
                    "fixed_map_available": True,
                    "fingerprint": "new-map",
                }
            )
        )
    )
    bridge._on_thermal_cloud(cloud_message)

    assert received == [cloud_message]
