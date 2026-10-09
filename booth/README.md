# 전시 부스 운영 스크립트

노트북에서 실행합니다. 로봇 전원을 켠 뒤 **`1 시작.bat`** 더블클릭 하나면 됩니다.

| 파일 | 하는 일 |
|---|---|
| `1 시작.bat` | 콘솔 백엔드 + 디스펜서 노드 + 웹UI 를 순서대로 띄우고 브라우저를 엽니다 |
| `2 상태.bat` | 지금 무엇이 떠 있는지만 봅니다. 아무것도 바꾸지 않습니다 |
| `3 큐브리셋.bat` | 떨어뜨린 큐브를 주워 다시 채운 뒤 실행합니다 |
| `4 정지.bat` | 띄운 것들을 내립니다. 로봇 전원은 따로 내리세요 |
| `5 영상복구.bat` | 카메라 영상이 멈췄을 때 |

웹UI 주소는 `http://127.0.0.1:5180`, 폰·태블릿에서는 `http://172.21.161.29:5180`.

## 부스 한 사이클

1. 로봇 전원 ON
2. **`1 시작.bat`**
3. 큐브 전원 ON → 30초쯤 뒤 웹UI 에 배터리가 뜹니다
4. 개요 탭 `후면 경고장치` 카드 → **비콘 수동 배출 (시연용)**
5. 큐브가 떨어지고 경광등 점등
6. 큐브를 주워 매거진에 다시 채움 → **`3 큐브리셋.bat`**
7. 3번부터 반복

경광등은 큐브를 **4번 흔들면** 꺼집니다. 안 끄면 30분 뒤 자동 소등됩니다.

## 알아두면 좋은 것

**큐브 없이도 버튼이 눌립니다.** 디스펜서만 보여줄 때 쓰라고 열어둔 것이고,
그때는 낙하 보고가 없어 결과가 "배출 미확인"으로 뜹니다. 서보는 정상적으로 돕니다.
실제로 큐브가 떨어져 `DROPPED` 를 보고해야만 "배출 확인"이 뜹니다.

**매 배출 뒤 큐브리셋이 필요합니다.** 떨어진 큐브는 "설치됨"으로 기록되어
다음 배출 대상에서 빠집니다. 물리적으로 다시 채워도 기록은 남습니다.

**전원을 껐다 켜면 챔버가 30도쯤 기울어진 채로 시작합니다.** 보드가 전원이
들어올 때 서보 채널에 자기 기본값을 내보내는데, 디스펜서 노드는 그때 떠 있지
않아 막을 수가 없습니다. 노드는 챔버가 0도에 있다고 가정하므로 첫 배출이
어긋납니다. 전원을 켠 뒤 첫 배출 전에 한 번 원점을 맞춰 주세요.

```
ssh jetson@100.107.60.123 "source /opt/ros/humble/setup.bash && export ROS_DOMAIN_ID=61 ROS_LOCALHOST_ONLY=1 && ros2 topic pub --once /hazard_guard/dispenser/command std_msgs/String '{data: \"home\"}'"
```

**카메라가 USB 에서 빠지면 스스로 복구하지 못합니다.** `ascamera` 노드는 죽지
않고 사라진 장치 핸들을 붙들고 있어서, 프로세스는 멀쩡한데 프레임만 0이 됩니다.
`2 상태.bat` 의 영상 항목이 `available=False` 면 `5 영상복구.bat` 를 쓰세요.

**열화상·카메라는 자동으로 안 뜹니다.** 웹UI 에서 운용 모드를 켜야 센서가
올라옵니다. 비콘 배출만 보여줄 거면 켤 필요 없습니다.

**라이다는 연결돼 있지 않습니다.** 2D 지도와 자율 주행에만 필요하므로 비콘
배출 시연에는 영향이 없습니다.

## 안 될 때

먼저 **`2 상태.bat`** 를 보세요. 어디가 비었는지 바로 보입니다.

| 증상 | 원인 |
|---|---|
| 로봇 SSH 실패 | 로봇 전원 또는 Tailscale. `tailscale status \| findstr yahboom` |
| 콘솔 백엔드 `--` | `ssh jetson@100.107.60.123 "tail -40 /tmp/hg-booth.log"` |
| 디스펜서 노드 `--` | `ssh jetson@100.107.60.123 "tail -30 /tmp/disp-booth.log"` |
| 배출 버튼 비활성 | `runtime.env` 의 `HAZARD_GUARD_DISPENSER_DEMO_DROP=1` 확인 |
| 눌러도 서보가 안 돎 | 상태의 `서보 실제 동작` 이 True 인지 확인 |
| `robot_not_stably_stopped` | 운용 모드가 꺼져 `/odom` 이 없는 것입니다. 모드를 켜세요 |
| 영상만 멈춤 | `5 영상복구.bat` |
| 큐브가 안 잡힘 | 큐브 전원. 30초 기다렸다가 `2 상태.bat` 다시 |

## 손으로 띄울 때

```bash
# 1) 콘솔 백엔드  (setsid nohup 없이 띄우면 SSH 끊을 때 같이 죽습니다)
ssh jetson@100.107.60.123 "cd ~/RoboLotus/hazard-guard-console && setsid nohup bash backend/scripts/start_hazardguard.sh > /tmp/hg.log 2>&1 < /dev/null &"

# 2) 디스펜서 노드
ssh jetson@100.107.60.123 "cd ~/RoboLotus/hazard-guard-robot && source /opt/ros/humble/setup.bash && source install/setup.bash && set -a && . ~/.config/hazard-guard/runtime.env && set +a && export ROS_DOMAIN_ID=61 ROS_LOCALHOST_ONLY=1 && setsid nohup ros2 run hazard_guard_dispenser dispenser_node --ros-args --params-file src/hazard_guard_dispenser/config/dispenser_physical.yaml -p allow_maintenance_manual_commands:=true -p require_cube_confirmation:=false -p enable_physical_drop:=true > /tmp/disp.log 2>&1 < /dev/null &"

# 3) 노트북 웹UI  (끌 때는 그 창에서 Ctrl-C)
cd C:/Users/coco2/hg-console/frontend && HAZARD_GUARD_BACKEND_URL=http://100.107.60.123:8000 npx vite --port 5180 --strictPort --host
```

디스펜서 노드를 내릴 때 `pkill -f dispenser_node` 는 쓰지 마세요. 명령문 자체에
그 문자열이 들어 있어서 자기 자신을 죽입니다. `pkill -f 'lib/hazard_guard_dispenser'`
를 쓰세요.

## 로봇 워크스페이스를 다시 빌드할 때

벤더 워크스페이스를 **반드시 함께 소싱**해야 합니다. colcon 은 빌드 시점의
환경을 `install/setup.bash` 에 체인으로 기록하는데, 빼먹으면 그 체인이 끊겨
`package 'yahboomcar_description' not found` 로 운용 모드가 통째로 실패합니다.

```bash
source /opt/ros/humble/setup.bash
source /home/jetson/yahboomcar_ros2_ws/yahboomcar_ws/install/setup.bash
colcon build --symlink-install --packages-select <패키지>
```

## 쓰는 브랜치

| 저장소 | 브랜치 |
|---|---|
| hazard-guard-console | `demo/exhibition-manual-drop` |
| hazard-guard-robot | `fix/reset-installed-maintenance-gate` |

## 참고

스크립트가 Windows 기본 `ssh.exe` 대신 Git 의 `ssh` 를 씁니다. 기본 ssh 는
`~/.ssh` 권한이 조금만 열려 있어도 키를 거부하는데, 이 PC 의 `.ssh` 에
`SSUserGroup` 접근권이 있어 막힙니다. 권한을 손대지 않으려고 우회했습니다.

`.ps1` 파일은 UTF-8 **BOM 포함**으로 저장해야 합니다. Windows PowerShell 5.1 은
BOM 이 없으면 ANSI 로 읽어 한글이 깨지고 구문 오류가 납니다.
