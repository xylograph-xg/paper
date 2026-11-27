const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(require('path').join(__dirname,'../workbench.html'),'utf8');
const fn=source.slice(source.indexOf('async function showCard(id){'),source.indexOf('\nlet searchTimer;'));
let finishA;const body={innerHTML:'',scrollTop:0};
const context={readerRequest:0,readerSelection:[],cardDialog:{open:false,showModal(){this.open=true}},document:{querySelector(sel){return sel==='#cardBody'?body:{focus(){}}}},window:{},globalThis:{},esc:s=>s,readerSummaryHTML:()=>'',closeImageView:()=>{},fetch:async()=>({ok:false}),fetchJSON:async url=>url.endsWith('A')?await new Promise(resolve=>finishA=()=>resolve({data:{title:'A'}})):{data:{title:'B'}}};
vm.createContext(context);vm.runInContext(fn,context);
(async()=>{
 const a=context.showCard('A');await context.showCard('B');finishA();await a;assert(body.innerHTML.includes('<h2>B</h2>'));
 const late=context.showCard('A');context.readerRequest++;finishA();await late;assert(body.innerHTML.includes('<h2>B</h2>'));
 console.log('reader latest selection and close invalidation: passed');
})().catch(e=>{console.error(e);process.exitCode=1});
