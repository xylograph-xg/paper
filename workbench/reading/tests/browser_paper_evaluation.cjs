const {chromium}=require('playwright');
const {workbenchAccess}=require('../../workbench/test_api.cjs');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 try{
 const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const access=await workbenchAccess(page);
 const card=await(await page.request.get(access.base+'/api/card?id='+access.paperId)).json();
 card.paper_evaluation={overall_quality:{score:86,reason:'有对照，但样本有限 <img src=x onerror=alert(1)>',source_pages:[1]},direction_novelty:{score:72,reason:'路线有改进，比较范围有限',source_pages:[1]}};
 await page.route('**/api/card?*',r=>r.fulfill({json:card}));
 await page.goto(access.authenticatedUrl);await page.waitForSelector('article.card');
 await page.locator(`[data-card][data-id="${access.paperId}"]`).click();await page.waitForSelector('#reader[open]');
 const text=await page.locator('#reader').innerText();if(/总体质量 86\/100|方向新颖性 72\/100|GPT文献评价依据/.test(text))throw Error('Technical evaluation is still shown in the reader');
 if(await page.locator('#reader img[onerror]').count())throw Error('Unsafe evaluation markup');
 if(!text.includes('Synthetic detail'))throw Error('Scientific reading text was lost');
 card.paper_evaluation.direction_novelty={score:null,reason:'信息不足',source_pages:[]};
 await page.evaluate(()=>document.querySelector('#reader').close());
 await page.locator(`[data-card][data-id="${access.paperId}"]`).click();
 await page.waitForSelector('#reader[open]');
 if((await page.locator('#reader').innerText()).includes('方向新颖性 信息不足'))throw Error('Missing-score annotation is still shown in the reader');
 if(errors.length)throw Error(errors.join('\n'));
 console.log('Scientific reader omits technical evaluation annotations and preserves reading text; JS errors 0');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
