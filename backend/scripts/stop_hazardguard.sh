#!/usr/bin/env bash
set -u

STATE_DIR="/home/jetson/.local/state/hazardguard-standalone"
PID_FILE="${STATE_DIR}/backend.pid"
PROCESS_FILE="${STATE_DIR}/processes.pid"

printf 'HazardGuard 전체 종료를 요청합니다.\n'

hazardguard_ros_groups() {
  local pid pgid
  while read -r pid; do
    [[ -n "${pid}" ]] || continue
    pgid="$(ps -o pgid= -p "${pid}" 2>/dev/null | tr -d '[:space:]')"
    [[ "${pgid}" =~ ^[0-9]+$ ]] && printf '%s\n' "${pgid}"
  done < <(
    pgrep -f \
      'ros2 launch (hazard_guard_simulation physical_(mapping|patrol|rgbd_mapping)\.launch\.py|hazard_guard_bag_recorder bag_record\.launch\.py)' \
      2>/dev/null || true
  ) | sort -u
}

group_exists() {
  kill -0 -- "-$1" 2>/dev/null
}

stop_group() {
  local pgid="$1"
  local signal_name timeout_ticks tick
  group_exists "${pgid}" || return 0

  for signal_name in INT TERM KILL; do
    case "${signal_name}" in
      INT) timeout_ticks=16 ;;
      TERM) timeout_ticks=6 ;;
      KILL) timeout_ticks=4 ;;
    esac
    group_exists "${pgid}" \
      && kill -s "${signal_name}" -- "-${pgid}" 2>/dev/null || true
    for tick in $(seq 1 "${timeout_ticks}"); do
      group_exists "${pgid}" || return 0
      sleep 0.5
    done
  done
  ! group_exists "${pgid}"
}

stop_recorded_group() {
  local pid="$1"
  local expected_cmdline="$2"
  local label="$3"
  local cmdline pgid

  [[ "${pid}" =~ ^[0-9]+$ ]] || return 1
  [[ -r "/proc/${pid}/cmdline" ]] || return 1
  cmdline="$(tr '\0' ' ' <"/proc/${pid}/cmdline")"
  [[ "${cmdline}" == *"${expected_cmdline}"* ]] || return 1
  pgid="$(ps -o pgid= -p "${pid}" 2>/dev/null | tr -d '[:space:]')"
  [[ "${pgid}" =~ ^[0-9]+$ ]] || return 1

  printf '상태 파일에 남은 HazardGuard %s 그룹을 종료합니다: %s\n' \
    "${label}" "${pgid}"
  if ! stop_group "${pgid}"; then
    printf 'HazardGuard %s 그룹 %s 종료에 실패했습니다.\n' \
      "${label}" "${pgid}" >&2
    return 2
  fi
  return 0
}

stop_recorded_groups() {
  local bag_pid="" backend_pid="" result=1 status
  [[ -r "${PROCESS_FILE}" ]] || return 1

  bag_pid="$(sed -n 's/^BAG_PID=//p' "${PROCESS_FILE}" | head -n 1)"
  backend_pid="$(sed -n 's/^BACKEND_PID=//p' "${PROCESS_FILE}" | head -n 1)"

  stop_recorded_group \
    "${backend_pid}" \
    '/home/jetson/venvs/hazard-guard-web/bin/python -m uvicorn app.main:app' \
    'FastAPI'
  status=$?
  ((status == 0)) && result=0
  ((status == 2)) && result=2

  stop_recorded_group \
    "${bag_pid}" \
    'ros2 launch hazard_guard_bag_recorder bag_record.launch.py' \
    'ROS Bag recorder'
  status=$?
  ((status == 0 && result != 2)) && result=0
  ((status == 2)) && result=2

  rm -f "${PROCESS_FILE}"
  return "${result}"
}

stop_orphaned_ros_groups() {
  local -a groups=()
  local pgid signal_name timeout_ticks tick
  mapfile -t groups < <(hazardguard_ros_groups)
  ((${#groups[@]} > 0)) || return 1

  printf '남아 있는 HazardGuard ROS 프로세스 그룹을 종료합니다: %s\n' \
    "${groups[*]}"
  for pgid in "${groups[@]}"; do
    if ! stop_group "${pgid}"; then
      printf 'ROS 프로세스 그룹 %s 종료에 실패했습니다.\n' "${pgid}" >&2
      return 2
    fi
  done
  return 0
}

backend_stopped="false"

if [[ -r "${PID_FILE}" ]]; then
  pid="$(tr -cd '0-9' <"${PID_FILE}")"
  if [[ -z "${pid}" ]] || [[ ! -r "/proc/${pid}/cmdline" ]]; then
    rm -f "${PID_FILE}"
  else
    cmdline="$(tr '\0' ' ' <"/proc/${pid}/cmdline")"
    case "${cmdline}" in
      *'.hazardguard-standalone/start.sh'*|*'/backend/scripts/start_hazardguard.sh'*)
        kill -TERM "${pid}" 2>/dev/null || true

        # FastAPI lifespan이 자신이 시작한 ROS 그룹과 지도 저장을 정리할 시간을 준다.
        for _ in $(seq 1 60); do
          if ! kill -0 "${pid}" 2>/dev/null; then
            rm -f "${PID_FILE}"
            backend_stopped="true"
            break
          fi
          sleep 0.5
        done
        ;;
      *)
        printf '안전을 위해 PID가 다른 프로세스를 가리켜 종료하지 않았습니다.\n' >&2
        rm -f "${PID_FILE}"
        ;;
    esac
  fi
fi

recorded_status=1
stop_recorded_groups
recorded_status=$?
if ((recorded_status == 2)); then
  printf '상태 파일의 일부 프로세스가 남아 있습니다.\n' >&2
  sleep 4
  exit 1
fi

# 백엔드가 비정상 종료되면 start_new_session으로 실행한 ROS launch가
# systemd --user 아래에 고아 프로세스 그룹으로 남을 수 있다. PID 파일이
# 없어도 해당 HazardGuard launch 그룹만 찾아 정리한다.
orphan_status=1
stop_orphaned_ros_groups
orphan_status=$?
if ((orphan_status == 2)); then
  printf '일부 ROS 프로세스가 남아 있습니다. 실행 터미널의 로그를 확인하세요.\n' >&2
  sleep 4
  exit 1
fi

if [[ "${backend_stopped}" == "true" ]] \
  || ((recorded_status == 0)) \
  || ((orphan_status == 0)); then
  printf 'FastAPI, ROS Bag recorder와 관리 중인 ROS 주행 구성을 정상 종료했습니다.\n'
else
  printf '이미 종료된 상태입니다.\n'
fi
sleep 2
exit 0
