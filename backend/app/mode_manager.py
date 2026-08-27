from __future__ import annotations

import os
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .process_control import ProcessController
from .world_catalog import RGBD_DATABASE_FILE, WorldCatalog


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def env_flag(name: str, default: bool = False) -> bool:
    fallback = "1" if default else "0"
    return os.getenv(name, fallback).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


class SystemModeManager:
    """Own the ROS launch process selected by the WebUI.

    This is a local-development supervisor. It only stops process groups that it
    started itself; terminal-launched ROS stacks are detected and left untouched.
    """

    MODES = {"mapping", "rgbd_mapping", "patrol"}
    MAPPING_PROFILES = {"toolbox", "toolbox_rtabmap"}
    DEPLOYMENT_TARGETS = {"simulation", "physical"}
    RGBD_WORKFLOW = "saved-map-second-pass-v2-dedicated-db"

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._cloud_export_lock = threading.RLock()
        self._process: subprocess.Popen[Any] | None = None
        self._simulation_process: subprocess.Popen[Any] | None = None
        self._generation = 0
        self._simulation_generation = 0
        self._ignore_external_until = 0.0
        self._enabled = os.getenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "0") == "1"
        self._deployment_target = os.getenv(
            "HAZARD_GUARD_DEPLOYMENT_TARGET", "simulation"
        ).strip().lower()
        if self._deployment_target not in self.DEPLOYMENT_TARGETS:
            supported = ", ".join(sorted(self.DEPLOYMENT_TARGETS))
            raise ValueError(
                "Unsupported HAZARD_GUARD_DEPLOYMENT_TARGET: "
                f"{self._deployment_target!r}. Expected one of: {supported}"
            )
        self._workspace = Path(
            os.getenv("HAZARD_GUARD_WORKSPACE", os.getcwd())
        ).expanduser().resolve()
        self._world_catalog = WorldCatalog(self._workspace)
        self._active_world = self._world_catalog.selected_world()
        self._current_session_id: str | None = None
        self._mapping_profile = "toolbox"
        # Patrol normally localizes on a saved map. With this on, SLAM Toolbox
        # runs instead of AMCL so manual driving keeps extending the map and it
        # can be saved again from the patrol screen.
        self._patrol_slam = False
        self._rtabmap_database_path: Path | None = None
        configured_map = Path(
            os.getenv("HAZARD_GUARD_MAP_PATH", "runtime/maps/facility.yaml")
        ).expanduser()
        legacy_map_path = (
            configured_map
            if configured_map.is_absolute()
            else (self._workspace / configured_map).resolve()
        )
        active_map_path = self._world_catalog.active_map_path(self._active_world["id"])
        self._map_path = active_map_path or (
            legacy_map_path
            if self._active_world["id"] == "facility_map"
            else self._workspace
            / "runtime"
            / "maps"
            / self._active_world["id"]
            / "unavailable.yaml"
        )
        self._localization_pose: dict[str, float] | None = None
        active_session = next(
            (
                session
                for session in self._world_catalog.sessions(self._active_world["id"])
                if session.get("active")
            ),
            None,
        )
        if active_session is not None:
            self._localization_pose = self._validated_pose(
                active_session.get("localization_pose")
            )
        self._active_map_session_id = (
            active_session.get("id") if active_session is not None else None
        )
        self._rgbd_session_id: str | None = None
        self._rgbd_finalize_pending_id: str | None = None
        self._thermal_map_session_id: str | None = (
            str(active_session["id"]) if active_session is not None else None
        )
        self._thermal_map_cloud_path: Path | None = (
            Path(active_session["cloud_path"])
            if active_session is not None
            else None
        )
        self._thermal_map_state_path: Path | None = (
            Path(active_session["thermal_layer_path"])
            if active_session is not None
            else None
        )
        self._thermal_status_provider: Callable[[], dict[str, Any]] | None = None
        self._gui = os.getenv("HAZARD_GUARD_SIMULATION_GUI", "true").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self._simulation_mode = os.getenv(
            "HAZARD_GUARD_SIMULATION_MODE", "kinematic"
        )
        self._log_path = self._workspace / "runtime" / "logs" / "system-mode.log"
        self._simulation_log_path = (
            self._workspace / "runtime" / "logs" / "simulation.log"
        )
        self._simulation_world_marker = self._active_world["file_name"]
        self._process_controller = ProcessController(
            self._workspace,
            self._simulation_world_marker,
        )
        self._data: dict[str, Any] = {
            "mode": "idle",
            "state": "disabled" if not self._enabled else "stopped",
            "accepted": False,
            "managed": False,
            "control_enabled": self._enabled,
            "deployment_target": self._deployment_target,
            "pid": None,
            "map_path": str(self._map_path),
            "map_files": self._map_file_summary(),
            "localization_pose": self._localization_pose,
            "active_world_id": self._active_world["id"],
            "active_world_label": (
                self._active_world["label"]
                if self._deployment_target == "simulation"
                else "실물 로봇 현장"
            ),
            "mapping_session_id": None,
            "active_map_session_id": self._active_map_session_id,
            "rgbd_session_id": None,
            "thermal_map_session_id": self._thermal_map_session_id,
            "thermal_map_enabled": False,
            "thermal_map_status": (
                str(active_session.get("thermal_map_status") or "not_ready")
                if active_session is not None
                else "not_ready"
            ),
            "thermal_map_message": None,
            "thermal_map_cloud_path": (
                str(self._thermal_map_cloud_path)
                if self._thermal_map_cloud_path is not None
                else None
            ),
            "thermal_map_state_path": (
                str(self._thermal_map_state_path)
                if self._thermal_map_state_path is not None
                else None
            ),
            "mapping_profile": self._mapping_profile,
            "patrol_slam": self._patrol_slam,
            "rtabmap_database_path": None,
            "log_path": str(self._log_path),
            "simulation_log_path": str(self._simulation_log_path),
            "simulation_state": (
                "stopped"
                if self._deployment_target == "simulation"
                else "not_applicable"
            ),
            "simulation_managed": False,
            "simulation_pid": None,
            "map_available": self._map_files_available(),
            "message": (
                "WebUI 모드 제어가 비활성화되어 있습니다."
                if not self._enabled
                else "선택된 로봇 운용 모드가 없습니다."
            ),
            "started_at": None,
            "updated_at": utc_now(),
            "exit_code": None,
        }

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_thermal_status_provider(
        self,
        provider: Callable[[], dict[str, Any]],
    ) -> None:
        self._thermal_status_provider = provider

    def _map_files_available(self) -> bool:
        return self._world_catalog.map_available(self._map_path)

    @staticmethod
    def _validated_pose(pose: Any) -> dict[str, float] | None:
        if not isinstance(pose, dict):
            return None
        try:
            return {
                "x": float(pose["x"]),
                "y": float(pose["y"]),
                "yaw": float(pose["yaw"]),
            }
        except (KeyError, TypeError, ValueError):
            return None

    def _map_file_summary(self) -> dict[str, Any]:
        image_path = self._world_catalog.map_image_path(self._map_path)
        session_directory = self._map_path.parent
        database_path = session_directory / "rtabmap.db"
        cloud_path = session_directory / "cloud.ply"
        thermal_layer_path = session_directory / "thermal_layer.npz"
        return {
            "directory": str(session_directory),
            "yaml": str(self._map_path),
            "image": str(image_path) if image_path is not None else None,
            "rtabmap_database": (
                str(database_path) if database_path.is_file() else None
            ),
            "point_cloud": str(cloud_path) if cloud_path.is_file() else None,
            "thermal_layer": (
                str(thermal_layer_path) if thermal_layer_path.is_file() else None
            ),
        }

    def set_localization_pose(self, pose: Any) -> dict[str, float] | None:
        """Remember the last mapped pose for the following AMCL startup."""

        validated = self._validated_pose(pose)
        if validated is None:
            return None
        with self._lock:
            self._localization_pose = validated
            self._data["localization_pose"] = dict(validated)
        return dict(validated)

    @staticmethod
    def _launch_value(value: float) -> str:
        formatted = format(float(value), ".6g")
        return formatted if any(marker in formatted for marker in ".eE") else f"{formatted}.0"

    def _world_launch_arguments(self) -> list[str]:
        world = self._active_world
        spawn = world["spawn"]
        arguments = [
            f"world:={world['path']}",
            f"world_name:={world['world_name']}",
            f"spawn_x:={self._launch_value(spawn['x'])}",
            f"spawn_y:={self._launch_value(spawn['y'])}",
            f"spawn_z:={self._launch_value(spawn['z'])}",
            f"spawn_yaw:={self._launch_value(spawn['yaw'])}",
        ]
        profile = world.get("heat_source_profile_path")
        if profile is not None:
            arguments.append(f"heat_source_profile:={profile}")
        return arguments

    def worlds(self) -> dict[str, Any]:
        return self._world_catalog.public_worlds()

    def maps(self, world_id: str | None = None) -> dict[str, Any]:
        selected_id = world_id or self._active_world["id"]
        return {
            "world_id": selected_id,
            "sessions": self._world_catalog.sessions(selected_id),
        }

    @property
    def map_root(self) -> Path:
        return self._world_catalog.map_root

    def spatial_registration_context(self) -> dict[str, Any]:
        """Describe whether equipment and routes may bind to the active map."""

        world_id = self._active_world["id"]
        session = next(
            (
                item
                for item in self._world_catalog.sessions(world_id)
                if item.get("id") == self._active_map_session_id
                and item.get("active")
            ),
            None,
        )
        map_ready = bool(session and session.get("available"))
        cloud_ready = bool(
            session
            and session.get("cloud_ready")
            and session.get("cloud_frame_id") == "map"
        )
        if not map_ready:
            state = "map_required"
            message = "2D 지도를 완성하고 저장한 뒤 등록할 수 있습니다."
        elif not cloud_ready:
            state = "cloud_required"
            message = "저장된 지도에서 3D 수집과 PLY 저장을 완료하세요."
        else:
            state = "ready"
            message = "설비 ROI와 순찰 웨이포인트를 등록할 수 있습니다."
        return {
            "world_id": world_id,
            "map_session_id": session.get("id") if session else None,
            "frame_id": "map",
            "map_ready": map_ready,
            "cloud_ready": cloud_ready,
            "registration_ready": map_ready and cloud_ready,
            "state": state,
            "message": message,
            "geometry_fingerprint": (
                session.get("thermal_layer_fingerprint") if session else None
            ),
            "cloud_path": session.get("cloud_path") if session else None,
        }

    def _active_map_session(self) -> dict[str, Any] | None:
        return next(
            (
                session
                for session in self._world_catalog.sessions(
                    self._active_world["id"]
                )
                if session.get("active") and session.get("available")
            ),
            None,
        )

    def edit_map_session(
        self,
        world_id: str,
        session_id: str,
        *,
        name: str | None = None,
        archived: bool | None = None,
    ) -> dict[str, Any]:
        try:
            session = self._world_catalog.edit_session(
                world_id,
                session_id,
                name=name,
                archived=archived,
            )
        except KeyError:
            return {
                "accepted": False,
                "message": "지도 세션을 찾지 못했습니다.",
            }
        return {
            "accepted": True,
            "message": "지도 세션 정보를 저장했습니다.",
            "session": session,
        }

    def export_map_cloud(self, world_id: str, session_id: str) -> dict[str, Any]:
        # Serialize manual export, automatic RGB-D finalization, and patrol
        # preparation. The subprocess itself never runs under ``self._lock``.
        with self._cloud_export_lock:
            return self._export_map_cloud(world_id, session_id)

    def _thermal_metadata_contract_valid(
        self,
        metadata: dict[str, Any],
    ) -> bool:
        return bool(
            metadata.get("rgbd_status") == "saved"
            and metadata.get("rgbd_workflow") == self.RGBD_WORKFLOW
            and metadata.get("cloud_frame_id") == "map"
            and metadata.get("rtabmap_database_file") == RGBD_DATABASE_FILE
            and metadata.get("rgbd_database_file") == RGBD_DATABASE_FILE
        )

    def _export_map_cloud(
        self,
        world_id: str,
        session_id: str,
    ) -> dict[str, Any]:
        with self._lock:
            process = self._process
            managed_session_id = (
                self._rgbd_session_id or self._data.get("rgbd_session_id")
            )
            current_mapping = (
                self._data.get("mode") in {"mapping", "rgbd_mapping"}
                and self._data.get("state") in {"starting", "running", "stopping"}
                and (
                    self._current_session_id == session_id
                    or managed_session_id == session_id
                )
                and process is not None
            )
            rgbd_finalization_pending = (
                self._rgbd_finalize_pending_id == session_id
            )
            current_thermal_use = (
                self._data.get("mode") == "patrol"
                and self._data.get("state")
                in {"starting", "running", "stopping"}
                and self._thermal_map_session_id == session_id
                and process is not None
            )
            external_stack = bool(
                self._data.get("state") == "external"
                and self._data.get("mode")
                in {"mapping", "rgbd_mapping", "patrol"}
            )
        try:
            paths = self._world_catalog.session_paths(world_id, session_id)
        except KeyError:
            return {"accepted": False, "message": "지도 세션을 찾지 못했습니다."}
        existing_cloud = paths["cloud"]
        existing_cloud_available = (
            existing_cloud.is_file() and existing_cloud.stat().st_size > 0
        )
        if current_thermal_use and existing_cloud_available:
            # Patrol only reads the frozen RGB-D surface. Serving that immutable
            # PLY lets the WebUI retain its 3D reference while the thermal layer
            # is starting, without touching the active RTAB-Map database.
            return {
                "accepted": True,
                "path": existing_cloud,
                "geometry_refreshed": False,
                "message": "순찰 기준 3D 지도 파일을 준비했습니다.",
            }
        if (
            current_mapping
            or current_thermal_use
            or rgbd_finalization_pending
            or external_stack
        ):
            return {
                "accepted": False,
                "message": (
                    "터미널에서 실행 중인 ROS 지도·순찰 스택을 종료한 뒤 "
                    "3D 지도를 내보내세요."
                    if external_stack
                    else (
                        "현재 누적 열화상 순찰을 종료한 뒤 3D 지도를 내보내세요."
                        if current_thermal_use
                        else "현재 3D 세션을 저장 후 종료한 뒤 내보내세요."
                    )
                ),
            }
        metadata = self._world_catalog.session_metadata(world_id, session_id)
        thermal_contract_valid = self._thermal_metadata_contract_valid(metadata)
        database_path = paths["database"]
        cloud_path = paths["cloud"]
        cloud_available = cloud_path.is_file() and cloud_path.stat().st_size > 0
        database_available = (
            database_path.is_file() and database_path.stat().st_size > 0
        )
        export_status = str(metadata.get("cloud_export_status") or "")
        database_newer = bool(
            cloud_available
            and database_available
            and database_path.stat().st_mtime_ns > cloud_path.stat().st_mtime_ns
        )
        requires_refresh = export_status in {"stale", "exporting", "failed"}
        if cloud_available and not requires_refresh and not database_newer:
            self._world_catalog.record_cloud_export(
                world_id, session_id, cloud_path
            )
            if (
                thermal_contract_valid
                and metadata.get("thermal_map_status") != "active"
            ):
                self._world_catalog.update_session(
                    session_id,
                    world_id,
                    thermal_map_status="ready",
                    thermal_map_error=None,
                )
            elif not thermal_contract_valid:
                self._world_catalog.update_session(
                    session_id,
                    world_id,
                    thermal_map_status="incompatible",
                    thermal_map_error=(
                        "이 PLY는 전용 map 좌표계 RGB-D DB에서 생성됐다는 "
                        "provenance가 없어 누적 열화상에는 사용하지 않습니다."
                    ),
                )
            return {
                "accepted": True,
                "path": cloud_path,
                "geometry_refreshed": False,
                "message": "저장된 3D 지도 파일을 준비했습니다.",
            }
        if not database_available:
            message = "선택한 세션에는 RTAB-Map 3D 데이터가 없습니다."
            self._world_catalog.update_session(
                session_id,
                world_id,
                cloud_export_status="failed",
                cloud_export_error=message,
                thermal_map_status="failed",
                thermal_map_error=message,
            )
            return {
                "accepted": False,
                "message": message,
            }
        output_name = "cloud-export"
        expected_path = paths["directory"] / f"{output_name}_cloud.ply"
        self._world_catalog.update_session(
            session_id,
            world_id,
            cloud_export_status="exporting",
            cloud_export_error=None,
            thermal_map_status="waiting_for_cloud",
            thermal_map_error=None,
        )
        try:
            expected_path.unlink(missing_ok=True)
            result = self._process_controller.run(
                [
                    "rtabmap-export",
                    "--cloud",
                    "--opt",
                    "2",
                    "--voxel",
                    "0.03",
                    "--decimation",
                    "4",
                    "--output",
                    output_name,
                    "--output_dir",
                    str(paths["directory"]),
                    str(database_path),
                ],
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            message = f"3D 지도 내보내기 도구를 실행하지 못했습니다: {exc}"
            self._world_catalog.update_session(
                session_id,
                world_id,
                cloud_export_status="failed",
                cloud_export_error=message,
                thermal_map_status="failed",
                thermal_map_error=message,
            )
            return {
                "accepted": False,
                "message": message,
            }
        if (
            result.returncode != 0
            or not expected_path.is_file()
            or expected_path.stat().st_size <= 0
        ):
            detail = (result.stderr or result.stdout).strip().splitlines()
            message = "3D 지도 파일을 생성하지 못했습니다." + (
                f" {detail[-1]}" if detail else ""
            )
            self._world_catalog.update_session(
                session_id,
                world_id,
                cloud_export_status="failed",
                cloud_export_error=message,
                thermal_map_status="failed",
                thermal_map_error=message,
            )
            return {
                "accepted": False,
                "message": message,
            }
        try:
            self._world_catalog.quarantine_thermal_layer(world_id, session_id)
        except OSError as exc:
            expected_path.unlink(missing_ok=True)
            message = f"기존 열화상 계층을 보존하지 못해 3D 지도 교체를 중단했습니다: {exc}"
            self._world_catalog.update_session(
                session_id,
                world_id,
                cloud_export_status="failed",
                cloud_export_error=message,
                thermal_map_status="failed",
                thermal_map_error=message,
            )
            return {"accepted": False, "message": message}
        expected_path.replace(cloud_path)
        self._world_catalog.record_cloud_export(world_id, session_id, cloud_path)
        self._world_catalog.update_session(
            session_id,
            world_id,
            thermal_map_status=(
                "ready" if thermal_contract_valid else "incompatible"
            ),
            thermal_map_error=(
                None
                if thermal_contract_valid
                else (
                    "이 PLY는 전용 map 좌표계 RGB-D DB에서 생성됐다는 "
                    "provenance가 없어 누적 열화상에는 사용하지 않습니다."
                )
            ),
        )
        return {
            "accepted": True,
            "path": cloud_path,
            "geometry_refreshed": True,
            "message": "저장된 RTAB-Map DB에서 컬러 PLY 지도를 생성했습니다.",
        }

    def _prepare_rgbd_collection(self, session: dict[str, Any]) -> Path:
        """Select a clean map-frame-only DB while preserving prior artifacts."""

        world_id = self._active_world["id"]
        session_id = str(session["id"])
        metadata = self._world_catalog.session_metadata(world_id, session_id)
        paths = self._world_catalog.session_paths(world_id, session_id)
        self._world_catalog.quarantine_rgbd_artifacts(world_id, session_id)
        dedicated_database = paths["rgbd_database"]
        current_database_file = metadata.get("rtabmap_database_file")
        mapping_database_file = metadata.get(
            "mapping_rtabmap_database_file"
        )
        if (
            not mapping_database_file
            and current_database_file
            and str(current_database_file) != dedicated_database.name
        ):
            mapping_database_file = str(current_database_file)
        self._world_catalog.update_session(
            session_id,
            world_id,
            mapping_rtabmap_database_file=mapping_database_file,
            rgbd_database_file=dedicated_database.name,
            rtabmap_database_file=dedicated_database.name,
            rgbd_status="preparing",
            rgbd_workflow=self.RGBD_WORKFLOW,
            cloud_frame_id="map",
            cloud_voxel_size_m=0.03,
            rgbd_finished_at=None,
            cloud_export_status="stale",
            cloud_export_error=None,
            thermal_map_status="waiting_for_cloud",
            thermal_map_error=None,
            thermal_layer_status="stale",
        )
        return dedicated_database

    def _prepare_frozen_thermal_map(self) -> dict[str, Any]:
        """Synchronously prepare thermal geometry before launching patrol."""

        session = self._active_map_session()
        if session is None:
            return {
                "enabled": False,
                "session_id": None,
                "cloud_path": None,
                "state_path": None,
                "message": "선택된 지도 세션이 없어 누적 열화상 지도를 비활성화합니다.",
            }
        session_id = str(session["id"])
        dedicated_database = Path(session["storage_directory"]) / RGBD_DATABASE_FILE
        if (
            session.get("rgbd_status") != "saved"
            or session.get("rgbd_workflow") != self.RGBD_WORKFLOW
            or session.get("cloud_frame_id") != "map"
            or session.get("rtabmap_database_file") != RGBD_DATABASE_FILE
            or session.get("rgbd_database_file") != RGBD_DATABASE_FILE
            or Path(str(session.get("rtabmap_database_path") or ""))
            != dedicated_database
        ):
            message = (
                "선택한 세션은 전용 DB를 사용한 저장 2D 지도 기반 RGB-D "
                "3D 수집 결과이거나 map 좌표계임이 확인되지 않아 누적 "
                "열화상을 비활성화합니다. 해당 세션에서 3D 수집을 다시 "
                "완료하세요."
            )
            self._world_catalog.update_session(
                session_id,
                self._active_world["id"],
                thermal_map_status="failed",
                thermal_map_error=message,
            )
            return {
                "enabled": False,
                "session_id": session_id,
                "cloud_path": Path(session["cloud_path"]),
                "state_path": Path(session["thermal_layer_path"]),
                "message": message,
            }
        try:
            paths = self._world_catalog.session_paths(
                self._active_world["id"], session_id
            )
        except KeyError:
            return {
                "enabled": False,
                "session_id": session_id,
                "cloud_path": None,
                "state_path": None,
                "message": "지도 세션 저장 경로를 확인할 수 없어 누적 열화상을 비활성화합니다.",
            }
        with self._lock:
            self._update_locked(
                mode="patrol",
                state="preparing",
                managed=False,
                pid=None,
                thermal_map_session_id=session_id,
                thermal_map_enabled=False,
                thermal_map_status="exporting",
                thermal_map_message=(
                    "첫 순찰을 위해 고정 3D 지도를 내보내는 중입니다. "
                    "지도 크기에 따라 최대 수 분 걸릴 수 있습니다."
                ),
                thermal_map_cloud_path=str(paths["cloud"]),
                thermal_map_state_path=str(paths["thermal_layer"]),
                message=(
                    "고정 3D 지도를 내보내고 누적 열화상 계층을 "
                    "준비하고 있습니다."
                ),
            )
        exported = self.export_map_cloud(self._active_world["id"], session_id)
        if not exported.get("accepted"):
            return {
                "enabled": False,
                "session_id": session_id,
                "cloud_path": paths["cloud"],
                "state_path": paths["thermal_layer"],
                "geometry_refreshed": False,
                "message": str(exported.get("message") or "3D 지도를 준비하지 못했습니다."),
            }
        return {
            "enabled": True,
            "session_id": session_id,
            "cloud_path": Path(exported["path"]),
            "state_path": paths["thermal_layer"],
            "geometry_refreshed": bool(exported.get("geometry_refreshed")),
            "message": "고정 3D 지도 기반 누적 열화상을 준비했습니다.",
        }

    def select_world(self, world_id: str) -> dict[str, Any]:
        with self._cloud_export_lock:
            return self._select_world(world_id)

    def _select_world(self, world_id: str) -> dict[str, Any]:
        if self._deployment_target != "simulation":
            with self._lock:
                return self._update_locked(
                    accepted=False,
                    message="시뮬레이션 환경 전환은 simulation 배포 대상에서만 사용할 수 있습니다.",
                )
        with self._lock:
            if self._process is not None or self._data["state"] in {
                "starting",
                "running",
                "preparing",
                "stopping",
                "external",
            }:
                return self._update_locked(
                    accepted=False,
                    message="SLAM 또는 순찰 모드를 종료한 뒤 환경을 전환하세요.",
                )
        with self._lock:
            managed_simulation = self._simulation_process is not None
        if managed_simulation:
            self._stop_managed_simulation()
        elif self._detect_external_simulation():
            with self._lock:
                return self._update_locked(
                    accepted=False,
                    message="터미널에서 실행 중인 Gazebo를 종료한 뒤 환경을 전환하세요.",
                )
        try:
            world = self._world_catalog.get(world_id)
        except KeyError:
            with self._lock:
                return self._update_locked(
                    accepted=False,
                    message="등록되지 않은 시뮬레이션 환경입니다.",
                )
        if self._enabled and not world["path"].is_file():
            with self._lock:
                return self._update_locked(
                    accepted=False,
                    message="선택한 시뮬레이션 환경 파일을 찾지 못했습니다.",
                )
        world = self._world_catalog.select_world(world_id)
        self._active_world = world
        self._current_session_id = None
        self._active_map_session_id = None
        self._rgbd_session_id = None
        self._thermal_map_session_id = None
        self._thermal_map_cloud_path = None
        self._thermal_map_state_path = None
        self._map_path = (
            self._world_catalog.active_map_path(world_id)
            or self._workspace / "runtime" / "maps" / world_id / "unavailable.yaml"
        )
        self._simulation_world_marker = world["file_name"]
        self._process_controller = ProcessController(
            self._workspace,
            self._simulation_world_marker,
        )
        with self._lock:
            return self._update_locked(
                accepted=True,
                mode="idle",
                state="stopped",
                active_world_id=world_id,
                active_world_label=world["label"],
                map_path=str(self._map_path),
                mapping_session_id=None,
                active_map_session_id=None,
                rgbd_session_id=None,
                thermal_map_session_id=None,
                thermal_map_enabled=False,
                thermal_map_status="not_ready",
                thermal_map_message=None,
                thermal_map_cloud_path=None,
                thermal_map_state_path=None,
                message=f"시뮬레이션 환경을 '{world['label']}'로 변경했습니다.",
            )

    def select_map(self, world_id: str, session_id: str) -> dict[str, Any]:
        with self._cloud_export_lock:
            return self._select_map(world_id, session_id)

    def _select_map(self, world_id: str, session_id: str) -> dict[str, Any]:
        if world_id != self._active_world["id"]:
            with self._lock:
                return self._update_locked(
                    accepted=False,
                    message="현재 선택된 환경의 지도만 순찰 지도에 지정할 수 있습니다.",
                )
        with self._lock:
            if self._data["state"] in {
                "starting",
                "running",
                "preparing",
                "stopping",
                "external",
            }:
                return self._update_locked(
                    accepted=False,
                    message="SLAM 또는 순찰 모드를 종료한 뒤 순찰 지도를 변경하세요.",
                )
        try:
            self._map_path = self._world_catalog.activate_session(world_id, session_id)
        except KeyError:
            with self._lock:
                return self._update_locked(
                    accepted=False,
                    message="사용 가능한 SLAM 지도 세션을 찾지 못했습니다.",
                )
        selected_session = next(
            (
                session
                for session in self._world_catalog.sessions(world_id)
                if session["id"] == session_id
            ),
            None,
        )
        self._localization_pose = self._validated_pose(
            selected_session.get("localization_pose") if selected_session else None
        )
        self._active_map_session_id = session_id
        self._rgbd_session_id = None
        self._thermal_map_session_id = session_id
        self._thermal_map_cloud_path = (
            Path(selected_session["cloud_path"]) if selected_session else None
        )
        self._thermal_map_state_path = (
            Path(selected_session["thermal_layer_path"])
            if selected_session
            else None
        )
        with self._lock:
            return self._update_locked(
                accepted=True,
                map_path=str(self._map_path),
                active_map_session_id=session_id,
                rgbd_session_id=None,
                thermal_map_session_id=session_id,
                thermal_map_enabled=False,
                thermal_map_status=(
                    str(selected_session.get("thermal_map_status") or "not_ready")
                    if selected_session
                    else "not_ready"
                ),
                thermal_map_message=None,
                thermal_map_cloud_path=(
                    str(self._thermal_map_cloud_path)
                    if self._thermal_map_cloud_path is not None
                    else None
                ),
                thermal_map_state_path=(
                    str(self._thermal_map_state_path)
                    if self._thermal_map_state_path is not None
                    else None
                ),
                message="선택한 SLAM 결과를 순찰용 지도로 지정했습니다.",
            )

    def _update_locked(self, **values: Any) -> dict[str, Any]:
        self._data.update(values)
        self._data["map_available"] = self._map_files_available()
        self._data["map_files"] = self._map_file_summary()
        self._data["localization_pose"] = self._localization_pose
        self._data["updated_at"] = utc_now()
        return dict(self._data)

    def _detect_external_mode(self) -> str | None:
        if not self._enabled:
            return None
        if time.monotonic() < self._ignore_external_until:
            return None
        nodes = self._process_controller.ros_nodes()
        if any(node.endswith("/slam_toolbox") for node in nodes):
            return "mapping"
        if any(node.endswith("/amcl") for node in nodes) or any(
            node.endswith("/controller_server") for node in nodes
        ):
            return "patrol"
        return None

    def snapshot(self, *, detect_external: bool = True) -> dict[str, Any]:
        with self._lock:
            process = self._process
            if process is not None:
                exit_code = process.poll()
                if exit_code is not None:
                    # The monitor owns process-group cleanup and session
                    # finalization. Keeping the handle here prevents a status
                    # poll from opening a DB-export race before descendants
                    # have closed RTAB-Map.
                    self._update_locked(
                        state="stopping",
                        managed=True,
                        exit_code=exit_code,
                        message="ROS 자식 프로세스 종료와 세션 저장을 마무리하고 있습니다.",
                    )
                return dict(self._data)

        external_mode = self._detect_external_mode() if detect_external else None
        external_simulation = (
            self._detect_external_simulation()
            if detect_external and self._deployment_target == "simulation"
            else False
        )
        with self._lock:
            if (
                detect_external
                and self._deployment_target == "simulation"
                and self._simulation_process is None
            ):
                if external_simulation:
                    self._data.update(
                        simulation_state="external",
                        simulation_managed=False,
                        simulation_pid=None,
                    )
                elif self._data["simulation_state"] == "external":
                    self._data.update(
                        simulation_state="stopped",
                        simulation_managed=False,
                        simulation_pid=None,
                    )
            if self._process is None and external_mode is not None:
                return self._update_locked(
                    mode=external_mode,
                    state="external",
                    managed=False,
                    pid=None,
                    message=(
                        "터미널에서 실행된 ROS 모드를 감지했습니다. "
                        "WebUI는 이 프로세스를 강제로 종료하지 않습니다."
                    ),
                )
            if (
                self._process is None
                and self._data["state"] == "external"
                and external_mode is None
            ):
                return self._update_locked(
                    mode="idle",
                    state="stopped",
                    managed=False,
                    pid=None,
                    message="선택된 로봇 운용 모드가 없습니다.",
                )
            self._data["map_available"] = self._map_files_available()
            self._data["updated_at"] = utc_now()
            return dict(self._data)

    def _launch_arguments(
        self,
        mode: str,
        *,
        mapping_profile: str | None = None,
        rtabmap_database_path: Path | None = None,
        thermal_map_config: dict[str, Any] | None = None,
    ) -> list[str]:
        selected_profile = mapping_profile or self._mapping_profile
        database_path = rtabmap_database_path or self._rtabmap_database_path
        if self._deployment_target == "physical":
            if mode == "mapping":
                enable_rtabmap = selected_profile == "toolbox_rtabmap"
                return [
                    "ros2",
                    "launch",
                    "hazard_guard_simulation",
                    "physical_mapping.launch.py",
                    f"enable_rtabmap:={'true' if enable_rtabmap else 'false'}",
                    "database_path:="
                    + str(
                        database_path
                        or self._workspace
                        / "runtime"
                        / "maps"
                        / "physical_rtabmap.db"
                    ),
                ]
            initial_pose = self._localization_pose or {"x": 0.0, "y": 0.0, "yaw": 0.0}
            if mode == "rgbd_mapping":
                selected_database = (
                    database_path
                    or self._map_path.parent / RGBD_DATABASE_FILE
                )
                return [
                    "ros2",
                    "launch",
                    "hazard_guard_simulation",
                    "physical_rgbd_mapping.launch.py",
                    f"map:={self._map_path}",
                    f"initial_pose_x:={self._launch_value(initial_pose['x'])}",
                    f"initial_pose_y:={self._launch_value(initial_pose['y'])}",
                    f"initial_pose_yaw:={self._launch_value(initial_pose['yaw'])}",
                    f"rtabmap_database_path:={selected_database}",
                    "rtabmap_reset_database:=true",
                    f"rtabmap_storage_path:={selected_database.parent}",
                    "rgbd_cloud_stamp_mode:="
                    + os.getenv("HAZARD_GUARD_RGBD_STAMP_MODE", "offset"),
                    "rgbd_cloud_stamp_offset_sec:="
                    + os.getenv("HAZARD_GUARD_RGBD_STAMP_OFFSET_SEC", "0.0"),
                    # RGB-D mapping needs the HP60C camera, but it should not
                    # spend Jetson resources on YOLO inference. The patrol
                    # launch starts the camera independently when
                    # enable_rgbd_mapping=true.
                    *self._physical_patrol_feature_arguments(
                        person_safety_enabled=False,
                    ),
                ]
            frozen_thermal_arguments = ["enable_frozen_thermal_map:=false"]
            if thermal_map_config and thermal_map_config.get("enabled"):
                frozen_thermal_arguments = [
                    "enable_frozen_thermal_map:=true",
                    f"thermal_map_cloud_path:={thermal_map_config['cloud_path']}",
                    f"thermal_map_state_path:={thermal_map_config['state_path']}",
                    f"thermal_map_session_id:={thermal_map_config['session_id']}",
                ]
            return [
                "ros2",
                "launch",
                "hazard_guard_simulation",
                "physical_patrol.launch.py",
                "enable_thermal_pipeline:=true",
                f"map:={self._map_path}",
                f"initial_pose_x:={self._launch_value(initial_pose['x'])}",
                f"initial_pose_y:={self._launch_value(initial_pose['y'])}",
                f"initial_pose_yaw:={self._launch_value(initial_pose['yaw'])}",
                *frozen_thermal_arguments,
                *self._physical_patrol_feature_arguments(),
            ]

        common = [
            f"gui:={'true' if self._gui else 'false'}",
            f"simulation_mode:={self._simulation_mode}",
            "start_simulation:=false",
            "enable_hazard_approval:="
            + (
                "true"
                if env_flag("HAZARD_GUARD_HAZARD_APPROVAL_ENABLED")
                else "false"
            ),
            *self._world_launch_arguments(),
        ]
        spawn = self._active_world["spawn"]
        initial_pose = self._localization_pose or {
            "x": float(spawn["x"]),
            "y": float(spawn["y"]),
            "yaw": float(spawn["yaw"]),
        }
        if mode == "mapping":
            enable_rtabmap = selected_profile == "toolbox_rtabmap"
            return [
                "ros2",
                "launch",
                "hazard_guard_simulation",
                "slam.launch.py",
                *common,
                f"enable_rtabmap:={'true' if enable_rtabmap else 'false'}",
                "rtabmap_database_path:="
                + str(
                    database_path
                    or Path("/tmp/hazard_guard_rtabmap_sim.db")
                ),
            ]
        if mode == "rgbd_mapping":
            selected_database = (
                database_path or self._map_path.parent / RGBD_DATABASE_FILE
            )
            return [
                "ros2",
                "launch",
                "hazard_guard_simulation",
                "rgbd_mapping.launch.py",
                *common,
                f"map:={self._map_path}",
                f"initial_pose_x:={self._launch_value(initial_pose['x'])}",
                f"initial_pose_y:={self._launch_value(initial_pose['y'])}",
                f"initial_pose_yaw:={self._launch_value(initial_pose['yaw'])}",
                f"rtabmap_database_path:={selected_database}",
                "rtabmap_reset_database:=true",
            ]
        return [
            "ros2",
            "launch",
            "hazard_guard_simulation",
            "localization.launch.py",
            *common,
            f"slam:={'true' if self._patrol_slam else 'false'}",
            # SLAM Toolbox owns map->odom in that case; there is no AMCL to seed.
            f"auto_initial_pose:={'false' if self._patrol_slam else 'true'}",
            f"map:={self._map_path}",
            f"initial_pose_x:={self._launch_value(initial_pose['x'])}",
            f"initial_pose_y:={self._launch_value(initial_pose['y'])}",
            f"initial_pose_yaw:={self._launch_value(initial_pose['yaw'])}",
        ]

    @staticmethod
    def _physical_patrol_feature_arguments(
        *,
        person_safety_enabled: bool | None = None,
    ) -> list[str]:
        """Translate deployment settings into the physical patrol contract."""

        # Physical deployments enable person safety by default, but test runs
        # must be able to disable the complete YOLO safety path explicitly.
        # Callers such as RGB-D mapping still take precedence over the runtime
        # default while keeping the camera available when requested.
        safety_enabled = (
            env_flag("HAZARD_GUARD_PERSON_SAFETY_ENABLED", True)
            if person_safety_enabled is None
            else person_safety_enabled
        )
        values = {
            "use_person_safety": (
                "true" if safety_enabled else "false"
            ),
            "enable_hazard_approval": (
                "true"
                if env_flag("HAZARD_GUARD_HAZARD_APPROVAL_ENABLED")
                else "false"
            ),
            "start_person_camera": (
                "true"
                if env_flag("HAZARD_GUARD_PERSON_CAMERA_START", True)
                else "false"
            ),
            "person_model_path": os.getenv(
                "HAZARD_GUARD_PERSON_MODEL_PATH", "yolo11n.pt"
            ),
            "person_device": os.getenv("HAZARD_GUARD_PERSON_DEVICE", "0"),
            "person_confidence": os.getenv(
                "HAZARD_GUARD_PERSON_CONFIDENCE", "0.4"
            ),
            "person_image_size": os.getenv(
                "HAZARD_GUARD_PERSON_IMAGE_SIZE", "640"
            ),
            "person_inference_rate_hz": os.getenv(
                "HAZARD_GUARD_PERSON_RATE_HZ", "6.0"
            ),
            "person_depth_registration_verified": (
                "true"
                if env_flag("HAZARD_GUARD_PERSON_DEPTH_REGISTERED")
                else "false"
            ),
            "enable_thermal_pipeline": (
                "true"
                if env_flag("HAZARD_GUARD_THERMAL_PIPELINE_ENABLED")
                else "false"
            ),
            "thermal_roi_config": os.getenv(
                "HAZARD_GUARD_THERMAL_ROI_CONFIG", ""
            ),
            "thermal_baseline_path": os.getenv(
                "HAZARD_GUARD_THERMAL_BASELINE_PATH", ""
            ),
            "thermal_history_path": os.getenv(
                "HAZARD_GUARD_THERMAL_HISTORY_PATH",
                "~/.local/share/hazard_guard/thermal_history.jsonl",
            ),
            "thermal_air_temperature_topic": os.getenv(
                "HAZARD_GUARD_THERMAL_AIR_TOPIC", ""
            ),
            "thermal_oil_temperature_topic": os.getenv(
                "HAZARD_GUARD_THERMAL_OIL_TOPIC", ""
            ),
            "thermal_sensor_timeout_sec": os.getenv(
                "HAZARD_GUARD_THERMAL_SENSOR_TIMEOUT_SEC", "5.0"
            ),
            "thermal_image_topic": os.getenv(
                "HAZARD_GUARD_THERMAL_TOPIC", "/thermal_camera/image_raw"
            ),
            "thermal_info_topic": os.getenv(
                "HAZARD_GUARD_THERMAL_INFO_TOPIC",
                "/thermal_camera/camera_info",
            ),
            "thermal_depth_image_topic": os.getenv(
                "HAZARD_GUARD_DEPTH_TOPIC", "/depth_camera/image_raw"
            ),
            "thermal_depth_info_topic": os.getenv(
                "HAZARD_GUARD_DEPTH_INFO_TOPIC",
                "/depth_camera/camera_info",
            ),
            "thermal_scale": os.getenv("HAZARD_GUARD_THERMAL_SCALE", "1.0"),
            "thermal_offset_c": os.getenv(
                "HAZARD_GUARD_THERMAL_OFFSET_C", "0.0"
            ),
        }
        return [f"{name}:={value}" for name, value in values.items()]

    def _simulation_launch_arguments(self) -> list[str]:
        return [
            "ros2",
            "launch",
            "hazard_guard_simulation",
            "simulation.launch.py",
            f"gui:={'true' if self._gui else 'false'}",
            f"simulation_mode:={self._simulation_mode}",
            "use_thermal_pipeline:=true",
            *self._world_launch_arguments(),
        ]

    def _detect_external_simulation(self) -> bool:
        if not self._enabled or self._deployment_target != "simulation":
            return False
        nodes = self._process_controller.ros_nodes()
        return any(node.endswith("/hazard_guard_gz_bridge") for node in nodes)

    def _terminate_process_group(
        self,
        process: subprocess.Popen[Any],
        *,
        process_group_id: int,
    ) -> None:
        del process_group_id
        self._process_controller.terminate_group(process)

    def _cleanup_orphaned_simulators(self) -> None:
        self._process_controller.cleanup_orphaned_simulators()

    def _monitor_simulation(
        self,
        process: subprocess.Popen[Any],
        generation: int,
    ) -> None:
        exit_code = process.wait()
        with self._lock:
            if (
                self._simulation_generation != generation
                or self._simulation_process is not process
            ):
                return
        self._terminate_process_group(
            process,
            process_group_id=process.pid,
        )
        with self._lock:
            if (
                self._simulation_generation != generation
                or self._simulation_process is not process
            ):
                return
            self._simulation_process = None
            self._update_locked(
                simulation_state="stopped" if exit_code == 0 else "failed",
                simulation_managed=False,
                simulation_pid=None,
            )

    def _ensure_simulation(self) -> bool:
        with self._lock:
            process = self._simulation_process
            if process is not None and process.poll() is None:
                self._update_locked(
                    simulation_state="running",
                    simulation_managed=True,
                    simulation_pid=process.pid,
                )
                return True

        if self._detect_external_simulation():
            with self._lock:
                self._update_locked(
                    simulation_state="external",
                    simulation_managed=False,
                    simulation_pid=None,
                )
            return True

        self._cleanup_orphaned_simulators()
        command = self._simulation_launch_arguments()
        try:
            process = self._process_controller.start_logged(
                command,
                self._simulation_log_path,
            )
        except OSError:
            with self._lock:
                self._update_locked(
                    simulation_state="failed",
                    simulation_managed=False,
                    simulation_pid=None,
                )
            return False
        with self._lock:
            self._simulation_generation += 1
            generation = self._simulation_generation
            self._simulation_process = process
            self._update_locked(
                simulation_state="starting",
                simulation_managed=True,
                simulation_pid=process.pid,
            )
        threading.Thread(
            target=self._monitor_simulation,
            args=(process, generation),
            name="hazard-guard-simulation-monitor",
            daemon=True,
        ).start()
        time.sleep(1)
        if process.poll() is not None:
            return False
        with self._lock:
            self._update_locked(simulation_state="running")
        return True

    def _ensure_runtime_environment(self) -> bool:
        if self._deployment_target == "physical":
            with self._lock:
                self._update_locked(
                    simulation_state="not_applicable",
                    simulation_managed=False,
                    simulation_pid=None,
                )
            return True
        return self._ensure_simulation()

    def _last_log_line(self) -> str | None:
        return self._process_controller.last_log_line(self._log_path)

    def _monitor(self, process: subprocess.Popen[Any], mode: str, generation: int) -> None:
        time.sleep(2)
        with self._lock:
            if self._generation != generation or self._process is not process:
                return
            if process.poll() is None:
                self._update_locked(
                    state="running",
                    message=(
                        "SLAM 지도 생성 모드가 실행 중입니다."
                        if mode == "mapping"
                        else (
                            "저장 2D 지도 기반 RGB-D 3D 수집 모드가 실행 중입니다."
                            if mode == "rgbd_mapping"
                            else "AMCL·Nav2 순찰 모드가 실행 중입니다."
                        )
                    ),
                )
        exit_code = process.wait()
        with self._lock:
            if self._generation != generation or self._process is not process:
                return
        self._terminate_process_group(
            process,
            process_group_id=process.pid,
        )
        if mode == "rgbd_mapping":
            self._finalize_rgbd_session()
        elif mode == "patrol":
            self._finalize_thermal_map_session()
        with self._lock:
            if self._generation != generation or self._process is not process:
                return
            self._process = None
            failure_detail = self._last_log_line() if exit_code != 0 else None
            self._update_locked(
                state="stopped" if exit_code == 0 else "failed",
                managed=False,
                pid=None,
                exit_code=exit_code,
                message=(
                    "ROS 운용 모드가 종료되었습니다."
                    if exit_code == 0
                    else (
                        f"ROS 운용 모드가 오류 코드 {exit_code}로 종료되었습니다."
                        + (f" {failure_detail}" if failure_detail else "")
                    )
                ),
            )

    def save_map(self) -> dict[str, Any]:
        if not self._enabled:
            return {
                **self.snapshot(detect_external=False),
                "accepted": False,
                "message": "WebUI 모드 제어가 비활성화되어 지도를 저장할 수 없습니다.",
            }
        with self._lock:
            map_source_running = self._data.get("mode") == "mapping" or (
                self._data.get("mode") == "patrol" and self._patrol_slam
            )
        if not map_source_running:
            return {
                **self.snapshot(detect_external=False),
                "accepted": False,
                "message": (
                    "2D SLAM 지도 작성 중일 때만 map.yaml을 저장할 수 있습니다. "
                    "3D 수집은 전용 종료 버튼으로 RTAB-Map DB를 저장하세요."
                ),
            }
        if self._current_session_id is None:
            session = self._world_catalog.begin_session(
                self._active_world["id"], self._mapping_profile
            )
            self._current_session_id = session["id"]
            self._map_path = session["map_path"]
            self._rtabmap_database_path = session["rtabmap_database_path"]
        self._map_path.parent.mkdir(parents=True, exist_ok=True)
        map_base = self._map_path.with_suffix("")
        try:
            result = self._process_controller.run(
                [
                    "ros2",
                    "run",
                    "nav2_map_server",
                    "map_saver_cli",
                    "-t",
                    "map",
                    "-f",
                    str(map_base),
                    "--ros-args",
                    "-p",
                    "save_map_timeout:=10.0",
                ],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            with self._lock:
                return self._update_locked(
                    accepted=False,
                    message=f"지도 저장 명령을 실행하지 못했습니다: {exc}",
                )
        accepted = result.returncode == 0 and self._map_files_available()
        rtabmap_available = bool(
            self._mapping_profile == "toolbox_rtabmap"
            and self._rtabmap_database_path is not None
            and self._rtabmap_database_path.is_file()
            and self._rtabmap_database_path.stat().st_size > 0
        )
        if self._current_session_id is not None:
            self._world_catalog.update_session(
                self._current_session_id,
                self._active_world["id"],
                status="saved" if accepted else "save_failed",
                mapping_profile=self._mapping_profile,
                rtabmap_available=rtabmap_available,
                rtabmap_database_bytes=(
                    self._rtabmap_database_path.stat().st_size
                    if rtabmap_available and self._rtabmap_database_path is not None
                    else 0
                ),
                localization_pose=self._localization_pose,
            )
            if accepted:
                self._map_path = self._world_catalog.activate_session(
                    self._active_world["id"], self._current_session_id
                )
        detail = (result.stderr or result.stdout).strip().splitlines()
        message = (
            (
                f"순찰용 지도를 세션 {self._current_session_id}에 저장했습니다. "
                f"저장 위치: {self._map_path.parent}"
            )
            if accepted
            else (
                "지도를 저장하지 못했습니다."
                + (f" {detail[-1]}" if detail else "")
            )
        )
        with self._lock:
            return self._update_locked(
                accepted=accepted,
                rtabmap_available=rtabmap_available,
                message=message,
            )

    def save_map_and_stop(self) -> dict[str, Any]:
        saved = self.save_map()
        if not saved.get("accepted"):
            return saved
        stopped = self.stop()
        return {
            **stopped,
            "accepted": True,
            "map_available": True,
            "rtabmap_available": saved.get("rtabmap_available", False),
            "message": (
                "현재 지도 세션을 저장하고 실물 로봇 SLAM을 종료했습니다."
                if self._deployment_target == "physical"
                else "현재 지도 세션을 저장하고 SLAM·Gazebo를 종료했습니다."
            ),
        }

    def _stop_managed_process(self) -> None:
        with self._lock:
            process = self._process
            if process is None:
                return
            self._generation += 1
            if self._data.get("mode") == "rgbd_mapping":
                self._rgbd_finalize_pending_id = self._rgbd_session_id
            self._update_locked(state="stopping", message="현재 ROS 모드를 종료하고 있습니다.")
        self._terminate_process_group(
            process,
            process_group_id=process.pid,
        )
        with self._lock:
            if self._process is process:
                self._process = None
            # ROS graph discovery can retain nodes briefly after a clean
            # shutdown. Do not mislabel those stale entries as a terminal-run
            # external stack.
            self._ignore_external_until = time.monotonic() + 10.0

    def switch_mode(
        self,
        mode: str,
        mapping_profile: str | None = None,
        patrol_slam: bool = False,
    ) -> dict[str, Any]:
        # One transition guard covers DB export decisions and ROS launch. This
        # prevents a new RGB-D writer from starting between an export-lock
        # probe and the actual launch.
        with self._cloud_export_lock:
            return self._switch_mode(
                mode,
                mapping_profile=mapping_profile,
                patrol_slam=patrol_slam,
            )

    def _switch_mode(
        self,
        mode: str,
        mapping_profile: str | None = None,
        patrol_slam: bool = False,
    ) -> dict[str, Any]:
        if mode not in self.MODES:
            raise ValueError(f"Unsupported mode: {mode}")
        requested_profile = mapping_profile or self._mapping_profile
        if requested_profile not in self.MAPPING_PROFILES:
            raise ValueError(f"Unsupported mapping profile: {requested_profile}")
        keep_mapping = bool(patrol_slam) and mode == "patrol"
        if keep_mapping and self._deployment_target == "physical":
            return {
                **self.snapshot(detect_external=False),
                "accepted": False,
                "message": (
                    "실물 로봇 순찰에서는 지도 갱신 옵션을 지원하지 않습니다. "
                    "맵 생성 모드에서 지도를 작성하세요."
                ),
            }
        if not self._enabled:
            return {
                **self.snapshot(detect_external=False),
                "accepted": False,
                "message": (
                    "WebUI 모드 제어가 비활성화되어 있습니다. "
                    "백엔드 환경 변수 HAZARD_GUARD_MODE_CONTROL_ENABLED=1이 필요합니다."
                ),
            }

        with self._lock:
            current_process = self._process
            current_mode = self._data["mode"]
            current_state = self._data["state"]
        if (
            current_process is not None
            and current_process.poll() is None
            and current_mode == mode
            and current_state in {"starting", "running"}
            and (mode != "mapping" or self._mapping_profile == requested_profile)
            and (mode != "patrol" or self._patrol_slam == keep_mapping)
        ):
            runtime_ready = self._ensure_runtime_environment()
            with self._lock:
                return self._update_locked(
                    accepted=runtime_ready,
                    state=current_state if runtime_ready else "failed",
                    message="이미 선택한 운용 모드가 실행 중입니다.",
                )

        if current_process is None:
            external_mode = self._detect_external_mode()
            if external_mode is not None:
                with self._lock:
                    return self._update_locked(
                        mode=external_mode,
                        state="external",
                        accepted=external_mode == mode,
                        managed=False,
                        message=(
                            "선택한 모드가 터미널에서 이미 실행 중입니다."
                            if external_mode == mode
                            else (
                                "다른 ROS 모드가 터미널에서 실행 중입니다. "
                                "해당 launch를 종료한 뒤 다시 전환하세요."
                            )
                        ),
                    )

        # Anything that was building a map loses it on shutdown, so store it
        # before the switch - that includes a patrol that was mapping.
        if (
            current_process is not None
            and (
                (mode in {"patrol", "rgbd_mapping"} and current_mode == "mapping")
                or (current_mode == "patrol" and self._patrol_slam)
            )
        ):
            saved = self.save_map()
            if not saved["accepted"]:
                return saved

        self._stop_managed_process()
        if current_mode == "rgbd_mapping":
            self._finalize_rgbd_session()
        elif current_mode == "patrol":
            self._finalize_thermal_map_session()

        if (
            mode in {"patrol", "rgbd_mapping"}
            and not keep_mapping
            and not self._map_files_available()
        ):
            with self._lock:
                return self._update_locked(
                    mode="idle",
                    state="failed",
                    accepted=False,
                    managed=False,
                    pid=None,
                    message=(
                        "저장 지도 기반 모드에 사용할 2D 지도가 없습니다. "
                        "먼저 맵 생성 모드에서 지도를 작성하고 저장하세요."
                    ),
                )

        if not self._ensure_runtime_environment():
            with self._lock:
                return self._update_locked(
                    mode="idle",
                    state="failed",
                    accepted=False,
                    managed=False,
                    pid=None,
                    message="운용 환경을 준비하지 못했습니다. "
                    + (
                        f"{self._simulation_log_path} 로그를 확인하세요."
                        if self._deployment_target == "simulation"
                        else f"{self._log_path} 로그와 실물 센서 연결을 확인하세요."
                    ),
                )

        pending_session: dict[str, Any] | None = None
        rgbd_session: dict[str, Any] | None = None
        rgbd_database_path: Path | None = None
        if mode == "mapping":
            pending_session = self._world_catalog.begin_session(
                self._active_world["id"], requested_profile
            )
        elif keep_mapping:
            # A patrol that keeps mapping writes into its own session, so
            # saving it does not overwrite the map it was started from. 2D
            # only - RTAB-Map is not part of this launch.
            requested_profile = "toolbox"
            pending_session = self._world_catalog.begin_session(
                self._active_world["id"], requested_profile
            )
        elif mode == "rgbd_mapping":
            rgbd_session = self._active_map_session()
            if rgbd_session is None:
                with self._lock:
                    return self._update_locked(
                        mode="idle",
                        state="failed",
                        accepted=False,
                        managed=False,
                        pid=None,
                        message=(
                            "3D 수집을 연결할 저장 2D 지도 세션이 없습니다. "
                            "지도 파일에서 사용할 세션을 먼저 지정하세요."
                        ),
                    )
            try:
                rgbd_database_path = self._prepare_rgbd_collection(
                    rgbd_session
                )
            except (KeyError, OSError) as exc:
                message = (
                    "기존 RGB-D 자료를 안전하게 보존하지 못해 새 3D 수집을 "
                    f"시작하지 않았습니다: {exc}"
                )
                self._world_catalog.update_session(
                    rgbd_session["id"],
                    self._active_world["id"],
                    rgbd_status="failed",
                    cloud_export_status="failed",
                    cloud_export_error=message,
                    thermal_map_status="failed",
                    thermal_map_error=message,
                )
                with self._lock:
                    return self._update_locked(
                        mode="idle",
                        state="failed",
                        accepted=False,
                        managed=False,
                        pid=None,
                        message=message,
                    )
        thermal_map_config: dict[str, Any] | None = None
        if mode == "patrol" and self._deployment_target == "physical":
            thermal_map_config = self._prepare_frozen_thermal_map()
        self._patrol_slam = keep_mapping
        command = self._launch_arguments(
            mode,
            mapping_profile=requested_profile,
            rtabmap_database_path=(
                pending_session["rtabmap_database_path"]
                if pending_session is not None
                else rgbd_database_path
            ),
            thermal_map_config=thermal_map_config,
        )
        try:
            process = self._process_controller.start_logged(
                command,
                self._log_path,
            )
        except OSError as exc:
            if pending_session is not None:
                self._world_catalog.discard_empty_session(
                    self._active_world["id"], pending_session["id"]
                )
            if rgbd_session is not None:
                message = f"RGB-D 3D 수집 launch를 시작하지 못했습니다: {exc}"
                self._world_catalog.update_session(
                    rgbd_session["id"],
                    self._active_world["id"],
                    rgbd_status="failed",
                    cloud_export_status="failed",
                    cloud_export_error=message,
                    thermal_map_status="failed",
                    thermal_map_error=message,
                )
            if thermal_map_config and thermal_map_config.get("enabled"):
                self._world_catalog.update_session(
                    str(thermal_map_config["session_id"]),
                    self._active_world["id"],
                    thermal_map_status="launch_failed",
                    thermal_map_error=str(exc),
                )
            with self._lock:
                failed = self._update_locked(
                    mode="idle",
                    state="failed",
                    accepted=False,
                    managed=False,
                    pid=None,
                    message=f"ROS launch를 시작하지 못했습니다: {exc}",
                )
                return {
                    **failed,
                    "thermal_cache_reset_required": bool(
                        thermal_map_config
                        and thermal_map_config.get("geometry_refreshed")
                    ),
                }
        if rgbd_session is not None:
            self._world_catalog.update_session(
                rgbd_session["id"],
                self._active_world["id"],
                rtabmap_database_file=rgbd_database_path.name,
                rgbd_database_file=rgbd_database_path.name,
                rgbd_status="collecting",
                rgbd_workflow=self.RGBD_WORKFLOW,
                cloud_frame_id="map",
                cloud_voxel_size_m=0.03,
                rgbd_started_at=utc_now(),
                rgbd_finished_at=None,
                cloud_export_status="stale",
                cloud_export_error=None,
                thermal_map_status="waiting_for_cloud",
                thermal_map_error=None,
                thermal_layer_status="stale",
            )
        if thermal_map_config and thermal_map_config.get("enabled"):
            self._world_catalog.update_session(
                str(thermal_map_config["session_id"]),
                self._active_world["id"],
                thermal_layer_file=Path(
                    thermal_map_config["state_path"]
                ).name,
                thermal_layer_status="active",
                thermal_map_status="active",
                thermal_map_error=None,
                thermal_map_started_at=utc_now(),
            )
        with self._lock:
            if pending_session is not None:
                self._mapping_profile = requested_profile
                self._current_session_id = pending_session["id"]
                self._map_path = pending_session["map_path"]
                self._localization_pose = None
                self._rtabmap_database_path = pending_session[
                    "rtabmap_database_path"
                ]
            elif rgbd_session is not None:
                self._current_session_id = None
                self._active_map_session_id = rgbd_session["id"]
                self._rgbd_session_id = rgbd_session["id"]
                self._rtabmap_database_path = rgbd_database_path
            if mode == "patrol" and thermal_map_config is not None:
                self._thermal_map_session_id = thermal_map_config.get(
                    "session_id"
                )
                self._thermal_map_cloud_path = thermal_map_config.get(
                    "cloud_path"
                )
                self._thermal_map_state_path = thermal_map_config.get(
                    "state_path"
                )
            else:
                self._thermal_map_session_id = None
                self._thermal_map_cloud_path = None
                self._thermal_map_state_path = None
            self._generation += 1
            generation = self._generation
            self._process = process
            result = self._update_locked(
                mode=mode,
                state="starting",
                accepted=True,
                managed=True,
                pid=process.pid,
                exit_code=None,
                started_at=utc_now(),
                map_path=str(self._map_path),
                mapping_session_id=self._current_session_id,
                active_map_session_id=self._active_map_session_id,
                rgbd_session_id=self._rgbd_session_id,
                thermal_map_session_id=self._thermal_map_session_id,
                thermal_map_enabled=bool(
                    thermal_map_config and thermal_map_config.get("enabled")
                ),
                thermal_map_status=(
                    "active"
                    if thermal_map_config and thermal_map_config.get("enabled")
                    else (
                        "failed"
                        if thermal_map_config is not None
                        else "disabled"
                        if mode == "patrol"
                        and self._deployment_target == "physical"
                        else "not_applicable"
                    )
                ),
                thermal_map_message=(
                    thermal_map_config.get("message")
                    if thermal_map_config is not None
                    else None
                ),
                thermal_map_cloud_path=(
                    str(self._thermal_map_cloud_path)
                    if self._thermal_map_cloud_path is not None
                    else None
                ),
                thermal_map_state_path=(
                    str(self._thermal_map_state_path)
                    if self._thermal_map_state_path is not None
                    else None
                ),
                mapping_profile=self._mapping_profile,
                patrol_slam=self._patrol_slam,
                rtabmap_database_path=(
                    str(self._rtabmap_database_path)
                    if (
                        mode == "rgbd_mapping"
                        or (
                            mode == "mapping"
                            and self._mapping_profile == "toolbox_rtabmap"
                        )
                    )
                    else None
                ),
                message=(
                    "SLAM 지도 생성 모드를 시작하고 있습니다."
                    if mode == "mapping"
                    else (
                        "저장된 2D 지도를 불러와 RGB-D 3D 수집을 시작하고 있습니다."
                        if mode == "rgbd_mapping"
                        else (
                            "지도 갱신 순찰 모드(SLAM·Nav2)를 시작하고 있습니다. "
                            "WASD로 주행한 뒤 지도를 저장할 수 있습니다."
                            if keep_mapping
                            else "AMCL·Nav2 순찰 모드를 시작하고 있습니다."
                        )
                    )
                    + (
                        " 누적 열화상 지도는 비활성 상태입니다: "
                        + str(thermal_map_config.get("message"))
                        if mode == "patrol"
                        and thermal_map_config is not None
                        and not thermal_map_config.get("enabled")
                        else ""
                    )
                ),
            )
        threading.Thread(
            target=self._monitor,
            args=(process, mode, generation),
            name=f"hazard-guard-{mode}-monitor",
            daemon=True,
        ).start()
        return result

    def _stop_managed_simulation(self) -> None:
        with self._lock:
            process = self._simulation_process
            if process is None:
                return
            self._simulation_generation += 1
        self._terminate_process_group(
            process,
            process_group_id=process.pid,
        )
        with self._lock:
            if self._simulation_process is process:
                self._simulation_process = None
            self._update_locked(
                simulation_state="stopped",
                simulation_managed=False,
                simulation_pid=None,
            )

    def stop(self) -> dict[str, Any]:
        # A patrol transition can synchronously export the fixed PLY before it
        # owns a process. Waiting on the same guard prevents a Stop request
        # from returning early and then allowing that transition to launch.
        with self._cloud_export_lock:
            return self._stop()

    def _stop(self) -> dict[str, Any]:
        with self._lock:
            stopped_mode = self._data.get("mode")
        self._stop_managed_process()
        if stopped_mode == "rgbd_mapping":
            self._finalize_rgbd_session()
        elif stopped_mode == "patrol":
            self._finalize_thermal_map_session()
        if self._deployment_target == "simulation":
            self._stop_managed_simulation()
        with self._lock:
            self._patrol_slam = False
            return self._update_locked(
                patrol_slam=False,
                rgbd_session_id=None,
                mode="idle",
                state="disabled" if not self._enabled else "stopped",
                accepted=True,
                managed=False,
                pid=None,
                message="WebUI가 시작한 ROS 운용 모드를 종료했습니다.",
            )

    def _finalize_rgbd_session(self) -> None:
        with self._lock:
            session_id = self._rgbd_session_id
            database_path = self._rtabmap_database_path
            if session_id is not None:
                # Claim finalization before inspecting artifacts so monitor
                # and explicit stop callers cannot finalize twice.
                self._rgbd_session_id = None
                self._rgbd_finalize_pending_id = session_id
        if session_id is None or database_path is None:
            return
        paths = self._world_catalog.session_paths(
            self._active_world["id"], session_id
        )
        metadata = self._world_catalog.session_metadata(
            self._active_world["id"], session_id
        )
        provenance_valid = bool(
            database_path == paths["rgbd_database"]
            and database_path.name == RGBD_DATABASE_FILE
            and metadata.get("rtabmap_database_file") == RGBD_DATABASE_FILE
            and metadata.get("rgbd_database_file") == RGBD_DATABASE_FILE
            and metadata.get("rgbd_workflow") == self.RGBD_WORKFLOW
            and metadata.get("cloud_frame_id") == "map"
        )
        available = (
            database_path.is_file() and database_path.stat().st_size > 0
        )
        session_values: dict[str, Any] = {
            "rgbd_status": "saved" if available else "empty",
            "rgbd_finished_at": utc_now(),
            "rtabmap_available": available,
            "rtabmap_database_bytes": (
                database_path.stat().st_size if available else 0
            ),
        }
        if provenance_valid:
            session_values.update(
                rgbd_workflow=self.RGBD_WORKFLOW,
                cloud_frame_id="map",
                cloud_voxel_size_m=0.03,
            )
        self._world_catalog.update_session(
            session_id,
            self._active_world["id"],
            **session_values,
        )
        if available and provenance_valid:
            # Desktop/backend shutdown must not wait up to 180 seconds for
            # rtabmap-export. Patrol preparation or the manual cloud endpoint
            # performs this after the DB has been closed.
            thermal_status = "waiting_for_cloud"
            thermal_message = (
                "RGB-D DB를 저장했습니다. 다음 순찰 시작 시 고정 3D 지도를 "
                "내보내고 누적 열화상을 준비합니다."
            )
            self._world_catalog.update_session(
                session_id,
                self._active_world["id"],
                cloud_export_status="stale",
                cloud_export_error=None,
                thermal_map_status=thermal_status,
                thermal_map_error=None,
            )
        else:
            thermal_status = "failed"
            thermal_message = (
                "RGB-D 수집 DB가 전용 map 좌표계 DB 계약을 충족하지 않아 "
                "고정 3D 지도를 생성하지 않습니다. 3D 수집을 다시 실행하세요."
                if available
                else "RGB-D 수집 종료 후 사용할 RTAB-Map DB가 없어 "
                "고정 3D 지도를 생성하지 못했습니다."
            )
            self._world_catalog.update_session(
                session_id,
                self._active_world["id"],
                cloud_export_status="failed",
                cloud_export_error=thermal_message,
                thermal_map_status="failed",
                thermal_map_error=thermal_message,
            )
        with self._lock:
            self._thermal_map_session_id = session_id
            self._thermal_map_cloud_path = paths["cloud"]
            self._thermal_map_state_path = paths["thermal_layer"]
            self._data.update(
                rgbd_session_id=None,
                thermal_map_session_id=session_id,
                thermal_map_enabled=False,
                thermal_map_status=thermal_status,
                thermal_map_message=thermal_message,
                thermal_map_cloud_path=str(paths["cloud"]),
                thermal_map_state_path=str(paths["thermal_layer"]),
            )
            if self._rgbd_finalize_pending_id == session_id:
                self._rgbd_finalize_pending_id = None

    def _finalize_thermal_map_session(self) -> None:
        """Record updater persistence only after the patrol group has stopped."""

        with self._lock:
            enabled = bool(self._data.get("thermal_map_enabled"))
            session_id = self._thermal_map_session_id
            state_path = self._thermal_map_state_path
            if enabled:
                # Claim the flush once; no filesystem work happens under the
                # manager lock.
                self._data["thermal_map_enabled"] = False
        if not enabled or session_id is None or state_path is None:
            return
        state_available = state_path.is_file() and state_path.stat().st_size > 0
        node_status: dict[str, Any] = {}
        provider = self._thermal_status_provider
        if provider is not None:
            try:
                node_status = provider()
            except Exception:
                node_status = {}
        status_session_id = node_status.get("session_id")
        status_matches_session = bool(
            node_status.get("available")
            and status_session_id == session_id
        )
        expected_fingerprint = str(node_status.get("fingerprint") or "")
        state_metadata = self._thermal_state_metadata(state_path)
        state_fingerprint = state_metadata.get("fingerprint")
        state_error = str(node_status.get("state_error") or "")
        map_error = str(node_status.get("map_error") or "")
        persisted_at_ns = int(state_metadata.get("persisted_at_ns") or 0)
        maximum_last_seen_ns = int(
            state_metadata.get("maximum_last_seen_ns") or 0
        )
        persisted_at = (
            datetime.fromtimestamp(
                persisted_at_ns / 1_000_000_000,
                timezone.utc,
            ).isoformat()
            if persisted_at_ns > 0
            else None
        )
        persisted_after_observation = bool(
            persisted_at_ns > 0 and persisted_at_ns >= maximum_last_seen_ns
        )
        if map_error or state_error:
            status = "failed"
            message = map_error or state_error
        elif not state_available:
            status = "ready"
            message = (
                "저장된 누적 열화상 계층이 없어 고정 3D 지도만 "
                "준비된 상태입니다."
            )
        elif not status_matches_session:
            status = "persistence_unknown"
            message = (
                "열화상 상태 파일은 있지만 현재 세션의 노드 상태를 "
                "확인하지 못해 저장 완료로 표시하지 않습니다."
            )
        elif not expected_fingerprint or state_fingerprint != expected_fingerprint:
            status = "failed"
            message = (
                "열화상 상태 파일의 3D 지도 fingerprint가 현재 고정 지도와 "
                "일치하지 않습니다."
            )
        elif not persisted_after_observation:
            status = "persistence_unknown"
            message = (
                "마지막 열화상 관측이 상태 파일에 저장됐는지 확인하지 못해 "
                "저장 완료로 표시하지 않습니다."
            )
        else:
            status = "saved"
            message = "누적 열화상 계층을 세션에 저장했습니다."
        self._world_catalog.update_session(
            session_id,
            self._active_world["id"],
            thermal_map_status=status,
            thermal_map_error=(message if status == "failed" else None),
            thermal_map_finished_at=utc_now(),
            thermal_layer_persisted_at=persisted_at,
            thermal_layer_status=status,
            thermal_layer_fingerprint=state_fingerprint,
            thermal_layer_bytes=(
                state_path.stat().st_size if state_available else 0
            ),
        )
        with self._lock:
            self._data.update(
                thermal_map_enabled=False,
                thermal_map_status=status,
                thermal_map_message=message,
            )

    @staticmethod
    def _thermal_state_metadata(path: Path) -> dict[str, Any]:
        if not path.is_file():
            return {}
        try:
            import numpy as np

            with np.load(path, allow_pickle=False) as state:
                if "geometry_fingerprint" not in state.files:
                    return {}
                last_seen = (
                    np.asarray(state["last_seen_ns"], dtype=np.int64)
                    if "last_seen_ns" in state.files
                    else np.asarray([], dtype=np.int64)
                )
                return {
                    "fingerprint": str(
                        np.asarray(state["geometry_fingerprint"]).item()
                    ),
                    "persisted_at_ns": (
                        int(np.asarray(state["persisted_at_ns"]).item())
                        if "persisted_at_ns" in state.files
                        else 0
                    ),
                    "maximum_last_seen_ns": (
                        int(last_seen.max()) if last_seen.size else 0
                    ),
                }
        except Exception:
            return {}


system_mode_manager = SystemModeManager()
