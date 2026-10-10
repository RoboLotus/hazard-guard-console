# 영상이 멈췄을 때 복구합니다.
#
# RGB-D 카메라가 USB 에서 한 번 빠지면 ascamera 노드는 죽지 않고 사라진 장치
# 핸들을 계속 붙들고 있습니다. 프로세스는 살아 있는데 프레임은 0이라, 노드를
# 다시 띄우는 것 말고는 방법이 없습니다. 운용 모드를 껐다 켜면 됩니다.
#
# 증상: 웹UI 영상이 멈춤 / media available=False / 센서가 stale

$ErrorActionPreference = 'Continue'
$Backend = 'http://100.107.60.123:8000'

function Say($text, $color = 'White') { Write-Host $text -ForegroundColor $color }

Say ''
Say '=== 영상 복구 (운용 모드 재시작) ===' Cyan
Say ''
Say '로봇 주변을 확인하세요. 모터 드라이버가 다시 올라옵니다.' Yellow
Say ''

Say '[1/3] 운용 모드 정지...'
try { $null = Invoke-RestMethod -Uri "$Backend/api/v1/system/mode" -Method Delete -TimeoutSec 60; Say '      정지됨' Green }
catch { Say '      정지 요청 실패 (이미 꺼져 있을 수 있음)' Yellow }
Start-Sleep -Seconds 12

Say '[2/3] 운용 모드 기동...'
try {
    $body = '{"mode":"patrol","patrol_slam":false}'
    $r = Invoke-RestMethod -Uri "$Backend/api/v1/system/mode" -Method Put -Body $body -ContentType 'application/json' -TimeoutSec 90
    Say ('      {0}' -f $r.state) Green
} catch {
    Say '      기동 실패' Red
    exit 1
}

Say '[3/3] 영상 확인...'
$ok = $false
foreach ($i in 1..10) {
    Start-Sleep -Seconds 8
    try {
        $m = Invoke-RestMethod -Uri "$Backend/api/v1/media/status" -TimeoutSec 8
        if ($m.rgb.available -and $m.thermal.available) { $ok = $true; break }
        Say ('      대기 중... rgb={0} thermal={1}' -f $m.rgb.available, $m.thermal.available) DarkGray
    } catch { }
}

Say ''
if ($ok) {
    Say '영상 복구됨. 웹UI 를 새로고침하세요.' Green
} else {
    Say '아직 영상이 안 올라옵니다.' Yellow
    Say '카메라 USB 케이블을 뽑았다 다시 꽂은 뒤 이 스크립트를 한 번 더 실행하세요.' DarkGray
}
Say ''
