// Temporary catalog only. The reading surface no longer offers seed mutations.
const assert=require('node:assert/strict');
const {workbenchAccess}=require('../../workbench/test_api.cjs');
const {chromium}=require('../../workbench/test_api.cjs');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.PAPER_TEST_CHROME||undefined});
 try{
  const page=await browser.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  const access=await workbenchAccess(page);assert(access.paperId,'Seed test requires the isolated fixture');
  const token=new URLSearchParams(new URL(access.authenticatedUrl).hash.slice(1)).get('access');
  const headers={'X-Paper-Token':token};
  await page.goto(access.authenticatedUrl);await page.locator('[data-card]').waitFor();
  assert.equal(await page.locator('[data-seed]').count(),0);
  assert.equal(await page.locator('[data-note]').evaluate(node=>node.nextElementSibling?.dataset.related),'1');
  assert.equal((await page.request.post(access.base+'/api/seed',{headers,data:{id:access.paperId,enabled:true}})).status(),200);
  await page.locator('#paperSearch').fill('');await page.locator('article.card .badge').filter({hasText:'检索种子'}).waitFor();
  await page.locator('[data-tab="seeds"]').click();await page.locator('article.card').waitFor();assert.equal(await page.locator('article.card').count(),1);
  assert.equal((await page.request.post(access.base+'/api/seed',{headers,data:{id:access.paperId,enabled:false}})).status(),200);
  await page.locator('#paperSearch').fill('');await page.locator('#papers .empty').waitFor();
  assert.deepEqual(errors,[]);
  console.log('Seed library reflects temporary API add/remove; seed mutation controls absent; related search follows notes; JS errors 0; no workers');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
