from __future__ import annotations

import json
import re
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


WORLD_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
SESSION_ID_PATTERN = WORLD_ID_PATTERN


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class WorldCatalog:
    """Discover repository-owned Gazebo worlds and keep map-session state."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()
        candidates = [
            self.workspace / "src" / "hazard_guard_simulation",
            self.workspace.parent / "Robot" / "src" / "hazard_guard_simulation",
            self.workspace.parent.parent / "Robot" / "src" / "hazard_guard_simulation",
        ]
        self.simulation_root = next(
            (candidate.resolve() for candidate in candidates if candidate.is_dir()),
            candidates[0].resolve(),
        )
        self.world_dir = (self.simulation_root / "worlds").resolve()
        self.metadata_path = self.world_dir / "world_catalog.json"
        self.map_root = (self.workspace / "runtime" / "maps").resolve()
        self.state_path = self.map_root / "world-state.json"
        self._state = self._load_json(self.state_path, {})

    @staticmethod
    def _load_json(path: Path, fallback: Any) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return fallback

    def _write_json(self, path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f"{path.suffix}.tmp")
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)

    def _catalog_metadata(self) -> dict[str, dict[str, Any]]:
        document = self._load_json(self.metadata_path, {})
        worlds = document.get("worlds", {}) if isinstance(document, dict) else {}
        return worlds if isinstance(worlds, dict) else {}

    @staticmethod
    def _sdf_world_name(path: Path) -> str:
        try:
            root = ET.parse(path).getroot()
            world = root.find("world")
            if world is not None and world.get("name"):
                return str(world.get("name"))
        except (OSError, ET.ParseError):
            pass
        return path.stem

    def _safe_profile(self, relative_value: Any) -> Path | None:
        if not relative_value:
            return None
        path = (self.simulation_root / str(relative_value)).resolve()
        try:
            path.relative_to(self.simulation_root)
        except ValueError:
            return None
        return path if path.is_file() else None

    def worlds(self) -> list[dict[str, Any]]:
        metadata = self._catalog_metadata()
        result: list[dict[str, Any]] = []
        if not self.world_dir.is_dir():
            return [self._fallback_world()]
        for path in sorted(self.world_dir.glob("*.sdf")):
            world_id = path.stem
            if not WORLD_ID_PATTERN.fullmatch(world_id):
                continue
            configured = metadata.get(world_id, {})
            if not isinstance(configured, dict):
                configured = {}
            spawn = configured.get("spawn", {})
            if not isinstance(spawn, dict):
                spawn = {}
            profile = self._safe_profile(configured.get("heat_source_profile"))
            result.append(
                {
                    "id": world_id,
                    "label": configured.get("label")
                    or world_id.replace("_", " ").title(),
                    "description": configured.get("description")
                    or "등록된 Gazebo 시뮬레이션 환경",
                    "difficulty": configured.get("difficulty", "unrated"),
                    "world_name": configured.get("world_name")
                    or self._sdf_world_name(path),
                    "file_name": path.name,
                    "path": path,
                    "spawn": {
                        "x": float(spawn.get("x", 0.6)),
                        "y": float(spawn.get("y", 0.7)),
                        "z": float(spawn.get("z", 0.04)),
                        "yaw": float(spawn.get("yaw", 0.0)),
                    },
                    "heat_source_profile_path": profile,
                    "has_heat_source_profile": profile is not None,
                }
            )
        return result or [self._fallback_world()]

    def _fallback_world(self) -> dict[str, Any]:
        return {
            "id": "facility_map",
            "label": "기본 시설 환경",
            "description": "기본 Gazebo 시뮬레이션 환경",
            "difficulty": "unrated",
            "world_name": "facility_map",
            "file_name": "facility_map.sdf",
            "path": self.world_dir / "facility_map.sdf",
            "spawn": {"x": 0.6, "y": 0.7, "z": 0.04, "yaw": 0.0},
            "heat_source_profile_path": None,
            "has_heat_source_profile": False,
        }

    def get(self, world_id: str) -> dict[str, Any]:
        if not WORLD_ID_PATTERN.fullmatch(world_id):
            raise KeyError(world_id)
        for world in self.worlds():
            if world["id"] == world_id:
                return world
        raise KeyError(world_id)

    def selected_world_id(self) -> str:
        available = self.worlds()
        if not available:
            return "facility_map"
        selected = self._state.get("selected_world_id")
        if any(world["id"] == selected for world in available):
            return str(selected)
        if any(world["id"] == "facility_map" for world in available):
            return "facility_map"
        return str(available[0]["id"])

    def selected_world(self) -> dict[str, Any]:
        return self.get(self.selected_world_id())

    def select_world(self, world_id: str) -> dict[str, Any]:
        world = self.get(world_id)
        self._state["selected_world_id"] = world_id
        self._write_json(self.state_path, self._state)
        return world

    @staticmethod
    def public_world(world: dict[str, Any], *, active: bool) -> dict[str, Any]:
        return {
            "id": world["id"],
            "label": world["label"],
            "description": world["description"],
            "difficulty": world["difficulty"],
            "world_name": world["world_name"],
            "file_name": world["file_name"],
            "spawn": world["spawn"],
            "has_heat_source_profile": world["has_heat_source_profile"],
            "active": active,
        }

    def public_worlds(self) -> dict[str, Any]:
        active_id = self.selected_world_id()
        return {
            "active_world_id": active_id,
            "worlds": [
                self.public_world(world, active=world["id"] == active_id)
                for world in self.worlds()
            ],
        }

    def begin_session(
        self,
        world_id: str,
        mapping_profile: str = "toolbox",
    ) -> dict[str, Any]:
        self.get(world_id)
        session_id = (
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            + f"-{uuid.uuid4().hex[:6]}"
        )
        session_dir = (self.map_root / world_id / session_id).resolve()
        session_dir.mkdir(parents=True, exist_ok=False)
        metadata = {
            "id": session_id,
            "world_id": world_id,
            "status": "mapping",
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "map_file": "map.yaml",
            "mapping_profile": mapping_profile,
            "rtabmap_database_file": (
                "rtabmap.db" if mapping_profile == "toolbox_rtabmap" else None
            ),
            "name": None,
            "archived": False,
            "cloud_file": None,
        }
        self._write_json(session_dir / "metadata.json", metadata)
        return {
            **metadata,
            "directory": session_dir,
            "map_path": session_dir / "map.yaml",
            "rtabmap_database_path": session_dir / "rtabmap.db",
        }

    def update_session(self, session_id: str, world_id: str, **values: Any) -> dict[str, Any]:
        session_dir = (self.map_root / world_id / session_id).resolve()
        try:
            session_dir.relative_to(self.map_root)
        except ValueError as exc:
            raise KeyError(session_id) from exc
        metadata_path = session_dir / "metadata.json"
        metadata = self._load_json(metadata_path, {})
        if metadata.get("id") != session_id or metadata.get("world_id") != world_id:
            raise KeyError(session_id)
        metadata.update(values)
        metadata["updated_at"] = utc_now()
        self._write_json(metadata_path, metadata)
        return metadata

    def discard_empty_session(self, world_id: str, session_id: str) -> bool:
        """Remove a launch-time session only while it contains metadata alone."""
        paths = self.session_paths(world_id, session_id)
        session_dir = paths["directory"]
        metadata_path = paths["metadata"]
        try:
            entries = list(session_dir.iterdir())
        except OSError:
            return False
        if entries != [metadata_path]:
            return False
        try:
            metadata_path.unlink()
            session_dir.rmdir()
        except OSError:
            return False
        return True

    def sessions(self, world_id: str) -> list[dict[str, Any]]:
        self.get(world_id)
        world_root = self.map_root / world_id
        active_id = (self._state.get("active_map_sessions") or {}).get(world_id)
        result: list[dict[str, Any]] = []
        if world_root.is_dir():
            for metadata_path in world_root.glob("*/metadata.json"):
                metadata = self._load_json(metadata_path, {})
                session_id = metadata.get("id")
                if not isinstance(session_id, str):
                    continue
                map_path = metadata_path.parent / str(metadata.get("map_file", "map.yaml"))
                database_file = metadata.get("rtabmap_database_file")
                database_path = (
                    metadata_path.parent / str(database_file)
                    if database_file
                    else None
                )
                cloud_file = metadata.get("cloud_file")
                cloud_path = (
                    metadata_path.parent / str(cloud_file)
                    if cloud_file
                    else metadata_path.parent / "cloud.ply"
                )
                image_path = self.map_image_path(map_path)
                result.append(
                    {
                        "id": session_id,
                        "world_id": world_id,
                        "status": metadata.get("status", "unknown"),
                        "created_at": metadata.get("created_at"),
                        "updated_at": metadata.get("updated_at"),
                        "name": metadata.get("name"),
                        "archived": bool(metadata.get("archived", False)),
                        "available": self.map_available(map_path),
                        "active": session_id == active_id,
                        "mapping_profile": metadata.get(
                            "mapping_profile", "toolbox"
                        ),
                        "rtabmap_available": bool(
                            database_path
                            and database_path.is_file()
                            and database_path.stat().st_size > 0
                        ),
                        "rtabmap_database_bytes": (
                            database_path.stat().st_size
                            if database_path and database_path.is_file()
                            else 0
                        ),
                        "rgbd_status": metadata.get("rgbd_status", "not_started"),
                        "rgbd_started_at": metadata.get("rgbd_started_at"),
                        "rgbd_finished_at": metadata.get("rgbd_finished_at"),
                        "cloud_available": cloud_path.is_file()
                        and cloud_path.stat().st_size > 0,
                        "cloud_bytes": (
                            cloud_path.stat().st_size if cloud_path.is_file() else 0
                        ),
                        "storage_directory": str(metadata_path.parent),
                        "map_yaml_path": str(map_path),
                        "map_image_path": str(image_path) if image_path else None,
                        "rtabmap_database_path": (
                            str(database_path) if database_path else None
                        ),
                        "cloud_path": str(cloud_path),
                        "localization_pose": metadata.get("localization_pose"),
                    }
                )
        return sorted(result, key=lambda item: item.get("created_at") or "", reverse=True)

    def session_paths(self, world_id: str, session_id: str) -> dict[str, Path]:
        self.get(world_id)
        if not SESSION_ID_PATTERN.fullmatch(session_id):
            raise KeyError(session_id)
        session_dir = (self.map_root / world_id / session_id).resolve()
        try:
            session_dir.relative_to(self.map_root)
        except ValueError as exc:
            raise KeyError(session_id) from exc
        metadata_path = session_dir / "metadata.json"
        metadata = self._load_json(metadata_path, {})
        if metadata.get("id") != session_id or metadata.get("world_id") != world_id:
            raise KeyError(session_id)
        database_file = metadata.get("rtabmap_database_file") or "rtabmap.db"
        cloud_file = metadata.get("cloud_file") or "cloud.ply"
        return {
            "directory": session_dir,
            "metadata": metadata_path,
            "database": session_dir / str(database_file),
            "cloud": session_dir / str(cloud_file),
        }

    def edit_session(
        self,
        world_id: str,
        session_id: str,
        *,
        name: str | None = None,
        archived: bool | None = None,
    ) -> dict[str, Any]:
        self.session_paths(world_id, session_id)
        values: dict[str, Any] = {}
        if name is not None:
            values["name"] = name
        if archived is not None:
            values["archived"] = bool(archived)
        self.update_session(session_id, world_id, **values)
        return next(
            item for item in self.sessions(world_id) if item["id"] == session_id
        )

    def record_cloud_export(
        self,
        world_id: str,
        session_id: str,
        cloud_path: Path,
    ) -> dict[str, Any]:
        paths = self.session_paths(world_id, session_id)
        try:
            relative = cloud_path.resolve().relative_to(paths["directory"])
        except ValueError as exc:
            raise KeyError(session_id) from exc
        self.update_session(
            session_id,
            world_id,
            cloud_file=str(relative),
            cloud_exported_at=utc_now(),
        )
        return next(
            item for item in self.sessions(world_id) if item["id"] == session_id
        )

    @staticmethod
    def map_available(map_path: Path) -> bool:
        if not map_path.is_file():
            return False
        try:
            for line in map_path.read_text(encoding="utf-8").splitlines():
                if not line.lstrip().startswith("image:"):
                    continue
                image_value = line.split(":", 1)[1].strip().strip("'\"")
                image_path = Path(image_value).expanduser()
                if not image_path.is_absolute():
                    image_path = map_path.parent / image_path
                return image_path.is_file()
        except OSError:
            return False
        return False

    @staticmethod
    def map_image_path(map_path: Path) -> Path | None:
        """Resolve the image referenced by a ROS occupancy-map YAML file."""

        if not map_path.is_file():
            return None
        try:
            for line in map_path.read_text(encoding="utf-8").splitlines():
                if not line.lstrip().startswith("image:"):
                    continue
                image_value = line.split(":", 1)[1].strip().strip("'\"")
                image_path = Path(image_value).expanduser()
                return (
                    image_path
                    if image_path.is_absolute()
                    else (map_path.parent / image_path).resolve()
                )
        except OSError:
            return None
        return None

    def activate_session(self, world_id: str, session_id: str) -> Path:
        matching = next(
            (item for item in self.sessions(world_id) if item["id"] == session_id),
            None,
        )
        if matching is None or not matching["available"]:
            raise KeyError(session_id)
        active = self._state.setdefault("active_map_sessions", {})
        active[world_id] = session_id
        self._write_json(self.state_path, self._state)
        return self.map_root / world_id / session_id / "map.yaml"

    def active_map_path(self, world_id: str) -> Path | None:
        session_id = (self._state.get("active_map_sessions") or {}).get(world_id)
        if not session_id:
            return None
        path = self.map_root / world_id / str(session_id) / "map.yaml"
        return path if self.map_available(path) else None
