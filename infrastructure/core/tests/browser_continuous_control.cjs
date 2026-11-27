const {chromium}=require('../../workbench/test_api.cjs');
const {workbenchAccess}=require('../../workbench/test_api.cjs');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 try{
 const page=await browser.newPage();const errors=[];let clicks=0;
 page.on('pageerror',e=>errors.push(e.message));
 const access=await workbenchAccess(page);
 await page.route('**/api/continuous/start',r=>{clicks++;return r.fulfill({json:{ok:true,services:{test:{ok:true}}}});});
 await page.goto(access.authenticatedUrl);await page.waitForSelector('article.card');
 const text=await page.locator('#libraryStats').textContent();
 if(!text.includes('2/2')||!text.includes('卡片 1'))throw Error('Incorrect statistics: '+text);
 if(await page.locator('#startContinuous').isVisible()||await page.locator('#libraryStats').isVisible())throw Error('Task controls still visible');
 await page.locator('#paperSearch').fill('Synthetic');await page.locator('#paperSearch').fill('');
 if(clicks!==0)throw Error('Reading must not start background tasks: '+clicks);
 if(errors.length)throw Error(errors.join('\n'));
 console.log('Library totals retained; task controls hidden; reading/search sends no continuous-start request; JS errors 0');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
