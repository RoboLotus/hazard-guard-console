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

Gazebo와 ROS 2를 연결한 전체 시뮬레이션은 WSL에서 다음을 실행합니다.

```bash
cd /mnt/d/Develop/hazard-guard/WebUI
./.harness/run-simulation-api.sh true
```

별도 PowerShell에서:

```powershell
cd D:\Develop\hazard-guard\WebUI\frontend
npm run dev:simulation
```

브라우저에서 `http://127.0.0.1:5174/`을 엽니다.

> 현재 열화상과 열원은 시뮬레이션 데이터이며, 실제 화재 판정이나 안전 성능을 검증한 결과가 아닙니다.
