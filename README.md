# HazardGuard Console

산업 현장을 순찰하는 ROSMASTER-M1 기반 안전 로봇의 관제 WebUI 프로토타입입니다. React 대시보드와 FastAPI ROS bridge를 통해 로봇 상태, 2D SLAM 지도, RGB·열화상 영상, 위험 이벤트, Nav2 목적지와 열원 히트맵을 확인합니다.

## 구성

```text
WebUI/
├─ frontend/   React 19 + Vite
└─ backend/    FastAPI + WebSocket + 선택적 ROS 2 bridge
```

실제 로봇이 없어도 Windows mock 모드로 UI를 실행할 수 있으며, WSL2에서는 Gazebo, ROS 2 Humble, SLAM Toolbox, Nav2와 연결할 수 있습니다.

## 빠른 실행

Windows PowerShell:

```powershell
cd D:\Develop\hazard-guard\WebUI
.\.harness\start-dev.ps1
```

브라우저에서 `http://127.0.0.1:5173/`을 엽니다.

Gazebo와 ROS 2를 연결한 전체 시뮬레이션은 로컬 Docker 컨테이너에서 FastAPI를
실행한 뒤 WebUI 왼쪽의 `맵 생성` 또는 `순찰`을 선택합니다. 이때 WebUI가
Gazebo·SLAM Toolbox·AMCL·Nav2 launch를 직접 관리하므로 별도 터미널에서 같은
launch를 동시에 실행하지 않습니다.

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
npm run dev:simulation
```

브라우저에서 `http://127.0.0.1:5174/`을 엽니다.

## 맵 생성·순찰 모드

| WebUI 모드 | ROS 구성 | 용도 |
|---|---|---|
| 맵 생성 | SLAM Toolbox + Gazebo | 처음 방문한 공간을 수동 주행하며 점유 지도를 작성 |
| 순찰 | Map Server + AMCL + Nav2 + Gazebo | 저장된 지도에서 위치를 추정하고 웨이포인트를 자율 순찰 |

`맵 생성 → 순찰` 전환 시 WebUI 백엔드는 현재 `/map`을
`Robot/runtime/maps/facility.yaml`과 `facility.pgm`으로 먼저 저장합니다. 지도가
없으면 순찰 모드는 시작하지 않고 원인을 화면에 표시합니다. 지도 상세 화면의
`ROS 지도 저장` 버튼으로도 명시적으로 저장할 수 있습니다.

터미널에서 시작한 기존 SLAM 또는 Nav2가 감지되면 WebUI는 해당 프로세스를
강제로 종료하지 않습니다. 기존 launch를 터미널에서 종료한 후 WebUI 모드
제어를 사용합니다.

Docker Desktop의 WebUI 제어는 WSLg 창 연결 여부와 무관하게 동작하도록 Gazebo
GUI를 기본적으로 끈 headless 모드입니다. 브라우저의 2D 지도·RGB·열화상은
계속 표시됩니다. Gazebo 3D 창까지 필요하면 WSL2 셸에서 launch의 `gui:=true`를
사용하되, 이때는 WebUI 모드 제어와 동시에 실행하지 않습니다.

> 현재 열화상과 열원은 시뮬레이션 데이터이며, 실제 화재 판정이나 안전 성능을 검증한 결과가 아닙니다.
