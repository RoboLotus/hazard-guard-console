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
