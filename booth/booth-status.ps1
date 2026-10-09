# HazardGuard 전시 부스 - 상태 확인 (아무것도 바꾸지 않습니다)

$ErrorActionPreference = 'Continue'

$SshExe = 'ssh'
foreach ($cand in @('C:\Program Files\Git\usr\bin\ssh.exe',
                    'C:\Program Files (x86)\Git\usr\bin\ssh.exe')) {
    if (Test-Path $cand) { $SshExe = $cand; break }
}

$Jetson  = 'jetson@100.107.60.123'
$Backend = 'http://100.107.60.123:8000'

function Say($text, $color = 'White') { Write-Host $text -ForegroundColor $color }
function Mark($ok) { if ($ok) { return 'OK  ' } else { return '--  ' } }

Say ''
Say '=== HazardGuard 부스 상태 ===' Cyan
Say ''

$null = & $SshExe -o BatchMode=yes -o ConnectTimeout=6 $Jetson 'echo ok' 2>$null
$sshOk = ($LASTEXITCODE -eq 0)
Say ('{0}로봇 SSH' -f (Mark $sshOk))
if (-not $sshOk) {
    Say ''
    Say '  로봇에 접속할 수 없습니다. 전원과 Tailscale 을 확인하세요.' Yellow
    Say '  tailscale status | findstr yahboom' DarkGray
    Say ''
    exit 0
}

$svc = & $SshExe -o BatchMode=yes $Jetson 'systemctl is-active hazardguard-base hazardguard-iot hazardguard-status' 2>$null
Say ('    상시 서비스 (모터보드/IoT/상태서버): {0}' -f (($svc | Where-Object { $_ }) -join ' ')) DarkGray

$health = $null
try { $health = Invoke-RestMethod -Uri "$Backend/api/health" -TimeoutSec 6 } catch { }
Say ('{0}콘솔 백엔드  :8000' -f (Mark $health))
if ($health) {
    Say ('    ros_bridge={0}  target={1}  mode={2}' -f $health.ros_bridge, $health.deployment_target, $health.mode) DarkGray
}

$disp = & $SshExe -o BatchMode=yes $Jetson "pgrep -f 'lib/hazard_guard_[d]ispenser' | head -1" 2>$null
Say ('{0}디스펜서 노드' -f (Mark $disp))
if ($disp) {
    $raw = & $SshExe -o BatchMode=yes $Jetson 'source /opt/ros/humble/setup.bash; export ROS_DOMAIN_ID=61 ROS_LOCALHOST_ONLY=1; timeout 8 ros2 param get /dispenser_node enable_physical_drop; timeout 8 ros2 param get /dispenser_node require_cube_confirmation' 2>$null
    $vals = @($raw | ForEach-Object { ($_ -split ' ')[-1] })
    Say ('    서보 실제 동작={0}  큐브 확인 요구={1}' -f $vals[0], $vals[1]) DarkGray
}

# 부팅 자동시작으로 되살아나면 안전 게이트를 거치지 않는 /cmd_vel 경로가 열립니다.
$vendor = & $SshExe -o BatchMode=yes $Jetson "pgrep -f 'yahboom[c]ar_joy_launch' | head -1" 2>$null
if ($vendor) {
    Say '!!  벤더 조이스틱 자동시작이 떠 있습니다 (안전 게이트 우회 경로)' Yellow
    Say '    1 시작.bat 를 실행하면 정리됩니다.' DarkGray
}

$web = Get-NetTCPConnection -LocalPort 5180 -State Listen -ErrorAction SilentlyContinue
Say ('{0}웹UI  :5180' -f (Mark $web))

if ($health) {
    try {
        $d = Invoke-RestMethod -Uri "$Backend/api/v1/dispenser/status" -TimeoutSec 8
        Say ''
        Say ('  배출 버튼 : {0}' -f $(if ($d.demo_drop_enabled) { '사용 가능' } else { '비활성' }))
        Say ('  큐브      : {0}/{1} 연결, 배출가능 {2}' -f $d.battery.connected, $d.battery.expected, $d.battery.available_for_drop)
        foreach ($b in $d.battery.beacons) {
            $state = if ($b.installed) { '설치됨 (큐브리셋 필요)' } elseif ($b.connected) { '대기' } else { '미연결' }
            Say ('    {0}  {1}%  {2}' -f $b.address, $b.percent, $state) DarkGray
        }
    } catch { }

    # 영상은 ROS 토픽이 살아 있어도 USB 가 한 번 빠지면 갱신이 멈춥니다.
    # available=False 면 노드가 죽은 장치 핸들을 붙들고 있는 것이니 모드 재시작이 필요합니다.
    try {
        $m = Invoke-RestMethod -Uri "$Backend/api/v1/media/status" -TimeoutSec 8
        Say ''
        foreach ($k in 'rgb', 'thermal', 'map') {
            $v = $m.$k
            $tone = if ($v.available) { 'DarkGray' } else { 'Yellow' }
            Say ('  영상 {0,-8} available={1,-6} updated={2}' -f $k, $v.available, $v.updated_at) $tone
        }
        if (-not $m.rgb.available -or -not $m.thermal.available) {
            Say '    -> 영상이 멈췄습니다. 5 영상복구.bat 를 실행하세요.' Yellow
        }
    } catch { }

    try {
        $s = Invoke-RestMethod -Uri "$Backend/api/v1/system/sensors" -TimeoutSec 8
        $live = ($s.sensors | Where-Object { $_.state -eq 'live' }).Count
        Say ''
        Say ('  센서 : {0}/{1} live' -f $live, $s.sensors.Count)
        foreach ($x in $s.sensors | Where-Object { $_.state -eq 'live' }) {
            Say ('    {0}  {1:N1} Hz' -f $x.label, $x.rate_hz) DarkGray
        }
        if ($live -eq 0) { Say '    운용 모드가 꺼져 있습니다. 웹UI 에서 켜세요.' DarkGray }
    } catch { }
}

Say ''
