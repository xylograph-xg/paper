// Isolated browser regression: no production server, workers, or API sources.
const {spawn}=require('child_process');
const {createRequire}=require('module');
const {once}=require('events');
const {chromium}=require('../../workbench/test_api.cjs');
(async()=>{
 const fixture=spawn(process.env.PAPER_TEST_PYTHON||'python3',['-u','workbench/tests/workbench_browser_fixture.py'],{cwd:process.cwd(),env:{...process.env,PYTHONPATH:process.cwd()},stdio:['ignore','pipe','pipe']});
 let browser;
 try{
  const info=await new Promise((resolve,reject)=>{
   let output='',errors='';const timer=setTimeout(()=>reject(Error('Fixture startup timed out: '+errors)),10000);
   fixture.stderr.on('data',data=>errors+=data);
   fixture.stdout.on('data',data=>{output+=data;if(output.includes('\n')){clearTimeout(timer);resolve(JSON.parse(output.split('\n')[0]));}});
   fixture.once('exit',code=>{clearTimeout(timer);reject(Error('Fixture exited '+code+': '+errors));});
  });
  browser=await chromium.launch({headless:true,executablePath:process.env.PAPER_TEST_CHROME||undefined});
  const context=await browser.newContext();const page=await context.newPage();const errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  page.on('console',message=>{if(message.type()==='error'&&/Content Security Policy|Refused to execute/i.test(message.text()))errors.push(message.text());});
  const bootstrap=await page.request.get(info.url+'/');if((await bootstrap.text()).includes(info.secret))throw Error('Public root exposed secret');
  if((await page.request.get(info.url+'/api/state')).status()!==403)throw Error('Unauthenticated state exposed');
  await page.goto(info.url);await page.locator('#login').waitFor({state:'visible'});
  await page.locator('#accessToken').fill('wrong');await page.locator('#loginForm button').click();await page.locator('#loginError').waitFor({state:'visible'});
  await page.locator('#accessToken').fill(info.secret);await page.locator('#loginForm button').click();
  await page.locator('#login').waitFor({state:'hidden'});await page.waitForFunction(()=>document.querySelectorAll('article.card').length===1);
  const cookies=await context.cookies();if(!cookies.some(c=>c.name==='PaperSession'&&c.httpOnly&&c.sameSite==='Strict'))throw Error('Session cookie attributes wrong');
  if((await page.request.get(info.url+'/asset?id='+info.paper_id)).status()!==200)throw Error('Authenticated original inaccessible');
  await page.locator('#paperSearch').fill('hidden_storage_marker');await page.waitForFunction(()=>document.querySelectorAll('article.card').length===0);
  await page.locator('#paperSearch').fill('Synthetic emitter');await page.waitForFunction(()=>document.querySelectorAll('article.card').length===1);
  await page.locator('#paperSearch').fill('');await page.waitForFunction(()=>document.querySelectorAll('article.card').length===1);
  await page.evaluate(()=>window.firstNode=document.querySelector('article.card'));await page.locator('#paperSearch').fill('');
  await page.waitForFunction(()=>window.firstNode===document.querySelector('article.card'));
  const headers={'X-Paper-Token':info.secret};
  const state=await(await page.request.get(info.url+'/api/state',{headers})).json();
  if(state.jobs.filter(job=>job.state==='failed').length!==35)throw Error('API omitted task failures');
  if(await page.locator('#runDetails').isVisible()||await page.locator('#modelSettings').isVisible()||await page.locator('details.tools').isVisible())throw Error('Task or management controls remain visible');
  const configure=async data=>{const response=await page.request.post(info.url+'/api/model-schedule',{headers,data});if(response.status()!==200)throw Error('Temporary schedule API failed');return response.json();};
  let schedule=await configure({mode:'window',start:'12:00',end:'23:00'});
  if(schedule.start!=='12:00'||schedule.end!=='23:00')throw Error('Temporary schedule window was not persisted');
  schedule=await configure({mode:'allow',minutes:30});if(!schedule.override_until)throw Error('Temporary override missing');
  schedule=await configure({mode:'reset'});if(schedule.start!=='10:00'||schedule.end!=='24:00'||schedule.override_until)throw Error('Schedule reset failed');
  schedule=await configure({mode:'all_day'});if(schedule.start!=='00:00'||schedule.end!=='24:00')throw Error('All day schedule missing');
  schedule=await configure({mode:'reset'});if(schedule.start!=='10:00'||schedule.end!=='24:00'||schedule.override_until)throw Error('Final schedule reset failed');
  await page.locator('#paperSearch').focus();if(!await page.evaluate(()=>document.activeElement.id==='paperSearch'))throw Error('Search is not keyboard accessible');
  await page.evaluate(()=>document.querySelector('#reader').showModal());await page.locator('#closeReader').click();await page.locator('#reader').waitFor({state:'hidden'});
  await page.reload();await page.locator('#login').waitFor({state:'hidden'});await page.waitForFunction(()=>document.querySelectorAll('article.card').length===1);
  const second=await browser.newContext();const fragmentPage=await second.newPage();
  await fragmentPage.goto(info.url+'/#access='+info.secret);await fragmentPage.waitForFunction(()=>document.querySelectorAll('article.card').length===1);
  if(await fragmentPage.evaluate(()=>location.hash)!=='')throw Error('Bootstrap secret retained in location');
  const outside=await browser.newContext();if((await outside.request.get(info.url+'/api/state')).status()!==403)throw Error('Separate unauthenticated context exposed catalog');
  if(errors.length)throw Error(errors.join('\n'));
  console.log(JSON.stringify({authentication:true,cookieProtectedOriginal:true,fragmentRemoved:true,searchExcludesInternalFields:true,all35FailuresRetainedInAPI:true,nodePreserved:true,keyboardSearch:true,taskControlsHidden:true,temporaryModelScheduleAPI:true,JSandCSPerrors:errors.length}));
 }finally{
  if(browser)await browser.close();
  const closed=once(fixture,'exit');fixture.kill('SIGTERM');await closed;
 }
})().catch(error=>{console.error(error);process.exit(1)});
