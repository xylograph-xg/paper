const assert=require('node:assert/strict');
const {workbenchAccess}=require('../../workbench/test_api.cjs');
const {chromium}=require('../../workbench/test_api.cjs');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.PAPER_TEST_CHROME||undefined});
 try{
  const page=await browser.newPage(),errors=[];page.on('pageerror',error=>errors.push(error.message));
  const access=await workbenchAccess(page),id=access.paperId;assert(id,'Media test requires isolated fixture');
  const card=await(await page.request.get(access.base+'/asset?id='+encodeURIComponent(id)+'&file=card.json')).json(),fixture=JSON.parse(JSON.stringify(card));
  fixture.figures[0].asset_file='figure.png';
  fixture.meta.media_evidence.source={state:'available',version:'test-fixture-v1'};
  fixture.meta.media_evidence.source_figures=[{id:'source-figure-1',labels:['fig:one'],caption:'<script>window.injected=true</script>',file:'main.tex',line:20,in_main_tree:true,originals:[{path:'figure.png',preview_path:'figure.png',format:'.png',argument:'original.png'}]}];
  fixture.meta.media_evidence.figures[0].source_figure_id='source-figure-1';
  fixture.meta.media_evidence.source_equations=[{file:'main.tex',line:30,labels:['eq:one'],latex:'x_1=\\myop{y}',validation:'source_exact_not_independently_rendered'}];
  fixture.meta.media_evidence.macros=['\\newcommand{\\myop}[1]{\\mathbf{#1}}'];
  const before=JSON.stringify(fixture);
  await page.route('**/api/card?*',route=>route.fulfill({json:fixture}));
  await page.goto(access.authenticatedUrl);await page.locator('[data-card]').first().waitFor();
  await page.locator('[data-card][data-id="'+id+'"]').click();await page.locator('#reader[open]').waitFor();
  assert.doesNotMatch(await page.locator('#cardBody').innerText(),/图片与公式证据：|源码图像索引|源码公式|自定义宏|main\.tex|test-fixture-v1/);
  await page.waitForFunction(()=>document.querySelector('#cardBody img')?.naturalWidth>0);
  assert.equal(await page.locator('#cardBody img').count(),1);assert.match(await page.locator('#cardBody').innerText(),/Synthetic detail/);
  await page.locator('#cardBody button[data-zoom-src]').click();await page.locator('#imageViewer[open]').waitFor();
  await page.waitForFunction(()=>document.querySelector('#fullImage').naturalWidth>0);
  assert.match(await page.locator('#imagePdf').getAttribute('href'),/source\.pdf/);
  assert.equal(await page.evaluate(()=>window.injected),undefined);assert.equal(JSON.stringify(fixture),before);assert.deepEqual(errors,[]);
  await page.screenshot({path:'/private/tmp/dual-media-preview.png'});
  console.log('Original figure and paired PDF link preserved; technical source index omitted; source bytes unchanged, JS errors 0');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
