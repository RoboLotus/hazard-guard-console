from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any


class ProcessController:
    """Own low-level process discovery, launch, logging, and termination."""

    def __init__(self, workspace: Path, simulator_world_marker: str) -> None:
        self.workspace = workspace
        self.simulator_world_marker = simulator_world_marker

    def ros_nodes(self) -> set[str]:
        try:
            result = self.run(
                ["ros2", "node", "list"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return set()
        return set(result.stdout.splitlines())

    def run(self, command: list[str], **options: Any) -> subprocess.CompletedProcess[Any]:
        return subprocess.run(
            command,
            cwd=self.workspace,
            **options,
        )

    def start_logged(
        self,
        command: list[str],
        log_path: Path,
    ) -> subprocess.Popen[Any]:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_file = log_path.open("w", encoding="utf-8")
        options: dict[str, Any] = {
            "cwd": self.workspace,
            "start_new_session": os.name == "posix",
            "stdout": log_file,
            "stderr": subprocess.STDOUT,
        }
        if os.name == "nt":
            options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        try:
            return subprocess.Popen(command, **options)
        finally:
            log_file.close()

    def terminate_group(self, process: subprocess.Popen[Any]) -> None:
        if os.name != "posix":
            self._terminate_windows_process(process)
            return

        process_group_id = process.pid

        def process_group_exists() -> bool:
            process.poll()
            return self._process_group_exists(process_group_id)

        for stop_signal, timeout in (
            (signal.SIGINT, 8.0),
            (signal.SIGTERM, 3.0),
            (signal.SIGKILL, 2.0),
        ):
            if not process_group_exists():
                break
            try:
                os.killpg(process_group_id, stop_signal)
            except ProcessLookupError:
                break
            self._wait_while(process_group_exists, timeout=timeout)
        if process.poll() is None:
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass

    def cleanup_orphaned_simulators(self) -> None:
        process_ids = self._find_simulator_process_ids()
        if not process_ids:
            return
        for stop_signal, timeout in (
            (signal.SIGINT, 4.0),
            (signal.SIGTERM, 2.0),
            (signal.SIGKILL, 1.0),
        ):
            alive = [pid for pid in process_ids if self._pid_exists(pid)]
            if not alive:
                return
            for pid in alive:
                try:
                    os.kill(pid, stop_signal)
                except ProcessLookupError:
                    pass
            self._wait_while(
                lambda: any(self._pid_exists(pid) for pid in process_ids),
                timeout=timeout,
            )

    @staticmethod
    def last_log_line(log_path: Path) -> str | None:
        try:
            lines = [
                line.strip()
                for line in log_path.read_text(
                    encoding="utf-8",
                    errors="replace",
                ).splitlines()
                if line.strip()
            ]
        except OSError:
            return None
        for line in reversed(lines):
            if "[ERROR]" in line or "Error" in line or "Exception" in line:
                return line[-240:]
        return lines[-1][-240:] if lines else None

    def _find_simulator_process_ids(self) -> list[int]:
        if os.name != "posix":
            return []
        try:
            result = subprocess.run(
                ["ps", "-eo", "pid=,args="],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return []
        process_ids: list[int] = []
        for line in result.stdout.splitlines():
            pid_text, separator, command = line.strip().partition(" ")
            if not separator or not pid_text.isdigit():
                continue
            if (
                "ign gazebo" in command
                and self.simulator_world_marker in command
            ):
                process_ids.append(int(pid_text))
        return process_ids

    @staticmethod
    def _terminate_windows_process(process: subprocess.Popen[Any]) -> None:
        if process.poll() is not None:
            return
        process.send_signal(signal.CTRL_BREAK_EVENT)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)

    @staticmethod
    def _pid_exists(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    @staticmethod
    def _process_group_exists(process_group_id: int) -> bool:
        try:
            os.killpg(process_group_id, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    @staticmethod
    def _wait_while(
        predicate: Any,
        *,
        timeout: float,
        interval: float = 0.1,
    ) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not predicate():
                return True
            time.sleep(interval)
        return not predicate()
