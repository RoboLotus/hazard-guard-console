import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .bridge import media_store, navigation_store, ros_bridge, telemetry_store
from .models import (
    CommandRequest,
    MockCommand,
    NavigationGoal,
    RobotTelemetry,
    ThresholdSettings,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    ros_bridge.start()
    try:
        yield
    finally:
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


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "mode": "ros-mock" if ros_bridge.active else "mock",
        "ros_bridge": ros_bridge.active,
    }


@app.get("/api/v1/robot/status", response_model=RobotTelemetry)
def robot_status():
    return telemetry_store.snapshot()


@app.get("/api/v1/media/status")
def media_status():
    return media_store.status()


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
    return ros_bridge.navigate_to(goal.x, goal.y, goal.yaw, goal.frame_id)


@app.delete("/api/v1/navigation/goal")
def cancel_navigation_goal():
    return ros_bridge.cancel_navigation()


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
