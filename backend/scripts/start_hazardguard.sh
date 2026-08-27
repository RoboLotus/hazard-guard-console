#!/usr/bin/env bash
set -Eeuo pipefail

# This launcher intentionally lives outside either Git checkout.  Only the
# application and ROS build products are discovered at runtime.
STATE_DIR="/home/jetson/.local/state/hazardguard-standalone"
PID_FILE="${STATE_DIR}/backend.pid"
PROCESS_FILE="${STATE_DIR}/processes.pid"
LOCK_FILE="${STATE_DIR}/backend.lock"
LOG_DIR="${STATE_DIR}/logs"
BAG_STORAGE_ROOT="/home/jetson/.local/share/hazard_guard/bags"
BACKEND_PYTHON="/home/jetson/venvs/hazard-guard-web/bin/python"
PORT=8000

mkdir -p "${STATE_DIR}" "${LOG_DIR}" "${BAG_STORAGE_ROOT}"

die() {
  printf '오류: %s\n' "$*" >&2
  printf '\n실행하지 못했습니다. 위 오류를 확인한 뒤 Enter를 누르세요.\n'
  read -r _ || true
  exit 1
}

find_workspace() {
  local candidate
  for candidate in \
    /home/jetson/RoboLotus/hazard-guard-robot \
    /home/jetson/hazard-guard-robot; do
    if [[ -f "${candidate}/install/setup.bash" ]] && \
       [[ -f "${candidate}/src/hazard_guard_simulation/launch/physical_mapping.launch.py" ]]; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done
  return 1
}

find_console() {
  local candidate
  for candidate in \
    /home/jetson/RoboLotus/hazard-guard-console \
    /home/jetson/hazard-guard-console; do
    if [[ -f "${candidate}/backend/app/main.py" ]] && \
       grep -q 'physical_mapping.launch.py' "${candidate}/backend/app/mode_manager.py" 2>/dev/null; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done
  return 1
}

ROBOT_WORKSPACE="$(find_workspace)" \
  || die '실물 로봇용 HazardGuard ROS 빌드를 찾지 못했습니다.'
CONSOLE_ROOT="$(find_console)" \
  || die '실물 관리 모드를 지원하는 HazardGuard FastAPI를 찾지 못했습니다.'
BACKEND_DIR="${CONSOLE_ROOT}/backend"

[[ -x "${BACKEND_PYTHON}" ]] \
  || die "FastAPI Python 환경이 없습니다: ${BACKEND_PYTHON}"

exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
  printf 'HazardGuard가 이미 실행 중입니다.\n'
  printf '종료하려면 바탕화면의 "HazardGuard 전체 종료"를 사용하세요.\n'
  sleep 3
  exit 0
fi

if ss -ltnH "sport = :${PORT}" 2>/dev/null | grep -q .; then
  die "TCP ${PORT} 포트를 다른 프로그램이 사용 중입니다."
fi

HOST=""
if command -v tailscale >/dev/null 2>&1; then
  HOST="$(tailscale ip -4 2>/dev/null | head -n 1 || true)"
fi
HOST="${HOST:-0.0.0.0}"

set +u
source "${ROBOT_WORKSPACE}/install/setup.bash"
set -u

ros2 pkg prefix hazard_guard_bag_recorder >/dev/null 2>&1 \
  || die 'ROS Bag recorder 빌드를 찾지 못했습니다. Robot 작업공간을 재빌드하세요.'
ros2 pkg prefix hazard_guard_thermal_analysis >/dev/null 2>&1 \
  || die '열화상 분석 패키지 빌드를 찾지 못했습니다. Robot 작업공간을 재빌드하세요.'

THERMAL_CALIBRATION_DIR="/home/jetson/.local/share/hazard_guard/calibration"
[[ -r "${THERMAL_CALIBRATION_DIR}/thermal_intrinsics.yaml" ]] \
  || die "열화상 내부 캘리브레이션 파일이 없습니다: ${THERMAL_CALIBRATION_DIR}/thermal_intrinsics.yaml"
[[ -r "${THERMAL_CALIBRATION_DIR}/thermal_rgb_extrinsic.yaml" ]] \
  || die "열화상 외부 캘리브레이션 파일이 없습니다: ${THERMAL_CALIBRATION_DIR}/thermal_rgb_extrinsic.yaml"

# Load machine-local feature flags that are shared with interactive SSH
# sessions.  The launcher keeps the tested physical-run overrides below, but
# values that were previously missing here (for example RGB-D registration)
# must not silently fall back to unsafe defaults.
RUNTIME_ENV="/home/jetson/.config/hazard-guard/runtime.env"
if [[ -r "${RUNTIME_ENV}" ]]; then
  # Runtime overrides must reach FastAPI and every ROS process it launches.
  # Plain assignments sourced without allexport stay local to this shell and
  # silently fall back to application defaults in child processes.
  set -a
  # shellcheck disable=SC1090
  source "${RUNTIME_ENV}"
  set +a
fi

# Physical WebUI-managed defaults selected by the Jetson load test.
export ROS_DOMAIN_ID=61
export ROS_LOCALHOST_ONLY=1
export ROBOT_TYPE=M1
export RPLIDAR_TYPE=tmini
export CAMERA_TYPE=nuwa
export INIT_SERVO_S1=90
export INIT_SERVO_S2=30
export HAZARD_GUARD_MODE_CONTROL_ENABLED=1
export HAZARD_GUARD_DEPLOYMENT_TARGET=physical
export HAZARD_GUARD_WORKSPACE="${ROBOT_WORKSPACE}"
export HAZARD_GUARD_ROS_ENABLED=1
# Keep dispensing fail-closed until shared Rosmaster serial-port ownership and
# the physical interlocks have been validated on the robot.
export HAZARD_GUARD_DISPENSER_DROP_ENABLED=0
export HAZARD_GUARD_RGB_TOPIC=/ascamera_hp60c/camera_publisher/rgb0/image
export HAZARD_GUARD_RGB_INFO_TOPIC=/ascamera_hp60c/camera_publisher/rgb0/camera_info
export HAZARD_GUARD_DEPTH_TOPIC=/ascamera_hp60c/camera_publisher/depth0/image_raw
export HAZARD_GUARD_DEPTH_INFO_TOPIC=/ascamera_hp60c/camera_publisher/depth0/camera_info
export HAZARD_GUARD_SCAN_TOPIC=/scan
export HAZARD_GUARD_IMU_TOPIC=/imu/data_raw
export HAZARD_GUARD_ODOM_TOPIC=/odom
export YOLO_AUTOINSTALL=false
export HAZARD_GUARD_PERSON_SAFETY_ENABLED="${HAZARD_GUARD_PERSON_SAFETY_ENABLED:-1}"
export HAZARD_GUARD_PERSON_CAMERA_START="${HAZARD_GUARD_PERSON_CAMERA_START:-1}"
export HAZARD_GUARD_PERSON_MODEL_PATH=/home/jetson/ultralytics/ultralytics/yolo11n.engine
export HAZARD_GUARD_PERSON_DEVICE=cuda:0
export HAZARD_GUARD_PERSON_DEPTH_REGISTERED=1
# ROS 2 rejects command-line launch overrides in the form ``name:=`` even
# when the feature using them is disabled.  Keep every optional physical
# patrol argument non-empty so mapping can transition directly to patrol.
# ThermoEye TMC160F Y16 is Kelvin x 100. Enable the camera, calibrated 3D
# projection, WebUI stream, and patrol-time thermal analysis together.
export HAZARD_GUARD_THERMAL_PIPELINE_ENABLED=1
export HAZARD_GUARD_THERMAL_MAPPING_ENABLED=1
export HAZARD_GUARD_THERMAL_TOPIC=/thermal_camera/image_raw
export HAZARD_GUARD_THERMAL_INFO_TOPIC=/thermal_camera/camera_info
export HAZARD_GUARD_THERMAL_CLOUD_TOPIC=/hazard_guard/thermal/map
export HAZARD_GUARD_THERMAL_SCALE=0.01
export HAZARD_GUARD_THERMAL_OFFSET_C=-273.15
export HAZARD_GUARD_THERMAL_ROI_CONFIG="${HAZARD_GUARD_THERMAL_ROI_CONFIG:-${ROBOT_WORKSPACE}/src/hazard_guard_thermal_analysis/config/demo_facility_scaled_rois.json}"
export HAZARD_GUARD_THERMAL_BASELINE_PATH="/home/jetson/.local/share/hazard_guard/physical_thermal_baselines.json"
export HAZARD_GUARD_THERMAL_HISTORY_PATH="/home/jetson/.local/share/hazard_guard/physical_thermal_history.jsonl"
export HAZARD_GUARD_THERMAL_AIR_TOPIC=/hazard_guard/thermal/air_temperature_disabled
export HAZARD_GUARD_THERMAL_OIL_TOPIC=/hazard_guard/thermal/oil_temperature_disabled
export HAZARD_GUARD_POINT_CLOUD_TOPIC="${HAZARD_GUARD_POINT_CLOUD_TOPIC:-/hazard_guard/rtabmap/cloud_surface}"
export HAZARD_GUARD_POINT_CLOUD_MAX_POINTS=100000
export HAZARD_GUARD_POINT_CLOUD_INTERVAL_SEC=0.75
export HAZARD_GUARD_CLOUD_NORMAL_POINTS=9000
export HAZARD_GUARD_CLOUD_HIGH_LOAD_POINTS=4500
export HAZARD_GUARD_CLOUD_NORMAL_INPUT_HZ=8.0
export HAZARD_GUARD_CLOUD_HIGH_LOAD_INPUT_HZ=4.0
export HAZARD_GUARD_CLOUD_NORMAL_SURFACE_HZ=1.0
export HAZARD_GUARD_CLOUD_HIGH_LOAD_SURFACE_HZ=0.5
export HAZARD_GUARD_CLOUD_DECIMATION=2
export HAZARD_GUARD_CLOUD_VOXEL_SIZE=0.03
export HAZARD_GUARD_CLOUD_LINEAR_UPDATE=0.10
export HAZARD_GUARD_CLOUD_ANGULAR_UPDATE=0.10472

printf '%s\n' "$$" >"${PID_FILE}"
bag_pid=""
backend_pid=""

write_state() {
  local temp_file="${PROCESS_FILE}.tmp.$$"
  {
    printf 'START_PID=%s\n' "$$"
    printf 'BAG_PID=%s\n' "${bag_pid}"
    printf 'BACKEND_PID=%s\n' "${backend_pid}"
  } >"${temp_file}"
  mv -f "${temp_file}" "${PROCESS_FILE}"
}

group_alive() {
  [[ "$1" =~ ^[0-9]+$ ]] && kill -0 -- "-$1" 2>/dev/null
}

stop_group() {
  local pid="$1"
  local signal_name tick
  [[ "${pid}" =~ ^[0-9]+$ ]] || return 0
  group_alive "${pid}" || return 0
  for signal_name in INT TERM KILL; do
    kill -s "${signal_name}" -- "-${pid}" 2>/dev/null || true
    for tick in $(seq 1 20); do
      group_alive "${pid}" || return 0
      sleep 0.25
    done
  done
}

cleanup() {
  local status=$?
  trap - EXIT INT TERM HUP
  set +e
  stop_group "${backend_pid}"
  stop_group "${bag_pid}"
  [[ -n "${backend_pid}" ]] && wait "${backend_pid}" 2>/dev/null
  [[ -n "${bag_pid}" ]] && wait "${bag_pid}" 2>/dev/null
  rm -f "${PID_FILE}" "${PROCESS_FILE}" "${PROCESS_FILE}.tmp.$$"
  exit "${status}"
}
trap cleanup EXIT
trap 'exit 0' INT TERM HUP

# Do not reuse a ros2 daemon created for another domain when checking the
# recorder service in this isolated local graph.
ros2 daemon stop >/dev/null 2>&1 || true

printf 'ROS Bag recorder를 시작합니다.\n'
setsid ros2 launch hazard_guard_bag_recorder bag_record.launch.py \
  storage_root:="${BAG_STORAGE_ROOT}" \
  auto_start:=false \
  enable_control_services:=true \
  >"${LOG_DIR}/rosbag-recorder.log" 2>&1 9>&- &
bag_pid=$!
write_state

for _ in $(seq 1 40); do
  ros2 service list 2>/dev/null \
    | grep -Fxq /hazard_guard/bag/control && break
  group_alive "${bag_pid}" \
    || die "ROS Bag recorder가 시작 중 종료됐습니다: ${LOG_DIR}/rosbag-recorder.log"
  sleep 0.5
done
ros2 service list 2>/dev/null | grep -Fxq /hazard_guard/bag/control \
  || die "ROS Bag 제어 서비스를 찾지 못했습니다: ${LOG_DIR}/rosbag-recorder.log"

printf '\nHazardGuard 실물 주행 백엔드\n'
printf '  FastAPI:       http://%s:%s\n' "${HOST}" "${PORT}"
printf '  로봇 구성:     WebUI 관리형 FastAPI + ROS Bag recorder\n'
printf '  ROS Bag:       WebUI ON/OFF 대기, %s\n' "${BAG_STORAGE_ROOT}"
printf '  디스펜서:     안전모드 (물리 배출 차단, 노드 미기동)\n'
printf '  3D 기본값:     9,000 points, decimation 2, voxel 0.03 m\n'
printf '  열화상:       카메라 + 3D 투영 + 분석 + WebUI 스트림 활성\n'
printf '  ROS:           domain 61, localhost only\n'
printf '  코드 위치:     실행 시 자동 탐색 (Git 브랜치/스크립트 경로 비의존)\n'
printf '\n노트북 WebUI를 위 주소에 연결한 뒤 운용 모드를 선택하세요.\n'
printf '실제 주행 전 주변 안전과 비상 전원 차단 수단을 확인하세요.\n\n'

cd "${BACKEND_DIR}"
setsid "${BACKEND_PYTHON}" -m uvicorn app.main:app \
  --host "${HOST}" --port "${PORT}" 9>&- &
backend_pid=$!
write_state
set +e
ended_pid=""
wait -n -p ended_pid "${backend_pid}" "${bag_pid}"
status=$?
set -e

if [[ "${ended_pid}" == "${bag_pid}" ]]; then
  printf '\nROS Bag recorder가 종료되었습니다. 로그: %s\n' \
    "${LOG_DIR}/rosbag-recorder.log" >&2
elif ((status != 0 && status != 130 && status != 143)); then
  printf '\nFastAPI가 오류 코드 %s로 종료되었습니다.\n' "${status}" >&2
fi
if ((status != 0 && status != 130 && status != 143)) \
  || [[ "${ended_pid}" == "${bag_pid}" ]]; then
  printf '확인 후 Enter를 누르세요.\n' >&2
  read -r _ || true
fi
exit "${status}"
