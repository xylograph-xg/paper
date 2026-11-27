// Real local HTTP and a temporary database; never connects to production services.
const assert=require('node:assert/strict');
const path=require('node:path');
const {spawn}=require('node:child_process');
const {createHash}=require('node:crypto');
const {chromium}=require('../../workbench/test_api.cjs');
const root=path.resolve(__dirname,'..','..');

(async()=>{
 const child=spawn(process.env.PAPER_TEST_PYTHON||'python3',['-m','reading.tests.reading_library_browser_fixture'],{cwd:root,stdio:['ignore','pipe','inherit']});
 let browser;
 try{
  const fixture=await new Promise((resolve,reject)=>{let output='';child.stdout.on('data',chunk=>{output+=chunk;const end=output.indexOf('\n');if(end>=0)resolve(JSON.parse(output.slice(0,end)));});child.on('error',reject);child.on('exit',code=>reject(Error('Fixture exited: '+code)));});
  browser=await chromium.launch({headless:true,executablePath:process.env.PAPER_TEST_CHROME||undefined});
  const context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage(),errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  const auth={'X-Paper-Token':fixture.secret,'Origin':fixture.url},[first,second,lower,unscored]=fixture.ids;
  const article=id=>page.locator(`[data-paper-id="${id}"]`);
  const hash=async id=>createHash('sha256').update(await (await page.request.get(fixture.url+'/asset?id='+id+'&file=card.json',{headers:auth})).body()).digest('hex');
  const original=await Promise.all(fixture.ids.map(hash));
  await page.goto(fixture.url+'/#access='+fixture.secret);
  await page.locator('[data-note]').first().waitFor();
  assert.equal(await page.locator('[data-tab="deep"]').evaluate(node=>node.classList.contains('active')),true);
  assert.equal(await page.locator('[data-tab="candidates"]').count(),0);
  assert.deepEqual(await page.locator('.searchbar').evaluate(node=>[...node.children].filter(child=>child.getBoundingClientRect().width&&child.getBoundingClientRect().height).map(child=>child.id)),['paperSearch']);
  for(const selector of ['#channelFilter','#startContinuous','#libraryStats','#fetchReason','#runDetails','#modelSettings','#discover','#readingHint','#workbenchLibraryManagement'])assert.equal(await page.locator(selector).isVisible(),false,selector+' should be hidden');
  assert.equal(await page.locator('#workflowControls,[data-task-pause],[data-decision="keep"],[data-decision="reject"],[data-seed],[data-detail$=":more"]').count(),0);
  assert.equal(await article(first).locator('[data-note]').evaluate(node=>node.nextElementSibling?.dataset.related),'1');
  assert.equal(await article(first).locator('[data-related]').count(),1);
  await page.setViewportSize({width:390,height:844});
  const compact=await article(first).locator('.badge-strip').evaluate(strip=>({tops:[...strip.querySelectorAll('.badge')].map(badge=>badge.getBoundingClientRect().top),width:strip.clientWidth,content:strip.scrollWidth,documentWidth:document.documentElement.scrollWidth,viewport:innerWidth}));
  assert(compact.tops.length>=4);assert(Math.max(...compact.tops)-Math.min(...compact.tops)<1);assert(compact.content>compact.width);assert(compact.documentWidth<=compact.viewport);
  await page.screenshot({path:'/private/tmp/paper-reading-library-mobile.png',fullPage:true});
  await page.setViewportSize({width:1440,height:1000});await page.locator('[data-tab="deep"]').click();
  await page.waitForFunction(id=>document.querySelector('#papers article')?.dataset.paperId===id,first);
  assert.deepEqual(await page.locator('#papers article').evaluateAll(nodes=>nodes.map(node=>node.dataset.paperId)),[first,second,lower,unscored]);
  assert.match(await article(first).innerText(),/总体质量 95\/100/);assert.match(await article(unscored).innerText(),/信息不足/);
  const note='reading_search_50% <img src=x onerror="window.noteUnsafe=true">\n我的阅读疑问';
  await article(first).locator('[data-note]').click();await page.locator('#noteText').fill(note);await page.locator('#saveNote').click();
  await page.waitForFunction(()=>!document.querySelector('#noteEditor').open);
  await article(first).locator('.reading-note').waitFor({state:'attached'});
  await article(first).locator('[data-detail$=":note"] summary').click();
  assert.equal(await article(first).locator('.reading-note').innerText(),note);
  assert.equal(await article(first).locator('.reading-note img').count(),0);assert.equal(await page.evaluate(()=>!!window.noteUnsafe),false);
  await page.locator('#paperSearch').fill('reading_search_50%');
  await page.waitForFunction(()=>document.querySelectorAll('#papers article').length===1);
  assert.equal(await page.locator('#papers article').getAttribute('data-paper-id'),first);
  await page.locator('#paperSearch').fill('');await page.waitForFunction(()=>document.querySelectorAll('#papers article').length===4);
  // Save while a refresh still contains the old list: a subsequent refresh must run.
  let release,started;const gate=new Promise(resolve=>{release=resolve;});const ready=new Promise(resolve=>{started=resolve;});let held=false;
  await page.route('**/api/state?*',async route=>{if(held)return route.continue();held=true;const response=await route.fetch();started();await gate;await route.fulfill({response});});
  await page.locator('[data-tab="deep"]').click();await ready;
  const saved=page.waitForResponse(response=>response.url().endsWith('/api/reading')&&response.request().method()==='POST');
  await article(first).locator('[data-read="1"]').click();assert.equal((await saved).status(),200);release();
  await article(first).waitFor({state:'detached'});await page.unroute('**/api/state?*');
  await page.locator('[data-tab="read"]').click();await article(first).waitFor();assert.equal(await page.locator('#papers article').count(),1);
  await page.reload();await page.locator('[data-note]').first().waitFor();await page.locator('[data-tab="read"]').click();await article(first).waitFor();
  assert.match(await article(first).innerText(),/设为未读/);assert.equal(await article(first).locator('.reading-note').textContent(),note);
  await article(first).locator('[data-read="0"]').click();await article(first).waitFor({state:'detached'});
  await page.locator('[data-tab="deep"]').click();await article(first).waitFor();
  await page.waitForFunction(id=>document.querySelector('#papers article')?.dataset.paperId===id,first);
  // Another device writes after this editor loaded: retain the local draft on 409.
  await article(first).locator('[data-note]').click();await page.locator('#noteText').fill('当前窗口的草稿');
  const other=await page.request.post(fixture.url+'/api/reading',{headers:auth,data:{id:first,note:'另一台电脑的备注',note_version:1}});assert.equal(other.status(),200);
  await page.locator('#saveNote').click();await page.waitForFunction(()=>document.querySelector('#noteError').textContent.includes('另一窗口'));
  assert.equal(await page.locator('#noteText').inputValue(),'当前窗口的草稿');assert.equal(await page.locator('#noteEditor[open]').count(),1);
  const stored=await (await page.request.get(fixture.url+'/api/reading?id='+first,{headers:auth})).json();assert.equal(stored.note,'另一台电脑的备注');
  await page.locator('#cancelNote').click();await article(first).locator('[data-note]').click();await page.locator('#noteEditor[open]').waitFor();assert.equal(await page.locator('#noteText').inputValue(),'另一台电脑的备注');
  await page.locator('#noteText').fill('');await page.locator('#saveNote').click();await page.waitForFunction(()=>!document.querySelector('#noteEditor').open);
  await page.waitForFunction(id=>!document.querySelector(`[data-paper-id="${id}"] .reading-note`),first);
  const state=await (await page.request.get(fixture.url+'/api/state?tab=deep',{headers:auth})).json();assert.equal(state.total,4);assert.equal(state.jobs.length,0);
  assert(state.papers.every(p=>p.decision==='unreviewed'));assert.deepEqual(await Promise.all(fixture.ids.map(hash)),original);assert.deepEqual(errors,[]);
  await page.screenshot({path:'/private/tmp/paper-reading-library.png',fullPage:true});
  console.log(JSON.stringify({defaultDeepLibrary:true,searchInputOnly:true,taskControlsHidden:true,decisionsRemoved:true,badgesSingleScrollableRow:true,scoreOrder:true,readHidden:true,readLibrary:true,reloadPersisted:true,undoRead:true,notesSearch:true,noteEscaped:true,concurrentDraftPreserved:true,refreshWhileSaving:true,cardHashesUnchanged:true,jobsCreated:0,errors:0}));
 }finally{if(browser)await browser.close();child.kill('SIGTERM');}
})().catch(error=>{console.error(error);process.exitCode=1;});
