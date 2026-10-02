"""Operator annotations only. Never dispatch robot or dispenser commands."""
import os
import sqlite3
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field


class EventStatusUpdate(BaseModel):
    map_id: str = Field(min_length=1, max_length=512)
    level: Literal["watch", "warning", "critical"]
    status: Literal["new", "acknowledged", "working", "resolved"]


class EventStatusStore:
    def __init__(self, path=None):
        self.path = Path(path or os.getenv(
            "HAZARD_GUARD_EVENT_STATUS_STORE",
            "~/.local/state/hazard_guard/events/status.sqlite3",
        )).expanduser()

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        db = sqlite3.connect(self.path, timeout=5)
        try:
            db.execute("""CREATE TABLE IF NOT EXISTS statuses (
                map_id TEXT, event_id TEXT, level TEXT, status TEXT,
                revision INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY(map_id,event_id,level))""")
            if os.name != "nt":
                os.chmod(self.path, 0o600)
        except (OSError, sqlite3.Error):
            db.close()
            raise
        return db

    def get(self, map_id):
        db = self._connect()
        try:
            return [{"id": row[0], "level": row[1], "status": row[2], "revision": row[3]} for row in db.execute(
                "SELECT event_id,level,status,revision FROM statuses WHERE map_id=?", (map_id,)
            )]
        finally:
            db.close()

    def put(self, map_id, event_id, level, status):
        db = self._connect()
        try:
            with db:
                db.execute("INSERT INTO statuses(map_id,event_id,level,status) VALUES (?,?,?,?) ON CONFLICT(map_id,event_id,level) DO UPDATE SET status=excluded.status, revision=statuses.revision+1", (map_id, event_id, level, status))
                revision = db.execute("SELECT revision FROM statuses WHERE map_id=? AND event_id=? AND level=?", (map_id, event_id, level)).fetchone()[0]
            return revision
        finally:
            db.close()


def detection_identity(item):
    event_id = item.get("detection_id")
    if not event_id:
        return None, None
    if item.get("visit_index") is not None:
        event_id = f"{event_id}-visit-{item['visit_index']}"
    status = str(item.get("trend_status") or "").split(":")[0]
    temperature = float(item.get("temperature_c") or 0)
    level = status if status in {"critical", "warning", "watch"} else "critical" if temperature >= 80 else "warning" if temperature >= 60 else None
    return event_id, level


def event_status_router(spatial_store, store=None):
    router = APIRouter(prefix="/api/v1/events")
    store = store or EventStatusStore()

    @router.get("/statuses")
    def statuses():
        map_id = str(spatial_store.snapshot().get("map", {}).get("map_id") or "")
        try:
            return {"map_id": map_id, "statuses": store.get(map_id)}
        except (OSError, sqlite3.Error):
            raise HTTPException(503, "이벤트 처리 상태 저장소에 연결하지 못했습니다.")

    @router.put("/{event_id}/status")
    def update_status(event_id: str, update: EventStatusUpdate):
        snapshot = spatial_store.snapshot()
        if update.map_id != str(snapshot.get("map", {}).get("map_id") or ""):
            raise HTTPException(409, "지도가 변경되었습니다. 이벤트를 다시 확인하세요.")
        valid = any(detection_identity(item) == (event_id, update.level)
                    for item in snapshot.get("heatmap", {}).get("detections", []))
        if not valid:
            raise HTTPException(409, "이벤트가 변경되었거나 현재 기록에 없습니다.")
        try:
            revision = store.put(update.map_id, event_id, update.level, update.status)
        except (OSError, sqlite3.Error):
            raise HTTPException(503, "이벤트 처리 상태를 저장하지 못했습니다.")
        return {"id": event_id, "revision": revision, **update.model_dump()}

    return router
