# 떨어뜨린 큐브를 주워 매거진에 다시 채운 뒤 실행합니다.
#
# 배출된 큐브는 "설치됨"으로 기록되어 다음 배출 대상에서 빠집니다. 물리적으로
# 재장전해도 그 기록은 남으므로 한 번 지워줘야 합니다.

$ErrorActionPreference = 'Continue'

$SshExe = 'ssh'
foreach ($cand in @('C:\Program Files\Git\usr\bin\ssh.exe',
                    'C:\Program Files (x86)\Git\usr\bin\ssh.exe')) {
    if (Test-Path $cand) { $SshExe = $cand; break }
}

$Jetson = 'jetson@100.107.60.123'

function Say($text, $color = 'White') { Write-Host $text -ForegroundColor $color }

Say ''
Say '=== 큐브 설치 기록 초기화 ===' Cyan

# ros2 topic pub 의 인자에 큰따옴표를 중첩하면 PowerShell 이 ssh 로 넘기는
# 과정에서 깨진다. YAML 평범한 스칼라로 쓰면 중첩이 없어진다.
$cmd = 'source /opt/ros/humble/setup.bash; export ROS_DOMAIN_ID=61 ROS_LOCALHOST_ONLY=1; timeout 12 ros2 topic pub --once /hazard_guard/dispenser/command std_msgs/String "{data: reset_installed}" >/dev/null 2>&1; sleep 3; cat ~/.local/state/hazard_guard/dispenser/installed_beacons.json'

# 접속 가능 여부를 먼저 따로 확인한다. 그래야 원격 명령이 실패했을 때
# "접속할 수 없습니다" 라는 엉뚱한 안내를 하지 않는다.
$null = & $SshExe -o BatchMode=yes -o ConnectTimeout=8 $Jetson 'echo ok' 2>$null
if ($LASTEXITCODE -ne 0) {
    Say '  로봇에 접속할 수 없습니다. 전원과 Tailscale 을 확인하세요.' Red
    exit 1
}

$result = & $SshExe -o BatchMode=yes -o ConnectTimeout=8 $Jetson $cmd 2>$null
if ($LASTEXITCODE -ne 0) {
    Say '  초기화 명령이 실패했습니다.' Red
    Say '  디스펜서 노드가 떠 있는지 2 상태.bat 로 확인하세요.' DarkGray
    exit 1
}

Say ("  상태 파일: {0}" -f $result)
if ($result -match '"installed"\s*:\s*\[\s*\]') {
    Say '  초기화 완료. 다시 배출할 수 있습니다.' Green
} else {
    Say '  아직 기록이 남아 있습니다.' Yellow
    Say '  디스펜서 노드가 allow_maintenance_manual_commands:=true 로 떠 있는지 확인하세요.' DarkGray
    Say ('  로그: ssh {0} "tail -5 /tmp/disp-booth.log"' -f $Jetson) DarkGray
}
Say ''
