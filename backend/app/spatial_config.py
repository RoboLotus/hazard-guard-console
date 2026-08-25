from __future__ import annotations

import json
import threading
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import (
    NavigationRoute,
    StoredNavigationRoute,
    ThermalEquipmentSettingsDocument,
)
from .settings_store import ThermalEquipmentSettingsStore


class SpatialContextUnavailableError(RuntimeError):
    """Raised when map-bound configuration is requested before maps are ready."""


def empty_equipment_document(
    world_id: str | None = None,
    map_session_id: str | None = None,
    geometry_fingerprint: str | None = None,
) -> ThermalEquipmentSettingsDocument:
    if not world_id or not map_session_id:
        world_id = None
        map_session_id = None
        geometry_fingerprint = None
    return ThermalEquipmentSettingsDocument(
        schema_version=2,
        world_id=world_id,
        map_session_id=map_session_id,
        frame_id="map",
        geometry_fingerprint=geometry_fingerprint,
        equipment=[],
    )


class MapSpatialConfigStore:
    """Persist equipment and routes beside the selected Jetson map session."""

    def __init__(
        self,
        context_provider: Callable[[], dict[str, Any]],
        map_root: Path,
    ) -> None:
        self._context_provider = context_provider
        self._map_root = map_root.resolve()
        self._lock = threading.RLock()
        self._equipment_stores: dict[tuple[str, str], ThermalEquipmentSettingsStore] = {}

    def context(self) -> dict[str, Any]:
        context = dict(self._context_provider())
        context.setdefault("frame_id", "map")
        context.setdefault("registration_ready", False)
        return context

    def _scope(self, *, require_ready: bool) -> tuple[dict[str, Any], Path]:
        context = self.context()
        world_id = context.get("world_id")
        session_id = context.get("map_session_id")
        if not world_id or not session_id:
            raise SpatialContextUnavailableError(
                "저장된 2D·3D 지도를 선택한 뒤 설비와 웨이포인트를 등록하세요."
            )
        if require_ready and not context.get("registration_ready"):
            raise SpatialContextUnavailableError(
                "2D 지도와 3D PLY 저장이 완료된 뒤 등록할 수 있습니다."
            )
        directory = (self._map_root / str(world_id) / str(session_id)).resolve()
        try:
            directory.relative_to(self._map_root)
        except ValueError as exc:
            raise SpatialContextUnavailableError("안전하지 않은 지도 세션 경로입니다.") from exc
        if not (directory / "metadata.json").is_file():
            raise SpatialContextUnavailableError("선택한 지도 세션을 찾을 수 없습니다.")
        return context, directory

    def _equipment_store(self, *, require_ready: bool) -> ThermalEquipmentSettingsStore:
        context, directory = self._scope(require_ready=require_ready)
        key = (str(context["world_id"]), str(context["map_session_id"]))
        with self._lock:
            store = self._equipment_stores.get(key)
            if store is None:
                store = ThermalEquipmentSettingsStore(
                    directory / "equipment.json",
                    default_factory=lambda: empty_equipment_document(
                        key[0], key[1], context.get("geometry_fingerprint")
                    ),
                )
                self._equipment_stores[key] = store
            return store

    def get(self) -> ThermalEquipmentSettingsDocument:
        try:
            return self._equipment_store(require_ready=False).get()
        except SpatialContextUnavailableError:
            return empty_equipment_document()

    def save(
        self,
        value: ThermalEquipmentSettingsDocument,
        *,
        reason: str = "manual",
    ) -> ThermalEquipmentSettingsDocument:
        context, _ = self._scope(require_ready=True)
        if (
            value.world_id != context["world_id"]
            or value.map_session_id != context["map_session_id"]
            or value.frame_id != "map"
        ):
            raise SpatialContextUnavailableError(
                "설비 설정이 현재 선택된 지도 세션과 일치하지 않습니다."
            )
        saved = value.model_copy(
            update={"geometry_fingerprint": context.get("geometry_fingerprint")}
        )
        return self._equipment_store(require_ready=True).save(saved, reason=reason)

    def metadata(self) -> dict[str, Any]:
        try:
            return self._equipment_store(require_ready=False).metadata()
        except SpatialContextUnavailableError:
            return {"updated_at": None, "revision_id": None}

    def history(self) -> list[dict[str, Any]]:
        try:
            return self._equipment_store(require_ready=False).history()
        except SpatialContextUnavailableError:
            return []

    def restore(self, revision_id: str) -> ThermalEquipmentSettingsDocument:
        return self._equipment_store(require_ready=True).restore(revision_id)

    def reset_defaults(self) -> ThermalEquipmentSettingsDocument:
        context = self.context()
        return self.save(
            empty_equipment_document(
                context.get("world_id"),
                context.get("map_session_id"),
                context.get("geometry_fingerprint"),
            ),
            reason="empty",
        )

    def get_route(self) -> StoredNavigationRoute | None:
        try:
            _, directory = self._scope(require_ready=False)
            return StoredNavigationRoute.model_validate_json(
                (directory / "route.json").read_text(encoding="utf-8")
            )
        except (SpatialContextUnavailableError, OSError, ValueError, TypeError):
            return None

    def save_route(self, route: NavigationRoute) -> StoredNavigationRoute:
        context, directory = self._scope(require_ready=True)
        if route.frame_id != "map":
            raise SpatialContextUnavailableError("웨이포인트 좌표계는 map이어야 합니다.")
        if (
            route.world_id != context["world_id"]
            or route.map_session_id != context["map_session_id"]
        ):
            raise SpatialContextUnavailableError(
                "웨이포인트가 현재 선택된 지도 세션과 일치하지 않습니다."
            )
        bound_route = route.model_copy(
            update={
                "world_id": context["world_id"],
                "map_session_id": context["map_session_id"],
            }
        )
        document = StoredNavigationRoute(
            world_id=context["world_id"],
            map_session_id=context["map_session_id"],
            saved_at=datetime.now(timezone.utc),
            route=bound_route,
        )
        target = directory / "route.json"
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(document.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(target)
        return document

    def delete_route(self) -> bool:
        _, directory = self._scope(require_ready=False)
        target = directory / "route.json"
        existed = target.exists()
        target.unlink(missing_ok=True)
        return existed
