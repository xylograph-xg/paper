const fs = require('fs');
const path = require('path');

async function workbenchAccess(page) {
  let fixture;
  if (!process.env.PAPER_WORKBENCH_URL) {
    const child=require('child_process').spawn(process.env.PAPER_TEST_PYTHON||'python3',['-m','workbench.tests.workbench_browser_fixture'],{cwd:path.resolve(__dirname,'..','..'),stdio:['ignore','pipe','inherit']});
    process.on('exit',()=>child.kill('SIGTERM'));
    page.context().browser().on('disconnected',()=>child.kill('SIGTERM'));
    fixture=await new Promise((resolve,reject)=>{
      let data='';child.stdout.on('data',chunk=>{data+=chunk;const end=data.indexOf('\n');if(end>=0)resolve(JSON.parse(data.slice(0,end)));});
      child.on('error',reject);child.on('exit',code=>reject(Error('Browser fixture exited: '+code)));
    });
  }
  const requested = new URL(process.env.PAPER_WORKBENCH_URL || fixture.url);
  const fragment = new URLSearchParams(requested.hash.slice(1));
  const base = requested.origin;
  let token = process.env.PAPER_WORKBENCH_TOKEN || fragment.get('access') || fixture?.secret;
  if (!token) throw Error('Set PAPER_WORKBENCH_URL to the startup access link, or set PAPER_WORKBENCH_TOKEN.');
  const response = await page.request.post(base + '/api/session', {
    headers: { 'X-Paper-Token': token }, data: {}
  });
  if (response.status() !== 200) throw Error('Workbench authentication failed (HTTP ' + response.status() + ').');
  return { base, paperId:fixture?.paper_id, authenticatedUrl: base + '/#access=' + encodeURIComponent(token) };
}

module.exports = { workbenchAccess };
