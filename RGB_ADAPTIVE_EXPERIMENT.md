# RGB 가변 압축·JPEG/H.264 전환 실험

상태: 2026-09-17, **운영 RGB 경로·Overview/영상 페이지까지 opt-in 통합 구현**.
로컬 회귀 및 Jetson 격리 RGB 동작 시험 완료. 운영 기본값은 off이며 운영 Jetson 서버에 배포하지 않았다.
실제 망 용량 제한·장시간·반복 비교에 의한 최적 임계값/성능 우위 검증은 별도다.
이슈: https://github.com/RoboLotus/hazard-guard-console/issues/29
브랜치: `perf/rgbd-streaming-pipeline`. Robot 저장소 변경 없음.

## 1. 결정 배경

이전 JPEG 선택은 당시 구현·측정 조건에서의 안전한 운영 선택이지 모든 네트워크에서의 최적해가 아니다.

- 동일 녹화 입력 60프레임의 이전 코덱 시험: JPEG Q82 201.96KiB/s / 인코딩 CPU 시간 2.28ms,
  H.264 ultrafast CRF23 79.23KiB/s / 5.76ms. 바이트 약60.8% 절감의 가능성이 있지만
  PSNR 47.28→38.42dB, SSIM .9980→.9892로 **동일 화질 비교가 아니다**.
- 이전 실시간 H.264는 WebRTC, JPEG는 별도 전달 방식이었다. CPU·복구 차이를 코덱만의 효과로 단정하지 않는다.
- 9/15 운영 JPEG 12연결 시험에서는 HTTP CPU 평균56.647%, WS33.895/34.247%가 관찰됐다.
  1코어=100%인 프로세스 지표이고 HTTP1회/WS2회다. 로봇12대·사용자12명이 아니라 한 브라우저12연결이다.
- 따라서 이번에는 **동일 WebSocket 전달 방식**에서 JPEG / H.264 / 자동 정책을 분리 비교한다.
  WebRTC 전체 설계보다 좋다는 비교는 하지 않는다.

## 2. 불변 조건

1. 640×480, 목표10FPS. 해상도를 몰래 줄이지 않는다.
2. 화면용 RGB만 변경. 원본 Depth·열화상·이상탐지·주행·디스펜서 경로 변경 없음.
3. 원본 대기1개, 인코딩 결과1개, 접속자당 미확인 프레임1개. 밀린 영상 재생 금지.
4. 새 프레임을 복원할 수 없으면 오래된 화면을 숨긴다. 연결 표시만 유지하며 멈춘 영상을 현재 영상처럼 보여주지 않는다.
5. `HAZARD_GUARD_RGB_ADAPTIVE=on`일 때만 운영 ROS media/화면에 연결한다.
   off는 기존 JPEG 경로다. 이 문서의 실물 재시험은 운영 서버가 아닌 별도 읽기 전용 시험 서버에서 수행했다.

## 3. 구조

```text
RGB 전용 입력(ROS 구독 / NPY 재생 / 합성 fixture)
  → 최신 원본 슬롯1 → 공유 인코더1(JPEG 또는 H.264)
  → 최신 압축 슬롯1 → WebSocket 요청/표시완료 ACK
  → JPEG ImageBitmap / H.264 WebCodecs → Canvas
                             ↓
  CPU + 인코딩시간 + ACK왕복 + 디코딩시간 + 수신후 나이 + 프레임바이트
                             ↓
           2초 판단창 / 지속조건 / 시험 전환 / 실패복귀 / 복구대기
```

- H.264: libx264 software, baseline/zerolatency/ultrafast, B프레임0, 인코더2스레드,
  기본800kbit/s, GOP목표1초, 키프레임에SPS/PPS 반복. 전용 NVENC 사용이라고 표시하지 않는다.
- H.264는 중간 프레임을 버리면 참조가 깨진다. 순번 누락·새 접속·epoch 변경 시
  P프레임을 보내지 않고 **새 키프레임을 요청**한다(공유 요청 최대4회/초).
  과거 키프레임+밀린 델타를 재전송하지 않는다. 키프레임 증가가 대역폭 이득을 상쇄할 수 있어 반드시 측정한다.
- H.264에서 모든 수신자가 ACK 대기 중이면 인코딩도 대기한다. 대기 중 입력은 최신 1개로 교체한다.
  수신 속도가 다른 화면들로 최근10초 키프레임 요청이12회 이상 누적되면 JPEG로 복귀한다.
- 모든 접속자가 H.264를 지원할 때만 공유 코덱을 바꾼다. 미지원/디코더 오류는 JPEG로 복구.
  고객별 별도 인코더를 만들지 않는다. 혼합 브라우저 한 대가 전체 JPEG를 선택하는 비용은 의도적으로 남겨둔다.
- 화면 숨김 시 연결/디코더 해제. 최대16접속, 수신1KiB, 송신timeout750ms,
  요청timeout2초, 브라우저무응답감시1.5초. Origin검사≠인증. 기본 loopback이며 공용 인터넷에 노출하지 않는다.

## 4. 초기 정책 — 실측 최적값이 아닌 검증할 가설

| 신호 | 초기 조건 | 조치 |
|---|---|---|
| 전달 지연 지속 | ACK>140ms, decode<60ms, 2초창3회 | CPU평균<65%이고 지원 가능하면 H.264 8초 시험 |
| H.264 시험 평가 | 수신후 나이 ≤max(500ms, 직전1.2배), decode≤100ms, 프레임바이트15% 이상 감소 | 유지. 하나라도 실패하면 JPEG 복귀, 60초 재시험 금지 |
| CPU/인코더 압박 | 전체CPU≥85% 또는 최근처리시간≥프레임간격75% | H.264→JPEG, 최대5FPS/Q70. JPEG도 부하 축소 |
| JPEG 전달 지연 | H.264 시험 불가/재시험 대기 | Q82→70→55, 이후 FPS10→8→5 |
| H.264 전달 지연 | 800kbit/s에서 압박 지속 | 400kbit/s, 이후 FPS10→8→5 |
| 시험 성공 후 안정된 RTT | 시험 성공 시 ACK의1.2배 이내, 나이<300ms | 같은 RTT만으로 계속 화질/FPS를 낮추지 않음 |
| H.264 참조 복구 과다 | 키프레임 요청≥12회/10초 | JPEG 복귀,60초 재시험 금지 |
| 클라이언트 처리 지연 | decode>100ms 또는 수신후 나이>500ms | FPS 축소, 네트워크 문제라고 단정하지 않음 |
| 안정적 회복 | ACK<100ms, 나이<300ms, decode<50ms, 2초창10회 | FPS 우선 회복 후 품질/비트레이트 회복 |

일반 하향 변경 최소10초, 상향 최소20초. CPU·코덱 오류 보호는 대기 예외다.
현재 H.264→JPEG 자동 복귀는 CPU/인코더/지원 여부/시험 실패/참조 복구 과다에 의한다.
단순 네트워크 회복만으로 JPEG를 주기적으로 재시험하는 기능은 아직 없다.
두 코덱 사이의 반복 전환 비용을 측정한 뒤 필요하면 추가한다.

접속자별 최근2.5초 ACK표본3개 이상 → 각각 중앙값 → 접속자간 중앙값으로 판단한다.
한 느린 화면에 맞춰 무조건 전체를 낮추지 않지만 **모든 사용자의 SLA를 보장하지는 않는다**.
ACK가 없는 창은 네트워크 측정치로 만들지 않는다. ACK가 없어도 CPU과부하 보호는 동작한다.
현재 인코딩시간 보호는 최근1회 값이며 p95가 아니다. Jetson 반복 결과에 따라 지속조건/분위수 적용 여부를 결정한다.

## 5. 최신성·로그의 정확한 뜻

- 서버는 자체 RGB 수신 monotonic 시각부터 500ms 넘은 원본/압축결과를 버린다.
- 브라우저 `age_ms`: 서버 전송시 수신후 나이 + 요청시작~디코딩~rAF 시각.
  요청 uplink/서버대기도 더해져 **보수적 상한 추정**이며 정확한 촬영→화면 지연은 아니다.
- 표시 직전500ms 넘은 영상은 폐기. 기존 영상도 잔여 유효기간 이후 숨김.
  100ms 타이머 및 브라우저 스케줄링 때문에 엄격한 실시간500ms 보장은 아니다.
- ACK는 서버송신~화면처리완료시간으로 네트워크·브라우저·스케줄링을 포함한다.
  ACK만으로 가용대역폭이나 패킷손실률을 측정했다고 말하지 않는다.
- 전체CPU: psutil 모든 논리코어 평균0~100%. 프로세스CPU: 1코어100%, 멀티코어이면100% 초과 가능.
- JSONL1초주기, 파일4MB×최대3개. 메모리 판단창300개/전환이력100개/접속자ACK120개 제한.
  오래된 로그는 회전된다. 정식측정은 회전 전에 조건별 폴더로 보존한다.
- 브라우저 JSON 저장은 최근600개 표본만 보존하는 **동작확인 자료**다. 전체 실행의 p95라고 부르지 않는다.
  프레임 PNG는 표시결과 참고자료이며 원본·압축바이트 동일시점 보존을 대체하지 않는다.
- 창이 가려져 rAF가300ms 안에 오지 않는 경우 코덱 오류로 취급하지 않는다. 연결·디코더를 해제하고
  화면 갱신이 재개될 때만 새 연결을 시작한다. 미표시 VideoFrame과 예약 rAF를 정리하고 wake 콜백1개만 유지한다.
  `paint_pauses`/최근오류20개로 디코더 실패와 구별한다.

## 6. 실행

backend 폴더에서 격리 venv에 `pip install -r requirements-adaptive.txt`.
Jetson은 기존 ROS/CvBridge를 읽을 수 있는 Python 환경을 선택하되 운영 venv를 덮어쓰지 않는다.
PyAV/libx264 제공 여부와 설치 시 FFmpeg 의존성은 기기에서 사전 점검한다.

```powershell
# Windows / backend
$env:PYTHONPATH='.'
.venv-adaptive/Scripts/python.exe scripts/rgb_adaptive_experiment.py --mode auto --source synthetic --port 8002 --output D:/Develop/hazard-guard/outputs/rgb-adaptive/local-auto

# 별도 터미널 / frontend: npm의 PowerShell 인자 전달 혼동을 피하려고 node로 실행
$env:HAZARD_GUARD_BACKEND_URL='http://127.0.0.1:8002'
node node_modules/vite/bin/vite.js --config tests/vite.benchmark.config.mjs --host 127.0.0.1 --port 5173 --strictPort
```

`http://127.0.0.1:5173/tests/rgb-adaptive-harness.html` → 시작.
다른 프런트 포트면 서버 `--origin http://127.0.0.1:포트` 추가.
서버 `--mode jpeg|h264|auto`로 비교. 고정 모드도 CPU/미지원 보호가 개입할 수 있으므로 로그의 **실제 profile** 확인.
`--source npy --path ...`는 `N×480×640×3 uint8 BGR` 배열을20FPS로 반복(메모리맵).
기본 합성영상은 움직이는 사각형이며 실제 영상 압축률 평가에 사용하면 안 된다.

```bash
# Jetson / backend: 이미 실행 중인 RGB 토픽에 읽기전용 구독만 연결
# ROS 환경을 source하고, 실제 센서와 같은 ROS_DOMAIN_ID를 먼저 확인한다.
PYTHONPATH=. python scripts/rgb_adaptive_experiment.py \
  --source ros --topic /실제/RGB/image_raw --mode auto \
  --port 8002 --output /시험결과/조건별폴더
```

센서 드라이버·Nav2·모터를 이 스크립트가 시작하지 않는다. SSH 포트포워딩 등 기존 승인된 사설 연결로 접근한다.
WebCodecs는 secure context(HTTPS 또는 localhost)가 필요하며 지원브라우저마다 확인한다.
실험 상태: `/api/bench/rgb-adaptive/status`, WS: `/ws/bench/rgb-adaptive`.
실험 종료: 서버 Ctrl+C, 브라우저 중지, Vite Ctrl+C. 운영 롤백은 필요 없음(기본경로 변경 없음).

## 7. 다음 비교 설계 / 통과 기준

1. **정확성:** 동일 입력의 JPEG/H.264 decode 확인, 키프레임 복구, 순번/epoch 변경, 미지원 브라우저,
   입력 중단/복구, 서버 재시작, 연결 해제, 느린클라이언트, 종료 시 메모리/작업 해제.
2. **고정코덱 비교:** JPEG Q82/70/55와 H.264 800/400kbit/s, 모두640×480/10FPS,
   같은WS·원본클립·전력모드·인코더스레드·워밍업. 정지차트와 녹화동적장면 분리.
   첫 선별30초워밍업+60초측정, 주요조건3회, 실행순서 교차. 긴 시험은 후보를 좁힌 후 실시.
3. **정책 비교:** 고정JPEG·고정H.264·자동을 정상망→제한망→회복으로 동일하게 반복.
   대역폭은 기준JPEG 실측송신량 대비150/100/60/30%로 설정하고 RTT/손실은 독립적으로 추가.
   시스템망 전체가 아니라 격리된 시험프로세스/네트워크에서 제한. SSH 제어망 손상 금지.
4. **부하:** 접속1/4/8/12, CPU낮음/중간/높음, 느린1명+정상다수, 전원/온도 통제.
   고정부하와 망제한을 먼저 각각 검증한 후 조합한다. 로봇다중화와 구별한다.
5. **지표:** 표시나이 p50/p95/p99/최대,500ms초과 폐기율, 영상미표시시간 비율 및최대연속공백,
   고유표시FPS, 프로세스/전체/코어별CPU·RSS, 실제전송bytes/s, 재접속/키프레임요청/전환횟수·복구시간,
   동일원본 프레임별PSNR/SSIM + 차트문자 판독. 채택 판단에서는 미표시시간을 반드시 함께 본다.
6. **가설:** 자동이 정상망에서는10FPS/기준품질을 유지하고, 제한망에서고정JPEG보다미표시시간을줄이며,
   CPU부하에서는고정H.264보다적은비용으로복구하는가? 동일제약에서최신성을만족하는후보끼리화질/FPS/자원을비교한다.

최신성 목표p95≤500ms만으로 채택하지 않는다. 전부 버려서 표본이 적어진 결과를 성공으로 만들 수 있기 때문이다.
미표시비율·실제FPS·전환실패율을 같이 보고, 허용공백/FPS 하한은 예비측정 후 확정한다.
수동 ACK지연/합성 정책입력은 회귀검증일 뿐, 실제 대역폭 개선 측정이 아니다.
현재 차트가 없는 상태에서 화질 우위나 Jetson 절감률을 새로 주장하지 않는다.

## 8. 근거

- [W3C WebCodecs](https://www.w3.org/TR/webcodecs/): VideoDecoder, decodeQueueSize, reset/close, secure context.
- [AVC WebCodecs 등록](https://www.w3.org/TR/webcodecs-avc-codec-registration/): description없는AnnexB, 키프레임IDR+필요parameter set. 코덱지원은브라우저의무가아님.
- [PyAV Codec API](https://pyav.org/docs/stable/api/codec.html): codec context와packet encode/decode.
- [NVIDIA Orin Nano Software Encode](https://docs.nvidia.com/jetson/archives/r36.4/DeveloperGuide/SD/Multimedia/SoftwareEncodeInOrinNano.html): Orin Nano의 소프트웨어인코딩 경로. CUDA전처리와NVENC를혼동하지않음.

이 문서의 정책 임계값은 위 표준의 권고값이 아니라 **우리 시스템에서 검증할 초기값**이다.

## 9. 운영 경로 사용·되돌리기

backend 가상환경에 `pip install -r requirements-adaptive.txt`를 적용한 뒤, 기존 ROS overlay와
환경변수를 유지하고 다음 두 값만 추가한다. ROS launch/주행 설정을 변경할 필요가 없다.

```bash
export HAZARD_GUARD_RGB_ADAPTIVE=on
export HAZARD_GUARD_RGB_ADAPTIVE_LOG=/원하는/로그/경로/rgb-adaptive.jsonl
# 기존과 같은 명령으로 FastAPI를 workers=1로 실행한다.
```

- 프런트엔드를 새 빌드로 실행하면 `/api/v1/media/status`의 `rgb.adaptive`에 따라 Overview/영상 페이지가 자동 선택한다.
  `/ws/media/rgb/adaptive`에서 JPEG ImageBitmap/H.264 WebCodecs를 사용한다. 새 프런트 환경변수는 필요 없다.
- `GET /api/v1/media/rgb/adaptive`: 현재 코덱·FPS·품질·비트레이트·전환 이유·자원/오류 지표.
- `GET /api/v1/media/rgb/pipeline`: 기존 JPEG 작업 및 적응형 지표. 로그는1Hz,4MB×3개, 경로 기본값은
  backend 실행 디렉터리의 `runtime/rgb-adaptive.jsonl`. 로그만 끄려면 `HAZARD_GUARD_RGB_ADAPTIVE_LOG=off`.
- H.264는 선택 의존성이다. PyAV/libx264 또는 브라우저 WebCodecs가 없으면 JPEG를 사용한다.
  psutil이 없으면 CPU를 추측하지 않고 H.264 자동 시험을 하지 않는다. 상태의 monitor_error로 확인한다.
- 입력이640×480이 아니면 기존 JPEG 경로를 선택한다. 원본 입력을 임의 리사이즈하지 않는다.
- 레거시 `/api/v1/media/rgb`와 `/ws/media/rgb`는 유지한다. 해당 소비자의 요청 후1초 동안만 별도 JPEG
  캐시를 생성하므로 적응형 단독 시청에 JPEG/H.264를 항상 이중 인코딩하지 않는다. 첫 스냅샷 요청은 최대250ms 준비 대기.
- 과거 RGB 유래 가상 열화상 fallback 자체는 이 작업 범위 밖이므로 그대로 유지했다. 실제 열화상 입력이 없으면
  그 기존 변환 부하는 남을 수 있다. 원본 열화상/Depth/이상탐지 경로 절감으로 성과를 계산하지 않는다.
- 되돌리기: `HAZARD_GUARD_RGB_ADAPTIVE=off` 후 backend 재시작. 미디어 상태가 기존 방식으로 돌아오며 새 화면도 JPEG 경로를 선택한다.
- RGB 코덱 모드는 로봇의 운용/주행 모드와 무관하다. 연결 승인/제어 API를 추가하거나 안전 정책을 변경하지 않았다.

## 10. 9/17 통합 후 짧은 실물 회귀

로봇 정지, 기존 RGB 카메라만 활용. 주행/YOLO/디스펜서 미기동, 새 이미지 캡처 없음.
Jetson 원본 운영 저장소·서버는 수정하지 않고 `/tmp/hg-rgb-final-20260917.iZJCr1`에서 읽기 전용 시험했다.

| 조건 | 측정 구간 | 복원 FPS | 응용 KiB/s | 수신 후 나이 상한 p95 | 503 |
|---|---|---:|---:|---:|---:|
| auto + ACK160ms 지연 | 워밍업10초+30초 | 4.73 | 17.89 | 126.04ms | 0 |
| 빠른 수신기 + 느린 수신기 중 빠른 쪽 | 워밍업5초+20초 | 7.50 | 33.48 | 262.32ms | 0 |
| 빠른 수신기 + 느린 수신기 중 느린 쪽 | 워밍업5초+20초 | 4.85 | 27.52 | 206.07ms | 0 |

- 첫 조건: JPEG→H.264 시험/채택, 키프레임 요청0, encode 실패/프로토콜오류/전송timeout0.
- 두 수신기는 약10초 차이로 시작되어 일부 구간만 겹친다. 동기화된 동일 구간 성능 비교가 아니라 혼합 속도 복구 시험이다.
  키프레임 요청 누적으로 H.264→JPEG 복귀했고 두 수신기 모두 종료까지 정상 복원했다.
- 모든 조건은 headless 복원 완료 기준이다. 브라우저 표시FPS나 촬영→화면 지연이 아니며,
  ACK160ms는 인위적인 피드백 지연이지 실제 가용대역폭 제한이 아니다. 목표10FPS는 상한/목표이지 모든 부하에서의 보장이 아니다.
- 이전 빠른 시험의 `monotonic`을 `perf_counter`로 변경해 Windows 타이머 양자화를 줄이고 측정창 끝 프레임을 제외했다.
  따라서 앞선 기록과 소수점 단위의 성능 개선율을 계산하지 않는다.
- 자료: workspace `outputs/rgb-adaptive/2026-09-17/implementation-check/`. 원본코드/로그도 함께 보존한다.
- 실제 브라우저: 최종 플레이어로 H.264752프레임 표시, 폐기/실패/재연결/paint_pause0.
  마지막600개 수신후나이상한p95 182.01ms. 고정 길이 FPS 시험이 아닌 UI 관찰이다.
  그 전에 가려진 창의 rAF 제한 및 구버전 Starlette close 예외를 발견해 수정했다. 이전 실패 로그도 보존했다.
- 최종 자동검증: backend300개, frontend123개 통과, Vite production build 성공.
  기존 Starlette deprecation2건과 번들500kB 경고는 남는다. 원격 운영 배포/실제 망 제한/장기 안정성 검증과 구별한다.

## 11. 포트폴리오 표현

**코덱 고정 대신 최신성 우선 적응형 RGB 전송 구현**

JPEG·H.264·VP8를 동일 입력으로 비교했다. H.264는 JPEG 대비 압축 데이터량을
**201.96→79.23KiB/s(60.8%)** 줄였지만, 프레임당 인코딩 CPU 시간은 **2.28→5.76ms(약2.5배)**로 증가했다.
이를 바탕으로 코덱을 하나로 고정하지 않고, **수신 지연·CPU 여유·인코딩 시간을 관찰해 JPEG 품질,
처리 FPS, H.264 비트레이트와 코덱을 자동 조절**하도록 구현했다. 최신 프레임만 유지하고,
CPU 부담이나 참조 프레임 복구 비용이 커지면 JPEG로 복귀해 오래된 영상이 밀려 재생되는 것을 방지했다.
Jetson RGB 시험에서 자동 전환 및 혼합 수신 속도에 따른 JPEG 복귀를 확인했다.

측정 각주: 코덱 비교값은640×480 동일60프레임을10FPS로 환산한 압축 바이트량이다. 실제 네트워크 처리량,
동일 화질 비교 또는 적응형 구현의 최종 절감률이 아니다. JPEG Q82와 H.264 CRF23 비교이며,
현 적응형 H.264는800/400kbit/s 제어를 사용한다. 단위는ms/frame이며ms/FPS가 아니다.
