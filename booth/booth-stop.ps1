# HazardGuard 전시 부스 - 전체 정지
#
# systemd 서비스(모터보드/IoT/상태서버)는 건드리지 않습니다. 그건 로봇의 기본
# 상태이고, 내리면 SmartThings 쪽 배터리 표시도 끊깁니다.

$ErrorActionPreference = 'Continue'

$SshExe = 'ssh'
foreach ($cand in @('C:\Program Files\Git\usr\bin\ssh.exe',
                    'C:\Program Files (x86)\Git\usr\bin\ssh.exe')) {
    if (Test-Path $cand) { $SshExe = $cand; break }
}

$Jetson = 'jetson@100.107.60.123'

function Say($text, $color = 'White') { Write-Host $text -ForegroundColor $color }

Say ''
Say '=== HazardGuard 부스 정지 ===' Cyan
Say ''

Say '[1/3] 웹UI 정지...'
$conns = Get-NetTCPConnection -LocalPort 5180 -State Listen -ErrorAction SilentlyContinue
if ($conns) {
    foreach ($c in $conns) {
        try { Stop-Process -Id $c.OwningProcess -Force -ErrorAction Stop; Say '      정지됨' Green }
        catch { Say '      정지 실패 - vite 창에서 Ctrl-C 하세요' Yellow }
    }
} else {
    Say '      떠 있지 않음' DarkGray
}

Say '[2/3] 디스펜서 노드 정지...'
# 'dispenser_node' 로 찾으면 이 명령문 자체가 걸려 자기 자신을 죽입니다.
# 실행 파일 경로로 찾아야 합니다.
& $SshExe -o BatchMode=yes -o ConnectTimeout=8 $Jetson "pkill -f 'lib/hazard_guard_dispenser'" 2>$null
if ($LASTEXITCODE -eq 255) { Say '      로봇에 접속 못 함 (이미 꺼졌을 수 있음)' Yellow }
else { Say '      정지됨' Green }

Say '[3/3] 콘솔 백엔드 정지...'
& $SshExe -o BatchMode=yes -o ConnectTimeout=8 $Jetson 'cd ~/RoboLotus/hazard-guard-console && bash backend/scripts/stop_hazardguard.sh' 2>$null
if ($LASTEXITCODE -eq 255) { Say '      로봇에 접속 못 함 (이미 꺼졌을 수 있음)' Yellow }
else { Say '      정지됨' Green }

Say ''
Say '정지 완료. 로봇 전원은 따로 내리세요.' Green
Say ''
