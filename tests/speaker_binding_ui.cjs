const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
(async () => {
 const browser = await chromium.launch({executablePath:'/usr/bin/google-chrome',headless:true});
 try {
  const page=await browser.newPage({viewport:{width:1440,height:1050}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:8765/');
  await page.getByRole('button',{name:'角色·场景·道具',exact:true}).click();
  const urls={};
  for(const name of ['无极','盘古','女娲','振明','冰雨']){
   const card=page.locator('section.card').filter({has:page.getByRole('heading',{name,exact:true})});
   await card.waitFor();
   const player=card.locator('audio');assert.equal(await player.count(),1);
   urls[name]=await player.getAttribute('src');
   const response=await page.request.get(new URL(urls[name],page.url()).href);assert.equal(response.status(),200);
   await player.evaluate(async a=>{a.load();await new Promise((resolve,reject)=>{a.addEventListener('loadedmetadata',resolve,{once:true});a.addEventListener('error',reject,{once:true})})});
   assert.ok(await player.evaluate(a=>a.duration>0));
  }
  assert.equal(urls['无极'],urls['振明']);assert.equal(urls['女娲'],urls['冰雨']);
  const nuwa=page.locator('section.card').filter({has:page.getByRole('heading',{name:'女娲',exact:true})});
  await nuwa.scrollIntoViewIfNeeded();
  await nuwa.locator('img').evaluate(img=>img.decode());
  await nuwa.screenshot({path:'docs/qa/nuwa-voice-card.png'});
  await page.getByRole('button',{name:'导演分镜',exact:true}).click();
  await page.getByText('无极：这是哪里？',{exact:true}).first().waitFor();
  assert.ok(await page.getByRole('link',{name:'对应参考音频 · 无极',exact:true}).count()>0);
  await page.getByRole('button',{name:'内容规划与锁定',exact:true}).click();
  await page.getByText('对白与说话人 · 60 句',{exact:true}).click();
  assert.ok(await page.getByRole('cell',{name:'这是哪里？',exact:true}).isVisible());
  const status=await(await page.request.get('http://127.0.0.1:8765/api/status')).json();
  for(const plan of status.content_plans){for(const scene of plan.script.scenes){for(const u of scene.utterances)assert.ok(u.speaker)}}
  assert.deepEqual(errors,[]);
  console.log('PASS: five playable audio cards, canonical voice aliases, speaker rows and complete script attribution.');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
