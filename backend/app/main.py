import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .bridge import (
    media_store,
    navigation_store,
    ros_bridge,
    route_mission_store,
    spatial_store,
    telemetry_store,
)
from .mode_manager import system_mode_manager
from .models import (
    CommandRequest,
    MockCommand,
    NavigationGoal,
    NavigationRoute,
    RobotTelemetry,
    SystemModeRequest,
    ThermalDetection,
    ThresholdSettings,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    ros_bridge.start()
    try:
        yield
    finally:
        system_mode_manager.stop()
        ros_bridge.stop()


app = FastAPI(
    title="HazardGuard Console API", version="0.2.0", lifespan=lifespan
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

thresholds = ThresholdSettings()


def require_patrol_mode() -> None:
    """Reject motion requests while the managed ROS stack is not in patrol mode."""

    status = system_mode_manager.snapshot()
    if not status.get("control_enabled"):
        return
    if status.get("mode") != "patrol":
        raise HTTPException(
            status_code=409,
            detail=(
                "맵 생성 모드에서는 순찰 명령을 실행할 수 없습니다. "
                "지도 탭에서 순찰 / AMCL·Nav2 모드로 전환하세요."
            ),
        )
    if status.get("state") not in {"running", "external"}:
        raise HTTPException(
            status_code=409,
            detail=(
                "순찰 모드가 아직 준비되지 않았습니다. "
                "AMCL·Nav2 실행 상태가 준비된 뒤 다시 시도하세요."
            ),
        )


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "mode": "ros-mock" if ros_bridge.active else "mock",
        "ros_bridge": ros_bridge.active,
        "capabilities": ros_bridge.capability_status(),
    }


@app.get("/api/v1/robot/status", response_model=RobotTelemetry)
def robot_status():
    return telemetry_store.snapshot()


@app.get("/api/v1/system/mode")
def system_mode():
    return system_mode_manager.snapshot()


@app.put("/api/v1/system/mode")
def update_system_mode(request: SystemModeRequest):
    ros_bridge.cancel_route()
    ros_bridge.cancel_navigation()
    result = system_mode_manager.switch_mode(request.mode)
    if not result["accepted"]:
        raise HTTPException(status_code=409, detail=result["message"])
    return result


@app.delete("/api/v1/system/mode")
def stop_system_mode():
    ros_bridge.cancel_route()
    ros_bridge.cancel_navigation()
    return system_mode_manager.stop()


@app.post("/api/v1/system/map/save")
def save_system_map():
    result = system_mode_manager.save_map()
    if not result["accepted"]:
        raise HTTPException(status_code=409, detail=result["message"])
    return result


@app.get("/api/v1/media/status")
def media_status():
    return media_store.status()


@app.get("/api/v1/spatial/status")
def spatial_status():
    return spatial_store.snapshot()


@app.post("/api/v1/spatial/detections")
def add_spatial_detection(detection: ThermalDetection):
    return spatial_store.add_detection(detection.model_dump(), live=not detection.simulated)


@app.get("/api/v1/media/{kind}")
def media_image(kind: str):
    if kind not in {"map", "rgb", "thermal"}:
        raise HTTPException(status_code=404, detail="Unknown media stream")
    item = media_store.get(kind)
    if item is None:
        raise HTTPException(status_code=503, detail=f"{kind} stream is not ready")
    return Response(
        content=item["content"],
        media_type=item["media_type"],
        headers={
            "Cache-Control": "no-store, max-age=0",
            "X-HazardGuard-Media-Source": item["source"],
        },
    )


@app.get("/api/v1/settings/thresholds", response_model=ThresholdSettings)
def get_thresholds():
    return thresholds


@app.put("/api/v1/settings/thresholds", response_model=ThresholdSettings)
def update_thresholds(settings: ThresholdSettings):
    global thresholds
    thresholds = settings
    return thresholds


@app.post("/api/v1/commands/{command}", response_model=MockCommand)
def robot_command(command: str, request: CommandRequest | None = None):
    enabled = request.enabled if request is not None else False
    return ros_bridge.command(command, enabled)


@app.get("/api/v1/navigation/status")
def navigation_status():
    return navigation_store.snapshot()


@app.post("/api/v1/navigation/goal")
def navigation_goal(goal: NavigationGoal):
    require_patrol_mode()
    return ros_bridge.navigate_to(goal.x, goal.y, goal.yaw, goal.frame_id)


@app.delete("/api/v1/navigation/goal")
def cancel_navigation_goal():
    return ros_bridge.cancel_navigation()


@app.get("/api/v1/navigation/route/status")
def navigation_route_status():
    return route_mission_store.snapshot()


@app.post("/api/v1/navigation/route/recommend")
def recommend_navigation_route(route: NavigationRoute):
    return ros_bridge.recommend_route(route.model_dump())


@app.post("/api/v1/navigation/route")
def start_navigation_route(route: NavigationRoute):
    require_patrol_mode()
    return ros_bridge.start_route(route.model_dump())


@app.delete("/api/v1/navigation/route")
def cancel_navigation_route():
    return ros_bridge.cancel_route()


@app.websocket("/ws/telemetry")
async def telemetry(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(telemetry_store.snapshot())
            await asyncio.sleep(0.5)
    except (WebSocketDisconnect, RuntimeError):
        # Some ASGI transports report an already-closed browser socket as a
        # RuntimeError instead of WebSocketDisconnect during the next send.
        return


@app.websocket("/ws/spatial")
async def spatial(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(spatial_store.snapshot())
            await asyncio.sleep(0.2)
    except (WebSocketDisconnect, RuntimeError):
        return
