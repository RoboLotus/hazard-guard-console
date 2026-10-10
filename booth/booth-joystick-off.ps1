# 조이스틱 수동 주행을 끕니다.
#
# 시연을 시작하기 전에 꺼두는 쪽이 안전합니다. 조이스틱 프로그램은 모터
# 드라이버를 함께 올리므로, 순찰·디스펜서와 같이 돌면 같은 USB 시리얼을
# 두 프로그램이 쓰게 됩니다.
#
# 1 시작.bat 도 같은 정리를 하므로 보통은 따로 쓸 일이 없습니다.
# 전원을 다시 켜면 Yahboom 자동시작으로 되살아납니다.

$ErrorActionPreference = 'Continue'

$SshExe = 'ssh'
foreach ($cand in @('C:\Program Files\Git\usr\bin\ssh.exe',
                    'C:\Program Files (x86)\Git\usr\bin\ssh.exe')) {
    if (Test-Path $cand) { $SshExe = $cand; break }
}

$Jetson = 'jetson@100.107.60.123'

function Say($text, $color = 'White') { Write-Host $text -ForegroundColor $color }

Say ''
Say '=== 조이스틱 수동 주행 끄기 ===' Cyan
Say ''

$null = & $SshExe -o BatchMode=yes -o ConnectTimeout=8 $Jetson 'echo ok' 2>$null
if ($LASTEXITCODE -ne 0) {
    Say '  로봇에 접속할 수 없습니다. 전원과 Tailscale 을 확인하세요.' Red
    exit 1
}

$running = & $SshExe -o BatchMode=yes $Jetson "pgrep -f 'yahboom[c]ar_joy_launch' | head -1" 2>$null
if (-not $running) {
    Say '  이미 꺼져 있습니다.' DarkGray
    Say ''
    exit 0
}

# 런치를 내리면 딸려 올라온 모터 드라이버와 joy_node 도 같이 내려갑니다.
& $SshExe -o BatchMode=yes $Jetson "pkill -f 'yahboom[c]ar_joy_launch'" 2>$null
Start-Sleep -Seconds 4

$still = & $SshExe -o BatchMode=yes $Jetson "pgrep -f 'yahboom[c]ar_joy_launch' | head -1" 2>$null
if ($still) {
    Say '  아직 남아 있습니다. 한 번 더 시도하세요.' Yellow
} else {
    Say '  꺼졌습니다.' Green
    Say '  다시 켜려면 6 조이스틱켜기.bat' DarkGray
}
Say ''
