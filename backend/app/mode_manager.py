from __future__ import annotations

import os
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .process_control import ProcessController


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SystemModeManager:
    """Own the ROS launch process selected by the WebUI.

    This is a local-development supervisor. It only stops process groups that it
    started itself; terminal-launched ROS stacks are detected and left untouched.
    """

    MODES = {"mapping", "patrol"}

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._process: subprocess.Popen[Any] | None = None
        self._simulation_process: subprocess.Popen[Any] | None = None
        self._generation = 0
        self._simulation_generation = 0
        self._ignore_external_until = 0.0
        self._enabled = os.getenv("HAZARD_GUARD_MODE_CONTROL_ENABLED", "0") == "1"
        self._workspace = Path(
            os.getenv("HAZARD_GUARD_WORKSPACE", os.getcwd())
        ).expanduser().resolve()
        configured_map = Path(
            os.getenv("HAZARD_GUARD_MAP_PATH", "runtime/maps/facility.yaml")
        ).expanduser()
        self._map_path = (
            configured_map
            if configured_map.is_absolute()
            else (self._workspace / configured_map).resolve()
        )
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
        self._simulation_world_marker = os.getenv(
            "HAZARD_GUARD_SIMULATION_WORLD_MARKER", "facility_map.sdf"
        )
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
            "pid": None,
            "map_path": str(self._map_path),
            "log_path": str(self._log_path),
            "simulation_log_path": str(self._simulation_log_path),
            "simulation_state": "stopped",
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

    def _map_files_available(self) -> bool:
        if not self._map_path.is_file():
            return False
        try:
            for line in self._map_path.read_text(encoding="utf-8").splitlines():
                if not line.lstrip().startswith("image:"):
                    continue
                image_value = line.split(":", 1)[1].strip().strip("'\"")
                if not image_value:
                    return False
                image_path = Path(image_value).expanduser()
                if not image_path.is_absolute():
                    image_path = self._map_path.parent / image_path
                return image_path.is_file()
        except OSError:
            return False
        return False

    def _update_locked(self, **values: Any) -> dict[str, Any]:
        self._data.update(values)
        self._data["map_available"] = self._map_files_available()
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
                    self._process = None
                    self._update_locked(
                        state="stopped" if exit_code == 0 else "failed",
                        managed=False,
                        pid=None,
                        exit_code=exit_code,
                        message=(
                            "ROS 운용 모드가 종료되었습니다."
                            if exit_code == 0
                            else f"ROS 운용 모드가 오류 코드 {exit_code}로 종료되었습니다."
                        ),
                    )
                return dict(self._data)

        external_mode = self._detect_external_mode() if detect_external else None
        with self._lock:
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

    def _launch_arguments(self, mode: str) -> list[str]:
        common = [
            f"gui:={'true' if self._gui else 'false'}",
            f"simulation_mode:={self._simulation_mode}",
            "start_simulation:=false",
        ]
        if mode == "mapping":
            return [
                "ros2",
                "launch",
                "hazard_guard_simulation",
                "slam.launch.py",
                *common,
            ]
        return [
            "ros2",
            "launch",
            "hazard_guard_simulation",
            "localization.launch.py",
            *common,
            f"map:={self._map_path}",
        ]

    def _simulation_launch_arguments(self) -> list[str]:
        return [
            "ros2",
            "launch",
            "hazard_guard_simulation",
            "simulation.launch.py",
            f"gui:={'true' if self._gui else 'false'}",
            f"simulation_mode:={self._simulation_mode}",
        ]

    def _detect_external_simulation(self) -> bool:
        if not self._enabled:
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
                        else "AMCL·Nav2 순찰 모드가 실행 중입니다."
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
        detail = (result.stderr or result.stdout).strip().splitlines()
        message = (
            f"순찰용 지도를 저장했습니다: {self._map_path.name}"
            if accepted
            else (
                "지도를 저장하지 못했습니다."
                + (f" {detail[-1]}" if detail else "")
            )
        )
        with self._lock:
            return self._update_locked(accepted=accepted, message=message)

    def _stop_managed_process(self) -> None:
        with self._lock:
            process = self._process
            if process is None:
                return
            self._generation += 1
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

    def switch_mode(self, mode: str) -> dict[str, Any]:
        if mode not in self.MODES:
            raise ValueError(f"Unsupported mode: {mode}")
        if not self._enabled:
            return {
                **self.snapshot(detect_external=False),
                "accepted": False,
                "message": (
                    "WebUI 모드 제어가 비활성화되어 있습니다. "
                    "Docker 환경 변수 HAZARD_GUARD_MODE_CONTROL_ENABLED=1이 필요합니다."
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
        ):
            simulation_ready = self._ensure_simulation()
            with self._lock:
                return self._update_locked(
                    accepted=simulation_ready,
                    state=current_state if simulation_ready else "failed",
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

        if mode == "patrol" and current_mode == "mapping" and current_process is not None:
            saved = self.save_map()
            if not saved["accepted"]:
                return saved

        self._stop_managed_process()

        if mode == "patrol" and not self._map_files_available():
            with self._lock:
                return self._update_locked(
                    mode="idle",
                    state="failed",
                    accepted=False,
                    managed=False,
                    pid=None,
                    message=(
                        "순찰 모드에 사용할 저장 지도가 없습니다. "
                        "먼저 맵 생성 모드에서 지도를 작성하고 저장하세요."
                    ),
                )

        if not self._ensure_simulation():
            with self._lock:
                return self._update_locked(
                    mode="idle",
                    state="failed",
                    accepted=False,
                    managed=False,
                    pid=None,
                    message=(
                        "Gazebo 시뮬레이터를 시작하지 못했습니다. "
                        f"{self._simulation_log_path} 로그를 확인하세요."
                    ),
                )

        command = self._launch_arguments(mode)
        try:
            process = self._process_controller.start_logged(
                command,
                self._log_path,
            )
        except OSError as exc:
            with self._lock:
                return self._update_locked(
                    mode="idle",
                    state="failed",
                    accepted=False,
                    managed=False,
                    pid=None,
                    message=f"ROS launch를 시작하지 못했습니다: {exc}",
                )
        with self._lock:
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
                message=(
                    "SLAM 지도 생성 모드를 시작하고 있습니다."
                    if mode == "mapping"
                    else "AMCL·Nav2 순찰 모드를 시작하고 있습니다."
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
        self._stop_managed_process()
        self._stop_managed_simulation()
        with self._lock:
            return self._update_locked(
                mode="idle",
                state="disabled" if not self._enabled else "stopped",
                accepted=True,
                managed=False,
                pid=None,
                message="WebUI가 시작한 ROS 운용 모드를 종료했습니다.",
            )


system_mode_manager = SystemModeManager()
