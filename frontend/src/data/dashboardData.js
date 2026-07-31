export const initialThresholds = {
  warningTemperature: 60,
  warningDuration: 5,
  criticalTemperature: 80,
  criticalDuration: 3,
  clearTemperature: 50,
  clearDuration: 10,
  warningRepeat: 60,
  criticalRepeat: 30,
};

export const initialEvents = [
  { id: 1, level: "critical", status: "new", title: "고온 위험 감지", date: "2026-07-23", time: "14:32:08", location: "A동 펌프실 · P-02", temperature: "84.6°C", threshold: "80°C · 3초", detail: "설정된 위험 조건이 지속되어 확인이 필요합니다.", acknowledged: false, assignee: "미지정", note: "열화상과 RGB 영상을 함께 확인하세요." },
  { id: 2, level: "warning", status: "new", title: "온도 상승 감지", date: "2026-07-23", time: "14:29:41", location: "A동 펌프실 · P-01", temperature: "63.2°C", threshold: "60°C · 5초", detail: "경고 온도 구간에 진입했습니다.", acknowledged: false, assignee: "미지정", note: "온도 상승 추이를 관찰 중입니다." },
  { id: 3, level: "warning", status: "new", title: "진동 주의", date: "2026-07-23", time: "14:18:07", location: "A동 펌프실 · P-03", temperature: null, threshold: "7.0 mm/s", detail: "진동 속도 7.8 mm/s가 감지되었습니다.", acknowledged: false, assignee: "미지정", note: "센서 규격 확정 후 진동 기준을 조정합니다." },
  { id: 4, level: "info", status: "resolved", title: "순찰 지점 통과", date: "2026-07-23", time: "14:15:22", location: "A동 중앙 통로 · WP-04", temperature: null, threshold: null, detail: "예정된 순찰 경로를 정상 주행 중입니다.", acknowledged: true, assignee: "시스템", note: "자동 기록된 순찰 로그입니다." },
  { id: 5, level: "info", status: "resolved", title: "LiDAR 데이터 정상", date: "2026-07-23", time: "14:12:05", location: "시스템 · T-MINI Plus", temperature: null, threshold: null, detail: "주행 센서 데이터가 정상 수신되고 있습니다.", acknowledged: true, assignee: "시스템", note: "자동 상태 점검 결과입니다." },
];

export const eventStatusLabels = {
  new: "신규",
  acknowledged: "확인됨",
  working: "처리 중",
  resolved: "해결됨",
};

export const reportData = {
  today: { label: "오늘", patrolHours: 6.4, distance: 3.8, completion: 92, events: 5, critical: 1, warning: 2, info: 2, acknowledge: 2.8, resolve: 18, temperature: 84.6 },
  week: { label: "최근 7일", patrolHours: 41.2, distance: 24.7, completion: 89, events: 31, critical: 4, warning: 12, info: 15, acknowledge: 3.4, resolve: 21, temperature: 88.1 },
  month: { label: "최근 30일", patrolHours: 172.8, distance: 103.5, completion: 87, events: 126, critical: 18, warning: 43, info: 65, acknowledge: 4.1, resolve: 24, temperature: 91.3 },
};

export const navigationLabels = {
  overview: "Overview",
  map: "지도",
  events: "이벤트",
  video: "영상",
  report: "리포트",
  settings: "설정",
  help: "도움말",
};
