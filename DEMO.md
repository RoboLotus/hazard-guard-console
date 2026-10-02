# HazardGuard 저장 자료 시연

`Demo`는 `integration/console-live-state-rgb`에서 분리한 독립 시연 브랜치입니다.
dev/main 병합이나 Robot 변경 없이, 백엔드·ROS·실물 로봇이 필요 없는 정적 웹으로 실행합니다.

## 실행

Node.js 20.19+ 또는 22.12+와 Python 3.10+를 사용합니다.

```powershell
python -m venv .venv-demo
.venv-demo/Scripts/python -m pip install -r scripts/demo-requirements.txt
.venv-demo/Scripts/python scripts/prepare_recorded_demo.py "D:/path/to/saved-session"
cd frontend
npm ci
npm run dev
```

브라우저에서 http://127.0.0.1:5179 를 엽니다. 실제 백엔드 주소/환경변수는 사용하지 않습니다.
macOS/Linux에서는 가상환경 Python 경로를 `.venv-demo/bin/python`으로 바꾸세요.

원본 세션 폴더에는 `cloud.ply`, `thermal_layer.npz`, `metadata.json`, `map.pgm`, `map.yaml`이 필요하며 `equipment.json`은 선택입니다.
현재 자료: [8월 27일 실측 지도 보관함](https://drive.google.com/drive/folders/1TKll5Q3BNAJggpPzW3dBsm1PeLjQ6Dxq), 세션 `20260827T131245Z-106599`.
폴더 이름과 실제 파일별 저장 시각은 다를 수 있으며, 화면은 메타데이터 시간을 KST로 표시합니다.

## 제공 기능

- 기존 App / Sidebar / Overview / 지도 / 설정 등 8개 메뉴의 레이아웃과 컴포넌트를 그대로 사용합니다.
- Overview의 기존 2D 지도에 저장 지도를 표시합니다.
- 지도 탭 → 기존 `2D 지도 / 3D RGB-D / 3D 열화상` 버튼으로 전환합니다.
- 기존 PointCloudPanel에 실측 RGB-D 114,651개와 열화상 관측 548개(22.1~43.4°C)를 공급합니다. 기존 회전/확대/이동과 화면 맞춤을 사용합니다.
- 설비 ROI·이름은 저장 자료를 사용합니다. 미관측 표면은 기존 열화상 뷰어의 옅은 기준 형상으로 표시합니다.
- 저장본이 없는 카메라 영상·현재 로봇 상태·이벤트·리포트는 생성하지 않습니다. 카메라는 연결 필요, 텔레메트리는 미연결입니다.

**주행 영상/경로 재생이 아닙니다.** 시간 순서 센서 기록이 없는 정적 지도입니다.
RGB 카메라 영상, ROS bag 재생, 동적 열화상 별도 레이어는 이번 범위에 포함하지 않습니다.
현재 로봇 위치를 알 수 없으므로 위치 마커를 표시하지 않습니다. 주행·배출·이벤트 생성은 제공하지 않습니다.

## 데이터 정합성과 안전

- 열화상 인덱스를 PLY 원본 행에 직접 붙이지 않습니다. Robot의 고정 지도 규칙과 동일하게 복셀을 정렬·평균한 뒤 SHA-256 지문을 비교합니다.
- NPZ와 메타데이터 지문이 다르거나 설비 세션이 다르면 변환을 중단합니다. 원본을 수정하지 않습니다.
- 생성물은 `frontend/public/demo-data/`에 저장되며 Git에서 제외됩니다. 다른 PC에서는 자료를 따로 받아 변환해야 합니다.
- Demo 진입점에서만 로컬 데이터 어댑터를 설치한 뒤 기존 App을 마운트합니다. 읽기 API는 로컬 저장 자료 또는 명시적 미연결 응답으로 처리합니다.
- 변경 요청과 다른 서버로의 fetch 요청은 403으로 차단합니다. Vite의 실제 API 프록시도 제거했으며 개발 서버의 `/api`, `/ws` 요청을 거부합니다.
- 기존 지도 렌더러만 재사용하고, 텔레메트리·공간정보·점군의 실물 WebSocket 연결은 생략합니다. 시연 데이터를 실시간 ROS 상태로 가장하지 않습니다.
- 프런트엔드 개발 서버의 HMR 연결만 있을 수 있습니다. 로봇 WebSocket은 연결하지 않습니다.

## 테스트 / 배포

```powershell
.venv-demo/Scripts/python -m unittest discover -s scripts -p "test_*.py"
cd frontend
npm test
npm run build
npm run preview -- --host 127.0.0.1 --port 5179
```

변환 후 빌드해야 데이터가 정적 산출물에 포함됩니다. `frontend/dist/client`를 정적 호스팅하면 됩니다.
배포 산출물에는 실측 지도와 설비 정보가 포함되므로 공개 배포 전 공개 범위를 확인하세요.
이 브랜치는 로컬 시연용이며 dev/main에 자동 통합하지 않습니다.

### 구현 검증 (2026-10-02)

- Python 변환기 단위 테스트와 프런트엔드 회귀 테스트, 프로덕션 빌드 확인.
- Edge 자동화: 기존 8개 메뉴와 1440 / 1024 / 390px의 3개 지도 모드 확인, 가로 넘침 없음.
- 기존 3D 캔버스·온도 관측 수·화면 맞춤, 저장 2D 지도, 자료 미존재 오류 안내 확인.
- 브라우저의 운영 API 요청 0건, JavaScript 오류 0건. 실물 장치 실행 없음.
- Three.js 포함 번들 크기 경고는 남아 있으며 기능 실패는 아닙니다.

선택적 브라우저 회귀 검사: Edge와 Playwright가 설치된 환경에서 `node scripts/check-demo.cjs <playwright-module-path> [screenshot-directory]` (frontend 폴더, 개발 서버 실행 상태).
