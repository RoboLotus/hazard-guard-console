import {
  Archive,
  ArrowRight,
  Binoculars,
  BookOpenText,
  Camera,
  CheckCircle,
  Clock,
  Cube,
  DownloadSimple,
  Eye,
  FloppyDisk,
  Gauge,
  Keyboard,
  ListChecks,
  MapTrifold,
  NavigationArrow,
  PencilSimple,
  Pulse,
  ShieldWarning,
  SlidersHorizontal,
  ThermometerHot,
  WarningCircle,
} from "@phosphor-icons/react";
import { DetailHeading } from "../components/Common.jsx";

const quickSteps = [
  {
    icon: Gauge,
    title: "연결 상태 확인",
    description: "Overview에서 서버와 센서 상태를 먼저 확인합니다.",
  },
  {
    icon: MapTrifold,
    title: "지도 생성",
    description: "지도 탭에서 환경을 고르고 새 SLAM 세션을 시작합니다.",
  },
  {
    icon: Keyboard,
    title: "공간 탐색",
    description: "조작기로 이동하며 선택한 방식의 2D·3D 지도를 수집합니다.",
  },
  {
    icon: NavigationArrow,
    title: "순찰 실행",
    description: "저장 지도를 선택하고 웨이포인트 순찰을 시작합니다.",
  },
];

const screenGuides = [
  ["Overview", "로봇·센서·영상·위험 이벤트를 한 화면에서 확인합니다."],
  ["지도", "SLAM/순찰 모드, 2D·3D 지도, 웨이포인트와 시뮬레이션 환경을 관리합니다."],
  ["이벤트", "감지된 위험을 확인하고 처리 상태를 변경합니다."],
  ["영상", "RGB 및 열화상 스트림을 크게 확인합니다."],
  ["리포트", "순찰별 Jetson CPU·GPU·RAM 부하와 프로세스 통계를 확인합니다."],
  ["설정", "화재 판정 임계값을 저장하고 ROS 센서 토픽의 수신 상태를 진단합니다."],
];

function StepList({ children }) {
  return <ol className="help-step-list">{children}</ol>;
}

function HelpSection({ id, icon: Icon, eyebrow, title, children }) {
  return (
    <section className="help-section" id={id}>
      <header>
        <span className="help-section-icon"><Icon size={22} weight="fill" /></span>
        <div>
          <span className="eyebrow">{eyebrow}</span>
          <h2>{title}</h2>
        </div>
      </header>
      <div className="help-section-body">{children}</div>
    </section>
  );
}

export default function HelpPage({ onNavigate }) {
  return (
    <div className="detail-page help-page">
      <DetailHeading
        eyebrow="HELP CENTER"
        title="HazardGuard WebUI 사용 가이드"
        description="처음 사용하는 작업자를 위한 지도 생성부터 웨이포인트 순찰까지의 운용 절차입니다."
      >
        <button type="button" className="button primary compact-button" onClick={() => onNavigate("map")}>
          <MapTrifold size={17} weight="fill" />지도 관제 열기
        </button>
      </DetailHeading>

      <section className="help-quick-start" aria-labelledby="quick-start-title">
        <header>
          <div>
            <span className="eyebrow">QUICK START</span>
            <h2 id="quick-start-title">기본 운용 흐름</h2>
          </div>
          <p>시뮬레이션·실물 공통 · 왼쪽부터 순서대로 진행</p>
        </header>
        <div className="help-quick-grid">
          {quickSteps.map(({ icon: Icon, title, description }, index) => (
            <article key={title}>
              <span className="help-step-number">{index + 1}</span>
              <Icon size={22} weight="fill" />
              <strong>{title}</strong>
              <p>{description}</p>
              {index < quickSteps.length - 1 && <ArrowRight className="help-step-arrow" size={17} weight="bold" />}
            </article>
          ))}
        </div>
      </section>

      <div className="help-layout">
        <nav className="help-toc" aria-label="도움말 목차">
          <strong><BookOpenText size={17} weight="fill" />이 페이지에서</strong>
          <a href="#screens">화면 구성</a>
          <a href="#mapping">새 지도 만들기</a>
          <a href="#patrol">웨이포인트 순찰</a>
          <a href="#sessions">저장 지도 관리</a>
          <a href="#digital-twin">2D·3D 지도 보기</a>
          <a href="#monitoring">위험 모니터링</a>
          <a href="#diagnostics">센서 진단</a>
          <a href="#status">표시 상태 이해하기</a>
          <a href="#troubleshooting">문제 해결</a>
        </nav>

        <div className="help-content">
          <HelpSection id="screens" icon={Binoculars} eyebrow="01 · NAVIGATION" title="화면 구성">
            <div className="help-screen-grid">
              {screenGuides.map(([name, description]) => (
                <article key={name}>
                  <strong>{name}</strong>
                  <p>{description}</p>
                  <button type="button" onClick={() => onNavigate(name === "Overview" ? "overview" : name === "지도" ? "map" : name === "이벤트" ? "events" : name === "영상" ? "video" : name === "리포트" ? "report" : "settings")}>
                    화면 열기<ArrowRight size={13} />
                  </button>
                </article>
              ))}
            </div>
          </HelpSection>

          <HelpSection id="mapping" icon={MapTrifold} eyebrow="02 · SLAM" title="2D 완성 후 RGB-D 3D 지도 만들기">
            <StepList>
              <li><strong>지도 탭</strong>에서 기존 운용 모드가 정지 상태인지 확인합니다.</li>
              <li>시뮬레이션에서는 <strong>시뮬레이션 환경·지도</strong>에서 시험 환경을 선택합니다. 실물에서는 <strong>현장 지도 세션</strong>이 표시됩니다.</li>
              <li><strong>1단계 · 2D 지도 작성</strong>을 선택합니다. 실행 중으로 바뀌면 SLAM Toolbox가 빈 세션에서 지도를 작성합니다.</li>
              <li>시뮬레이션은 <strong>가상 조작기</strong>의 버튼 또는 방향키/WASD를 사용하고, 실물 M1은 동봉 조이스틱으로 이동합니다.</li>
              <li>2D 작성이 끝나면 <strong>현재 2D SLAM 지도 저장</strong> 또는 <strong>지도 저장 후 종료</strong>를 누르고 저장 결과를 순찰 지도로 지정합니다.</li>
              <li><strong>2단계 · RGB-D 3D 수집</strong>을 선택하고 같은 공간을 한 번 더 주행합니다. 이 단계는 저장된 2D 지도에서 AMCL·Nav2로 위치를 추정합니다.</li>
              <li>수집이 끝나면 <strong>3D 수집 종료 및 DB 저장</strong>을 눌러 RTAB-Map DB를 안전하게 닫습니다.</li>
            </StepList>
            <div className="help-callout info">
              <Keyboard size={20} weight="fill" />
              <div><strong>가상 조작기는 시뮬레이션 전용입니다.</strong><p>키나 버튼을 놓거나 창에서 벗어나면 정지합니다. 통신이 끊겨도 서버가 자동으로 정지 명령을 보냅니다.</p></div>
            </div>
            <div className="help-callout warning">
              <ShieldWarning size={20} weight="fill" />
              <div><strong>실물 로봇은 WebUI 가상 조작을 차단합니다.</strong><p>백엔드를 physical 대상으로 실행하면 Gazebo와 가상 조작기가 비활성화됩니다. 맵 작성 중에는 조이스틱을 사용하고 비상 정지 공간을 확보하세요.</p></div>
            </div>
            <div className="help-callout neutral">
              <FloppyDisk size={20} weight="fill" />
              <div><strong>맵 생성은 매번 새로운 세션입니다.</strong><p>같은 환경에서도 회차별 결과가 누적됩니다. 순찰에 사용할 지도는 저장 결과 목록에서 별도로 지정합니다.</p></div>
            </div>
            <div className="help-callout neutral">
              <Cube size={20} weight="fill" />
              <div><strong>2D와 3D는 같은 세션의 서로 다른 주행 단계입니다.</strong><p>첫 주행에서 SLAM Toolbox가 2D 지도를 완성하고, 두 번째 주행에서는 저장 지도 localization이 좌표를 담당합니다. RTAB-Map은 map→odom을 발행하거나 ICP·loop closure로 별도 주행 좌표를 만들지 않고 RGB-D 기록만 담당합니다.</p></div>
            </div>
            <div className="help-callout warning">
              <WarningCircle size={20} weight="fill" />
              <div><strong>지도 완성률은 자동으로 계산하지 않습니다.</strong><p>현재 버전은 탐색률이나 미관측 영역을 표시하지 않습니다. 작업자가 2D 지도와 3D 관측 결과를 직접 확인한 뒤 저장해야 합니다.</p></div>
            </div>
          </HelpSection>

          <HelpSection id="patrol" icon={NavigationArrow} eyebrow="03 · NAV2" title="웨이포인트 순찰 실행하기">
            <StepList>
              <li>맵 생성이 끝났다면 지도를 저장하고 현재 모드를 종료합니다.</li>
              <li><strong>순찰용 SLAM 결과</strong>에서 사용할 지도를 선택하고 <strong>순찰 지도 지정</strong>을 누릅니다.</li>
              <li><strong>순찰</strong> 모드로 전환합니다. 맵 생성 종료 위치가 AMCL 초기 위치로 자동 전달되며, 실패하면 <strong>저장된 마지막 위치로 AMCL 다시 초기화</strong>를 누릅니다.</li>
              <li><strong>지도에서 웨이포인트 추가</strong>를 누르고 지점을 클릭한 뒤 이름, 바라볼 방향, 관찰 시간을 입력합니다.</li>
              <li>드래그 또는 순서 버튼으로 방문 순서를 바꿉니다. 지점이 여러 개면 <strong>순서 추천</strong>을 사용할 수 있습니다.</li>
              <li><strong>반복·운영 시간</strong>에서 즉시/예약 시작과 1회·지정 횟수·지정 시각·수동 종료 중 하나를 선택합니다. 반복 순찰은 회차 사이 대기시간도 지정할 수 있습니다.</li>
              <li><strong>경로 저장</strong> 후 순찰을 시작합니다. 실행 중에는 현재 회차, 다음 시작 시각, 운영 종료 시각과 현재 웨이포인트를 확인합니다.</li>
            </StepList>
            <div className="help-callout warning">
              <ShieldWarning size={20} weight="fill" />
              <div><strong>맵 생성 모드에서는 순찰 명령을 보낼 수 없습니다.</strong><p>오조작을 막기 위해 순찰 버튼이 제한됩니다. 반드시 저장 지도와 순찰 모드를 먼저 준비하세요.</p></div>
            </div>
            <div className="help-callout info">
              <Clock size={20} weight="fill" />
              <div><strong>예약은 Jetson의 실제 시각을 기준으로 실행됩니다.</strong><p>WebUI를 닫거나 새로고침해도 ROS 임무 관리자가 예약과 반복을 계속 처리합니다. 정확한 시작·종료를 위해 Jetson의 날짜, 시간대와 NTP 동기화 상태를 먼저 확인하세요.</p></div>
            </div>
          </HelpSection>

          <HelpSection id="sessions" icon={Archive} eyebrow="04 · MAP LIBRARY" title="저장된 지도 세션 관리하기">
            <StepList>
              <li><strong>순찰용 SLAM 결과</strong>에서 환경별로 누적된 지도 세션을 선택합니다.</li>
              <li><PencilSimple size={15} /> <strong>연필 아이콘</strong>으로 날짜 기반 기본 이름을 현장·회차를 알아보기 쉬운 이름으로 바꿉니다.</li>
              <li><Archive size={15} /> <strong>보관 아이콘</strong>으로 당장 사용하지 않는 세션을 목록에서 숨깁니다. 보관은 파일 삭제가 아니며 언제든 해제할 수 있습니다.</li>
              <li><Eye size={15} /> <strong>눈 아이콘</strong>으로 저장된 3D 세션을 다시 열고, <DownloadSimple size={15} /> <strong>다운로드 아이콘</strong>으로 컬러 PLY를 내려받습니다.</li>
              <li>순찰에 사용할 2D 지도는 세션을 고른 뒤 <strong>순찰 지도 지정</strong>으로 활성화합니다.</li>
              <li><strong>저장 파일 위치</strong>에서 세션 폴더와 map.yaml, map.pgm, RTAB-Map DB, PLY 경로를 확인하거나 폴더 경로를 복사합니다.</li>
            </StepList>
            <div className="help-callout info">
              <FloppyDisk size={20} weight="fill" />
              <div><strong>3D 결과를 다시 열려면 먼저 수집을 종료하세요.</strong><p>실행 중 데이터베이스를 안전하게 내보내기 위해 <strong>3D 수집 종료 및 DB 저장</strong>을 사용합니다. 최초 PLY 생성은 데이터 크기에 따라 시간이 걸릴 수 있습니다.</p></div>
            </div>
            <div className="help-callout neutral">
              <Archive size={20} weight="fill" />
              <div><strong>세션은 환경별로 계속 누적됩니다.</strong><p>보관은 목록 정리 기능이며 지도·DB·PLY 파일을 삭제하지 않습니다. 저장 공간 정리는 관리자와 합의한 뒤 별도로 수행해야 합니다.</p></div>
            </div>
          </HelpSection>

          <HelpSection id="digital-twin" icon={Cube} eyebrow="05 · DIGITAL TWIN" title="2D·3D 지도와 센서 정보 보기">
            <div className="help-two-column">
              <article>
                <MapTrifold size={21} weight="fill" />
                <strong>2D 지도</strong>
                <p>LiDAR 점유 지도, 로봇 방향, 이동 궤적, Depth·열화상 카메라 시야각과 열원 히트맵을 함께 표시합니다.</p>
                <ul><li>+/− 버튼: 확대·축소</li><li>지도 드래그: 화면 이동</li><li>중앙 정렬: 로봇 위치로 복귀</li></ul>
              </article>
              <article>
                <Cube size={21} weight="fill" />
                <strong>3D RGB-D</strong>
                <p>RTAB-Map의 라이브 컬러 포인트클라우드와 세션 DB에서 다시 만든 과거 3D 지도를 표시합니다.</p>
                <ul><li>파란 로봇 마커: 현재 위치와 전면 방향</li><li>회색 마커: 위치 갱신 지연, 빨간 상태: 좌표계 불일치·수신 끊김</li><li>저장 세션의 눈 아이콘: 3D 다시 보기</li><li>다운로드 아이콘: 컬러 PLY 저장</li><li>실물에서는 카메라 토픽·CameraInfo·TF 정합 필요</li></ul>
              </article>
              <article>
                <ThermometerHot size={21} weight="fill" />
                <strong>3D 열화상</strong>
                <p>열화상-Depth 캘리브레이션으로 구한 외부 파라미터를 써서 Depth 표면에 온도를 입힌 라이브 3D 지도입니다. 색은 고정된 온도 구간(기본 10~60°C)이라 프레임이 달라도 같은 온도는 같은 색입니다.</p>
                <ul><li>파랑이 차갑고 빨강이 뜨겁습니다</li><li>열화상-Depth 투영 포인트를 실시간으로 표시합니다</li><li>설비 판정용 복셀 크기는 Robot의 ROI 설정을 따릅니다</li><li>저장 세션 다시 보기는 아직 없습니다</li></ul>
              </article>
            </div>
          </HelpSection>

          <HelpSection id="monitoring" icon={Camera} eyebrow="06 · MONITORING" title="영상·이벤트·임계값 사용하기">
            <div className="help-feature-list">
              <div><Camera size={19} /><span><strong>영상</strong><p>RGB와 열화상 스트림을 확인합니다. MOCK 표시는 실제 센서 영상이 아니라는 뜻입니다.</p></span></div>
              <div><ListChecks size={19} /><span><strong>이벤트</strong><p>위험 온도와 기타 이상 이벤트를 확인하고 처리 중·해결 상태로 변경합니다.</p></span></div>
              <div><SlidersHorizontal size={19} /><span><strong>설정·센서 진단</strong><p>화재 판정값을 서버에 저장하고 LiDAR, RGB-D, 열화상, IMU, Odometry 토픽 상태를 확인합니다.</p></span></div>
              <div><FloppyDisk size={19} /><span><strong>리포트</strong><p>순찰 중 자동 수집한 Jetson 및 ROS 프로세스 성능 통계를 조회하고, 이름 변경·CSV 저장·삭제를 수행합니다.</p></span></div>
            </div>
            <div className="help-callout info">
              <SlidersHorizontal size={20} weight="fill" />
              <div><strong>임계값은 서버 저장값이 기준입니다.</strong><p>서버가 연결되면 서버에 저장된 값이 다시 로드됩니다. 서버가 잠시 끊기면 브라우저 저장값을 예비값으로 사용하며, 연결 복구 후 다시 서버 값과 동기화합니다.</p></div>
            </div>
          </HelpSection>

          <HelpSection id="diagnostics" icon={Pulse} eyebrow="07 · SENSOR HEALTH" title="센서 진단 결과 이해하기">
            <StepList>
              <li><strong>설정 탭</strong>의 센서 진단에서 LiDAR, RGB, Depth, 열화상, IMU, Odometry와 포인트클라우드 상태를 확인합니다.</li>
              <li><strong>실시간</strong>은 최근 토픽 메시지가 들어왔다는 뜻이고, <strong>데이터 대기</strong>는 아직 한 번도 수신하지 못했다는 뜻입니다.</li>
              <li><strong>갱신 중단</strong>은 이전에 수신했지만 정해진 시간 동안 새 메시지가 없다는 뜻입니다. <strong>ROS 미연결</strong>이면 먼저 백엔드의 ROS 브리지를 확인합니다.</li>
              <li>3D 수집 전에는 RGB·Depth 영상과 각각의 CameraInfo, Odometry가 모두 갱신되는지 확인하고 카메라와 로봇 사이 TF도 별도로 검증합니다.</li>
            </StepList>
            <div className="help-callout warning">
              <Pulse size={20} weight="fill" />
              <div><strong>실시간 표시는 캘리브레이션 성공을 보장하지 않습니다.</strong><p>센서 진단은 토픽 수신 시각만 검사합니다. RGB–Depth 정렬, 내부·외부 파라미터, TF 방향과 실제 측정 정확도는 RViz 및 기준 물체 테스트로 추가 확인해야 합니다.</p></div>
            </div>
          </HelpSection>

          <HelpSection id="status" icon={CheckCircle} eyebrow="08 · STATUS" title="화면 표시 상태 이해하기">
            <dl className="help-status-list">
              <div><dt><i className="help-status-dot live" />LIVE / ROS 연결</dt><dd>백엔드가 실제 ROS 토픽에서 최신 데이터를 받고 있습니다.</dd></div>
              <div><dt><i className="help-status-dot mock" />MOCK / UI MOCK</dt><dd>레이아웃 검증용 예시 데이터이며 실제 장치 동작을 의미하지 않습니다.</dd></div>
              <div><dt><i className="help-status-dot waiting" />준비 중</dt><dd>Gazebo, SLAM, AMCL 또는 Nav2의 시작을 기다리는 상태입니다.</dd></div>
              <div><dt><i className="help-status-dot danger" />오류 / 연결 끊김</dt><dd>명령을 반복하지 말고 서버, ROS 노드와 실행 로그를 먼저 확인합니다.</dd></div>
            </dl>
          </HelpSection>

          <HelpSection id="troubleshooting" icon={WarningCircle} eyebrow="09 · TROUBLESHOOTING" title="문제가 생겼을 때">
            <div className="help-faq-list">
              <details>
                <summary>지도가 목업 이미지로만 보입니다.</summary>
                <p>맵 생성 또는 순찰 모드가 실행 중인지 확인하고, 지도 상단의 데이터 상태가 ROS /map인지 확인합니다. 서버 연결이 끊겼다면 백엔드와 ROS 브리지를 다시 확인하세요.</p>
              </details>
              <details>
                <summary>가상 조작기 버튼이 비활성화되어 있습니다.</summary>
                <p>새 맵 생성 모드와 WebUI가 관리하는 Gazebo가 모두 실행 중이어야 합니다. 순찰 모드, 외부 터미널 실행 상태, ROS 브리지 미연결 상태에서는 사용할 수 없습니다.</p>
              </details>
              <details>
                <summary>순찰 시작 버튼을 누를 수 없습니다.</summary>
                <p>저장 지도 선택, 순찰 모드, AMCL 위치 추정, Nav2 및 임무 관리자 준비 상태를 순서대로 확인합니다. AMCL만 대기 중이면 저장된 마지막 위치 재적용 버튼을 사용합니다. 실물 로봇을 지도 저장 위치에서 옮겼다면 RViz의 2D Pose Estimate로 현재 위치를 다시 지정해야 합니다.</p>
              </details>
              <details>
                <summary>재실행 후 지도가 겹쳐 보입니다.</summary>
                <p>이전 SLAM 프로세스가 남아 있거나 새 세션과 기존 지도가 함께 표시될 수 있습니다. 운용 모드를 정상 종료한 뒤 새 맵 생성 세션을 시작하고 중복 ROS 노드가 없는지 확인합니다.</p>
              </details>
              <details>
                <summary>저장된 3D 지도가 열리지 않거나 PLY 다운로드가 실패합니다.</summary>
                <p>해당 2D 세션에서 <strong>2단계 · RGB-D 3D 수집</strong>을 실행해 RTAB-Map DB가 생성됐는지 확인합니다. 라이브 수집 중이면 3D 수집 종료 후 다시 시도하고, 백엔드 환경에 <code>rtabmap-export</code>가 설치되어 있는지도 확인합니다.</p>
              </details>
              <details>
                <summary>센서 진단이 모두 데이터 대기로 표시됩니다.</summary>
                <p>시뮬레이터나 실물 센서 노드가 정지해 있다면 정상적인 표시입니다. 실행 중인데도 바뀌지 않으면 ROS 브리지 연결, ROS_DOMAIN_ID, 네트워크 설정과 실제 토픽 이름을 확인합니다.</p>
              </details>
              <details>
                <summary>센서는 실시간인데 3D 지도가 어긋납니다.</summary>
                <p>토픽은 도착하지만 RGB–Depth 캘리브레이션, CameraInfo, 시간 동기화 또는 TF가 맞지 않을 가능성이 큽니다. RViz에서 같은 시각의 컬러·Depth·포인트클라우드를 겹쳐 보고 기준 물체의 위치가 일치하는지 확인합니다.</p>
              </details>
            </div>
          </HelpSection>
        </div>
      </div>
    </div>
  );
}
