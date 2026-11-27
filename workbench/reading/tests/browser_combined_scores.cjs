// Local synthetic cards/reports only; no worker, model, or production browser calls.
const assert=require('node:assert/strict');
const path=require('node:path');
const {spawn}=require('node:child_process');
const {chromium}=require('../../workbench/test_api.cjs');
(async()=>{
 const child=spawn(process.env.PAPER_TEST_PYTHON||'python3',['-m','reading.tests.reading_library_browser_fixture'],{
  cwd:path.resolve(__dirname,'..','..'),env:{...process.env,PAPER_RANKING_FIXTURE:'1'},stdio:['ignore','pipe','inherit']});
 let browser;
 try{
  const fixture=await new Promise((resolve,reject)=>{let out='';child.stdout.on('data',c=>{out+=c;const n=out.indexOf('\n');if(n>=0)resolve(JSON.parse(out.slice(0,n)));});child.on('error',reject);child.on('exit',code=>reject(Error('fixture exit '+code)));});
  browser=await chromium.launch({headless:true,executablePath:process.env.PAPER_TEST_CHROME||undefined});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto(fixture.url+'/#access='+fixture.secret);await page.locator('[data-note]').first().waitFor();
  const [first,second,lower,unknown]=fixture.ids;
  await page.locator('[data-tab="deep"]').click();
  await page.waitForFunction(id=>document.querySelector('#papers article')?.dataset.paperId===id,second);
  assert.deepEqual(await page.locator('#papers article').evaluateAll(ns=>ns.map(n=>n.dataset.paperId)),[second,lower,first,unknown]);
  const row=id=>page.locator(`[data-paper-id="${id}"]`);
  assert.match(await row(second).innerText(),/核验分 80\/100/);
  assert.match(await row(second).innerText(),/总分 175\/200/);
  assert.match(await row(first).innerText(),/总分 115\/200/);
  assert.match(await row(unknown).innerText(),/总分 待完整评分/);
  assert.match(await row(unknown).innerText(),/核验分 90\/100/);
  assert.match(await row(second).innerText(),/核验检查未完成/);
  assert.match(await page.locator('#readingHint').textContent(),/文献总体质量＋核验/);
  assert.equal(await page.locator('#readingHint').isVisible(),false);
  await row(second).locator('[data-read="1"]').click();await row(second).waitFor({state:'detached'});
  await row(lower).locator('[data-read="1"]').click();await row(lower).waitFor({state:'detached'});
  await page.locator('[data-tab="read"]').click();await row(second).waitFor();
  assert.deepEqual(await page.locator('#papers article').evaluateAll(ns=>ns.map(n=>n.dataset.paperId)),[second,lower]);
  const headers={'X-Paper-Token':fixture.secret};
  const state=await(await page.request.get(fixture.url+'/api/state?tab=deep&limit=1&offset=1',{headers})).json();
  assert.equal(state.papers[0].id,unknown);assert.equal(state.papers[0].review_score,90);assert.equal(state.papers[0].total_score,null);
  assert.equal(state.jobs.length,0);assert.deepEqual(errors,[]);
  await page.screenshot({path:'/private/tmp/paper-combined-scores.png',fullPage:true});
  console.log('Combined score ordering before pagination, explicit review/total scores, missing/partial labels and read library passed; no model calls; JS errors 0');
 }finally{if(browser)await browser.close();child.kill('SIGTERM');}
})().catch(e=>{console.error(e);process.exitCode=1;});
