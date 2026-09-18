// Read-only check against the running production workbench.
const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
(async () => {
  const browser = await chromium.launch({ executablePath: '/usr/bin/google-chrome', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1050 } });
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto('http://127.0.0.1:8765/');
    await page.getByRole('button', { name: '角色·场景·道具', exact: true }).click();
    await page.getByText(/基础资产已登记 199 项/).waitFor();
    await page.getByText(/已有图片 30 项 · 待补图 169 项/).waitFor();
    for (const name of ['太微宫', '太微殿', '玉笏']) {
      const card = page.locator('section.card').filter({ has: page.getByRole('heading', { name, exact: true }) });
      assert.equal(await card.getByText('已有图片 · 已审阅', { exact: true }).count(), 1);
      const response = await page.request.get(new URL(await card.locator('img').getAttribute('src'), page.url()).href);
      assert.equal(response.status(), 200);
      assert.match(response.headers()['content-type'], /image/);
    }
    const audit = await (await page.request.get('http://127.0.0.1:8765/media?path=analysis%2Ffull_book_asset_audit.json')).json();
    assert.equal(audit.complete, false);
    assert.equal(audit.added.length, 165);
    await page.screenshot({ path: 'docs/qa/asset-coverage-expansion.png' });
    assert.deepEqual(errors, []);
    console.log('PASS: counts, three registered images, incomplete audit, no browser errors.');
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
