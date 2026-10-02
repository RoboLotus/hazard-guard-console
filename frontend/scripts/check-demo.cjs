// Optional local browser smoke test: node scripts/check-demo.cjs <playwright-module> [screenshot-dir]
const { chromium } = require(process.argv[2] || 'playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true, args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const page = await browser.newPage();
  const errors = [], operational = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('websocket', socket => { if (new URL(socket.url()).pathname.startsWith('/ws')) operational.push(socket.url()); });
  page.on('request', req => { if (/\/(api|ws)(\/|\?|$)/.test(new URL(req.url()).pathname)) operational.push(req.url()); });
  if (process.argv[3]) fs.mkdirSync(process.argv[3], { recursive: true });
  try {
    await page.goto('http://127.0.0.1:5179/');
    await page.getByText('DEMO · 저장 자료', { exact: true }).waitFor();
    await page.getByRole('img', { name: '저장된 2D SLAM 지도' }).waitFor();
    for (const width of [1440, 1024, 390]) {
      await page.setViewportSize({ width, height: 1000 });
      await page.getByRole('button', { name: '지도', exact: true }).click();
      for (const tab of ['3D RGB-D', '3D 열화상', '2D 지도']) {
        await page.getByRole('button', { name: tab, exact: true }).click();
        if (tab !== '2D 지도') {
          await page.locator('canvas').waitFor();
          assert.equal(await page.locator('canvas').count(), 1);
          assert.equal(await page.getByRole('alert').count(), 0);
          await page.getByText('실측 저장 자료 · 실시간 아님', { exact: true }).waitFor();
          if (tab === '3D 열화상') await page.getByText('548', { exact: true }).waitFor();
          await page.getByRole('button', { name: '3D 지도 화면 맞춤' }).click();
        }
        assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `overflow: ${width}/${tab}`);
        if (process.argv[3]) await page.screenshot({ path: `${process.argv[3]}/${width}-${tab}.png`, fullPage: true });
      }
    }
    for (const tab of ['Overview', '이벤트', '영상', '리포트', 'ROS Bag 기록', '설정', '도움말']) {
      await page.getByRole('button', { name: tab, exact: true }).click();
      await page.waitForTimeout(200);
    }
    const blocked = await page.evaluate(async () => {
      const r = await fetch('/api/v1/commands/patrol', { method: 'POST' });
      return r.status;
    });
    assert.equal(blocked, 403);
    assert.equal((await page.request.get('http://127.0.0.1:5179/api/v1/system/mode')).status(), 403);
    assert.deepEqual(operational, []);
    assert.deepEqual(errors, []);
    await page.route('**/demo-data/manifest.json', route => route.fulfill({ status: 404, body: '' }));
    await page.reload();
    await page.getByRole('alert').waitFor();
    await page.getByRole('button', { name: '다시 불러오기' }).waitFor();
    console.log('PASS: original 8 pages + 3 map views x 3 widths, blocked writes, no operational network, no JS errors, missing-data recovery UI');
  } catch (error) {
    console.error('PAGE ERRORS', errors);
    console.error((await page.locator('body').innerText()).slice(0, 3500));
    if (process.argv[3]) await page.screenshot({ path: `${process.argv[3]}/failure.png`, fullPage: true });
    throw error;
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
