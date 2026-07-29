from pydantic import BaseModel, Field, model_validator


class ThresholdSettings(BaseModel):
    warningTemperature: float = Field(60, ge=1, le=200)
    warningDuration: int = Field(5, ge=1, le=300)
    criticalTemperature: float = Field(80, ge=1, le=250)
    criticalDuration: int = Field(3, ge=1, le=300)
    clearTemperature: float = Field(50, ge=0, le=200)
    clearDuration: int = Field(10, ge=1, le=600)
    warningRepeat: int = Field(60, ge=10, le=3600)
    criticalRepeat: int = Field(30, ge=10, le=3600)

    @model_validator(mode="after")
    def validate_temperature_order(self):
        if self.criticalTemperature <= self.warningTemperature:
            raise ValueError("criticalTemperature must exceed warningTemperature")
        if self.clearTemperature >= self.warningTemperature:
            raise ValueError("clearTemperature must be below warningTemperature")
        return self


class MockCommand(BaseModel):
    command: str
    accepted: bool = True
    mock: bool = True
    message: str = ""
    mode: str = "patrol"
    controller_enabled: bool = False


class CommandRequest(BaseModel):
    enabled: bool = False


class NavigationGoal(BaseModel):
    x: float = Field(..., ge=-1000, le=1000)
    y: float = Field(..., ge=-1000, le=1000)
    yaw: float = Field(0, ge=-3.141593, le=3.141593)
    frame_id: str = Field("map", pattern=r"^[A-Za-z][A-Za-z0-9_/]*$")


class RouteWaypoint(BaseModel):
    id: str = Field(
        ...,
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9_.:-]+$",
    )
    name: str = Field(..., min_length=1, max_length=40)
    x: float = Field(..., ge=-1000, le=1000)
    y: float = Field(..., ge=-1000, le=1000)
    yaw: float = Field(0, ge=-3.141593, le=3.141593)
    dwell_seconds: float = Field(0, ge=0, le=300)
    enabled: bool = True


class NavigationRoute(BaseModel):
    name: str = Field("기본 순찰 경로", min_length=1, max_length=80)
    frame_id: str = Field("map", pattern=r"^[A-Za-z][A-Za-z0-9_/]*$")
    return_to_start: bool = False
    waypoints: list[RouteWaypoint] = Field(..., min_length=1, max_length=50)

    @model_validator(mode="after")
    def validate_route(self):
        active = [waypoint for waypoint in self.waypoints if waypoint.enabled]
        if not active:
            raise ValueError("route must contain at least one enabled waypoint")
        ids = [waypoint.id for waypoint in self.waypoints]
        if len(ids) != len(set(ids)):
            raise ValueError("waypoint ids must be unique")
        return self


class ThermalDetection(BaseModel):
    detection_id: str = Field(
        "thermal-detection",
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9_.:-]+$",
    )
    frame_id: str = Field("map", pattern=r"^[A-Za-z][A-Za-z0-9_/]*$")
    x: float = Field(..., ge=-1000, le=1000)
    y: float = Field(..., ge=-1000, le=1000)
    z: float = Field(0, ge=-100, le=100)
    temperature_c: float = Field(..., ge=-273.15, le=1000)
    confidence: float = Field(1, ge=0, le=1)
    radius_m: float = Field(0.35, gt=0, le=20)
    source: str = Field("api", min_length=1, max_length=120)
    simulated: bool = True


class RobotTelemetry(BaseModel):
    timestamp: str
    robot_id: str
    mode: str
    battery_percent: float
    speed_mps: float
    network_quality: str
    network_rssi_dbm: int
    lidar_status: str
    lidar_hz: float
    max_temperature_c: float
    alert_level: str
    controller_enabled: bool
    mock: bool
