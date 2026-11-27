// Isolated reader rendering: every request is fulfilled locally; no worker or model calls.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {createHash}=require('node:crypto');
const {chromium}=require('../../workbench/test_api.cjs');
const root=path.resolve(__dirname,'..','..');
const html=fs.readFileSync(process.env.PAPER_TEST_WORKBENCH_HTML||path.join(root,'workbench/workbench.html'),'utf8').replace('__CSP_NONCE__','reader-layout-test');
const longPoint='已有方法在这一条件下仍有边界，需要对照不同条件的实验结果，保留原文中的数值、对象和适用范围。'.repeat(6);
const mathText=String.raw`\text{`+'公式内的条件。仍保留全部字符。'.repeat(15)+'}',formattedDiscussion='**保留粗体** '+longPoint+' $'+mathText+'$ [原文链接](https://example.com/original) '+longPoint;
const card={title:'Synthetic full-window reader',one_line_summary:'这段工作总结与原卡片保持一致。',key_findings:'保留具体结论 $E=mc^2$。',intro_summary:'第一点：现有研究提出一个问题。\n第二点：这项研究检查另一个条件。\n'+longPoint,conclusion_summary:'第一项讨论保留完整论述。\n第二项讨论保留适用边界。\n'+formattedDiscussion,paper_evaluation:{overall_quality:{score:88,reason:'Synthetic technical scoring reason'}},meta:{producer:'web_card_service',structural_complete:true,scientific_verified:false,media_evidence:{source:{state:'available'},warnings:['Synthetic source warning']}},_source_review:{review_score:90,review_scores:{figure_integrity:9},review_missing_inputs:['<img src=x onerror="window.unsafe=true">']},warnings:['Synthetic generated warning'],figures:[{label:'Fig. 1',source_page:2,asset_file:'pages/P2.png',status:'ok',one_line:'同一张图的阅读正文',caption:'原文图注仍保留。',detail:longPoint.repeat(4),result:'科学结论 1.25 × 10⁻³ 保留。',evidence_quote:'Technical source quote',evidence_status:'verified',evidence_verification:{kind:'literal_quote_same_page'},crop_note:'Synthetic crop note'},{label:'Fig. 2',source_page:3,asset_file:'pages/P3.png',one_line:'第二张图',detail:'另一张图对应的科学正文。'}],equations:[]};
const panelDescription='该图展示结构与堆积，无连续数值坐标轴。a：Synthetic-A，保留数值1.25与条件。b: Synthetic-B，保留另一种取向。 (c) Synthetic-C，保留第三个面板。';
const pipeDescription='组合面板｜说明：(a) Synthetic-A，保留条件。 （b）Synthetic-B，保留边界。';
const ordinaryVariables='普通变量 a：1.25， b：2.5，化学名称 DP-a、DP-b 与比值 a/b 均保留。';
const protectedPanels=String.raw`数学 $a:b=1$ 与 $\text{a: one. b: two}$ 保持完整。a：只有一个明确面板，不拆分。`;
card.figures[0].figure_info=panelDescription;card.figures[1].figure_info=pipeDescription;
card.figures.push({label:'Fig. 3',figure_info:ordinaryVariables},{label:'Fig. 4',figure_info:protectedPanels});
const original=JSON.stringify(card),rawCard=Buffer.from(original),cardHash=createHash('sha256').update(rawCard).digest('hex');
const paper={id:'reader-layout',title:card.title,metadata:{channels:['journal']},card_path:'synthetic/card.json',asset_path:'synthetic/source.pdf',acquisition:'available',decision:'unreviewed',candidate_order:0};
const image='<svg xmlns="http://www.w3.org/2000/svg" width="1800" height="1200"><rect width="1800" height="1200" fill="#edf4ef"/><path d="M80 950L400 730L720 580L1000 450L1500 180" stroke="#21675d" stroke-width="12" fill="none"/><text x="100" y="120" fill="#244f46" font-size="64">Synthetic figure for paired reading</text></svg>';

async function checkSize(browser,width,height){
 const context=await browser.newContext({viewport:{width,height}}),page=await context.newPage(),errors=[],requests=[];
 try{
  page.on('pageerror',error=>errors.push(error.message));
  await page.route('**/*',async route=>{
   const request=route.request(),u=new URL(request.url());requests.push({url:request.url(),method:request.method()});assert.equal(u.origin,'https://reader-layout.test');
   const json=data=>route.fulfill({json:data});
   if(u.pathname==='/')return route.fulfill({contentType:'text/html',headers:{'Content-Security-Policy':"default-src 'self'; script-src 'self' 'nonce-reader-layout-test'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; object-src 'none'"},body:html});
   if(u.pathname==='/api/session')return json({ok:true});
   if(u.pathname==='/api/state')return json({papers:[paper],jobs:[],runs:[],total:1,web_cards:{enabled:true,provider:'gpt'}});
   if(u.pathname==='/api/card')return json(card);
   if(u.pathname==='/vendor/runtime-status.json')return json({state:'stopped'});
   if(u.pathname.startsWith('/vendor/')){const target=path.resolve(root,'workbench',u.pathname.slice(1));assert(target.startsWith(path.join(root,'workbench/vendor')+path.sep));return route.fulfill({contentType:{'.js':'text/javascript','.css':'text/css','.woff2':'font/woff2','.woff':'font/woff','.ttf':'font/ttf'}[path.extname(target)],body:fs.readFileSync(target)});}
   if(u.pathname==='/asset'){const file=u.searchParams.get('file');if(file==='card.json')return route.fulfill({contentType:'application/json',body:rawCard});if(file==='display/index.json')return json({card_sha256:cardHash,items:{'figures:0':{asset:'display/figures-0.png',label:'Fig. 1',source_page:2}}});if(file==='parsed.json')return json({figures:[],equations:[]});if(file?.endsWith('.png'))return route.fulfill({contentType:'image/svg+xml',body:image});if(!file||file==='source.pdf')return route.fulfill({contentType:'application/pdf',body:'%PDF synthetic original'});}
   return route.fulfill({status:404,body:'Unexpected synthetic route'});
  });
  await page.goto('https://reader-layout.test/#access=synthetic');await page.locator('[data-card]').click();await page.locator('#reader[open]').waitFor();
  const rect=await page.locator('#reader').boundingBox();assert.deepEqual(rect,{x:0,y:0,width,height});
  assert.equal(await page.locator('#closeReader').innerText(),'退出');
  assert.equal(await page.locator('#reader .research-context').getAttribute('open'),'');
  assert.equal(await page.locator('#reader .research-motivation').evaluate(node=>node.textContent.trim()),card.intro_summary);
  const discussion=await page.locator('#reader .research-discussion').evaluate(node=>{const clone=node.cloneNode(true);for(const math of clone.querySelectorAll('.katex'))math.replaceWith(document.createTextNode('$'+math.querySelector('annotation[encoding="application/x-tex"]').textContent+'$'));return clone.textContent.trim();});
  assert.equal(discussion,card.conclusion_summary.replaceAll('**','').replace('[原文链接](https://example.com/original)','原文链接'));
  assert.equal(await page.locator('.research-discussion strong').first().innerText(),'保留粗体');assert.equal(await page.locator('.research-discussion a').getAttribute('href'),'https://example.com/original');
  assert.equal(await page.locator('.research-discussion annotation[encoding="application/x-tex"]').textContent(),mathText);
  const paragraphs=await page.locator('.research-motivation p').count();assert(paragraphs>=4,'Existing points and long prose must have separate paragraphs');
  assert.equal(await page.locator('#cardBody .notice, #cardBody .muted, #cardBody .badges, #cardBody .paper-quality-breakdown').count(),0);
  assert.doesNotMatch(await page.locator('#cardBody').innerText(),/GPT文献评价依据|卡片核验|生成完成|结构检查|逐字|科学复核|自动生成|生成与图像核验|裁图|Synthetic crop note/);
  assert.equal(await page.locator('#cardBody .katex').count(),4);assert.equal(await page.locator('#cardBody .katex-error').count(),0);assert.equal(await page.evaluate(()=>window.unsafe),undefined);
  const panelProse=page.locator('[data-reading-item="figure:0"] .figure-section').filter({has:page.getByRole('heading',{name:'读图：面板与坐标',exact:true})}).locator('.prose');
  const panelParagraphs=await panelProse.locator('li>p').allTextContents();assert.equal(panelParagraphs.length,4);assert.match(panelParagraphs[1],/^a：/);assert.match(panelParagraphs[2],/^b:/);assert.match(panelParagraphs[3],/^\(c\)/);
  assert.equal(panelParagraphs.join('').replace(/\s/g,''),panelDescription.replace(/\s/g,''));
  const pipeProse=page.locator('[data-reading-item="figure:1"] .panel-info dd');assert.equal(await pipeProse.locator('p').count(),2);assert.equal((await pipeProse.textContent()).replace(/\s/g,''),'(a)Synthetic-A，保留条件。（b）Synthetic-B，保留边界。');
  const ordinary=page.locator('[data-reading-item="figure:2"] .figure-section li');assert.equal(await ordinary.locator('p').count(),1);assert.equal((await ordinary.textContent()).trim(),ordinaryVariables);
  const protectedProse=page.locator('[data-reading-item="figure:3"] .figure-section li');assert.equal(await protectedProse.locator('p').count(),1);assert.deepEqual(await protectedProse.locator('annotation[encoding="application/x-tex"]').allTextContents(),['a:b=1',String.raw`\text{a: one. b: two}`]);
  await page.screenshot({path:`/private/tmp/paper-reader-full-${width}.png`});
  await panelProse.scrollIntoViewIfNeeded();await page.screenshot({path:`/private/tmp/paper-reader-panels-${width}.png`});
  const selected=await page.locator('.research-motivation p').first().evaluate(node=>{const range=document.createRange();range.selectNodeContents(node);const selection=getSelection();selection.removeAllRanges();selection.addRange(range);return selection.toString();});
  await page.locator('.display-crop').click();await page.locator('#imageViewer[open]').waitFor();await page.waitForFunction(()=>document.querySelector('#fullImage').naturalWidth===1800);
  assert.equal(await page.evaluate(()=>getSelection().toString()),selected);
  const layout=await page.evaluate(()=>{const a=document.querySelector('#imageViewer').getBoundingClientRect(),b=document.querySelector('#cardBody').getBoundingClientRect(),r=document.querySelector('#readerLayout').getBoundingClientRect();return {image:a.width,card:b.width,available:r.width,imageLeft:a.left,cardRight:b.right};});
  assert(Math.abs(layout.image-width*2/3)<1);assert(Math.abs(layout.card-width/3)<1);assert.equal(layout.imageLeft,0);assert(Math.abs(layout.cardRight-width)<1);
  assert.match(await page.locator('#imagePdf').getAttribute('href'),/source\.pdf#page=2$/);
  await page.locator('[data-image-zoom="1"]').click();assert.equal(await page.locator('#fullImage').evaluate(img=>img.getBoundingClientRect().width),1800);
  await page.locator('[data-image-zoom="2"]').click();assert.equal(await page.locator('#fullImage').evaluate(img=>img.getBoundingClientRect().width),3600);
  const scroll=await page.evaluate(()=>{const a=document.querySelector('#imageViewport'),b=document.querySelector('#cardBody'),old=b.scrollTop;a.scrollLeft=300;a.scrollTop=200;const unchanged=b.scrollTop===old;b.scrollTop=old+250;return {imageLeft:a.scrollLeft,imageTop:a.scrollTop,cardIndependent:unchanged,cardMoved:b.scrollTop>old};});
  assert.equal(scroll.imageLeft,300);assert.equal(scroll.imageTop,200);assert(scroll.cardIndependent);assert(scroll.cardMoved);
  await page.locator('[data-image-zoom="fit"]').click();await page.waitForTimeout(30);
  await page.screenshot({path:`/private/tmp/paper-reader-paired-${width}.png`});
  await page.keyboard.press('Escape');assert.equal(await page.locator('#reader[open]').count(),1);assert.equal(await page.locator('#imageViewer[open]').count(),0);
  await page.locator('[data-reading-item="figure:1"] button[data-zoom-src]').click();await page.locator('#imageViewer[open]').waitFor();assert.match(await page.locator('#imagePdf').getAttribute('href'),/source\.pdf#page=3$/);
  await page.locator('#closeImageViewer').click();assert.equal(await page.locator('#reader[open]').count(),1);assert.equal(await page.evaluate(()=>getSelection().toString()),selected);
  await page.keyboard.press('Escape');assert.equal(await page.locator('#reader[open]').count(),0);
  await page.locator('[data-card]').click();await page.locator('#reader[open]').waitFor();assert.equal(await page.locator('#imageViewer[open]').count(),0);assert.equal(await page.locator('#cardBody').evaluate(node=>node.scrollTop),0);
  await page.locator('#closeReader').click();assert.equal(await page.locator('#reader[open]').count(),0);
  assert.equal(JSON.stringify(card),original);assert.deepEqual(errors,[]);assert(requests.every(request=>request.method==='GET'||new URL(request.url).pathname==='/api/session'));
  return {width,height,paragraphs,imageWidth:layout.image,cardWidth:layout.card,fullWindow:true,pairedReading:true,independentScroll:true,zoom:true,escape:true,selectionPreserved:true,scientificTextPreserved:true,panelParagraphs:panelParagraphs.length,panelCharactersPreserved:true,pipePanelSplit:true,ordinaryVariablesUnsplit:true,mathLabelsUnsplit:true,errors:0,businessWrites:0};
 }finally{await context.close();}
}

(async()=>{const browser=await chromium.launch({headless:true,executablePath:process.env.PAPER_TEST_CHROME||undefined});try{const results=[];for(const [width,height] of [[1280,900],[720,900]])results.push(await checkSize(browser,width,height));console.log(JSON.stringify(results));}finally{await browser.close();}})().catch(error=>{console.error(error);process.exitCode=1;});
