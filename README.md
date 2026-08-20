# HazardGuard Console

산업 현장을 순찰하는 ROSMASTER-M1 기반 안전 로봇의 관제 WebUI 프로토타입입니다. React 대시보드와 FastAPI ROS bridge를 통해 로봇 상태, 2D SLAM 지도, RTAB-Map RGB-D 컬러 3D 지도, 캘리브레이션으로 온도를 입힌 열화상 3D 지도,
RGB·ThermoEye TMC160B 사양 기반 합성 열화상 영상, 위험 이벤트, Nav2 목적지와 열원 히트맵을 확인합니다.

## 구성

```text
WebUI/
├─ frontend/   React 19 + Vite
└─ backend/    FastAPI + WebSocket + 선택적 ROS 2 bridge
```

실제 로봇이 없어도 Windows mock 모드로 UI를 실행할 수 있으며, WSL2에서는 Gazebo, ROS 2 Humble, SLAM Toolbox, Nav2와 연결할 수 있습니다.

## 빠른 실행

실제 ROS 2와 연결하지 않고 UI와 FastAPI mock 데이터를 확인하는 방법입니다.
Node.js 20 이상과 Python 3.10 이상을 권장합니다.

첫 번째 Windows PowerShell에서 백엔드를 실행합니다.

```powershell
cd D:\Develop\hazard-guard\WebUI\backend
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

가상환경과 의존성이 이미 준비되어 있다면 생성·설치 명령은 생략해도 됩니다.

두 번째 Windows PowerShell에서 프런트엔드를 실행합니다.

```powershell
cd D:\Develop\hazard-guard\WebUI\frontend
npm ci
npm run dev
```

브라우저에서 `http://127.0.0.1:5173/`을 엽니다. Vite 개발 서버는 `/api`와
`/ws` 요청을 `http://127.0.0.1:8000`으로 전달합니다.

### 순찰 성능 리포트 경로

`리포트` 탭은 Robot의 성능 모니터가 생성한 순찰별 CPU·GPU·RAM 보고서를
읽습니다. Robot과 FastAPI를 같은 Jetson 사용자로 실행하면 기본 경로를 자동으로
공유합니다.

```text
~/.local/share/hazard-guard/performance
```

Docker, 다른 사용자 또는 별도 저장장치를 사용할 때는 Robot launch와 FastAPI에
동일한 경로를 지정해야 합니다.

```bash
export HAZARD_GUARD_PERFORMANCE_DIR=/data/hazard-guard/performance
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

리포트 탭에서는 완료된 임무의 평균·중앙값·P95·최댓값, CPU 코어와 주요 ROS
프로세스별 부하를 확인할 수 있습니다. 이름 변경은 보고서 메타데이터와 Markdown
제목에 함께 반영됩니다. 삭제는 해당 임무의 원본 JSONL·CSV·JSON·Markdown을
모두 제거하며 되돌릴 수 없으므로 확인 창을 거칩니다.

Gazebo와 ROS 2를 연결한 전체 시뮬레이션은 로컬 Docker 컨테이너에서 FastAPI를
실행한 뒤 WebUI의 `지도` 탭에 있는 `지도 운용 모드`에서 `맵 생성` 또는
`순찰`을 선택합니다. 이때 WebUI가 Gazebo·SLAM Toolbox·AMCL·Nav2 launch를
직접 관리하므로 별도 터미널에서 같은 launch를 동시에 실행하지 않습니다.

```bash
cd /mnt/d/Develop/hazard-guard/local-docker
docker compose -f compose.robot.yaml up -d
docker compose -f compose.robot.yaml exec robot bash -lc \
  'source /opt/ros/humble/setup.bash &&
   source /workspace/install/setup.bash &&
   cd /webui/backend &&
   uvicorn app.main:app --host 0.0.0.0 --port 8000'
```

최초 실행이거나 Robot 소스가 변경됐다면 API 실행 전에 컨테이너에서 빌드합니다.

```bash
docker compose -f compose.robot.yaml exec robot bash -lc \
  'source /opt/ros/humble/setup.bash &&
   cd /workspace &&
   colcon build --symlink-install'
```

별도 PowerShell에서 WebUI를 실행합니다.

```powershell
cd D:\Develop\hazard-guard\WebUI\frontend
npm ci
npm run dev
```

브라우저에서 `http://127.0.0.1:5173/`을 엽니다.

## 맵 생성·순찰 모드

| WebUI 모드 | ROS 구성 | 용도 |
|---|---|---|
| 맵 생성 | SLAM Toolbox + Gazebo | 처음 방문한 공간을 수동 주행하며 점유 지도를 작성 |
| 순찰 | Map Server + AMCL + Nav2 + Gazebo | 저장된 지도에서 위치를 추정하고 웨이포인트를 자율 순찰 |

`맵 생성 → 순찰` 전환 시 WebUI 백엔드는 현재 `/map`을
`Robot/runtime/maps/facility.yaml`과 `facility.pgm`으로 먼저 저장합니다. 지도가
없으면 순찰 모드는 시작하지 않고 원인을 화면에 표시합니다. 지도 상세 화면의
`ROS 지도 저장` 버튼으로도 명시적으로 저장할 수 있습니다.

맵 생성 모드에서는 단일 목적지 이동과 웨이포인트 순찰 명령이 차단됩니다.
웨이포인트 영역의 `순찰 모드로 전환` 버튼을 누르거나 지도 운용 모드에서
`순찰 / AMCL·Nav2`를 선택하십시오. 모드 상태가 `실행 중`으로 바뀐 뒤
`이 순서로 순찰 시작`을 다시 눌러야 합니다. 모드 전환만으로 로봇이 자동
출발하지는 않습니다.

다중 웨이포인트 임무는 FastAPI가 Nav2를 직접 반복 호출하지 않습니다.
FastAPI는 `/hazard_guard/run_patrol` ROS 2 Action으로 임무를 제출하고,
`hazard_guard_mission_manager`가 전체 구간 경로 확인, Nav2 순차 이동,
목표 방향 정렬, 점검 대기와 취소를 담당합니다. 진행 상태는
`/hazard_guard/mission/status`에서 다시 WebUI로 전달됩니다.

지도 탭의 `반복·운영 시간`에서는 즉시 또는 실제 시각 예약 시작을 고르고,
`1회 완료`, `지정 횟수`, `지정 시각`, `수동 종료` 중 하나를 종료 조건으로
선택할 수 있습니다. 반복 임무는 회차 사이 대기시간을 분 단위로 설정합니다.
예약은 ROS 임무 관리자에서 실행되므로 WebUI를 새로고침해도 유지되지만,
Jetson을 재부팅하면 다시 등록해야 합니다. 실제 시각 운용 전에는 Jetson의 NTP
동기화를 확인하십시오.

터미널에서 시작한 기존 SLAM 또는 Nav2가 감지되면 WebUI는 해당 프로세스를
강제로 종료하지 않습니다. 기존 launch를 터미널에서 종료한 후 WebUI 모드
제어를 사용합니다.

### 실물 순찰의 사람 안전·열화상 기능

실물 Jetson에서 FastAPI가 순찰 모드를 시작할 때 아래 환경 변수를
`physical_patrol.launch.py` 인자로 전달합니다. 두 기능은 실물 검증 전까지
기본적으로 꺼져 있으므로 명시적으로 활성화해야 합니다.

```bash
export HAZARD_GUARD_DEPLOYMENT_TARGET=physical
export HAZARD_GUARD_MODE_CONTROL_ENABLED=1
export HAZARD_GUARD_ROS_ENABLED=1

# ROSMASTER bringup과 동일한 값 사용. 아래는 단일 Jetson 운용 예시입니다.
export ROS_DOMAIN_ID=0
export ROS_LOCALHOST_ONLY=1

# YOLO11n 사람 탐지 → 안전 감독 → Nav2 감속/정지
export HAZARD_GUARD_PERSON_SAFETY_ENABLED=1
export HAZARD_GUARD_PERSON_MODEL_PATH=/absolute/path/to/yolo11n.engine
export HAZARD_GUARD_PERSON_DEVICE=cuda:0
export HAZARD_GUARD_PERSON_RATE_HZ=6.0
export HAZARD_GUARD_PERSON_DEPTH_REGISTERED=1

# 열화상·Depth 융합 및 장기 추세 분석
export HAZARD_GUARD_THERMAL_PIPELINE_ENABLED=1
export HAZARD_GUARD_THERMAL_ROI_CONFIG=/absolute/path/to/rois.json
export HAZARD_GUARD_THERMAL_SCALE=1.0
export HAZARD_GUARD_THERMAL_OFFSET_C=0.0
```

`HAZARD_GUARD_PERSON_DEPTH_REGISTERED=1`은 HP60C의 RGB 픽셀과 Depth 픽셀이
실제로 정합된 것을 확인한 뒤에만 사용합니다. 확인 전에는 안전 감독이
fail-closed 상태를 유지합니다. `PERSON_DEVICE`, 열화상 scale·offset 및 토픽은
Jetson 센서 드라이버의 실제 출력값에 맞춰야 합니다. 사람 안전 상태는
`/hazard_guard/person/safety_state`에서 수신해 지도 탭의 `사람 안전` 항목에
정상·감속·정지·센서 이상으로 표시합니다.

사람 안전 기능을 활성화해도 YOLO는 순찰 모드에서만 실행합니다. 1차 2D 지도
작성과 2차 RGB-D 3D 수집에서는 YOLO 추론 및 사람 안전 감속기를 실행하지
않습니다. 2차 수집에서는 HP60C 카메라만 계속 실행해 RGB·Depth 포인트클라우드를
생성합니다. 따라서 지도 작성은 사람과 장애물을 통제한 시험 공간에서 저속으로
수행해야 합니다. Jetson의 실제 `.env` 또는 `runtime.env`는 Git에 커밋하지 말고,
저장소의 `.env.example`을 복사해 장치별 경로만 설정합니다.

### Jetson 네이티브 ROS Bag·WebUI 연결

Jetson에서는 FastAPI 가상환경이 시스템 ROS Python을 볼 수 있어야 합니다.
일반 `requirements.txt`는 Windows mock 개발용 NumPy·OpenCV까지 설치하므로,
실물 Jetson에서는 다음처럼 전용 최소 requirements를 사용합니다. JetPack이
제공한 NumPy·OpenCV·CUDA PyTorch를 PyPI 패키지로 덮어쓰지 않습니다.

```bash
cd ~/hazard-guard/WebUI/backend
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-jetson.txt
python -c 'import rclpy, cv_bridge, numpy, cv2; print("ROS Python imports OK")'
```

Robot 저장소를 갱신한 뒤 새 서비스 인터페이스와 recorder를 함께 빌드합니다.
`rosdep`은 ROS Bag CLI, 기본 sqlite3 저장 플러그인과 `python3-serial`을
확인·설치합니다. 이미 설치된 항목은 다시 설치하지 않습니다.

```bash
cd ~/hazard-guard/Robot
source /opt/ros/humble/setup.bash
rosdep install --from-paths \
  src/hazard_guard_interfaces \
  src/hazard_guard_bag_recorder \
  src/hazard_guard_dispenser \
  --ignore-src -r -y
colcon build --symlink-install --packages-up-to \
  hazard_guard_bag_recorder hazard_guard_dispenser
source install/setup.bash
```

ROS Bag 노드는 FastAPI와 별도로 한 번 실행해야 합니다. WebUI 제어를 사용할
때만 `enable_control_services:=true`를 명시하고, 대용량 RGB-D 기록은 Jetson의
여유 공간을 확인한 저장 경로로 지정합니다.

```bash
ros2 launch hazard_guard_bag_recorder bag_record.launch.py \
  enable_control_services:=true \
  storage_root:=$HOME/.local/share/hazard_guard/bags
```

같은 셸에서 환경 파일을 실제 환경변수로 내보낸 뒤 FastAPI를 실행합니다.
`.env.example`을 복사하는 것만으로는 자동 적용되지 않습니다.

```bash
cd ~/hazard-guard/WebUI
cp -n .env.example runtime.env
# runtime.env의 장치 경로와 현재 ROS_DOMAIN_ID를 확인한 뒤 실행합니다.
cd backend
source /opt/ros/humble/setup.bash
source ~/hazard-guard/Robot/install/setup.bash
source .venv/bin/activate
set -a
source ../runtime.env
set +a
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

`ROS_DOMAIN_ID`는 실행 중인 ROSMASTER bringup 셸의 값을 그대로 사용해야 합니다.
Robot 노드와 FastAPI ROS 브리지가 모두 같은 Jetson에서 실행되면
`ROS_LOCALHOST_ONLY=1`로 충분하며, 노트북 프런트엔드는 DDS가 아니라 HTTP와
WebSocket으로 연결됩니다. 다른 PC에서도 ROS 2 노드를 직접 실행할 때만 모든
ROS 호스트에서 `ROS_LOCALHOST_ONLY=0`과 같은 `ROS_DOMAIN_ID`를 사용합니다.

디스펜서는 현재 기본값이 `enable_physical_drop=false`라 설치 후에도 실제 서보를
움직이지 않습니다. BLE·Rosmaster 직렬 포트 단일 소유와 정지 가드를 실물로
검증하기 전에는 Robot과 WebUI의 배출 활성화 값을 모두 `false/0`으로 유지합니다.

열화상 3D 뷰어의 기본 입력은 Robot 열화상 융합 노드가 발행하는
`/hazard_guard/thermal/points`입니다. 다른 토픽을 사용할 때만
`HAZARD_GUARD_THERMAL_CLOUD_TOPIC`으로 덮어씁니다.

Docker Desktop의 WebUI 제어는 WSLg 창 연결 여부와 무관하게 동작하도록 Gazebo
GUI를 기본적으로 끈 headless 모드입니다. 브라우저의 2D 지도·RGB·열화상은
계속 표시됩니다. Gazebo 3D 창까지 필요하면 WSL2 셸에서 launch의 `gui:=true`를
사용하되, 이때는 WebUI 모드 제어와 동시에 실행하지 않습니다.

## RGB-D 3D 지도 보기

WebUI의 `지도` 탭에서 `맵 생성`을 선택한 다음 지도 작성 프로필을 고릅니다.

| 지도 작성 프로필 | ROS 구성 | 저장 결과 |
|---|---|---|
| `2D 표준` | SLAM Toolbox | Nav2용 `map.yaml`·`map.pgm` |
| `2D + RGB-D 3D` | SLAM Toolbox + RTAB-Map | 같은 2D 지도 + 세션별 `rtabmap.db` |

`2D + RGB-D 3D` 프로필에서도 Nav2용 `/map`은 SLAM Toolbox가 단독으로
발행합니다. RTAB-Map은 RGB·Depth의 3D 정보를 별도 좌표계에 누적하므로 두
SLAM이 같은 TF나 2D 지도를 중복 발행하지 않습니다. 프로필을 선택하고
`새 맵 생성`을 누른 뒤 로봇을 움직이면 `3D RGB-D` 화면에서 현재 포인트 수와
컬러 지도를 확인할 수 있습니다. 정지한 상태에서는 관측 범위가 늘지 않으므로
3D 지도가 거의 생성되지 않는 것처럼 보일 수 있습니다.

`현재 SLAM 지도 저장` 또는 `현재 2D + 3D 세션 저장`을 누르면 현재 세션의
2D 지도를 저장하고 RTAB-Map DB의 존재와
크기도 세션 메타데이터에 기록합니다. 현재 WebUI는 저장된 3D DB의 과거 장면을
세션 목록의 눈 아이콘으로 다시 열 수 있습니다. 최초 조회 시 백엔드가
`rtabmap-export`를 사용해 컬러 PLY를 생성하며, 같은 파일을 팀원 공유용으로
내려받을 수 있습니다. `지도 저장 후 종료`는 2D 지도와 RTAB-Map DB를 보존한
뒤 WebUI가 시작한 SLAM·Gazebo 프로세스를 함께 종료합니다.

지도 세션은 이름을 붙이거나 보관 상태로 전환할 수 있습니다. 보관은 목록에서
숨기는 기능일 뿐 원본 지도·DB·PLY를 삭제하지 않습니다.

## 센서 진단과 설정 저장

`설정` 화면의 ROS 센서 연결 진단에서 LiDAR, RGB, Depth, 두 CameraInfo,
열화상, IMU, Odometry, 2D 지도와 RTAB-Map 컬러 클라우드의 최근 수신 상태를
확인할 수 있습니다. `실시간`, `데이터 대기`, `갱신 중단`, `ROS 미연결`은
각 토픽의 마지막 수신 시각을 기준으로 표시합니다.

화재 판정 임계값은 브라우저 localStorage뿐 아니라
`Robot/runtime/settings/thresholds.json`에도 원자적으로 저장됩니다. 따라서
FastAPI를 재시작하거나 다른 관제 PC에서 접속해도 서버 설정을 다시 불러옵니다.

Robot 저장소에서 RTAB-Map 실험을 실행한 뒤 WebUI의 `지도` 탭에서
`3D RGB-D`를 선택합니다.

```bash
ros2 launch hazard_guard_simulation rtabmap_sim.launch.py \
  gui:=false \
  rviz:=false \
  demo_route:=true
```

데이터는 다음 순서로 전달됩니다.

1. RGB·Depth 포인트를 RTAB-Map의 `map` 좌표계에 누적해
   `/hazard_guard/rtabmap/cloud_surface`에 X/Y/Z/RGB 포인트를 발행합니다.
2. FastAPI ROS bridge가 포인트 수를 제한하고 브라우저용 바이너리 패킷으로
   변환합니다.
3. `/ws/pointcloud` WebSocket이 스냅샷을 전송합니다.
4. React의 Three.js 뷰어가 점 색상, 높이, 원근을 포함한 3D 지도를 표시합니다.

마우스 왼쪽 버튼은 회전, 오른쪽 버튼은 이동, 휠은 확대·축소입니다. 화면
맞춤 버튼을 누르면 현재 포인트 전체가 보이도록 카메라가 이동합니다.
웨이포인트 작성과 Nav2 순찰 경로 편집은 계속 2D 지도에서 수행합니다.

이 화면은 RViz 화면을 캡처하거나 전송하지 않습니다. ROS의 원본
`PointCloud2` 데이터를 직접 변환하므로 RViz를 실행하지 않아도 동작합니다.
상태 확인 API는 `/api/v1/spatial/cloud/status`입니다. 다른 토픽을 사용할
때는 백엔드 실행 전에 `HAZARD_GUARD_POINT_CLOUD_TOPIC`을 지정할 수 있습니다.

3D RGB-D 화면은 카메라가 실제로 관측한 표면을 복원한 SLAM 결과입니다.
가려졌거나 아직 지나가지 않은 구역은 표시되지 않습니다. Gazebo SDF에 정의된
벽과 메시를 처음부터 완전한 형태로 보여주는 기능은 SLAM이 아니라 별도의
`시뮬레이터 원본 디지털 트윈` 뷰이며, 필요하면 SDF·메시 로더로 분리해
추가해야 합니다.

> 현재 열화상은 TMC160B의 160×120, 수평 57°, 8.7 Hz 형식을 반영한 시뮬레이션 데이터입니다. 지도 부채꼴의 5 m 길이는 시뮬레이션 표시 범위이며 제조사 측정거리 보장이 아닙니다. 실제 화재 판정이나 안전 성능을 검증한 결과도 아닙니다.
