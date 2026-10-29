# 운용 모드를 끕니다.
#
# 웹UI 에는 순찰 모드를 끄는 버튼이 없습니다. 모드 종료 기능은 3D 수집을 끝낼
# 때만 연결돼 있습니다. 조이스틱으로 직접 몰기 전에 이걸로 끄세요.
#
# 끄면 카메라·열화상·odom 이 내려가므로 영상이 멈추고 배출도 거부됩니다.
# 다시 켜려면 웹UI 지도 탭 -> 운용 · 순찰.

$ErrorActionPreference = 'Continue'
$Backend = 'http://100.107.60.123:8000'

function Say($text, $color = 'White') { Write-Host $text -ForegroundColor $color }

Say ''
Say '=== 운용 모드 끄기 ===' Cyan
Say ''

try {
    $m = Invoke-RestMethod -Uri "$Backend/api/v1/system/mode" -TimeoutSec 8
} catch {
    Say '  콘솔 백엔드에 연결할 수 없습니다. 1 시작.bat 을 먼저 실행하세요.' Red
    exit 1
}

if ($m.state -ne 'running' -and $m.state -ne 'starting') {
    Say ('  이미 꺼져 있습니다. (현재: {0})' -f $m.mode) DarkGray
    Say ''
    exit 0
}

Say ('  현재 {0} 실행 중. 끄는 중...' -f $m.mode)
try {
    $r = Invoke-RestMethod -Uri "$Backend/api/v1/system/mode" -Method Delete -TimeoutSec 60
    Say ('  꺼졌습니다. (현재: {0})' -f $r.mode) Green
    Say '  조이스틱으로 몰려면 6 조이스틱켜기.bat' DarkGray
    Say '  다시 켜려면 웹UI 지도 탭 -> 운용 · 순찰' DarkGray
} catch {
    Say '  끄지 못했습니다.' Red
    Say ('  {0}' -f $_.Exception.Message) DarkGray
    exit 1
}
Say ''
