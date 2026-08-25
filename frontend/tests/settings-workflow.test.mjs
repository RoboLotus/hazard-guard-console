import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const settings = readFileSync(new URL("../src/pages/Settings.jsx", import.meta.url), "utf8");
const equipment = readFileSync(new URL("../src/components/EquipmentSettings.jsx", import.meta.url), "utf8");
const mapEquipment = readFileSync(new URL("../src/components/MapEquipmentPanel.jsx", import.meta.url), "utf8");
const mapPanel = readFileSync(new URL("../src/components/MapPanel.jsx", import.meta.url), "utf8");
const pointCloudPanel = readFileSync(new URL("../src/components/PointCloudPanel.jsx", import.meta.url), "utf8");
const equipmentModel = readFileSync(new URL("../src/equipmentSettingsModel.js", import.meta.url), "utf8");
const diagnostics = readFileSync(new URL("../src/components/SensorDiagnostics.jsx", import.meta.url), "utf8");
const styles = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");

test("settings navigation persists the selected internal tab in the URL", () => {
  assert.match(settings, /searchParams\.set\("settings", nextSection\)/);
  assert.match(settings, /role="tablist"/);
  assert.match(settings, /이상 탐지 설정/);
  assert.match(settings, /연결 상태 점검/);
});

test("equipment editing provides safe confirmation and portable settings", () => {
  assert.doesNotMatch(equipment, /window\.confirm/);
  assert.match(equipment, /설정 파일을 불러왔습니다/);
  assert.match(equipment, /hazard-guard-equipment-/);
  assert.match(equipment, /기준선 다시 수집/);
  assert.match(equipment, /저장되지 않은 변경/);
  assert.match(equipment, /adaptive_threshold_enabled/);
  assert.match(equipment, /자동 가변 기준 사용/);
  assert.match(equipment, /지속 상승 추세/);
  assert.match(equipment, /최근 실효 임계점/);
  assert.match(equipmentModel, /로봇 적용 실패/);
  assert.match(equipment, /\/api\/v1\/settings\/equipment\/apply/);
  assert.match(equipment, /syncStatus\.error/);
  assert.match(styles, /\.equipment-list \{[^}]*overflow-y: auto/);
  assert.match(styles, /\.equipment-list-card \{[^}]*height: 100%/);
  assert.match(equipment, /편집할 설비가 없습니다/);
  assert.match(equipment, /첫 설비 추가/);
});

test("spatial equipment editing stays in the map workflow", () => {
  assert.doesNotMatch(equipment, /EquipmentRoiPicker/);
  assert.doesNotMatch(equipment, /설비 위치 · ROI/);
  assert.match(mapEquipment, /ROI_STEP_M = 0\.01/);
  assert.match(mapEquipment, /0\.01m 감소/);
  assert.match(mapEquipment, /0\.01m 증가/);
  assert.match(styles, /\.map-equipment-actions \{[^}]*justify-content: flex-end/);
});

test("equipment labels are bounded in 2D and rendered in 3D", () => {
  assert.match(mapPanel, /clipPath={`url\(#\$\{clipId\}\)`}/);
  assert.match(mapPanel, /dominantBaseline="central"/);
  assert.match(pointCloudPanel, /createEquipmentLabelSprite/);
  assert.match(pointCloudPanel, /isEquipmentLabel/);
});

test("sensor diagnostics distinguishes current requirements and TF state", () => {
  assert.match(diagnostics, /required_now/);
  assert.match(diagnostics, /expected_min_hz/);
  assert.match(diagnostics, /tf_connected/);
  assert.match(diagnostics, /현재 모드 필수/);
});
