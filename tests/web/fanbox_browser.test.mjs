// Isolated application E2E test. Requires playwright@1.58.2 in temp/fanbox-ui-qa.
// Runs with synthetic data in a fresh headless profile; never attaches to a user browser.
import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {pathToFileURL} from 'node:url';
const {chromium}=await import(process.env.FANBOX_PLAYWRIGHT_MODULE||pathToFileURL('temp/fanbox-ui-qa/node_modules/playwright/index.mjs').href);
const root=process.cwd(),data=JSON.parse(execFileSync('python',['-c','import json;from video_downloader.core.constants import DEFAULT_CONFIG;from video_downloader.platforms.fanbox.options import normalize_options;print(json.dumps(dict(config=DEFAULT_CONFIG,options=normalize_options())))'],{encoding:'utf8'}));
let config=structuredClone(data.config),options=data.options,created=[],jobs=[];
let recordCount=0;
const job={id:'a'.repeat(32),source:'https://www.fanbox.cc/@sample',status:'preview_ready',version:1,created_at:1793376000,phase:'preview',counts:{posts:1},scope:{list_complete:true}};
const server=http.createServer(async(req,res)=>{
  const url=new URL(req.url,'http://localhost');let body='';for await(const chunk of req)body+=chunk;
  if(url.pathname.startsWith('/api/')){
    const name=url.pathname;
    if(name==='/api/events'){res.writeHead(200,{'Content-Type':'text/event-stream'});res.write('data: '+JSON.stringify({type:'ready',data:{logs:[],tasks:[],fanbox_jobs:jobs,download:{running:false}}})+'\n\n');return;}
    let result={};
    if(name==='/api/config')result={version:'2.6.0',config};
    if(name==='/api/save-config'){config={...config,...JSON.parse(body)};result={ok:true};}
    if(name==='/api/fanbox/options')result={options,defaults:options,enabled:true,anonymous:true,cookie_file:''};
    if(name==='/api/fanbox/auth')result={runtime:{available:true},status:'anonymous'};
    if(name==='/api/fanbox/jobs')result={jobs};
    if(name==='/api/fanbox/create'){created.push(JSON.parse(body));jobs=[job];result={job};}
    if(name==='/api/fanbox/job')result={job,options,posts:[{id:'1',title:'Sample post',fee:500,published_at:'2026-10-31',access:'accessible',resources:0,known_bytes:0}],total:1};
    if(name==='/api/fanbox/logs')result={logs:[]};
    if(name==='/api/fanbox/records'){
      if(body){const input=JSON.parse(body);result={accepted:input.records?.length||0,rejected:0,duplicates:0,inserted:input.records?.length||0};
        if(input.action==='import')recordCount+=input.records.length;if(input.action==='clear')recordCount=0;
      }else result={urls:recordCount,imported:recordCount,verified:1,records:[]};
    }
    if(name==='/api/fanbox/usage')result={timezone:'Asia/Shanghai',days:[{date:'2026-11-01',bytes:100,completed_bytes:80}]};
    if(name==='/api/fanbox/history')result={runs:[job]};
    if(name==='/api/history')result={history:[{platform:'Fanbox',url:job.source,title:'sample',time:'2026-10-31'}]};
    if(name==='/api/tasks')result={tasks:[],version:0};
    if(name==='/api/live/capabilities')result={platforms:[]};
    res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify(result));return;
  }
  const file=url.pathname==='/'?'resource/templates/index.html':'resource'+url.pathname;
  if(!file.startsWith('resource/')||file.includes('..')){res.writeHead(404);res.end();return;}
  try{let content=fs.readFileSync(path.join(root,file));if(file.endsWith('.html'))content=Buffer.from(content.toString().replaceAll('__SESSION_TOKEN__','test-token'));
    res.setHeader('Content-Type',file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':file.endsWith('.html')?'text/html':'application/octet-stream');res.end(content);
  }catch{res.writeHead(404);res.end();}
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const browser=await chromium.launch({headless:true,executablePath:process.env.FANBOX_BROWSER_EXECUTABLE||'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
page.on('pageerror',e=>errors.push(e.message));
try{
  await page.goto('http://127.0.0.1:'+server.address().port);await page.locator('[data-fanbox-option="fan_cards.scope"]').waitFor({state:'attached'});
  await page.locator('.ni[data-page="settings"]').click();
  await page.locator('#set-fanbox').scrollIntoViewIfNeeded();

  const checkboxes=await page.locator('#set-fanbox .fb-switch').evaluateAll(items=>items.filter(el=>el.getClientRects().length).map(el=>({width:el.getBoundingClientRect().width,height:el.getBoundingClientRect().height})));
  assert.ok(checkboxes.every(box=>box.width===32&&box.height===18));
  assert.equal(await page.locator('#fanboxSettingsFields [data-fb-fold="occasional"]').getAttribute('open'),null);
  await page.locator('#fanboxSettingsFields [data-fb-fold="occasional"]>summary').click();
  const rows=await page.locator('#fanboxSettingsFields .fb-field').evaluateAll(items=>items.filter(el=>el.getClientRects().length).map(el=>el.getBoundingClientRect().y));
  assert.ok(rows.every((y,i)=>i===0||y>rows[i-1]));
  await page.locator('.ni[data-page="download"]').click();await page.locator('#urlInput').fill('https://sample.fanbox.cc');
  await page.locator('#btnStart').click();await page.locator('#fanboxTaskDialog').waitFor({state:'visible'});
  await page.locator('#fanboxTaskFields [data-fanbox-option="filters.fee.maximum"]').fill('1000');
  await page.locator('#fanboxTaskFields [data-fanbox-option="filters.fee.maximum"]').press('Tab');

  await page.locator('#fanboxTaskConfirm').click();await page.locator('#fanboxTaskDialog').waitFor({state:'hidden'});
  assert.equal(created[0].options.filters.fee.maximum,1000);
  assert.equal(JSON.parse(config.FANBOX_OPTIONS).filters.fee.maximum,null);
  await page.locator('.ni[data-page="history"]').click();await page.locator('.fb-history').click();await page.locator('#fanboxHistoryDialog .fb-post').waitFor({state:'attached'});
  assert.equal(await page.locator('#fanboxDownloadSelected').isVisible(),false);assert.equal(await page.locator('#fanboxSelectAll').isVisible(),false);
  await page.locator('#fanboxHistoryDialog [data-fb-close]').click();
  for(const theme of ['light','dark']){
    await page.evaluate(t=>document.documentElement.dataset.theme=t,theme);
    for(const width of [320,768,1440]){
      await page.setViewportSize({width,height:900});await page.evaluate(()=>setActivePage('settings'));await page.locator('#set-fanbox').scrollIntoViewIfNeeded();
      const overflow=await page.locator('#set-fanbox').evaluate(el=>({client:el.clientWidth,scroll:el.scrollWidth}));
      assert.ok(overflow.scroll<=overflow.client+1,`${theme}/${width}: settings overflow ${JSON.stringify(overflow)}`);

      await page.evaluate(()=>{setActivePage('download');FanboxUI.start('https://sample.fanbox.cc');});
      const modal=await page.locator('#fanboxTaskDialog').evaluate(el=>({right:el.getBoundingClientRect().right,width:innerWidth,body:el.scrollWidth,client:el.clientWidth}));
      assert.ok(modal.right<=modal.width&&modal.body<=modal.client+1,`${theme}/${width}: dialog overflow`);
      await page.locator('#fanboxTaskDialog [data-fb-close]').first().click();
      await page.evaluate(()=>setActivePage('settings'));await page.locator('#fanboxRecords').click();
      await page.locator('#fanboxRecordFile').setInputFiles({name:'records.json',mimeType:'application/json',buffer:Buffer.from('[{"url":"files/sample.zip"}]')});
      await page.locator('#fanboxRecordConfirm').waitFor({state:'visible'});await page.locator('#fanboxRecordConfirm').click();
      await page.locator('#fanboxRecordConfirm').waitFor({state:'hidden'});
      assert.ok((await page.locator('#fanboxRecordCounts').textContent()).includes('已校验文件 1'));
      const recordSize=await page.locator('#fanboxRecordsDialog').evaluate(el=>({scroll:el.scrollWidth,client:el.clientWidth}));
      assert.ok(recordSize.scroll<=recordSize.client+1,`${theme}/${width}: records overflow`);
      await page.locator('#fanboxRecordsDialog [data-fb-close]').click();
      await page.locator('#fanboxUsage').click();await page.locator('.fb-usage-table').waitFor();
      assert.equal(await page.locator('.fb-usage-bars>span').count(),1);
      await page.locator('#fanboxHistoryDialog [data-fb-close]').click();
    }
  }
  assert.deepEqual(errors,[]);console.log('PASS: full page init, task overrides, grouped history, native controls, 6 theme/viewport layouts; no JS errors');
}finally{
  // End the synthetic SSE stream before closing the browser. Otherwise test
  // workers can retain an active connection while the browser is shutting down.
  server.closeAllConnections();await new Promise(resolve=>server.close(resolve));await browser.close();
}
