// Local application test only. Uses the bundled Playwright and a fresh browser.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const browser = await chromium.launch({ executablePath: '/usr/bin/google-chrome', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1050 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto('http://127.0.0.1:8765');
    await page.getByText('318 段章', { exact: true }).waitFor();
    const initial = await (await page.request.get('http://127.0.0.1:8765/api/status')).json();
    assert(!initial.state.assets.keyframe_tongtian_001, 'This smoke test requires the untouched missing-keyframe fixture.');
    assert(initial.analysis_done === 0, 'Do not run the initial-fixture test against a production project.');
    const output = path.resolve('docs/qa');
    fs.mkdirSync(output, { recursive: true });
    await page.screenshot({ path: path.join(output, 'overview.png'), fullPage: true });
    await page.getByRole('button', { name: '角色·场景·道具', exact: true }).click();
    await page.getByRole('heading', { name: '振明', exact: true }).waitFor();
    await page.getByRole('heading', { name: '射日神弓', exact: true }).waitFor();
    await page.screenshot({ path: path.join(output, 'assets.png'), fullPage: true });
    await page.getByRole('button', { name: '内容规划与锁定', exact: true }).click();
    await page.getByRole('button', { name: '打开视觉编写工作单' }).click();
    await page.getByRole('dialog').waitFor();
    assert((await page.locator('#dialogBody').textContent()).includes('content_sha256'));
    await page.getByRole('button', { name: '关闭', exact: true }).click();
    await page.getByRole('button', { name: '导演分镜', exact: true }).click();
    await page.getByText('E1S001 / 5.17秒', { exact: true }).waitFor();
    await page.getByRole('button', { name: '生成下一镜', exact: true }).click();
    await page.getByText('图片 keyframe_tongtian_001 尚未生成或尚未验收', { exact: true }).waitFor();
    await page.getByRole('button', { name: '原文与完整性', exact: true }).click();
    await page.getByRole('textbox', { name: '搜索章节' }).fill('315');
    assert.equal(await page.getByRole('button', { name: '打开原文工作单', exact: true }).count(), 3);
    await page.getByRole('button', { name: '图片工作单', exact: true }).click();
    await page.getByText('模型来源未核实', { exact: true }).waitFor();
    await page.getByRole('button', { name: '看片与验收', exact: true }).click();
    await page.getByText('已停止', { exact: true }).waitFor();
    await page.getByRole('button', { name: '分集与长片交付', exact: true }).click();
    await page.getByRole('button', { name: '合并全部正式分集' }).click();
    await page.getByText('仍有原文未分析或未改编，禁止将部分视频标为全书', { exact: true }).waitFor();
    assert.deepEqual(errors, []);
    console.log('UI passed: 8 pages, source search, visual packet, missing-image gate, whole-book gate; no page errors.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
