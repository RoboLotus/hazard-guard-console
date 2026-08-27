import asyncio
import hmac
import math
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import (
    FastAPI,
    Header,
    HTTPException,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .bridge import (
    media_store,
    navigation_store,
    point_cloud_store,
    ros_bridge,
    route_mission_store,
    sensor_diagnostics_store,
    spatial_store,
    telemetry_store,
    thermal_cloud_store,
    thermal_delta_store,
    thermal_map_status_store,
)
from .mode_manager import system_mode_manager
from .dispenser_requests import (
    DispenserRequestStore,
    DispenserRequestStoreError,
)
from .incidents import (
    IncidentDecisionConflictError,
    IncidentStore,
    IncidentStoreError,
    OPERATOR_PATTERN,
    sign_incident_decision,
)
from .models import (
    CommandRequest,
    BagRecorderControlRequest,
    BagRecorderEnabledRequest,
    DispenserDropRequest,
    IncidentDecisionRequest,
    LocalizationPoseRequest,
    MockCommand,
    MapSelectionRequest,
    MapSessionUpdate,
    NavigationGoal,
    NavigationRoute,
    PerformanceReportUpdate,
    RobotTelemetry,
    SystemModeRequest,
    ThermalDetection,
    ThresholdSettings,
    ThermalEquipmentSettingsDocument,
    WorldSelectionRequest,
)
from .performance_reports import PerformanceReportStore, UnsafeReportPathError
from .settings_store import (
    ThermalEquipmentSettingsStore,
    ThresholdSettingsStore,
    default_thermal_equipment_settings,
)
from .spatial_config import (
    MapSpatialConfigStore,
    SpatialContextUnavailableError,
    empty_equipment_document,
)


thermal_map_status_store.reset(
    system_mode_manager.snapshot(detect_external=False).get(
        "thermal_map_session_id"
    )
)
system_mode_manager.set_thermal_status_provider(thermal_map_status_store.snapshot)


def reset_thermal_map_stream(session_id: str | None) -> None:
    thermal_map_status_store.reset(session_id)
    thermal_cloud_store.clear(
        source=os.getenv(
            "HAZARD_GUARD_THERMAL_CLOUD_TOPIC",
            "/hazard_guard/thermal/map",
        )
    )
    thermal_delta_store.reset(session_id)


def prepare_managed_ros_stop() -> dict[str, object]:
    """Publish a final motion stop while the managed ROS graph is still alive."""

    failures = []
    for name, operation in (
        ("cancel_route", ros_bridge.cancel_route),
        ("cancel_navigation", ros_bridge.cancel_navigation),
        ("stop_motion", ros_bridge.stop_motion),
    ):
        try:
            result = operation()
            if isinstance(result, dict) and result.get("accepted") is False:
                failures.append(
                    f"{name}: {result.get('message') or 'rejected'}"
                )
        except Exception as exc:
            failures.append(f"{name}: {exc}")
    return {
        "accepted": not failures,
        "message": "; ".join(failures) if failures else None,
    }


system_mode_manager.set_pre_stop_hook(prepare_managed_ros_stop)


@asynccontextmanager
async def lifespan(_: FastAPI):
    ros_bridge.start()
    current_equipment = equipment_store.get()
    ros_bridge.publish_thermal_equipment_config(
        current_equipment.model_dump(by_alias=True)
    )
    try:
        yield
    finally:
        try:
            system_mode_manager.stop()
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

threshold_store = ThresholdSettingsStore()
performance_report_store = PerformanceReportStore()
equipment_store = MapSpatialConfigStore(
    system_mode_manager.spatial_registration_context,
    system_mode_manager.map_root,
)
try:
    dispenser_request_store: DispenserRequestStore | None = DispenserRequestStore()
    dispenser_request_store_error: str | None = None
except DispenserRequestStoreError as exc:
    # Keep monitoring available while the physical dispenser remains fail-closed.
    dispenser_request_store = None
    dispenser_request_store_error = str(exc)
if dispenser_request_store is not None:
    ros_bridge.set_dispenser_result_handler(
        dispenser_request_store.apply_robot_result
    )
try:
    incident_store: IncidentStore | None = IncidentStore()
    incident_store_error: str | None = None
except IncidentStoreError as exc:
    incident_store = None
    incident_store_error = str(exc)
if incident_store is not None:
    ros_bridge.set_incident_handler(incident_store.upsert_incident)


def dispenser_drop_enabled() -> bool:
    return os.getenv("HAZARD_GUARD_DISPENSER_DROP_ENABLED", "0") == "1"


def dispenser_safety_context(request: DispenserDropRequest) -> dict:
    if not dispenser_drop_enabled():
        raise HTTPException(
            status_code=503,
            detail="디스펜서 안전 승인 기능이 비활성화되어 있습니다.",
        )
    if not request.operator_approved:
        raise HTTPException(status_code=403, detail="관리자 배출 승인이 필요합니다.")

    telemetry = telemetry_store.snapshot()
    try:
        speed_mps = float(telemetry.get("speed_mps"))
    except (TypeError, ValueError):
        speed_mps = math.nan
    try:
        stop_threshold = float(
            os.getenv("HAZARD_GUARD_DISPENSER_STOP_SPEED_MPS", "0.02")
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=503,
            detail="디스펜서 정지 속도 설정이 유효하지 않습니다.",
        ) from exc
    if not math.isfinite(stop_threshold) or stop_threshold < 0:
        raise HTTPException(
            status_code=503,
            detail="디스펜서 정지 속도 설정이 유효하지 않습니다.",
        )
    if not math.isfinite(speed_mps) or abs(speed_mps) > stop_threshold:
        raise HTTPException(
            status_code=409,
            detail="로봇의 완전 정지가 확인되지 않아 배출할 수 없습니다.",
        )

    mission = route_mission_store.snapshot()
    safe_statuses = {
        "idle", "paused", "stopped", "succeeded", "failed", "canceled",
        "cancelled",
    }
    if str(mission.get("status", "")).lower() not in safe_statuses:
        raise HTTPException(
            status_code=409,
            detail="순찰 임무가 정지된 뒤에만 배출할 수 있습니다.",
        )

    return {
        "operator_approved": True,
        "speed_mps": speed_mps,
        "mission_status": mission.get("status"),
    }


def require_dispenser_store() -> DispenserRequestStore:
    if dispenser_request_store is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "디스펜서 요청 원장을 사용할 수 없어 배출을 차단했습니다: "
                f"{dispenser_request_store_error or 'unknown error'}"
            ),
        )
    return dispenser_request_store


def require_incident_store() -> IncidentStore:
    if incident_store is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "위험 이벤트 원장을 사용할 수 없습니다: "
                f"{incident_store_error or 'unknown error'}"
            ),
        )
    return incident_store


def validate_incident_decision(incident: dict, decision: str) -> None:
    state = str(incident.get("state") or "")
    allowed = {
        "approval_required": {
            "resume", "drop_then_resume", "drop_then_monitor"
        },
        "admin_release_required": {"complete_monitoring"},
        "field_check_required": {"acknowledge_field_check"},
        "hardware_error": {"acknowledge_field_check"},
    }.get(state, set())
    if decision not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"현재 이벤트 상태({state})에서 선택할 수 없는 조치입니다.",
        )
    if decision.startswith("drop_then_"):
        battery = ros_bridge.dispenser_battery_status()
        if battery.get("stale") or int(battery.get("available_for_drop", 0)) < 1:
            raise HTTPException(
                status_code=409,
                detail="배출 가능한 비콘이 없어 배출 조치를 선택할 수 없습니다.",
            )


def validate_incident_runtime(incident: dict) -> None:
    """Reject decisions for an incident owned by a previous ROS process.

    The SQLite incident ledger intentionally survives a backend restart, but
    the mission manager's in-memory approval latch does not. Replaying the old
    approval against a newly launched physical patrol can otherwise target an
    empty or unrelated latch. Fail closed and require a fresh sensor visit.
    """
    if str(incident.get("state") or "") not in {
        "approval_required",
        "dispensing",
        "monitoring",
        "admin_release_required",
        "field_check_required",
        "hardware_error",
    }:
        return
    runtime = system_mode_status()
    if runtime.get("deployment_target") != "physical":
        return
    if runtime.get("mode") not in {"patrol", "rgbd_mapping"} or runtime.get(
        "state"
    ) not in {"running", "external"}:
        raise HTTPException(
            status_code=409,
            detail=(
                "현재 ROS 순찰 세션이 없어 이전 위험 이벤트를 처리할 수 "
                "없습니다. 새 센서 관측으로 이벤트를 다시 확인해 주세요."
            ),
        )
    try:
        incident_updated = datetime.fromisoformat(str(incident["updated_at"]))
        runtime_started = datetime.fromisoformat(str(runtime["started_at"]))
        if incident_updated.tzinfo is None:
            incident_updated = incident_updated.replace(tzinfo=timezone.utc)
        if runtime_started.tzinfo is None:
            runtime_started = runtime_started.replace(tzinfo=timezone.utc)
    except (KeyError, TypeError, ValueError):
        raise HTTPException(
            status_code=409,
            detail=(
                "위험 이벤트의 ROS 세션 정보를 확인할 수 없어 관리자 조치를 "
                "차단했습니다. 새 센서 관측으로 다시 확인해 주세요."
            ),
        )
    if incident_updated < runtime_started:
        raise HTTPException(
            status_code=409,
            detail=(
                "ROS가 재기동되기 전에 생성된 위험 이벤트입니다. 중복 배출을 "
                "막기 위해 새 센서 관측 후 다시 승인해 주세요."
            ),
        )


def require_admin_operator(admin_token: str | None) -> str:
    expected_token = os.getenv("HAZARD_GUARD_ADMIN_API_TOKEN", "")
    operator_id = os.getenv("HAZARD_GUARD_ADMIN_OPERATOR_ID", "").strip()
    if not expected_token or not OPERATOR_PATTERN.fullmatch(operator_id):
        raise HTTPException(
            status_code=503,
            detail="관리자 인증 환경이 설정되지 않아 조치를 차단했습니다.",
        )
    if admin_token is None or not hmac.compare_digest(admin_token, expected_token):
        raise HTTPException(status_code=401, detail="관리자 인증에 실패했습니다.")
    return operator_id


def equipment_settings_response(
    settings: ThermalEquipmentSettingsDocument,
    *,
    runtime: dict | None = None,
) -> dict:
    current_runtime = (
        runtime
        if runtime is not None
        else ros_bridge.thermal_equipment_config_status()
    )
    return {
        **settings.model_dump(by_alias=True),
        "runtime": current_runtime,
        "metadata": equipment_store.metadata(),
        "spatial_context": (
            equipment_store.context()
            if isinstance(equipment_store, MapSpatialConfigStore)
            else {"registration_ready": True, "state": "legacy"}
        ),
    }


def validate_route_equipment(route: NavigationRoute) -> None:
    if isinstance(equipment_store, MapSpatialConfigStore):
        context = equipment_store.context()
        route_is_bound = bool(route.world_id or route.map_session_id)
        if route_is_bound and not context.get("registration_ready"):
            raise HTTPException(status_code=409, detail=context["message"])
        if route_is_bound and (
            route.world_id not in {None, context["world_id"]} or route.map_session_id not in {
            None,
            context["map_session_id"],
            }
        ):
            raise HTTPException(
                status_code=409,
                detail="웨이포인트가 현재 선택한 지도 세션과 일치하지 않습니다.",
            )
    configured = {item.id: item for item in equipment_store.get().equipment}
    for waypoint in route.waypoints:
        if not waypoint.equipment_id:
            continue
        equipment = configured.get(waypoint.equipment_id)
        if equipment is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"웨이포인트 {waypoint.name!r}의 설비 ID "
                    f"{waypoint.equipment_id!r}가 존재하지 않습니다."
                ),
            )
        if not equipment.enabled:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"웨이포인트 {waypoint.name!r}에 연결된 "
                    f"{equipment.display_name!r} 설비가 비활성 상태입니다."
                ),
            )


def system_mode_status() -> dict:
    status = system_mode_manager.snapshot()
    capabilities = ros_bridge.capability_status()
    cloud_status = point_cloud_store.status()
    cloud_live = bool(cloud_status.get("available")) and float(
        cloud_status.get("age_sec") or 0.0
    ) <= 2.0
    pose = spatial_store.snapshot().get("pose") or {}
    pose_fresh = False
    if pose.get("available") and not pose.get("mock"):
        try:
            updated_at = datetime.fromisoformat(str(pose["updated_at"]))
            pose_fresh = (
                datetime.now(timezone.utc) - updated_at.astimezone(timezone.utc)
            ).total_seconds() <= 2.0
        except (KeyError, TypeError, ValueError):
            pose_fresh = False

    patrol_process_ready = (
        status.get("mode") in {"patrol", "rgbd_mapping"}
        and status.get("state") in {"running", "external"}
    )
    readiness = {
        "navigate_to_pose": bool(capabilities.get("navigate_to_pose")),
        "compute_path_to_pose": bool(capabilities.get("compute_path_to_pose")),
        "mission_manager": bool(capabilities.get("mission_manager")),
        "localized_pose": pose_fresh,
    }
    navigation_ready = patrol_process_ready and all(readiness.values())
    if navigation_ready:
        readiness_message = "AMCL 위치 추정과 Nav2 주행 서버가 준비되었습니다."
    elif status.get("mode") not in {"patrol", "rgbd_mapping"}:
        readiness_message = "순찰 모드가 선택되지 않았습니다."
    elif status.get("state") not in {"running", "external"}:
        readiness_message = "순찰 모드 프로세스를 시작하고 있습니다."
    else:
        missing = {
            "navigate_to_pose": "Nav2 목적지 서버",
            "compute_path_to_pose": "Nav2 경로 계획 서버",
            "mission_manager": "ROS 순찰 임무 관리자",
            "localized_pose": "AMCL 위치 추정",
        }
        waiting_for = [label for key, label in missing.items() if not readiness[key]]
        readiness_message = f"{', '.join(waiting_for)} 준비를 기다리고 있습니다."
    return {
        **status,
        "rtabmap": {
            "enabled": (
                status.get("mode") == "rgbd_mapping"
                or status.get("mapping_profile") == "toolbox_rtabmap"
            ),
            "live": cloud_live,
            "point_count": int(cloud_status.get("point_count") or 0),
            "color_available": bool(cloud_status.get("color_available")),
            "source": cloud_status.get("source"),
            "age_sec": cloud_status.get("age_sec"),
        },
        "navigation_ready": navigation_ready,
        "readiness": readiness,
        "readiness_message": readiness_message,
    }


def require_patrol_mode() -> None:
    """Allow Nav2 requests only in saved-map localization modes."""

    status = system_mode_status()
    if not status.get("control_enabled"):
        return
    if status.get("mode") not in {"patrol", "rgbd_mapping"}:
        raise HTTPException(
            status_code=409,
            detail=(
                "2D 맵 생성 모드에서는 Nav2 명령을 실행할 수 없습니다. "
                "지도 탭에서 3D 수집 또는 순찰 모드로 전환하세요."
            ),
        )
    if not status.get("navigation_ready"):
        raise HTTPException(
            status_code=409,
            detail=status["readiness_message"],
        )


def simulation_teleop_readiness() -> tuple[bool, str]:
    """Allow browser teleop only for a WebUI-managed simulation."""

    status = system_mode_status()
    if status.get("deployment_target") == "physical":
        return False, "실물 로봇에서는 안전을 위해 WebUI 가상 조작기를 사용할 수 없습니다."
    if not status.get("control_enabled"):
        return False, "WebUI 시뮬레이션 제어가 비활성화되어 있습니다."
    if status.get("mode") not in {"mapping", "rgbd_mapping", "patrol"}:
        return False, "가상 조작은 지도 작성·3D 수집·순찰 모드에서만 사용할 수 있습니다."
    if status.get("state") != "running" or not status.get("managed"):
        return False, "WebUI에서 시작한 SLAM 맵 생성 프로세스가 준비되지 않았습니다."
    if (
        status.get("simulation_state") != "running"
        or not status.get("simulation_managed")
    ):
        return False, "WebUI에서 시작한 Gazebo 시뮬레이션이 준비되지 않았습니다."
    if not ros_bridge.active:
        return False, "ROS 시뮬레이션 브리지가 준비되지 않았습니다."
    return True, "시뮬레이션 조작 준비 완료"


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "mode": "ros-mock" if ros_bridge.active else "mock",
        "ros_bridge": ros_bridge.active,
        "deployment_target": system_mode_manager.snapshot(
            detect_external=False
        ).get("deployment_target"),
        "capabilities": ros_bridge.capability_status(),
    }


@app.get("/api/v1/dispenser/status")
def dispenser_status():
    return {
        "drop_enabled": dispenser_drop_enabled(),
        "ledger_available": dispenser_request_store is not None,
        "ledger_error": dispenser_request_store_error,
        "battery": ros_bridge.dispenser_battery_status(),
    }


@app.get("/api/v1/incidents")
def incidents(limit: int = 100):
    store = require_incident_store()
    return {
        "incidents": store.list(limit=limit),
        "battery": ros_bridge.dispenser_battery_status(),
    }


@app.get("/api/v1/incidents/{incident_id}")
def incident_detail(incident_id: str):
    store = require_incident_store()
    incident = store.get(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="위험 이벤트를 찾을 수 없습니다.")
    return {
        "incident": incident,
        "decisions": store.decisions_for(incident_id),
        "battery": ros_bridge.dispenser_battery_status(),
    }


@app.post("/api/v1/incidents/{incident_id}/decision")
def decide_incident(
    incident_id: str,
    request: IncidentDecisionRequest,
    admin_token: str | None = Header(
        None, alias="X-HazardGuard-Admin-Token"
    ),
):
    if not request.confirmed:
        raise HTTPException(status_code=403, detail="관리자 확인이 필요합니다.")
    operator_id = require_admin_operator(admin_token)
    if request.operator_id is not None and request.operator_id != operator_id:
        raise HTTPException(
            status_code=403,
            detail="요청한 운영자와 인증된 운영자가 일치하지 않습니다.",
        )
    store = require_incident_store()
    incident = store.get(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="위험 이벤트를 찾을 수 없습니다.")
    validate_incident_runtime(incident)
    secret = os.getenv("HAZARD_GUARD_DISPENSER_APPROVAL_SECRET", "")
    if not secret:
        raise HTTPException(
            status_code=503,
            detail="관리자 승인 서명 키가 설정되지 않아 조치를 차단했습니다.",
        )
    request_id = request.request_id or f"decision:{uuid.uuid4().hex}"
    try:
        existing = store.get_decision(request_id) if request.request_id else None
        if existing is None:
            validate_incident_decision(incident, request.decision)
        decision_record, created = store.begin_decision(
            request_id=request_id,
            incident_id=incident_id,
            decision=request.decision,
            operator_id=operator_id,
        )
        if not created and decision_record["state"] in {"accepted", "rejected"}:
            if decision_record["state"] == "rejected":
                raise HTTPException(
                    status_code=409,
                    detail=decision_record.get("message") or "Robot이 관리자 조치를 거절했습니다.",
                )
            return {**decision_record, "replayed": True}
        _, claimed = store.claim_dispatch(
            request_id,
            owner_id=f"api-{uuid.uuid4().hex}",
        )
        if not claimed:
            return {**decision_record, "replayed": True}
    except IncidentDecisionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IncidentStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    authorization = sign_incident_decision(
        secret=secret,
        incident_id=incident_id,
        request_id=request_id,
        decision=request.decision,
        operator_id=operator_id,
    )
    result = ros_bridge.decide_incident(
        {
            "incident_id": incident_id,
            "request_id": request_id,
            "decision": request.decision,
            "operator_id": operator_id,
            "authorization": authorization,
        }
    )
    try:
        if not result.get("delivered"):
            store.transition_decision(
                request_id,
                state="transport_unavailable",
                message=str(result.get("message") or "승인 서비스를 사용할 수 없습니다."),
            )
            raise HTTPException(status_code=503, detail=result["message"])
        final_state = "accepted" if result.get("accepted") else "rejected"
        record = store.transition_decision(
            request_id,
            state=final_state,
            robot_response=result,
            message=str(result.get("message") or ""),
        )
    except IncidentStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if final_state == "rejected":
        raise HTTPException(status_code=409, detail=result.get("message"))
    return {**record, "replayed": not created}


@app.get("/api/v1/robot/status", response_model=RobotTelemetry)
def robot_status():
    return telemetry_store.snapshot()


@app.get("/api/v1/system/mode")
def system_mode():
    return system_mode_status()


@app.put("/api/v1/system/mode")
def update_system_mode(request: SystemModeRequest):
    if request.mode in {"patrol", "rgbd_mapping"}:
        remember_live_localization_pose()
    previous = system_mode_manager.snapshot(detect_external=False)
    result = system_mode_manager.switch_mode(
        request.mode,
        mapping_profile=request.mapping_profile,
        patrol_slam=request.patrol_slam,
    )
    if not result["accepted"]:
        if result.get("thermal_cache_reset_required"):
            # Geometry changed but no node was launched. Keep the receiver
            # disarmed so a delayed same-session transient status cannot
            # repopulate the old PointCloud2 snapshot.
            reset_thermal_map_stream(None)
        raise HTTPException(status_code=409, detail=result["message"])
    if (
        previous.get("mode") != result.get("mode")
        or previous.get("pid") != result.get("pid")
    ):
        reset_thermal_map_stream(
            str(result.get("thermal_map_session_id"))
            if result.get("thermal_map_session_id")
            and request.mode == "patrol"
            else None
        )
    # A patrol that keeps mapping starts from an empty SLAM map, so it needs the
    # mapping reset rather than the localization one.
    if (
        result.get("mapping_session_id")
        and (request.mode == "mapping" or result.get("patrol_slam"))
    ):
        media_store.clear("map")
        session_id = result["mapping_session_id"]
        spatial_store.reset_for_mapping(
            f"{result.get('active_world_id', 'world')}:{session_id}"
        )
    elif request.mode in {"patrol", "rgbd_mapping"}:
        spatial_store.reset_for_localization(
            f"{result.get('active_world_id')}:{result.get('active_map_session_id')}"
        )
        current_equipment = equipment_store.get()
        ros_bridge.publish_thermal_equipment_config(
            current_equipment.model_dump(by_alias=True)
        )
    return result


def remember_live_localization_pose() -> None:
    """Persist only the currently admitted map-frame pose for a map save."""

    mode = system_mode_manager.snapshot(detect_external=False)
    map_source_running = mode.get("mode") == "mapping" or (
        mode.get("mode") == "patrol" and mode.get("patrol_slam")
    )
    session_id = (
        mode.get("mapping_session_id")
        if map_source_running
        else mode.get("active_map_session_id")
    )
    world_id = mode.get("active_world_id")
    if not world_id or not session_id:
        return
    expected_map_id = f"{world_id}:{session_id}"
    spatial = spatial_store.snapshot()
    current_pose = spatial.get("pose") or {}
    frame_id = str(current_pose.get("frame_id") or "").lstrip("/")
    try:
        updated_at = datetime.fromisoformat(str(current_pose["updated_at"]))
        if updated_at.tzinfo is None:
            raise ValueError("pose timestamp must include a timezone")
        age_sec = (
            datetime.now(timezone.utc) - updated_at.astimezone(timezone.utc)
        ).total_seconds()
    except (KeyError, TypeError, ValueError):
        return
    if (
        current_pose.get("available")
        and not current_pose.get("mock")
        and frame_id == "map"
        and spatial.get("map", {}).get("map_id") == expected_map_id
        and current_pose.get("map_id") == expected_map_id
        and 0 <= age_sec <= 2.0
    ):
        system_mode_manager.set_localization_pose(
            current_pose,
            world_id=str(world_id),
            session_id=str(session_id),
        )


@app.post("/api/v1/system/localization/initialize")
def initialize_localization(request: LocalizationPoseRequest):
    status = system_mode_status()
    if status.get("mode") not in {"patrol", "rgbd_mapping"} or status.get(
        "state"
    ) not in {
        "running",
        "external",
    }:
        raise HTTPException(
            status_code=409,
            detail="저장 지도 기반 모드가 실행 중일 때만 AMCL 초기 위치를 적용할 수 있습니다.",
        )
    system_mode_manager.set_localization_pose(request.model_dump())
    spatial_store.reset_for_localization(
        f"{status.get('active_world_id')}:{status.get('active_map_session_id')}"
    )
    result = ros_bridge.publish_initial_pose(request.x, request.y, request.yaw)
    if not result["accepted"]:
        raise HTTPException(status_code=409, detail=result["message"])
    return result


@app.delete("/api/v1/system/mode")
def stop_system_mode():
    result = system_mode_manager.stop()
    if not result["accepted"]:
        raise HTTPException(status_code=409, detail=result["message"])
    if result.get("managed_stop_performed"):
        reset_thermal_map_stream(None)
    return result


@app.post("/api/v1/system/map/save")
def save_system_map():
    remember_live_localization_pose()
    result = system_mode_manager.save_map()
    if not result["accepted"]:
        raise HTTPException(status_code=409, detail=result["message"])
    return result


@app.post("/api/v1/system/map/save-and-stop")
def save_and_stop_system_map():
    remember_live_localization_pose()
    result = system_mode_manager.save_map_and_stop()
    if not result["accepted"]:
        raise HTTPException(status_code=409, detail=result["message"])
    if result.get("managed_stop_performed"):
        reset_thermal_map_stream(None)
    return result


@app.get("/api/v1/system/worlds")
def simulation_worlds():
    return system_mode_manager.worlds()


@app.put("/api/v1/system/world")
def select_simulation_world(request: WorldSelectionRequest):
    ros_bridge.cancel_route()
    ros_bridge.cancel_navigation()
    result = system_mode_manager.select_world(request.world_id)
    if not result["accepted"]:
        raise HTTPException(status_code=409, detail=result["message"])
    media_store.clear("map")
    spatial_store.reset_for_mapping(f"{request.world_id}:waiting")
    reset_thermal_map_stream(None)
    ros_bridge.publish_thermal_equipment_config(
        equipment_store.get().model_dump(by_alias=True)
    )
    return result


@app.get("/api/v1/system/maps")
def saved_system_maps(world_id: str | None = None):
    try:
        return system_mode_manager.maps(world_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="등록되지 않은 환경입니다.")


@app.put("/api/v1/system/map/active")
def select_active_system_map(request: MapSelectionRequest):
    result = system_mode_manager.select_map(request.world_id, request.session_id)
    if not result["accepted"]:
        raise HTTPException(status_code=409, detail=result["message"])
    # A cached pose belongs to the previously active map frame. Invalidate it
    # before a later RGB-D/patrol request has a chance to overwrite the pose
    # restored from the newly selected session metadata.
    spatial_store.reset_for_localization(
        f"{request.world_id}:{request.session_id}"
    )
    reset_thermal_map_stream(None)
    ros_bridge.publish_thermal_equipment_config(
        equipment_store.get().model_dump(by_alias=True)
    )
    return result


@app.patch("/api/v1/system/maps/{world_id}/{session_id}")
def update_system_map_session(
    world_id: str,
    session_id: str,
    request: MapSessionUpdate,
):
    result = system_mode_manager.edit_map_session(
        world_id,
        session_id,
        name=request.name,
        archived=request.archived,
    )
    if not result["accepted"]:
        raise HTTPException(status_code=404, detail=result["message"])
    return result


@app.get("/api/v1/system/maps/{world_id}/{session_id}/cloud.ply")
def system_map_cloud(world_id: str, session_id: str, download: bool = False):
    result = system_mode_manager.export_map_cloud(world_id, session_id)
    if not result["accepted"]:
        raise HTTPException(status_code=409, detail=result["message"])
    if result.get("geometry_refreshed"):
        mode = system_mode_manager.snapshot(detect_external=False)
        if session_id in {
            mode.get("active_map_session_id"),
            mode.get("thermal_map_session_id"),
        }:
            # No updater node is expected during a manual export. Leave the
            # receiver disarmed until a successful patrol transition arms it.
            reset_thermal_map_stream(None)
    disposition = "attachment" if download else "inline"
    return FileResponse(
        result["path"],
        media_type="application/octet-stream",
        filename=f"hazard-guard-{session_id}.ply",
        content_disposition_type=disposition,
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.get("/api/v1/media/status")
def media_status():
    return media_store.status()


@app.get("/api/v1/spatial/status")
def spatial_status():
    return spatial_store.snapshot()


@app.get("/api/v1/spatial/cloud/status")
def point_cloud_status():
    return point_cloud_store.status()


@app.get("/api/v1/spatial/cloud/thermal/status")
def thermal_cloud_status():
    # The browser packet adapter recolours radiometric values using this fixed
    # window, including clouds that already contain a packed ROS rgb field.
    mode = system_mode_manager.snapshot(detect_external=False)
    cloud_status = thermal_cloud_store.status()
    node_status = thermal_map_status_store.snapshot()
    session_id = mode.get("thermal_map_session_id")
    status_matches_session = bool(
        node_status.get("available")
        and session_id
        and node_status.get("session_id") == session_id
    )
    cloud_path_value = mode.get("thermal_map_cloud_path")
    state_path_value = mode.get("thermal_map_state_path")
    cloud_path = Path(str(cloud_path_value)) if cloud_path_value else None
    state_path = Path(str(state_path_value)) if state_path_value else None
    backend_fixed_map_ready = bool(
        mode.get("thermal_map_status")
        in {"ready", "active", "saved", "persistence_unknown"}
        and cloud_path
        and cloud_path.is_file()
        and cloud_path.stat().st_size > 0
    )
    state_available = bool(
        state_path and state_path.is_file() and state_path.stat().st_size > 0
    )
    persisted_at = (
        datetime.fromtimestamp(state_path.stat().st_mtime, timezone.utc).isoformat()
        if state_available and state_path is not None
        else None
    )
    topic = os.getenv(
        "HAZARD_GUARD_THERMAL_CLOUD_TOPIC", "/hazard_guard/thermal/map"
    )
    node_fields = (
        "frame_id",
        "geometry_voxel_count",
        "observed_voxel_count",
        "published_voxel_count",
        "match_ratio",
        "rejected_observation_count",
        "accepted_frame_count",
        "rejected_frame_count",
        "last_result",
        "last_observation_at",
        "fingerprint",
        "state_restored",
        "persistence_enabled",
        "state_path",
        "map_error",
        "state_error",
        "local_alignment_enabled",
        "snapshot_truncated",
        "surface_range_rejected_count",
        "dropped_pending_observation_count",
        "localization_ready",
        "localization_stable_sample_count",
    )
    node_details = (
        {name: node_status.get(name) for name in node_fields}
        if status_matches_session
        else {}
    )
    observation_age = (
        node_status.get("observation_age_sec")
        if status_matches_session
        else None
    )
    node_persisted_at = (
        node_status.get("persisted_at") if status_matches_session else None
    )
    result = {
        **cloud_status,
        **node_details,
        "min_temp_c": float(
            os.getenv("HAZARD_GUARD_THERMAL_COLOR_MIN_C", "20.0")
        ),
        "max_temp_c": float(
            os.getenv("HAZARD_GUARD_THERMAL_COLOR_MAX_C", "40.0")
        ),
        "cumulative": (
            bool(node_status.get("cumulative"))
            if status_matches_session
            else topic == "/hazard_guard/thermal/map"
        ),
        "session_id": session_id,
        "status_available": status_matches_session,
        "status_age_sec": (
            node_status.get("status_age_sec")
            if status_matches_session
            else None
        ),
        # The 1 Hz snapshot receipt age is not sensor freshness. Only the
        # timestamp of the last accepted thermal observation is authoritative.
        "age_sec": observation_age,
        "observation_age_sec": observation_age,
        "stale_after_sec": (
            node_status.get("stale_after_sec")
            if status_matches_session
            else float(
                os.getenv("HAZARD_GUARD_THERMAL_MAP_STALE_SEC", "15.0")
            )
        ),
        "observation_fresh": bool(
            status_matches_session and node_status.get("observation_fresh")
        ),
        "fixed_map_available": bool(
            backend_fixed_map_ready
            and (
                not status_matches_session
                or node_status.get("fixed_map_available")
            )
        ),
        "state_available": state_available,
        "persisted_at": node_persisted_at or persisted_at,
        "map_status": mode.get("thermal_map_status"),
        "map_message": mode.get("thermal_map_message"),
    }
    if topic == "/hazard_guard/thermal/map" and not status_matches_session:
        # An empty PointCloudStore generation has a fresh updated_at of its
        # own. It is a cache reset, not a thermal observation timestamp.
        result["last_observation_at"] = None
    return result


@app.get("/api/v1/spatial/cloud/thermal/delta/bootstrap")
def thermal_delta_bootstrap():
    result = thermal_delta_store.bootstrap()
    node_status = thermal_map_status_store.snapshot()
    result["dynamic_voxel_size_m"] = node_status.get("dynamic_voxel_size_m", 0.05)
    result["snapshot_fallback_available"] = bool(
        thermal_cloud_store.status().get("available")
    )
    return result


@app.get("/api/v1/spatial/cloud/thermal/delta/resync")
def thermal_delta_resync(
    session_id: str,
    geometry_fingerprint: str,
    base_sequence: int,
):
    recovery = thermal_delta_store.recover(
        session_id=session_id,
        geometry_fingerprint=geometry_fingerprint,
        base_sequence=base_sequence,
    )
    bootstrap = thermal_delta_store.bootstrap()
    return {
        "status": recovery.status,
        "reason": recovery.reason or None,
        "session_id": bootstrap["session_id"],
        "geometry_fingerprint": bootstrap["geometry_fingerprint"],
        "protocol_version": bootstrap["protocol_version"],
        "latest_sequence": bootstrap["latest_sequence"],
        "replay_packet_count": len(recovery.packets),
        "snapshot_fallback_websocket": "/ws/pointcloud/thermal",
    }


@app.get("/api/v1/system/sensors")
def sensor_diagnostics():
    mode = system_mode_manager.snapshot(detect_external=False)
    requirements = {
        "mapping": ("mapping",),
        "rgbd_mapping": ("patrol", "3d", "inspection"),
        "patrol": ("patrol", "inspection"),
    }.get(str(mode.get("mode")), ())
    return ros_bridge.sensor_diagnostics_snapshot(
        active_requirements=requirements,
        deployment_target=mode.get("deployment_target"),
    )


@app.get("/api/v1/performance/reports")
def performance_reports():
    return performance_report_store.list()


@app.get("/api/v1/performance/reports/{report_id}")
def performance_report(report_id: str):
    try:
        return performance_report_store.get(report_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="성능 리포트를 찾을 수 없습니다.")


@app.patch("/api/v1/performance/reports/{report_id}")
def rename_performance_report(report_id: str, request: PerformanceReportUpdate):
    try:
        return performance_report_store.rename(report_id, request.name)
    except KeyError:
        raise HTTPException(status_code=404, detail="성능 리포트를 찾을 수 없습니다.")
    except UnsafeReportPathError:
        raise HTTPException(status_code=409, detail="안전하지 않은 리포트 파일입니다.")


@app.delete("/api/v1/performance/reports/{report_id}")
def delete_performance_report(report_id: str, confirm: bool = False):
    if not confirm:
        raise HTTPException(status_code=409, detail="삭제 확인이 필요합니다.")
    try:
        return performance_report_store.delete(report_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="성능 리포트를 찾을 수 없습니다.")
    except UnsafeReportPathError:
        raise HTTPException(status_code=409, detail="안전하지 않은 리포트 파일입니다.")


@app.get("/api/v1/performance/reports/{report_id}/download")
def download_performance_report(report_id: str, format: str = "csv"):
    try:
        content, media_type, filename = performance_report_store.download(
            report_id,
            format,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="성능 리포트를 찾을 수 없습니다.")
    except UnsafeReportPathError:
        raise HTTPException(status_code=409, detail="안전하지 않은 리포트 파일입니다.")
    except ValueError:
        raise HTTPException(status_code=422, detail="지원하지 않는 리포트 형식입니다.")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="리포트 파일이 없습니다.")
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
    return threshold_store.get()


@app.put("/api/v1/settings/thresholds", response_model=ThresholdSettings)
def update_thresholds(settings: ThresholdSettings):
    return threshold_store.save(settings)


@app.get("/api/v1/settings/equipment")
def get_equipment_settings():
    return equipment_settings_response(equipment_store.get())


@app.get("/api/v1/settings/equipment/defaults")
def get_default_equipment_settings():
    if isinstance(equipment_store, MapSpatialConfigStore):
        context = equipment_store.context()
        return empty_equipment_document(
            context.get("world_id"),
            context.get("map_session_id"),
            context.get("geometry_fingerprint"),
        ).model_dump(by_alias=True)
    return default_thermal_equipment_settings().model_dump(by_alias=True)


@app.get("/api/v1/settings/equipment/history")
def get_equipment_settings_history():
    return {"revisions": equipment_store.history()}


@app.put("/api/v1/settings/equipment")
def update_equipment_settings(
    settings: ThermalEquipmentSettingsDocument,
):
    try:
        saved = equipment_store.save(settings, reason="manual")
    except SpatialContextUnavailableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    runtime = ros_bridge.publish_thermal_equipment_config(
        saved.model_dump(by_alias=True)
    )
    return equipment_settings_response(saved, runtime=runtime)


@app.post("/api/v1/settings/equipment/apply")
def apply_saved_equipment_settings():
    """Retry the saved desired settings without creating another revision."""
    saved = equipment_store.get()
    runtime = ros_bridge.publish_thermal_equipment_config(
        saved.model_dump(by_alias=True)
    )
    return equipment_settings_response(saved, runtime=runtime)


@app.post("/api/v1/settings/equipment/reset-defaults")
def reset_equipment_settings():
    try:
        saved = equipment_store.reset_defaults()
    except SpatialContextUnavailableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    runtime = ros_bridge.publish_thermal_equipment_config(
        saved.model_dump(by_alias=True)
    )
    return equipment_settings_response(saved, runtime=runtime)


@app.post("/api/v1/settings/equipment/history/{revision_id}/restore")
def restore_equipment_settings(revision_id: str):
    try:
        saved = equipment_store.restore(revision_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="설정 이력을 찾을 수 없습니다.")
    except SpatialContextUnavailableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    runtime = ros_bridge.publish_thermal_equipment_config(
        saved.model_dump(by_alias=True)
    )
    return equipment_settings_response(saved, runtime=runtime)


@app.post("/api/v1/settings/equipment/baseline/reset")
def reset_equipment_baseline_collection():
    result = ros_bridge.reset_thermal_baseline_collection()
    if not result["accepted"]:
        raise HTTPException(status_code=409, detail=result["message"])
    return result

@app.post("/api/v1/commands/{command}", response_model=MockCommand)
def robot_command(command: str, request: CommandRequest | None = None):
    enabled = request.enabled if request is not None else False
    return ros_bridge.command(command, enabled)


@app.get("/api/v1/rosbag/status")
def rosbag_status():
    return ros_bridge.bag_status()


@app.put("/api/v1/rosbag/enabled")
def set_rosbag_enabled(request: BagRecorderEnabledRequest):
    result = ros_bridge.bag_control("enable" if request.enabled else "disable")
    if not result["accepted"]:
        raise HTTPException(status_code=409, detail=result["message"])
    return result.get("status", rosbag_status())


@app.post("/api/v1/rosbag/control")
def rosbag_control(request: BagRecorderControlRequest):
    result = ros_bridge.bag_control(
        request.command, request.profile, request.session_name, request.allow_experimental
    )
    if not result["accepted"]:
        raise HTTPException(status_code=409, detail=result["message"])
    return result


@app.get("/api/v1/rosbag/sessions")
def rosbag_sessions():
    result = ros_bridge.bag_control("list")
    if not result["accepted"]:
        raise HTTPException(status_code=409, detail=result["message"])
    status = result.get("status", {})
    return {"sessions": status.get("sessions", []), "truncated": bool(status.get("sessions_truncated"))}


@app.post("/api/v1/dispenser/requests/drop", status_code=202)
def request_dispenser_drop(request: DispenserDropRequest):
    """Reject the legacy bypass; operators must approve a latched incident."""

    del request
    raise HTTPException(
        status_code=410,
        detail=(
            "직접 비콘 배출 API는 안전상 비활성화되었습니다. "
            "위험 이벤트 관리자 승인 흐름을 사용하세요."
        ),
    )


@app.get("/api/v1/dispenser/requests/{request_id}")
def dispenser_request_status(request_id: str):
    store = require_dispenser_store()
    record = store.get(request_id)
    if record is None:
        raise HTTPException(status_code=404, detail="디스펜서 요청 기록이 없습니다.")
    if record.get("state") == "recovery_required":
        robot_record = ros_bridge.lookup_dispenser_request(
            request_id, str(record.get("detection_id") or "")
        )
        if robot_record is not None:
            restored = store.apply_robot_result(robot_record)
            if restored is not None:
                record = restored
    return record


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


@app.get("/api/v1/navigation/route/config")
def get_navigation_route_config():
    if not isinstance(equipment_store, MapSpatialConfigStore):
        return {"route": None, "spatial_context": {"registration_ready": True}}
    stored = equipment_store.get_route()
    return {
        "route": stored.model_dump(mode="json") if stored else None,
        "spatial_context": equipment_store.context(),
    }


@app.put("/api/v1/navigation/route/config")
def save_navigation_route_config(route: NavigationRoute):
    validate_route_equipment(route)
    if not isinstance(equipment_store, MapSpatialConfigStore):
        return {"route": route.model_dump()}
    try:
        stored = equipment_store.save_route(route)
    except SpatialContextUnavailableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"route": stored.model_dump(mode="json")}


@app.delete("/api/v1/navigation/route/config")
def delete_navigation_route_config():
    if not isinstance(equipment_store, MapSpatialConfigStore):
        return {"deleted": False}
    try:
        return {"deleted": equipment_store.delete_route()}
    except SpatialContextUnavailableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/v1/navigation/route/recommend")
def recommend_navigation_route(route: NavigationRoute):
    validate_route_equipment(route)
    return ros_bridge.recommend_route(route.model_dump())


@app.post("/api/v1/navigation/route")
def start_navigation_route(route: NavigationRoute):
    require_patrol_mode()
    validate_route_equipment(route)
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


async def stream_cloud(websocket: WebSocket, store) -> None:
    await websocket.accept()
    sequence = None
    try:
        while True:
            item = store.packet_after(sequence)
            if item is not None:
                sequence, packet = item
                await websocket.send_bytes(packet)
            await asyncio.sleep(0.2)
    except (WebSocketDisconnect, RuntimeError):
        return


@app.websocket("/ws/pointcloud")
async def point_cloud(websocket: WebSocket):
    await stream_cloud(websocket, point_cloud_store)


@app.websocket("/ws/pointcloud/thermal")
async def thermal_point_cloud(websocket: WebSocket):
    await stream_cloud(websocket, thermal_cloud_store)


@app.websocket("/ws/pointcloud/thermal/delta")
async def thermal_point_cloud_delta(websocket: WebSocket):
    """Replay missing HGTD packets, then relay newly received bytes unchanged."""
    await websocket.accept()
    bootstrap = thermal_delta_store.bootstrap()
    session_id = websocket.query_params.get("session_id", "")
    fingerprint = websocket.query_params.get("geometry_fingerprint", "")
    try:
        base_sequence = int(websocket.query_params.get("base_sequence", "0"))
    except ValueError:
        await websocket.send_json({"status": "RESYNC_REQUIRED", "reason": "invalid_sequence"})
        await websocket.close(code=1008)
        return
    recovery = thermal_delta_store.recover(
        session_id=session_id,
        geometry_fingerprint=fingerprint,
        base_sequence=base_sequence,
    )
    await websocket.send_json({
        "status": recovery.status,
        "reason": recovery.reason or None,
        "session_id": bootstrap["session_id"],
        "geometry_fingerprint": bootstrap["geometry_fingerprint"],
        "protocol_version": bootstrap["protocol_version"],
        "latest_sequence": bootstrap["latest_sequence"],
        "snapshot_fallback_websocket": "/ws/pointcloud/thermal",
    })
    if recovery.status == "RESYNC_REQUIRED":
        await websocket.close(code=1008)
        return
    cursor = base_sequence
    try:
        while True:
            recovery = thermal_delta_store.recover(
                session_id=session_id,
                geometry_fingerprint=fingerprint,
                base_sequence=cursor,
            )
            if recovery.status == "RESYNC_REQUIRED":
                await websocket.send_json({
                    "status": "RESYNC_REQUIRED",
                    "reason": recovery.reason,
                    "snapshot_fallback_websocket": "/ws/pointcloud/thermal",
                })
                await websocket.close(code=1008)
                return
            for packet in recovery.packets:
                await websocket.send_bytes(packet)
                # Metadata inspection is constant-size/count validation and
                # does not unpack or rebuild voxel records.
                cursor = int.from_bytes(packet[8:16], "little")
            await asyncio.sleep(0.1)
    except (WebSocketDisconnect, RuntimeError):
        return


@app.websocket("/ws/teleop")
async def simulation_teleop(websocket: WebSocket):
    """Receive hold-to-drive simulator commands with a server-side dead man."""

    await websocket.accept()
    ready, message = simulation_teleop_readiness()
    if not ready:
        await websocket.send_json({"accepted": False, "direction": "stop", "message": message})
        await websocket.close(code=1008, reason="simulation teleop unavailable")
        return

    await websocket.send_json(
        {"accepted": True, "direction": "stop", "message": message}
    )
    moving = False
    try:
        while True:
            ready, message = simulation_teleop_readiness()
            if not ready:
                ros_bridge.stop_simulation_teleop()
                await websocket.send_json(
                    {"accepted": False, "direction": "stop", "message": message}
                )
                await websocket.close(code=1008, reason="simulation teleop disabled")
                return
            try:
                payload = await asyncio.wait_for(
                    websocket.receive_json(),
                    timeout=0.35,
                )
            except asyncio.TimeoutError:
                if moving:
                    ros_bridge.stop_simulation_teleop()
                    moving = False
                    await websocket.send_json(
                        {
                            "accepted": True,
                            "direction": "stop",
                            "message": "조작 신호가 끊겨 자동 정지했습니다.",
                        }
                    )
                continue

            direction = payload.get("direction") if isinstance(payload, dict) else None
            if direction not in {"forward", "backward", "left", "right", "stop"}:
                ros_bridge.stop_simulation_teleop()
                moving = False
                await websocket.send_json(
                    {
                        "accepted": False,
                        "direction": "stop",
                        "message": "지원하지 않는 시뮬레이션 조작 명령입니다.",
                    }
                )
                continue
            # Saved-map modes run Nav2 on the same /cmd_vel. Hand the wheel
            # over on the first key press instead of letting the two fight.
            if (
                direction != "stop"
                and not moving
                and system_mode_status().get("mode")
                in {"patrol", "rgbd_mapping"}
            ):
                ros_bridge.cancel_route()
                ros_bridge.cancel_navigation()
            result = ros_bridge.publish_simulation_teleop(direction)
            moving = bool(result.get("accepted") and direction != "stop")
            await websocket.send_json(result)
    except (WebSocketDisconnect, RuntimeError):
        return
    finally:
        ros_bridge.stop_simulation_teleop()
