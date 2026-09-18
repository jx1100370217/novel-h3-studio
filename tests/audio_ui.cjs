// Exercises our local workbench with a synthetic music control, never a film soundtrack.
const assert = require('node:assert/strict');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
(async()=>{
 const browser=await chromium.launch({executablePath:'/usr/bin/google-chrome',headless:true});
 try {
  const page=await browser.newPage({viewport:{width:1440,height:1050}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:8765');
  await page.getByRole('button',{name:'音频审片',exact:true}).click();
  await page.getByText('转写与声音理解冲突：疑似噪声幻听，已阻止进入候选字幕。',{exact:true}).waitFor();
  const reports=await (await page.request.get('http://127.0.0.1:8765/api/audio-reports')).json();
  const flood=reports.find(r=>r.id==='opening_tongtian_v2');
  assert.equal(flood.report.release_approved,false);
  assert.equal(flood.report.windows[0].transcription.status,'conflict_possible_hallucination');
  const audioResponse=await page.request.get('http://127.0.0.1:8765/media?path='+encodeURIComponent(flood.audio),{headers:{Range:'bytes=0-1023'}});
  assert.equal(audioResponse.status(),206);
  assert.equal((await audioResponse.body()).length,1024);
  await page.screenshot({path:'docs/qa/audio-review.png',fullPage:true});
  await page.getByRole('textbox',{name:'本地音频或视频路径'}).fill('/home/jx/codes/novel-h3-studio/runtime/audio_test/synthetic_music_control.wav');
  const response=page.waitForResponse(r=>r.url().endsWith('/api/audio-review') && r.request().method()==='POST');
  await page.getByRole('button',{name:'开始音频分析',exact:true}).click();
  const started=await (await response).json();assert(started.result?.id,JSON.stringify(started));
  console.log('Audio job started from real UI:',started.result.id);
  await page.getByText('synthetic_music_control.wav',{exact:true}).waitFor({timeout:120000});
  await page.getByText('模型判断有配乐，需检查',{exact:true}).waitFor({timeout:120000});
  await page.screenshot({path:'docs/qa/audio-music-control.png',fullPage:true});
  await page.getByRole('button',{name:'分集与长片交付',exact:true}).click();
  await page.getByRole('heading',{name:'制作预览 · 尚未验收',exact:true}).waitFor();
  const video=page.locator('video').first();
  await video.evaluate(v=>new Promise((resolve,reject)=>{if(v.readyState>=1)return resolve();v.addEventListener('loadedmetadata',resolve,{once:true});v.addEventListener('error',reject,{once:true})}));
  const duration=await video.evaluate(v=>v.duration);assert(duration>10 && duration<11);
  await page.screenshot({path:'docs/qa/opening-preview.png',fullPage:true});
  assert.deepEqual(errors,[]);console.log('PASS: actual audio job, music detection, report, WAV range playback, video preview; no page errors.');
 } finally {await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
