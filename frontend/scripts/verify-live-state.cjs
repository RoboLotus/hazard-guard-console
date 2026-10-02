// Run against local Vite. All API and WebSocket traffic is intercepted; no robot commands leave this browser.
// PLAYWRIGHT_MODULE optionally points to a local Playwright installation.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const path = require('node:path');

(async () => {
  const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:5173';
  assert.ok(['localhost', '127.0.0.1'].includes(new URL(base).hostname));
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  let fail = false, imageFail = false, imageHang = false, eventFail = false;
  let source = 'derived:rgb-colormap';
  let poseFresh = true;
  let telemetry = { mock: true, robot_id: 'mock', mode: 'patrol', speed_mps: .32, network_quality: 'good', network_rssi_dbm: -48, lidar_status: 'normal', lidar_hz: 10.2, max_temperature_c: 63, battery_stale: true };
  const map = { map_id: 'saved-a', frame_id: 'map', width: 100, height: 100, resolution: .1, origin_x: 0, origin_y: 0 };
  const statuses = [];
  const detection = { detection_id: 'heater', equipment_id: 'heater', equipment_name: '테스트 설비', visit_index: 1, trend_status: 'warning', temperature_c: 65, x: 2, y: 3, frame_id: 'map', updated_at: new Date().toISOString() };
  const sockets = new Set();
  const send = () => {
    for (const ws of sockets) {
      try {
        if (ws.url().endsWith('/ws/telemetry')) ws.send(JSON.stringify(telemetry));
        if (ws.url().endsWith('/ws/spatial')) ws.send(JSON.stringify({
          source: 'ros', mock: false, map, trail: [], sensors: [],
          pose: { available: true, x: 2, y: 3, yaw: 0, frame_id: 'map', updated_at: new Date(Date.now() - (poseFresh ? 0 : 10000)).toISOString() },
          heatmap: { available: true, detections: [detection] },
        }));
      } catch { sockets.delete(ws); }
    }
  };
  await page.routeWebSocket(/\/ws\//, ws => { sockets.add(ws); ws.onClose(() => sockets.delete(ws)); send(); });
  const producer = setInterval(send, 200);
  const pixel = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j1ioAAAAASUVORK5CYII=', 'base64');
  await page.route('**/api/**', async route => {
    const req = route.request();
    const p = new URL(req.url()).pathname;
    const json = (body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
    if (fail) return json({ detail: 'test offline' }, 503);
    if (req.method() !== 'GET') {
      if (req.method() !== 'PUT' || !p.startsWith('/api/v1/events/')) throw new Error(`Unexpected mutation ${req.method()} ${p}`);
      if (eventFail) return json({ detail: 'test save failed' }, 503);
      const body = req.postDataJSON();
      const row = { ...body, id: 'heater-visit-1', revision: (statuses[0]?.revision || 0) + 1 };
      statuses.splice(0, statuses.length, row);
      return json(row);
    }
    if (imageHang && p.endsWith('/media/thermal')) {
      await new Promise(resolve => setTimeout(resolve, 6500));
      return route.fulfill({ contentType: 'image/png', body: pixel }).catch(() => {});
    }
    if (/\/media\/(rgb|thermal|map)$/.test(p)) return imageFail && p.endsWith('/thermal')
      ? json({}, 503) : route.fulfill({ contentType: 'image/png', body: pixel });
    if (p === '/api/health') return json({ status: 'ok', deployment_target: 'physical' });
    if (p === '/api/v1/media/status') return json({ map: { available: true, width: 100, height: 100, metadata: map }, rgb: { available: true, source: 'ros:/rgb' }, thermal: { available: true, source } });
    if (p === '/api/v1/incidents') return json({ incidents: [], battery: { expected: 3, connected: 0, available_for_drop: 0, beacons: [], stale: true } });
    if (p === '/api/v1/events/statuses') return json({ map_id: map.map_id, statuses });
    if (p === '/api/v1/system/mode') return json({ mode: 'patrol', state: 'running', deployment_target: 'physical', control_enabled: false, navigation_ready: true });
    if (p === '/api/v1/rosbag/status') return json({ state: 'recording', recording: true, profile: 'navigation-core', recording_control_enabled: true, control_enabled: false });
    if (p === '/api/v1/performance/reports') return json({ reports: [], active: [{ id: 'active', stale: false, mission_id: 'test' }] });
    if (p === '/api/v1/system/sensors') return json({ ros_active: true, summary: { required_total: 1, required_live: 1 }, sensors: [{ id: 'scan', label: 'LiDAR', state: 'live', required_now: true, required_for: ['mapping'], topic: '/scan', tf_connected: true, rate_hz: 10 }] });
    if (p === '/api/v1/settings/equipment') return json({ equipment: [], history: [] });
    return json({});
  });
  const nav = async name => page.getByRole('button', { name, exact: true }).click();
  const eventually = async check => {
    for (let i = 0; i < 80; i++) { if (await check()) return; await page.waitForTimeout(100); }
    throw new Error('Condition did not become true');
  };
  try {
    await page.goto(base);
    await page.locator('.dock-block.telemetry').waitFor();
    await page.waitForTimeout(400);
    assert.equal(await page.getByRole('button', { name: '일시정지', exact: true }).isEnabled(), false);
    assert.ok(!(await page.locator('.dock-block.telemetry').innerText()).includes('0.32'));
    await nav('영상');
    assert.equal(await page.locator('.thermal-stream img').count(), 0);
    assert.equal(await page.locator('.temperature-summary, .thermal-reading, .temperature-progress').count(), 0);
    source = 'ros:/thermal_camera/image_color';
    await eventually(async () => (await page.locator('.thermal-stream .live-label').innerText()) === 'LIVE');
    imageFail = true;
    await eventually(async () => (await page.locator('.thermal-stream .live-label').innerText()) === '영상 수신 실패');
    assert.equal(await page.getByRole('button', { name: '열화상 스냅샷', exact: true }).isEnabled(), false);
    imageFail = false;
    await eventually(async () => (await page.locator('.thermal-stream .live-label').innerText()) === 'LIVE');
    imageHang = true;
    await eventually(async () => (await page.locator('.thermal-stream .live-label').innerText()) === '영상 수신 실패');
    imageHang = false;
    await eventually(async () => (await page.locator('.thermal-stream .live-label').innerText()) === 'LIVE');
    fail = true;
    await eventually(async () => (await page.locator('.thermal-stream .live-label').innerText()) === '연결 필요');
    await nav('ROS Bag 기록');
    assert.ok(!(await page.locator('.rosbag-runtime').innerText()).includes('기록 중'));
    fail = false;
    await nav('리포트');
    await page.getByText('순찰 성능 수집 중', { exact: true }).waitFor();
    fail = true;
    await page.getByText('수집 중단 여부 확인 필요', { exact: true }).waitFor();
    fail = false;
    await page.getByText('순찰 성능 수집 중', { exact: true }).waitFor();
    await nav('설정');
    await page.getByRole('tab', { name: /연결 상태 점검/ }).click();
    await page.locator('.sensor-diagnostic-row.live').waitFor();
    fail = true;
    await eventually(async () => await page.locator('.sensor-diagnostic-row.live').count() === 0);
    fail = false;
    telemetry = { ...telemetry, mock: false, stale: false, age_sec: 0, speed_mps: null, lidar_hz: null, network_rssi_dbm: null };
    await nav('Overview');
    await page.waitForTimeout(400);
    assert.ok(!(await page.locator('.dock-block.telemetry').innerText()).includes('0.00 m/s'));
    telemetry = { ...telemetry, stale: true, age_sec: 10 };
    await eventually(async () => !(await page.getByRole('button', { name: '일시정지', exact: true }).isEnabled()));
    await nav('지도');
    await page.getByRole('button', { name: '로봇 위치 중앙 정렬', exact: true }).click();
    await page.waitForTimeout(200);
    const centerError = await page.locator('.live-robot').evaluate(el => {
      const origin = new DOMPoint(0, 0).matrixTransform(el.getScreenCTM());
      const bounds = el.closest('.map-stage').getBoundingClientRect();
      return Math.hypot(origin.x - bounds.x - bounds.width / 2, origin.y - bounds.y - bounds.height / 2);
    });
    assert.ok(centerError < 2, `Center error ${centerError}`);
    poseFresh = false;
    await eventually(async () => await page.locator('.live-robot').count() === 0);
    assert.equal(await page.locator('.live-map').count(), 1);
    await nav('이벤트');
    eventFail = true;
    await page.getByRole('button', { name: '처리 시작', exact: true }).click();
    await page.getByText('test save failed', { exact: true }).waitFor();
    assert.equal(await page.getByRole('button', { name: '처리 시작', exact: true }).count(), 1);
    eventFail = false;
    await page.getByRole('button', { name: '처리 시작', exact: true }).click();
    await page.getByRole('button', { name: '해결 완료', exact: true }).waitFor();
    await page.reload();
    await nav('이벤트');
    await page.getByRole('button', { name: '해결 완료', exact: true }).waitFor();
    for (const width of [1440, 1024, 390]) {
      await page.setViewportSize({ width, height: 900 });
      for (const name of ['Overview', '영상', '지도', '이벤트', '리포트', 'ROS Bag 기록', '설정', '도움말']) {
        await nav(name);
        await page.waitForTimeout(150);
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
        assert.equal(overflow, false, `${name} ${width} overflow`);
        if (process.env.TEST_SCREENSHOTS && ['Overview', '영상', '설정'].includes(name)) {
          await page.screenshot({ path: path.join(process.env.TEST_SCREENSHOTS, `live-state-${width}-${name}.png`), fullPage: true });
        }
      }
    }
    fail = true;
    await nav('영상');
    await eventually(async () => (await page.locator('.thermal-stream .live-label').innerText()) === '연결 필요');
    if (process.env.TEST_SCREENSHOTS) {
      for (const width of [1440, 390]) {
        await page.setViewportSize({ width, height: 900 });
        await page.screenshot({ path: path.join(process.env.TEST_SCREENSHOTS, `offline-video-${width}.png`), fullPage: true });
      }
    }
    assert.deepEqual(errors, []);
    console.log('PASS: mock/stale telemetry, missing values, derived thermal, image failure/recovery, HTTP 503, saved map/pose, robot centering, event save failure/persistence, 8 pages x 3 widths.');
  } finally {
    clearInterval(producer);
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
