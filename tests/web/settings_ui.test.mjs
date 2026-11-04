// 合成设置和本地 DOM 验证，不读取用户配置或连接外部服务。
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {execFileSync} from 'node:child_process';
import {pathToFileURL} from 'node:url';

const {Window}=await import(process.env.FANBOX_DOM_MODULE||pathToFileURL('temp/fanbox-ui-qa/node_modules/happy-dom/lib/index.js').href);
const config=JSON.parse(execFileSync(process.env.PYTHON_EXECUTABLE||'python',[
  '-c','import json;from video_downloader.core.constants import DEFAULT_CONFIG;print(json.dumps(DEFAULT_CONFIG))'
],{encoding:'utf8'}));
const template=fs.readFileSync('resource/templates/index.html','utf8').replace(/<script[\s\S]*?<\/script>/g,'');
const app=fs.readFileSync('resource/static/js/app.js','utf8').replace(/^init\(\);$/m,'');

async function page(){
  const w=new Window({url:'http://localhost:19876',settings:{disableCSSFileLoading:true,disableJavaScriptFileLoading:true}});
  w.document.write(template);
  w.eval(app);
  w.applyConfig(structuredClone(config));
  return w;
}

async function tocPage(collapsed = []){
  const w=await page();
  w.fillSelect('s_resolution',[['best','最高画质'],['720','720p']]);
  // Happy DOM 不计算布局；此组只验证点击状态，不冒充实际滚动/视觉验收。
  w.requestAnimationFrame=()=>1;
  for(const section of w.document.querySelectorAll('.settings-section')) section.scrollIntoView=()=>{};
  w.localStorage.setItem('video-dl-settings-collapsed-sections',JSON.stringify(collapsed));
  w.initSettingsToc();
  return w;
}

function clickToc(w,id,part='span'){
  const button=w.document.querySelector(`.settings-toc-item[data-target="${id}"]`);
  const target=part==='button'?button:button.querySelector(part);
  target.dispatchEvent(new w.MouseEvent('pointerdown',{bubbles:true}));
  target.dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
}

test('selecting another expanded settings section keeps it open',async()=>{
  const w=await tocPage();
  try{
    assert.equal(w.document.querySelector('.settings-toc-item.on').dataset.target,'set-presets');
    assert.equal(w.document.getElementById('set-output-body').hidden,false);
    clickToc(w,'set-output');
    assert.equal(w.document.querySelector('.settings-toc-item.on').dataset.target,'set-output');
    assert.equal(w.document.getElementById('set-output-body').hidden,false);
    assert.equal(w.document.getElementById('set-presets-body').hidden,false);
    assert.equal(w.document.querySelectorAll('.settings-toc-item.on').length,1);
  }finally{await w.happyDOM.abort();}
});

test('selecting a different collapsed section opens it and synchronizes both buttons',async()=>{
  const w=await tocPage(['set-output']);
  try{
    assert.equal(w.document.getElementById('set-output-body').hidden,true);
    clickToc(w,'set-output','i');
    assert.equal(w.document.getElementById('set-output-body').hidden,false);
    for(const button of w.document.querySelectorAll('[data-section="set-output"]'))
      assert.equal(button.getAttribute('aria-expanded'),'true');
    assert.equal(JSON.parse(w.localStorage.getItem('video-dl-settings-collapsed-sections')).includes('set-output'),false);
  }finally{await w.happyDOM.abort();}
});

test('the current settings directory still toggles from every part of its row',async()=>{
  const w=await tocPage();
  try{
    clickToc(w,'set-output');
    w.document.getElementById('s_resolution').value='720';
    for(const part of ['span','i','button','svg']){
      clickToc(w,'set-output',part);
      assert.equal(w.document.getElementById('set-output-body').hidden,true);
      clickToc(w,'set-output',part);
      assert.equal(w.document.getElementById('set-output-body').hidden,false);
      assert.equal(w.collectCfg().RESOLUTION,'720');
    }
  }finally{await w.happyDOM.abort();}
});

test('settings content headings keep their direct toggle behavior',async()=>{
  const w=await tocPage();
  try{
    const heading=w.document.querySelector('#set-output > .settings-section-heading');
    heading.querySelector('b').click();
    assert.equal(w.document.getElementById('set-output-body').hidden,true);
    assert.equal(w.document.querySelector('.settings-toc-item.on').dataset.target,'set-output');
    heading.click();
    assert.equal(w.document.getElementById('set-output-body').hidden,false);
    assert.equal(w.document.querySelector('.settings-toc-item[data-target="set-output"]').getAttribute('aria-expanded'),'true');
  }finally{await w.happyDOM.abort();}
});

test('delayed live capabilities keep unsaved platform mode choices',async()=>{
  const w=await page();
  try{
    let respond;
    w.fetch=()=>new Promise(resolve=>{respond=resolve;});
    const pending=w.loadLiveCapabilities();
    const choice=w.document.querySelector('[data-live-platform="YouTube"]');
    choice.value='live_edge';
    choice.dispatchEvent(new w.Event('change',{bubbles:true}));
    respond({ok:true,text:async()=>JSON.stringify({platforms:{
      YouTube:{catch_up:'supported',live_edge:true},
      Twitch:{catch_up:'supported',live_edge:true},
    }})});
    await pending;
    assert.equal(w.document.querySelector('[data-live-platform="YouTube"]').value,'live_edge');
    assert.equal(JSON.parse(w.collectCfg().LIVE_PLATFORM_MODES).YouTube,'live_edge');
  }finally{await w.happyDOM.abort();}
});

test('loading another config still replaces previous platform mode choices',async()=>{
  const w=await page();
  try{
    w.document.querySelector('[data-live-platform="YouTube"]').value='live_edge';
    w.applyConfig({...structuredClone(config),LIVE_PLATFORM_MODES:'{"YouTube":"catch_up"}'});
    assert.equal(w.document.querySelector('[data-live-platform="YouTube"]').value,'catch_up');
    assert.equal(JSON.parse(w.collectCfg().LIVE_PLATFORM_MODES).YouTube,'catch_up');
  }finally{await w.happyDOM.abort();}
});
