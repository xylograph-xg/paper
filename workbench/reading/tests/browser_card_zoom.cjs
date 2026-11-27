const {chromium}=require('playwright');
const crypto=require('crypto');
const {workbenchAccess}=require('../../workbench/test_api.cjs');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 try{
 const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const access=await workbenchAccess(page);const id=access.paperId;
 const raw=await(await page.request.get(access.base+`/asset?id=${id}&file=card.json`)).body();
 const card=JSON.parse(raw.toString());card.figures[0].source_page=1;card.figures[0].asset_file='figure.png';
 await page.route('**/api/card?*',r=>r.fulfill({json:card}));
 await page.route('**/asset?*',async r=>{
  const u=new URL(r.request().url()),file=u.searchParams.get('file');
  if(file==='display/index.json')return r.fulfill({json:{card_sha256:crypto.createHash('sha256').update(raw).digest('hex'),items:{'figures:0':{asset:'display/figures-0.png',label:'Fig. 1',source_page:1}}}});
  if(file==='display/figures-0.png')return r.fulfill({response:await page.request.get(access.base+`/asset?id=${id}&file=figure.png`)});
  return r.continue();
 });
 await page.goto(access.authenticatedUrl);await page.waitForSelector('article.card');
 await page.locator(`[data-card][data-id="${id}"]`).click();await page.waitForSelector('#reader[open] .display-crop');
 await page.locator('.display-crop').click();await page.waitForSelector('#imageViewer[open]');
 await page.waitForFunction(()=>document.querySelector('#fullImage').naturalWidth>0);
 await page.locator('[data-image-zoom="1"]').click();
 let size=await page.locator('#fullImage').evaluate(i=>({width:i.getBoundingClientRect().width,native:i.naturalWidth}));
 if(size.width!==size.native)throw Error('100% view still constrained');
 await page.locator('[data-image-zoom="2"]').click();
 size=await page.locator('#fullImage').evaluate(i=>({width:i.getBoundingClientRect().width,native:i.naturalWidth}));
 if(size.width!==size.native*2)throw Error('200% zoom incorrect');
 if(!(await page.locator('#imagePdf').getAttribute('href')).endsWith('#page=1'))throw Error('PDF source page missing');
 await page.screenshot({path:'/private/tmp/paper-card-zoom.png'});
 await page.locator('#closeImageViewer').click();if(!await page.locator('#reader').isVisible())throw Error('Closing image closed card');
 if(errors.length)throw Error(errors.join('\n'));
 console.log('Crop preview, nested viewer, native 100%/200%, page PDF link, close behavior: passed; JS errors 0');
 }finally{await browser.close();}
})().then(()=>process.exit(0)).catch(e=>{console.error(e);process.exit(1);});
