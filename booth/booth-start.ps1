# HazardGuard 전시 부스 - 전체 기동
# 로봇 전원을 켠 뒤 이것 하나만 실행하면 됩니다.
#
# systemd 서비스(모터보드/IoT/상태서버)는 부팅 때 자동으로 뜨므로 건드리지 않습니다.
# 여기서 띄우는 것은 전부 수동으로만 뜨는 것들입니다.

$ErrorActionPreference = 'Continue'

# Windows 기본 ssh.exe 는 ~/.ssh 권한이 조금만 열려 있어도 키를 거부합니다.
# Git 에 딸려오는 ssh 는 그 검사를 하지 않으므로 그쪽을 먼저 씁니다.
$SshExe = 'ssh'
foreach ($cand in @('C:\Program Files\Git\usr\bin\ssh.exe',
                    'C:\Program Files (x86)\Git\usr\bin\ssh.exe')) {
    if (Test-Path $cand) { $SshExe = $cand; break }
}

$Jetson   = 'jetson@100.107.60.123'
$Backend  = 'http://100.107.60.123:8000'
$WebUiDir = 'C:\Users\coco2\hg-console\frontend'
$WebUiUrl = 'http://127.0.0.1:5180'

function Say($text, $color = 'White') { Write-Host $text -ForegroundColor $color }

Say ''
Say '=== HazardGuard 부스 기동 ===' Cyan
Say ''

# --- 1. 로봇에 닿는지 -------------------------------------------------------
Say '[1/5] 로봇 연결 확인...'
$reachable = $false
foreach ($i in 1..12) {
    $null = & $SshExe -o BatchMode=yes -o ConnectTimeout=5 $Jetson 'echo ok' 2>$null
    if ($LASTEXITCODE -eq 0) { $reachable = $true; break }
    Start-Sleep -Seconds 5
    Say ("      대기 중... ({0}초)" -f ($i * 5)) DarkGray
}
if (-not $reachable) {
    Say '      실패: 로봇에 접속할 수 없습니다.' Red
    Say '      로봇 전원과 Tailscale 을 확인하세요.' Red
    Say '      tailscale status | findstr yahboom' DarkGray
    exit 1
}
Say '      연결됨' Green

# --- 2. 콘솔 백엔드 ---------------------------------------------------------
Say '[2/5] 콘솔 백엔드 기동...'
$already = $null
try { $already = Invoke-RestMethod -Uri "$Backend/api/health" -TimeoutSec 5 } catch { }
if ($already) {
    Say '      이미 떠 있음 (건너뜀)' DarkGray
} else {
    # setsid nohup 없이 띄우면 SSH 를 끊는 순간 같이 죽습니다.
    & $SshExe -o BatchMode=yes $Jetson 'cd ~/RoboLotus/hazard-guard-console && setsid nohup bash backend/scripts/start_hazardguard.sh > /tmp/hg-booth.log 2>&1 < /dev/null &' 2>$null

    $up = $false
    foreach ($i in 1..24) {
        Start-Sleep -Seconds 5
        try {
            $h = Invoke-RestMethod -Uri "$Backend/api/health" -TimeoutSec 5
            if ($h.status -eq 'ok') { $up = $true; break }
        } catch { }
        Say ("      대기 중... ({0}초)" -f ($i * 5)) DarkGray
    }
    if (-not $up) {
        Say '      실패: 백엔드가 응답하지 않습니다.' Red
        Say ('      로그: ssh {0} "tail -40 /tmp/hg-booth.log"' -f $Jetson) DarkGray
        exit 1
    }
    Say '      기동됨' Green
}

# --- 3. 디스펜서 노드 -------------------------------------------------------
Say '[3/5] 디스펜서 노드 기동...'
$running = & $SshExe -o BatchMode=yes $Jetson "pgrep -f 'lib/hazard_guard_dispenser' | head -1" 2>$null
if ($running) {
    Say '      이미 떠 있음 (건너뜀)' DarkGray
} else {
    # enable_physical_drop      : 서보를 실제로 움직인다
    # require_cube_confirmation : false = 큐브가 없어도 배출을 진행한다 (시연용)
    # allow_maintenance_manual_commands : home / angle:NN / reset_installed 허용
    $cmd = 'cd ~/RoboLotus/hazard-guard-robot && source /opt/ros/humble/setup.bash && source install/setup.bash && set -a && . ~/.config/hazard-guard/runtime.env && set +a && export ROS_DOMAIN_ID=61 ROS_LOCALHOST_ONLY=1 && setsid nohup ros2 run hazard_guard_dispenser dispenser_node --ros-args --params-file src/hazard_guard_dispenser/config/dispenser_physical.yaml -p allow_maintenance_manual_commands:=true -p require_cube_confirmation:=false -p enable_physical_drop:=true > /tmp/disp-booth.log 2>&1 < /dev/null &'
    & $SshExe -o BatchMode=yes $Jetson $cmd 2>$null
    Start-Sleep -Seconds 20
    $running = & $SshExe -o BatchMode=yes $Jetson "pgrep -f 'lib/hazard_guard_dispenser' | head -1" 2>$null
    if ($running) {
        Say '      기동됨' Green
    } else {
        Say '      실패: 노드가 뜨지 않았습니다.' Red
        Say ('      로그: ssh {0} "tail -30 /tmp/disp-booth.log"' -f $Jetson) DarkGray
    }
}

# --- 4. 노트북 웹UI ---------------------------------------------------------
Say '[4/5] 웹UI 기동...'
$listening = Get-NetTCPConnection -LocalPort 5180 -State Listen -ErrorAction SilentlyContinue
if ($listening) {
    Say '      이미 떠 있음 (건너뜀)' DarkGray
} else {
    # 별도 창으로 띄워야 이 스크립트가 끝나도 살아 있습니다. 끌 때는 그 창에서 Ctrl-C.
    $inner = "cd '$WebUiDir'; `$env:HAZARD_GUARD_BACKEND_URL = '$Backend'; npx vite --port 5180 --strictPort --host"
    Start-Process powershell -ArgumentList '-NoExit', '-NoProfile', '-Command', $inner
    foreach ($i in 1..12) {
        Start-Sleep -Seconds 3
        $listening = Get-NetTCPConnection -LocalPort 5180 -State Listen -ErrorAction SilentlyContinue
        if ($listening) { break }
    }
    if ($listening) { Say '      기동됨' Green } else { Say '      아직 안 뜸 (새 창을 확인하세요)' Yellow }
}

# --- 5. 상태 ----------------------------------------------------------------
Say '[5/5] 상태 확인...'
Start-Sleep -Seconds 3
try {
    $d = Invoke-RestMethod -Uri "$Backend/api/v1/dispenser/status" -TimeoutSec 8
    $cubes = $d.battery.connected
    Say ''
    Say ('  배출 버튼   : {0}' -f $(if ($d.demo_drop_enabled) { '사용 가능' } else { '비활성 - runtime.env 의 HAZARD_GUARD_DISPENSER_DEMO_DROP 확인' }))
    Say ('  큐브 연결   : {0} / {1}' -f $cubes, $d.battery.expected)
    if ($cubes -lt 1) {
        Say '                큐브 전원을 켜면 30초쯤 뒤 잡힙니다.' DarkGray
        Say '                큐브 없이 눌러도 서보는 돕니다 (결과는 낙하 미확인).' DarkGray
    }
} catch {
    Say '  디스펜서 상태를 읽지 못했습니다.' Yellow
}

Say ''
Say "준비 완료 -> $WebUiUrl" Green
Say '  폰/태블릿에서는 http://172.21.161.29:5180' DarkGray
Say ''
Start-Process $WebUiUrl
