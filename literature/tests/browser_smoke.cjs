// Isolated headless browser only; never connects to production Chrome or CDP.
const {spawn}=require('child_process');
const assert=require('assert/strict');
const {chromium}=require('../../workbench/test_api.cjs');
(async()=>{
 const fixture=spawn(process.env.PAPER_TEST_PYTHON||'python3',['-u','literature/tests/browser_fixture.py'],{env:process.env,stdio:['ignore','pipe','pipe']});
 let browser;
 try{
  const info=await new Promise((resolve,reject)=>{let output='',errors='';const timer=setTimeout(()=>reject(Error('Fixture timeout '+errors)),15000);fixture.stderr.on('data',d=>errors+=d);fixture.stdout.on('data',d=>{output+=d;if(output.includes('\n')){clearTimeout(timer);resolve(JSON.parse(output.split('\n')[0]));}});fixture.once('exit',code=>{clearTimeout(timer);reject(Error('Fixture exit '+code+' '+errors));});});
  browser=await chromium.launch({headless:true,executablePath:process.env.PAPER_TEST_CHROME||undefined});
  const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(info.url+'/literature');
  await page.locator('#loginBox').waitFor({state:'visible'});
  await page.locator('#accessToken').fill(info.secret);await page.locator('#loginForm button').click();
  await page.locator('#app').waitFor({state:'visible'});await page.waitForFunction(()=>document.querySelectorAll('article').length===3);
  assert.equal(await page.locator('button[data-tag]').count(),0);
  const paper=page.locator('article').filter({hasText:'Energy transfer study'});
  await paper.locator('button[data-auto]').click();
  await page.waitForFunction(()=>document.querySelector('#papers').textContent.includes('反向系间窜越'));assert((await page.locator('#papers').innerText()).includes('第2级'));
  const badges=await paper.locator('.badge').allTextContents();
  assert(!badges.some(text=>text.includes('温度依赖光谱')));
  assert(!badges.some(text=>text.includes('/ 有机发光 ·')));
  await page.locator('#search').fill('TADF');await page.locator('#filters button.primary').click();await page.waitForFunction(()=>document.querySelectorAll('article').length===1);
  await page.locator('#newCollection').click();await page.locator('#collectionForm [name=name]').fill('理解能量转移');await page.locator('#collectionForm [name=goal]').fill('比较不同机制');await page.locator('#collectionForm [name=filterMode]').selectOption('current');await page.locator('#collectionForm button').click();await page.locator('#editor').waitFor({state:'hidden'});
  await page.locator('button[data-member]').click();await page.locator('#memberForm [name=role]').selectOption('intro');await page.locator('#memberForm [name=progress]').selectOption('reading');await page.locator('#memberForm [name=note]').fill('先建立基本概念');await page.locator('#memberForm button').click();await page.locator('#editor').waitFor({state:'hidden'});
  await page.waitForFunction(()=>document.querySelector('#papers').textContent.includes('先建立基本概念'));
  await page.locator('button[data-detail]').click();await page.locator('#editor').waitFor({state:'visible'});const detail=await page.locator('#editorBody').innerText();assert(detail.includes('TADF'));assert(detail.includes('辅助证据'));assert(detail.includes('上位分类（检索继承）'));await page.locator('#closeEditor').click();
  if(process.env.PAPER_LITERATURE_DESKTOP_SCREENSHOT)await page.screenshot({path:process.env.PAPER_LITERATURE_DESKTOP_SCREENSHOT,fullPage:true});
  await page.setViewportSize({width:390,height:844});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  const screenshot=process.env.PAPER_LITERATURE_SCREENSHOT;if(screenshot)await page.screenshot({path:screenshot,fullPage:true});
  assert.deepEqual(errors,[]);assert(!(await page.locator('#message').innerText()).includes('错误'));
  console.log('PASS: login, automatic-only labeling, evidence, filtering, dynamic collection, role/progress, mobile layout; no JS errors');
 }finally{if(browser)await browser.close();fixture.kill('SIGTERM');}
})().catch(e=>{console.error(e);process.exitCode=1;});
