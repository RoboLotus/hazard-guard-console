import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
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
)
from .mode_manager import system_mode_manager
from .models import (
    CommandRequest,
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
from .settings_store import ThermalEquipmentSettingsStore, ThresholdSettingsStore


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

threshold_store = ThresholdSettingsStore()
performance_report_store = PerformanceReportStore()
equipment_store = ThermalEquipmentSettingsStore()


def equipment_settings_response(
    settings: ThermalEquipmentSettingsDocument,
) -> dict:
    return {
        **settings.model_dump(by_alias=True),
        "runtime": ros_bridge.thermal_equipment_config_status(),
    }


def validate_route_equipment(route: NavigationRoute) -> None:
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


@app.get("/api/v1/robot/status", response_model=RobotTelemetry)
def robot_status():
    return telemetry_store.snapshot()


@app.get("/api/v1/system/mode")
def system_mode():
    return system_mode_status()


@app.put("/api/v1/system/mode")
def update_system_mode(request: SystemModeRequest):
    ros_bridge.cancel_route()
    ros_bridge.cancel_navigation()
    ros_bridge.stop_motion()
    if request.mode in {"patrol", "rgbd_mapping"}:
        current_pose = spatial_store.snapshot().get("pose") or {}
        if current_pose.get("available") and not current_pose.get("mock"):
            system_mode_manager.set_localization_pose(current_pose)
    result = system_mode_manager.switch_mode(
        request.mode,
        mapping_profile=request.mapping_profile,
        patrol_slam=request.patrol_slam,
    )
    if not result["accepted"]:
        raise HTTPException(status_code=409, detail=result["message"])
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
        spatial_store.reset_for_localization()
    return result


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
    spatial_store.reset_for_localization()
    result = ros_bridge.publish_initial_pose(request.x, request.y, request.yaw)
    if not result["accepted"]:
        raise HTTPException(status_code=409, detail=result["message"])
    return result


@app.delete("/api/v1/system/mode")
def stop_system_mode():
    ros_bridge.cancel_route()
    ros_bridge.cancel_navigation()
    ros_bridge.stop_motion()
    return system_mode_manager.stop()


@app.post("/api/v1/system/map/save")
def save_system_map():
    result = system_mode_manager.save_map()
    if not result["accepted"]:
        raise HTTPException(status_code=409, detail=result["message"])
    return result


@app.post("/api/v1/system/map/save-and-stop")
def save_and_stop_system_map():
    result = system_mode_manager.save_map_and_stop()
    if not result["accepted"]:
        raise HTTPException(status_code=409, detail=result["message"])
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
    # The colour window is the robot node's, and there is no channel back from
    # it - so both sides read the same defaults, overridable in one place.
    return {
        **thermal_cloud_store.status(),
        "min_temp_c": float(os.getenv("HAZARD_GUARD_THERMAL_MIN_C", "10.0")),
        "max_temp_c": float(os.getenv("HAZARD_GUARD_THERMAL_MAX_C", "60.0")),
    }


@app.get("/api/v1/system/sensors")
def sensor_diagnostics():
    return sensor_diagnostics_store.snapshot(ros_active=ros_bridge.active)


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


@app.put("/api/v1/settings/equipment")
def update_equipment_settings(
    settings: ThermalEquipmentSettingsDocument,
):
    saved = equipment_store.save(settings)
    ros_bridge.publish_thermal_equipment_config(saved.model_dump(by_alias=True))
    return equipment_settings_response(saved)


@app.post("/api/v1/settings/equipment/reset-defaults")
def reset_equipment_settings():
    saved = equipment_store.reset_defaults()
    ros_bridge.publish_thermal_equipment_config(saved.model_dump(by_alias=True))
    return equipment_settings_response(saved)

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
