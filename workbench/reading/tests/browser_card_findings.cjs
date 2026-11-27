// Read the generated conclusion through the actual temporary API and list renderer.
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
  const page=await browser.newPage({viewport:{width:1400,height:1000}}),errors=[],requests=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>requests.push({method:r.method(),url:r.url()}));
  const auth={'X-Paper-Token':fixture.secret},[first,second,missing,unscored]=fixture.ids;
  const hash=async id=>createHash('sha256').update(await(await page.request.get(fixture.url+'/asset?id='+id+'&file=card.json',{headers:auth})).body()).digest('hex');
  const before=await Promise.all(fixture.ids.map(hash));
  await page.goto(fixture.url+'/#access='+fixture.secret);await page.locator('article.card').first().waitFor();
  await page.locator('[data-tab="deep"]').click();
  const findings=id=>page.locator(`[data-paper-id="${id}"] .findings`);
  const expectedSummary='本文形成了一个可检验的整体解释，将研究中的主要发现连成一致的贡献。summary_search_50% <img src=x onerror="window.summaryUnsafe=true">';
  const displayedSummary=expectedSummary.split(' <img')[0];
  for(const id of [first,second]){
   await findings(id).waitFor();assert.equal(await findings(id).locator('.work-summary .prose').innerText(),displayedSummary);
   assert.equal(await findings(id).locator('.core-findings').getAttribute('open'),null);
   assert.doesNotMatch(await findings(id).innerText(),/制卡核心结论 findings_search_50%/);
   assert.equal(await findings(id).locator('img').count(),0);
   await findings(id).locator('.core-findings>summary').click();
  }
  for(const id of [first,second,unscored]){
   await findings(id).waitFor();assert.match(await findings(id).innerText(),/制卡核心结论 findings_search_50%/);
   assert.equal(await findings(id).locator('ol>li').count(),3);assert.equal(await findings(id).locator('img').count(),0);
  }
  assert.doesNotMatch(await findings(first).innerText(),/旧初筛摘要|等待网页制卡|30%/);
  assert.match(await findings(missing).innerText(),/卡片核心结论暂不可用/);
  assert.equal(await page.evaluate(()=>!!window.findingsUnsafe),false);
  assert.equal(await page.evaluate(()=>!!window.summaryUnsafe),false);
  assert.match(await findings(unscored).innerText(),/此卡尚无工作总结/);
  await page.locator('#paperSearch').fill('summary_search_50%');
  await page.waitForFunction(()=>document.querySelectorAll('#papers article').length===2);
  const summarySearch=await(await page.request.get(fixture.url+'/api/state?q=summary_search_50%&tab=all',{headers:auth})).json();assert.equal(summarySearch.total,2);
  assert(summarySearch.papers.every(p=>p.card_work_summary===expectedSummary));
  await page.locator('#paperSearch').fill('findings_search_50%');
  await page.waitForFunction(()=>document.querySelectorAll('#papers article').length===3);
  const search=await(await page.request.get(fixture.url+'/api/state?q=findings_search_50%&tab=all',{headers:auth})).json();assert.equal(search.total,3);
  const state=await(await page.request.get(fixture.url+'/api/state?tab=deep',{headers:auth})).json();assert.equal(state.jobs.length,0);
  await page.locator('#paperSearch').fill('');await findings(first).waitFor();
  const card=await(await page.request.get(fixture.url+'/api/card?id='+first,{headers:auth})).json();
  Object.assign(card.meta,{producer:'web_card_service',structural_complete:true,scientific_validation_status:'unreviewed'});
  card.paper_evaluation.overall_quality.dimensions=Object.fromEntries(['contribution','method_rigor','evidence_strength','claim_support','scope_limits'].map(key=>[key,{score:9.5,reason:'Synthetic strength and limitation <img src=x onerror="window.qualityUnsafe=true">',source_pages:[1]}]));
  card.figures=[{label:'Fig.1',source_page:1,evidence_quote:'Synthetic source quote',evidence_status:'verified',evidence_verification:{kind:'literal_quote_same_page'}}];
  card.tables=[{label:'Table 1',source_page:1,evidence_quote:'Synthetic pending quote',evidence_status:'needs_review'}];
  await page.route('**/api/card?*',r=>r.fulfill({json:card}));
  await page.locator(`[data-card][data-id="${first}"]`).click();await page.locator('#reader[open]').waitFor();
  assert.equal(await page.locator('#reader .work-summary .prose').innerText(),displayedSummary);
  assert.equal(await page.locator('#reader .core-findings').getAttribute('open'),null);
  await page.locator('#reader .core-findings>summary').click();
  assert.match(await page.locator('#reader .core-findings').innerText(),/制卡核心结论 findings_search_50%/);
  assert.equal(await page.locator('#reader .findings img').count(),0);
  assert.equal(await page.locator('#reader .paper-quality-breakdown').count(),0);
  assert.doesNotMatch(await page.locator('#reader').innerText(),/GPT文献评价依据|结构检查通过|引文逐字定位|科学复核|Synthetic source quote|Synthetic pending quote/);
  assert.equal(await page.locator('#reader img[onerror]').count(),0);
  assert.equal(await page.evaluate(()=>!!window.qualityUnsafe),false);
  assert.equal(await page.locator('#reader .notice').count(),0);
  await page.locator('#closeReader').click();await page.unroute('**/api/card?*');
  assert.deepEqual(await Promise.all(fixture.ids.map(hash)),before);assert.deepEqual(errors,[]);
  assert(requests.every(r=>new URL(r.url).hostname==='127.0.0.1'));
  assert(requests.every(r=>r.method==='GET'||new URL(r.url).pathname==='/api/session'));
  await page.screenshot({path:'/private/tmp/paper-card-findings.png',fullPage:true});
  console.log('Work synthesis shared by list and reader; evidence expands, legacy fallback, literal search, safe Markdown and unchanged cards passed; JS errors 0, business writes 0');
 }finally{if(browser)await browser.close();child.kill('SIGTERM');}
})().catch(e=>{console.error(e);process.exitCode=1;});
