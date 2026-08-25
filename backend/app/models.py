from datetime import datetime, timezone
import hashlib
from typing import Literal

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


class EquipmentRoi(BaseModel):
    minimum: list[float] = Field(
        ..., alias="min", min_length=3, max_length=3
    )
    maximum: list[float] = Field(
        ..., alias="max", min_length=3, max_length=3
    )

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def validate_bounds(self):
        if any(low >= high for low, high in zip(self.minimum, self.maximum)):
            raise ValueError("each ROI min value must be smaller than max")
        return self


class ThermalEquipmentSettings(BaseModel):
    id: str = Field(
        ...,
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9_.:-]+$",
    )
    display_name: str = Field(..., min_length=1, max_length=60)
    enabled: bool = True
    critical_temperature_c: float = Field(..., ge=1, le=300)
    adaptive_delta_c: float = Field(..., ge=0.1, le=100)
    adaptive_threshold_enabled: bool = True
    roi: EquipmentRoi

    @model_validator(mode="after")
    def normalize_name(self):
        self.display_name = self.display_name.strip()
        if not self.display_name:
            raise ValueError("display_name must not be blank")
        return self


EQUIPMENT_ROI_CLEARANCE_M = 0.03


def equipment_rois_conflict(
    first: ThermalEquipmentSettings,
    second: ThermalEquipmentSettings,
    *,
    clearance_m: float = EQUIPMENT_ROI_CLEARANCE_M,
) -> bool:
    """Return whether two enabled AABBs overlap or violate their clearance."""

    return all(
        first.roi.maximum[axis] + clearance_m > second.roi.minimum[axis]
        and second.roi.maximum[axis] + clearance_m > first.roi.minimum[axis]
        for axis in range(3)
    )


class ThermalEquipmentSettingsDocument(BaseModel):
    schema_version: Literal[1, 2] = 1
    world_id: str | None = Field(
        None,
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$",
    )
    map_session_id: str | None = Field(
        None,
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$",
    )
    frame_id: Literal["map"] = "map"
    geometry_fingerprint: str | None = Field(
        None,
        min_length=16,
        max_length=128,
        pattern=r"^[A-Fa-f0-9]+$",
    )
    equipment: list[ThermalEquipmentSettings] = Field(
        ..., max_length=100
    )

    @model_validator(mode="after")
    def validate_equipment(self):
        if bool(self.world_id) != bool(self.map_session_id):
            raise ValueError(
                "world_id and map_session_id must be supplied together"
            )
        if self.schema_version == 2 and not self.world_id and self.equipment:
            raise ValueError("unbound schema version 2 settings must be empty")
        identifiers = [item.id for item in self.equipment]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("equipment ids must be unique")
        if self.schema_version == 1 and not any(
            item.enabled for item in self.equipment
        ):
            raise ValueError("at least one equipment item must be enabled")
        enabled = [item for item in self.equipment if item.enabled]
        for index, first in enumerate(enabled):
            for second in enabled[index + 1 :]:
                if equipment_rois_conflict(first, second):
                    raise ValueError(
                        "enabled equipment ROIs overlap or are closer than "
                        f"{EQUIPMENT_ROI_CLEARANCE_M:.2f} m: "
                        f"{first.id!r}, {second.id!r}"
                    )
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


class BagRecorderControlRequest(BaseModel):
    command: Literal["start", "stop"]
    profile: Literal[
        "navigation-core", "rgbd-mapping", "patrol-core", "thermal-calibration", "patrol-thermal"
    ] = "navigation-core"
    session_name: str = Field("field-session", min_length=1, max_length=80)
    allow_experimental: bool = False


class BagRecorderEnabledRequest(BaseModel):
    enabled: bool


class DispenserDropRequest(BaseModel):
    request_id: str | None = Field(
        None,
        min_length=1,
        max_length=96,
        pattern=r"^[A-Za-z0-9_.:-]+$",
    )
    detection_id: str | None = Field(
        None,
        min_length=1,
        max_length=96,
        pattern=r"^[A-Za-z0-9_.:-]+$",
    )
    operator_approved: bool = False

    @model_validator(mode="after")
    def require_idempotency_key(self):
        if not self.request_id and not self.detection_id:
            raise ValueError("request_id or detection_id is required")
        if not self.request_id:
            digest = hashlib.sha256(self.detection_id.encode("utf-8")).hexdigest()
            self.request_id = f"detection:{digest[:32]}"
        return self


class IncidentDecisionRequest(BaseModel):
    request_id: str | None = Field(
        None,
        min_length=1,
        max_length=96,
        pattern=r"^[A-Za-z0-9_.:-]+$",
    )
    decision: Literal[
        "resume",
        "drop_then_resume",
        "drop_then_monitor",
        "complete_monitoring",
        "acknowledge_field_check",
    ]
    operator_id: str | None = Field(
        None,
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9_.:@-]+$",
    )
    confirmed: bool = False


class SystemModeRequest(BaseModel):
    mode: Literal["mapping", "rgbd_mapping", "patrol"]
    mapping_profile: Literal["toolbox", "toolbox_rtabmap"] = "toolbox"
    # Patrol with SLAM Toolbox instead of AMCL, so manual driving keeps
    # extending the map and it can be saved from the patrol screen.
    patrol_slam: bool = False


class LocalizationPoseRequest(BaseModel):
    x: float = Field(..., ge=-1000, le=1000)
    y: float = Field(..., ge=-1000, le=1000)
    yaw: float = Field(0, ge=-3.141593, le=3.141593)


class WorldSelectionRequest(BaseModel):
    world_id: str = Field(
        ...,
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$",
    )


class MapSelectionRequest(WorldSelectionRequest):
    session_id: str = Field(
        ...,
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$",
    )


class MapSessionUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=60)
    archived: bool | None = None

    @model_validator(mode="after")
    def require_change(self):
        if self.name is None and self.archived is None:
            raise ValueError("at least one session field must be provided")
        if self.name is not None:
            self.name = self.name.strip()
            if not self.name:
                raise ValueError("session name must not be blank")
        return self


class PerformanceReportUpdate(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)

    @model_validator(mode="after")
    def normalize_name(self):
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("name must not be blank")
        return self


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
    equipment_id: str | None = Field(
        None,
        max_length=80,
        pattern=r"^[A-Za-z0-9_.:-]+$",
    )
    x: float = Field(..., ge=-1000, le=1000)
    y: float = Field(..., ge=-1000, le=1000)
    yaw: float = Field(0, ge=-3.141593, le=3.141593)
    dwell_seconds: float = Field(0, ge=0, le=300)
    enabled: bool = True

    @model_validator(mode="after")
    def require_measurement_dwell(self):
        if self.equipment_id and self.dwell_seconds <= 0:
            raise ValueError(
                "equipment waypoints require a positive dwell time"
            )
        return self


class NavigationRoute(BaseModel):
    name: str = Field("기본 순찰 경로", min_length=1, max_length=80)
    world_id: str | None = Field(
        None,
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$",
    )
    map_session_id: str | None = Field(
        None,
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$",
    )
    frame_id: str = Field("map", pattern=r"^[A-Za-z][A-Za-z0-9_/]*$")
    return_to_start: bool = False
    repeat_mode: Literal["once", "count", "until_time", "forever"] = "once"
    repeat_count: int = Field(1, ge=1, le=1000)
    repeat_interval_seconds: float = Field(0, ge=0, le=86400)
    start_at: datetime | None = None
    end_at: datetime | None = None
    waypoints: list[RouteWaypoint] = Field(..., min_length=1, max_length=50)

    @model_validator(mode="after")
    def validate_route(self):
        active = [waypoint for waypoint in self.waypoints if waypoint.enabled]
        if not active:
            raise ValueError("route must contain at least one enabled waypoint")
        ids = [waypoint.id for waypoint in self.waypoints]
        if len(ids) != len(set(ids)):
            raise ValueError("waypoint ids must be unique")
        if self.repeat_mode == "count" and self.repeat_count < 2:
            raise ValueError("repeat_count must be at least 2 in count mode")
        if self.start_at is not None and self.start_at.tzinfo is None:
            raise ValueError("start_at must include a timezone offset")
        if self.end_at is not None and self.end_at.tzinfo is None:
            raise ValueError("end_at must include a timezone offset")
        if self.repeat_mode == "until_time":
            if self.end_at is None:
                raise ValueError("end_at is required in until_time mode")
            effective_start = self.start_at or datetime.now(timezone.utc)
            if self.end_at <= effective_start:
                raise ValueError("end_at must be later than start_at")
        return self


class StoredNavigationRoute(BaseModel):
    schema_version: Literal[1] = 1
    world_id: str = Field(
        ...,
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$",
    )
    map_session_id: str = Field(
        ...,
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$",
    )
    saved_at: datetime
    route: NavigationRoute

    @model_validator(mode="after")
    def validate_map_binding(self):
        if self.route.frame_id != "map":
            raise ValueError("stored routes must use the map frame")
        if self.route.world_id not in {None, self.world_id}:
            raise ValueError("route world_id does not match its stored scope")
        if self.route.map_session_id not in {None, self.map_session_id}:
            raise ValueError(
                "route map_session_id does not match its stored scope"
            )
        self.route.world_id = self.world_id
        self.route.map_session_id = self.map_session_id
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


class PersonSafetyStatus(BaseModel):
    state: int = Field(0, ge=0, le=4)
    state_name: str = "CLEAR"
    person_count: int = Field(0, ge=0)
    nearest_distance_m: float | None = Field(None, ge=0)
    distance_valid: bool = False
    detector_stale: bool = False
    reason: str = ""
    updated_at: str | None = None


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
    person_safety: PersonSafetyStatus = Field(
        default_factory=PersonSafetyStatus
    )
