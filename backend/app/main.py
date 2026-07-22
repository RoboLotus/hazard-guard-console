import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .bridge import ros_bridge, telemetry_store
from .models import CommandRequest, MockCommand, RobotTelemetry, ThresholdSettings


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


@app.websocket("/ws/telemetry")
async def telemetry(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(telemetry_store.snapshot())
            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        return
