import asyncio
from datetime import datetime, timezone

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .models import MockCommand, ThresholdSettings

app = FastAPI(title="HazardGuard Console API", version="0.1.0")
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
    return {"status": "ok", "mode": "mock", "ros_bridge": False}


@app.get("/api/v1/robot/status")
def robot_status():
    return {
        "robot_id": "rosmaster-m1",
        "mode": "patrol",
        "battery": 78,
        "network_dbm": -48,
        "lidar_hz": 10.2,
        "speed_mps": 0.32,
        "mock": True,
    }


@app.get("/api/v1/settings/thresholds", response_model=ThresholdSettings)
def get_thresholds():
    return thresholds


@app.put("/api/v1/settings/thresholds", response_model=ThresholdSettings)
def update_thresholds(settings: ThresholdSettings):
    global thresholds
    thresholds = settings
    return thresholds


@app.post("/api/v1/commands/{command}", response_model=MockCommand)
def mock_command(command: str):
    return MockCommand(command=command)


@app.websocket("/ws/telemetry")
async def telemetry(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "battery": 78,
                    "speed_mps": 0.32,
                    "max_temperature": 84.6,
                    "mock": True,
                }
            )
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        return

