// Isolated HTTP/HTTPS regression: routes use local assets and synthetic cards only.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {createHash}=require('node:crypto');
const {chromium}=require('../../workbench/test_api.cjs');
const root=path.resolve(__dirname,'..','..');
const html=fs.readFileSync(process.env.PAPER_TEST_WORKBENCH_HTML||path.join(root,'workbench/workbench.html'),'utf8').replace('__CSP_NONCE__','lan-card-test');
const card={title:'LAN rendering regression',key_findings:String.raw`**结果** $\alpha_1=\frac{x_1}{y_2}$；原字串 MATH4iX0END。 <img src=x onerror="window.unsafe=true">`,intro_summary:String.raw`\(\omega=2\pi f\)`,conclusion_summary:String.raw`\[E=mc^2\]`,warnings:[],figures:[{label:'Fig. 1',source_page:1,asset_file:'pages/P1.png',status:'ok',caption:String.raw`$$\sum_{i=1}^{n}x_i$$`,detail:'Evidence stays readable.'}],equations:[]};
const rawCard=Buffer.from(JSON.stringify(card));
const cardHash=createHash('sha256').update(rawCard).digest('hex');
const image=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=','base64');
const paper={id:'lan-card',title:card.title,metadata:{channels:['journal']},assessment:null,card_path:'synthetic/card.json',asset_path:'synthetic/source.pdf',acquisition:'available',decision:'unreviewed',candidate_order:0};
const state={papers:[paper],jobs:[],runs:[],total:1,web_cards:{enabled:true,provider:'gpt'}};

async function checkOrigin(browser,url,secure){
 const context=await browser.newContext();
 try{
  await context.addInitScript(()=>{Math.random=()=>0.125;});
  const page=await context.newPage(),errors=[],requests=[];
  let matchingHash=true,cardMode='',cardRequests=0,failures=0,postRequests=0;
  page.on('pageerror',error=>errors.push(error.message));
  page.on('console',msg=>{if(msg.type()==='error'&&/Content Security Policy|Refused to execute/i.test(msg.text()))errors.push(msg.text());});
  await page.route('**/*',async route=>{
   const request=route.request(),u=new URL(request.url());requests.push(u.pathname+decodeURIComponent(u.search));
   const json=data=>route.fulfill({json:data});
   if(u.origin!==url)throw Error('Unexpected external request: '+request.url());
   if(u.pathname==='/')return route.fulfill({contentType:'text/html; charset=utf-8',headers:{'Content-Security-Policy':"default-src 'self'; script-src 'self' 'nonce-lan-card-test'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; object-src 'none'"},body:html});
   if(u.pathname==='/api/session')return json({ok:true});
   if(u.pathname==='/api/state'){
    const headers={ETag:'"synthetic-state"'};
    if(request.headers()['if-none-match']===headers.ETag)return route.fulfill({status:304,headers});
    return route.fulfill({json:state,headers});
   }
   if(u.pathname==='/api/card'){
    cardRequests++;
    if(cardMode==='transient'&&failures>0){const status=failures===2?503:200;failures--;return route.fulfill({status,contentType:'application/json',body:status===503?'':'{"title":'});}
    if(cardMode==='empty')return route.fulfill({contentType:'application/json',body:''});
    if(cardMode==='proxy')return route.fulfill({status:502,contentType:'text/html',body:'<h1>Proxy unavailable</h1>'});
    if(cardMode==='forbidden')return route.fulfill({status:403,contentType:'application/json',body:''});
    return json(card);
   }
   if(u.pathname==='/api/discover'){postRequests++;return route.fulfill({contentType:'application/json',body:''});}
   if(u.pathname==='/vendor/runtime-status.json')return json({state:'stopped'});
   if(u.pathname.startsWith('/vendor/')){
    const target=path.resolve(root,'workbench',u.pathname.slice(1));
    assert(target.startsWith(path.join(root,'workbench/vendor')+path.sep));
    const type={'.js':'text/javascript','.css':'text/css','.woff':'font/woff','.woff2':'font/woff2','.ttf':'font/ttf'}[path.extname(target)];
    return route.fulfill({contentType:type,body:fs.readFileSync(target)});
   }
   if(u.pathname==='/asset'){
    const file=u.searchParams.get('file');
    if(file==='card.json')return route.fulfill({contentType:'application/json',body:rawCard});
    if(file==='display/index.json')return json({card_sha256:matchingHash?cardHash:'0'.repeat(64),items:{'figures:0':{asset:'display/figures-0.png',label:'Fig. 1',source_page:1}}});
    if(file==='parsed.json')return json({figures:[],equations:[]});
    if(file?.endsWith('.png'))return route.fulfill({contentType:'image/png',body:image});
    if(!file||file==='source.pdf')return route.fulfill({contentType:'application/pdf',body:'%PDF synthetic original'});
   }
   return route.fulfill({status:404,body:'Unexpected synthetic route'});
  });
  await page.goto(url+'/#access=synthetic');
  await page.locator('[data-card]').waitFor();
  const capabilities=await page.evaluate(()=>({secure:isSecureContext,uuid:typeof crypto.randomUUID,digest:typeof crypto.subtle?.digest}));
  assert.equal(capabilities.secure,secure);
  assert.equal(capabilities.uuid,secure?'function':'undefined');
  assert.equal(capabilities.digest,secure?'function':'undefined');
  const original=await page.evaluate(async()=>{const response=await fetch(document.querySelector('a.link[href="/asset?id=lan-card"]').href);return {status:response.status,type:response.headers.get('Content-Type'),body:await response.text()};});
  assert.equal(original.status,200);assert.equal(original.type,'application/pdf');assert.match(original.body,/^%PDF/);
  await page.locator('[data-card]').click();
  try{await page.locator('#reader[open]').waitFor({timeout:5000});}
  catch{throw Error('Card did not open: '+await page.locator('#message').innerText());}
  assert.match(await page.locator('#cardBody').innerText(),/MATH4iX0END/);
  assert.equal(await page.locator('#cardBody .katex').count(),4);
  assert.equal(await page.locator('#cardBody .katex-error').count(),0);
  assert.equal(await page.locator('#cardBody img[onerror]').count(),0);
  assert.equal(await page.evaluate(()=>Boolean(window.unsafe)),false);
  assert.equal(await page.locator('#cardBody .display-crop').count(),secure?1:0);
  const displayedMath=await page.locator('#cardBody annotation[encoding="application/x-tex"]').allTextContents();
  assert.deepEqual(displayedMath,[String.raw`\alpha_1=\frac{x_1}{y_2}`,String.raw`\omega=2\pi f`,'E=mc^2',String.raw`\sum_{i=1}^{n}x_i`]);
  const figure=page.locator('#cardBody .page-evidence');await figure.locator('summary').click();
  await page.waitForFunction(()=>document.querySelector('#cardBody .page-evidence img')?.naturalWidth>0);
  await page.locator('#cardBody button[data-zoom-src]').click();await page.locator('#imageViewer[open]').waitFor();
  assert.match(await page.locator('#imagePdf').getAttribute('href'),/source\.pdf#page=1$/);
  await page.locator('#closeImageViewer').click();await page.locator('#closeReader').click();
  matchingHash=false;
  await page.locator('[data-card]').click();await page.locator('#reader[open]').waitFor();
  assert.equal(await page.locator('#cardBody .display-crop').count(),0,'An unmatched crop index must never be trusted');
  assert.equal(await page.locator('#cardBody .katex').count(),4);
  assert.equal(await page.locator('a.link[href="/asset?id=lan-card"]').getAttribute('target'),'_blank');
  assert.equal(requests.some(request=>request.includes('display/index.json')),secure);
  if(!secure){
   await page.locator('#closeReader').click();
   cardMode='transient';failures=2;cardRequests=0;
   await page.locator('[data-card]').click();await page.locator('#reader[open]').waitFor();
   assert.equal(cardRequests,3,'Read-only requests retry transient empty/truncated responses twice');
   await page.locator('#closeReader').click();cardMode='empty';cardRequests=0;
   await page.locator('[data-card]').click();
   await page.waitForFunction(()=>document.querySelector('#message').textContent.includes('数据不完整'));
   assert.equal(cardRequests,3,'Broken responses must stop after bounded retries');
   assert.equal(await page.locator('#reader[open]').count(),0);
   cardMode='proxy';cardRequests=0;await page.locator('[data-card]').click();
   await page.waitForFunction(()=>document.querySelector('#message').textContent.includes('HTTP 502'));
   assert.equal(cardRequests,3);assert.equal(await page.locator('#message h1').count(),0);
   cardMode='forbidden';cardRequests=0;await page.locator('[data-card]').click();
   await page.waitForFunction(()=>document.querySelector('#message').textContent.includes('HTTP 403'));
   assert.equal(cardRequests,1,'Permanent access errors must not be retried');
   await page.locator('[data-related="1"]').click();
   await page.waitForFunction(()=>document.querySelector('#message').textContent.includes('操作回执未确认'));
   assert.equal(postRequests,1,'An uncertain mutation receipt must never trigger automatic resubmission');
   cardMode='';await page.locator('[data-card]').click();await page.locator('#reader[open]').waitFor();
   assert.equal(await page.locator('#cardBody .katex').count(),4);
  }
  assert.deepEqual(errors,[]);
  return {origin:url,secureContext:secure,cardOpened:true,formulae:displayedMath.length,originalImage:true,zoom:true,cropHashGuard:true,...(!secure?{boundedReadRetry:true,emptyAndProxyErrors:true,mutationNotRetried:true}:{}),errors:errors.length};
 }finally{await context.close();}
}

(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.PAPER_TEST_CHROME||undefined});
 try{
  const results=[];
  for(const [url,secure] of [['http://paper-lan.test',false],['http://127.0.0.1',true],['https://paper-secure.test',true]])results.push(await checkOrigin(browser,url,secure));
  console.log(JSON.stringify(results));
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
