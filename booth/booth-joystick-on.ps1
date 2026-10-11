# 조이스틱 수동 주행을 켭니다.
#
# Yahboom 기본 조이스틱 프로그램을 다시 띄웁니다. 전원을 켜면 원래 자동으로
# 뜨는 것이고, 1 시작.bat 가 시연 준비를 하면서 내려둡니다.
#
# 사람이 쥐고 모는 동안에는 사람이 안전장치입니다. 자율 순찰용 안전 필터는
# 이 경로에 적용되지 않습니다. 그게 Yahboom 기본 설계입니다.

$ErrorActionPreference = 'Continue'

$SshExe = 'ssh'
foreach ($cand in @('C:\Program Files\Git\usr\bin\ssh.exe',
                    'C:\Program Files (x86)\Git\usr\bin\ssh.exe')) {
    if (Test-Path $cand) { $SshExe = $cand; break }
}

$Jetson  = 'jetson@100.107.60.123'
$Backend = 'http://100.107.60.123:8000'

function Say($text, $color = 'White') { Write-Host $text -ForegroundColor $color }

Say ''
Say '=== 조이스틱 수동 주행 켜기 ===' Cyan
Say ''

$null = & $SshExe -o BatchMode=yes -o ConnectTimeout=8 $Jetson 'echo ok' 2>$null
if ($LASTEXITCODE -ne 0) {
    Say '  로봇에 접속할 수 없습니다. 전원과 Tailscale 을 확인하세요.' Red
    exit 1
}

# 이미 떠 있으면 두 개가 겹친다.
$already = & $SshExe -o BatchMode=yes $Jetson "pgrep -f 'yahboom[c]ar_joy_launch' | head -1" 2>$null
if ($already) {
    Say '  이미 켜져 있습니다. 바로 쓰시면 됩니다.' Green
    Say ''
    exit 0
}

# --- 충돌 확인 -------------------------------------------------------------
# Yahboom 조이스틱 프로그램은 모터 드라이버를 함께 올립니다. 순찰이 켜져
# 있으면 드라이버가 둘이 되고, 디스펜서까지 떠 있으면 같은 USB 시리얼에
# 세 프로그램이 말을 겁니다. 서보 명령이 깨질 수 있습니다.
$conflict = @()

$disp = & $SshExe -o BatchMode=yes $Jetson "pgrep -f 'lib/hazard_guard_[d]ispenser' | head -1" 2>$null
if ($disp) { $conflict += '디스펜서 노드' }

try {
    $mode = Invoke-RestMethod -Uri "$Backend/api/v1/system/mode" -TimeoutSec 8
    if ($mode.state -eq 'running') { $conflict += ('운용 모드 ({0})' -f $mode.mode) }
} catch { }

if ($conflict.Count -gt 0) {
    Say ('  주의: {0} 가 돌고 있습니다.' -f ($conflict -join ', ')) Yellow
    Say ''
    Say '  조이스틱 프로그램은 모터 드라이버를 함께 올립니다. 같은 USB 시리얼을' DarkGray
    Say '  두 프로그램이 쓰게 되어 디스펜서 서보 명령이 깨질 수 있습니다.' DarkGray
    Say '  조이스틱으로 먼저 몰고, 그 다음 시연을 시작하는 순서를 권합니다.' DarkGray
    Say ''
    $answer = Read-Host '  그래도 켤까요? (y/N)'
    if ($answer -ne 'y' -and $answer -ne 'Y') {
        Say '  취소했습니다.' DarkGray
        Say ''
        exit 0
    }
}

# --- 기동 ------------------------------------------------------------------
Say '  조이스틱 프로그램 기동...'
$cmd = 'exec >/tmp/joy-booth.log 2>&1 </dev/null; source /opt/ros/humble/setup.bash && source /home/jetson/yahboomcar_ros2_ws/yahboomcar_ws/install/setup.bash && export ROS_DOMAIN_ID=61 ROS_LOCALHOST_ONLY=1 && setsid ros2 launch yahboomcar_ctrl yahboomcar_joy_launch.py &'
& $SshExe -o BatchMode=yes $Jetson $cmd 2>$null
Start-Sleep -Seconds 12

$up = & $SshExe -o BatchMode=yes $Jetson "pgrep -f 'yahboom[c]ar_joy_launch' | head -1" 2>$null
Say ''
if ($up) {
    Say '  켜졌습니다. 조이스틱으로 조종할 수 있습니다.' Green
    Say '  끄려면 7 조이스틱끄기.bat' DarkGray
} else {
    Say '  기동하지 못했습니다.' Red
    Say ('  로그: ssh {0} "tail -20 /tmp/joy-booth.log"' -f $Jetson) DarkGray
    Say '  조이스틱 USB 가 꽂혀 있는지도 확인하세요.' DarkGray
}
Say ''
