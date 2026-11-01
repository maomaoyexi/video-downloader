// Run: node --test tests/web/fanbox_ui.test.mjs
// Install happy-dom@20.8.4 into temp/fanbox-ui-qa, or set FANBOX_DOM_MODULE.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {execFileSync} from 'node:child_process';
import {pathToFileURL} from 'node:url';

const {Window}=await import(process.env.FANBOX_DOM_MODULE||pathToFileURL('temp/fanbox-ui-qa/node_modules/happy-dom/lib/index.js').href);
const defaults=JSON.parse(execFileSync('python',['-c','import json;from video_downloader.platforms.fanbox.options import normalize_options;print(json.dumps(normalize_options()))'],{encoding:'utf8'}));
const template=fs.readFileSync('resource/templates/index.html','utf8').replace(/<script[\s\S]*?<\/script>/g,'');
const script=fs.readFileSync('resource/static/js/fanbox.js','utf8');
const app=fs.readFileSync('resource/static/js/app.js','utf8').replace(/^init\(\);$/m,'');
const tick=()=>new Promise(resolve=>setTimeout(resolve,10));

async function page(){
  const w=new Window({url:'http://localhost:19876',settings:{disableCSSFileLoading:true,disableJavaScriptFileLoading:true}});
  w.document.write(template);w.structuredClone=structuredClone;
  const calls=[],saved=[];
  const job={id:'a'.repeat(32),source:'https://www.fanbox.cc/@sample',version:1,status:'preview_ready',phase:'preview',created_at:1,counts:{posts:1}};
  w.__api=async(path,opts)=>{
    calls.push({path,body:opts?.body?JSON.parse(opts.body):null});
    if(path==='/api/fanbox/options')return {options:structuredClone(defaults),defaults:structuredClone(defaults),enabled:true,anonymous:true,cookie_file:''};
    if(path==='/api/fanbox/auth')return {runtime:{available:true},status:'anonymous'};
    if(path==='/api/fanbox/jobs')return {jobs:[]};
    if(path==='/api/fanbox/create')return {job};
    if(path.startsWith('/api/fanbox/history'))return {runs:[job]};
    if(path.startsWith('/api/fanbox/logs'))return {logs:[]};
    if(path.startsWith('/api/fanbox/job'))return {job,posts:[{id:'1',title:'Match <script>',published_at:'2026-10-01',access:'accessible',resources:0}],total:1,options:defaults};
    if(path==='/api/check-update')return {};
    throw new Error('Unexpected endpoint: '+path);
  };
  w.__save=async()=>saved.push(JSON.parse(w.FanboxUI.configValues().FANBOX_OPTIONS));
  w.eval(app+'\napi=window.__api;saveSettingsNoAlert=window.__save;loadTasks=()=>{};showToast=()=>{};\n'+script);await tick();
  return {w,calls,saved,close:()=>w.happyDOM.abort()};
}

test('all settings render and one-run edits never mutate defaults',async()=>{
  const {w,calls,saved,close}=await page();
  try{
    const d=w.document,ui=w.FanboxUI;
    assert.equal(d.getElementById('fanboxSettingsStatus').textContent,'匿名');
    assert.ok(d.querySelectorAll('#fanboxSettingsFields .fb-field').length>=60,'all setting groups must render');
    assert.equal(d.querySelectorAll('#fanboxSettingsFields textarea').length,5);
    assert.equal(d.querySelector('#fanboxSettingsFields [data-fanbox-option="fan_cards.scope"]').value,'current');
    assert.equal(d.getElementById('fanboxImportButton'),null);
    assert.equal(d.querySelector('#fanboxSettingsFields details[data-fb-fold="occasional"]').open,false);
    assert.equal(d.getElementById('fanboxPreview').nextElementSibling.id,'btnStart');
    ui.start('https://sample.fanbox.cc');
    assert.ok(d.getElementById('fanboxTaskDialog').open);
    assert.equal(d.querySelector('#fanboxTaskFields details[data-fb-fold="occasional"]').open,true);
    assert.equal(d.querySelector('#fanboxTaskFields details[data-fb-fold="defaults"]').open,false);
    assert.equal(calls.filter(c=>c.path==='/api/fanbox/create').length,0);
    const maximum=d.querySelector('#fanboxTaskFields [data-fanbox-option="filters.fee.maximum"]');
    maximum.value='1000';maximum.dispatchEvent(new w.Event('change'));
    assert.equal(JSON.parse(ui.configValues().FANBOX_OPTIONS).filters.fee.maximum,null);
    await d.getElementById('fanboxTaskConfirm').onclick();
    const creation=calls.find(c=>c.path==='/api/fanbox/create');
    assert.equal(creation.body.options.filters.fee.maximum,1000);
    assert.equal(saved[0].filters.fee.maximum,null);
    assert.equal(d.getElementById('fanboxTaskDialog').open,false);
    ui.start('https://sample.fanbox.cc');
    assert.equal(d.querySelector('#fanboxTaskFields [data-fanbox-option="filters.fee.maximum"]').value,'');
    const auto=d.querySelector('#fanboxTaskFields [data-fanbox-option="workflow.auto_download"]');
    auto.checked=false;auto.dispatchEvent(new w.Event('change'));
    assert.equal(d.getElementById('fanboxTaskConfirm').textContent,'确认预览');
    assert.equal(JSON.parse(ui.configValues().FANBOX_OPTIONS).workflow.auto_download,true);
    d.querySelector('#fanboxTaskDialog [data-fb-close]').click();
    assert.equal(calls.filter(c=>c.path==='/api/fanbox/create').length,1);
  }finally{await close();}
});

test('FANBOX console isolates logs, history groups URLs and opens detailed runs',async()=>{
  const {w,close}=await page();
  try{
    const d=w.document;
    w.addLog({time:'00:00',msg:'video log',level:'info'});
    d.getElementById('urlInput').value='https://sample.fanbox.cc';w.FanboxUI.sync();
    const entry={time:'00:01',msg:'[FANBOX] 开始抓取',level:'info',job_id:'a',seq:1};
    w.FanboxUI.log(entry);w.FanboxUI.log(entry);
    assert.equal(d.getElementById('logBox').children.length,1);
    assert.ok(!d.getElementById('logBox').textContent.includes('video log'));
    w.renderHistory([{platform:'Fanbox',url:'https://sample.fanbox.cc',title:'sample',time:'2026-10-31'},
      {platform:'Fanbox',url:'https://sample.fanbox.cc',title:'sample',time:'2026-10-30'}]);
    assert.equal(d.querySelectorAll('.fb-history').length,1);
    d.querySelector('.fb-history').click();await tick();
    assert.ok(d.getElementById('fanboxHistoryDialog').open);
    assert.equal(d.querySelectorAll('#fanboxPosts .fb-post').length,1);
    assert.equal(d.getElementById('fanboxDownloadSelected').hidden,true);
    assert.ok(d.getElementById('fanboxPosts').textContent.includes('<script>'));
    assert.equal(d.querySelector('#fanboxPosts script'),null);
    d.getElementById('urlInput').value='https://youtube.com/watch?v=x';w.FanboxUI.sync();
    assert.ok(d.getElementById('logBox').textContent.includes('video log'));
    assert.ok(!d.getElementById('logBox').textContent.includes('[FANBOX]'));
  }finally{await close();}
});
