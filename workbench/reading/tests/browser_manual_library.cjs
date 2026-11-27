const assert=require('node:assert/strict');
const {spawn}=require('node:child_process');
const {chromium}=require('../../workbench/test_api.cjs');
(async()=>{
 const child=spawn(process.env.PAPER_TEST_PYTHON,['-m','reading.tests.manual_library_browser_fixture'],{cwd:require('node:path').resolve(__dirname,'..','..'),stdio:['ignore','pipe','inherit']});let browser;
 try{
 const fixture=await new Promise((resolve,reject)=>{let out='';child.stdout.on('data',c=>{out+=c;if(out.includes('\n'))resolve(JSON.parse(out.split('\n')[0]));});child.on('error',reject);child.on('exit',code=>reject(Error('fixture '+code)));});
 browser=await chromium.launch({headless:true,executablePath:process.env.PAPER_TEST_CHROME});
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 const ids=()=>page.locator('#papers article').evaluateAll(nodes=>nodes.map(n=>n.dataset.paperId));
 const wait=expected=>page.waitForFunction(expected=>JSON.stringify([...document.querySelectorAll('#papers article')].map(n=>n.dataset.paperId))===JSON.stringify(expected),expected);
 await page.goto(fixture.url+'/#access='+fixture.secret);await wait([fixture.ids[3]]);
 await page.locator('[data-curated-page="manual"]').click();await wait([fixture.ids[0]]);
 await page.locator('[data-manual-page="derived"]').click();await wait([fixture.ids[1],fixture.ids[2]]);
 await page.locator('#paperSearch').fill('Second evidence');await wait([fixture.ids[1]]);
 await page.locator('#paperSearch').fill('');await wait([fixture.ids[1],fixture.ids[2]]);
 await page.screenshot({path:'/private/tmp/paper-manual-library.png',fullPage:true});
 await page.locator(`[data-paper-id="${fixture.ids[1]}"] [data-read="1"]`).click();await wait([fixture.ids[2]]);
 await page.locator('[data-tab="read"]').click();await wait([fixture.ids[1]]);
 assert.equal(await page.locator('#curatedPages').isVisible(),false);
 await page.locator('[data-read="0"]').click();await wait([]);
 await page.locator('[data-tab="deep"]').click();await wait([fixture.ids[1],fixture.ids[2]]);
 await page.locator('[data-curated-page="ordinary"]').click();await wait([fixture.ids[3]]);
 await page.locator('[data-tab="manual_seed_cards"]').click();await wait([fixture.ids[0],fixture.candidate]);
 const candidate=page.locator(`[data-paper-id="${fixture.candidate}"]`);
 assert.match(await candidate.innerText(),/候选卡/);
 await candidate.getByRole('button',{name:'查看候选卡'}).click();
 await page.locator('#reader[open] .notice').filter({hasText:'候选卡'}).waitFor();
 assert.match(await page.locator('#reader').innerText(),/Candidate summary/);
 const changed=await page.request.get(fixture.url+'/api/card?id='+fixture.candidate+'&sha256=stale');
 assert.equal(changed.status(),409);
 assert.deepEqual(errors,[]);console.log(JSON.stringify({ordinaryManualTabs:true,seedDerivedTabs:true,promotedSeedRetainsOrigin:true,search:true,readUndo:true,errors:0}));
 }finally{if(browser)await browser.close();child.kill('SIGTERM');}
})().catch(e=>{console.error(e);process.exitCode=1;});
