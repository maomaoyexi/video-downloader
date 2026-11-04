// 合成更新状态验证；不下载文件、不替换程序、不访问 GitHub。
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {pathToFileURL} from 'node:url';

const {Window}=await import(process.env.FANBOX_DOM_MODULE||pathToFileURL('temp/fanbox-ui-qa/node_modules/happy-dom/lib/index.js').href);
const template=fs.readFileSync('resource/templates/index.html','utf8').replace(/<script[\s\S]*?<\/script>/g,'');
const script=fs.readFileSync('resource/static/js/app.js','utf8').replace(/^init\(\);$/m,'');
const releases='https://github.com/maomaoyexi/video-downloader/releases/latest';
const available={latest_version:'v9.9.9',current_version:'v2.7.1',download_url:'https://github.com/fixture.exe',release_notes:'fixture'};

async function page(run){
  const w=new Window({url:'http://localhost:19876',settings:{disableCSSFileLoading:true,disableJavaScriptFileLoading:true}});
  try{
    w.document.write(template);w.eval(script);
    w.showToast=()=>{};w.replayAnimation=()=>{};
    w.setTimeout=callback=>{callback();return 1;};
    await run(w);
  }finally{await w.happyDOM.abort();}
}

function fallback(w){
  assert.equal(w.document.getElementById('updatePanel').classList.contains('show'),true);
  const panel=w.document.getElementById('updateManual');
  assert.ok(panel,'失败后需要可见的手动更新说明');
  assert.notEqual(panel.style.display,'none');
  const link=w.document.getElementById('updateManualLink');
  assert.equal(link.href,releases);
  assert.equal(link.target,'_blank');
  assert.ok(link.rel.split(/\s+/).includes('noopener'));
}

test('download or verification error offers the official manual release link',()=>page(w=>{
  w.handleUpdateAvailable(available);
  w.handleUpdateProgress({error:'SHA-256 校验失败'});
  fallback(w);
  assert.match(w.document.getElementById('updateProgText').textContent,/SHA-256/);
  assert.equal(w.document.getElementById('btnDoUpdate').textContent,'重试');
}));

test('release check failure opens a manual fallback with check retry',()=>page(async w=>{
  w.api=async path=>path==='/api/check-update'?{}:{checking:false,error:'GitHub 不可用'};
  await w.checkUpdateNow();fallback(w);
  assert.equal(w.document.getElementById('btnDoUpdate').textContent,'重新检查');
  assert.equal(w.document.getElementById('updateVersionRow').style.display,'none');
}));

test('release check timeout also offers manual updating',()=>page(async w=>{
  w.api=async path=>path==='/api/check-update'?{}:{checking:true};
  await w.checkUpdateNow();fallback(w);
  assert.match(w.document.getElementById('updateProgText').textContent,/超时/);
}));

test('missing asset URL offers manual updating instead of only a toast',()=>page(async w=>{
  await w.doUpdateNow();fallback(w);
  assert.equal(w.document.getElementById('btnDoUpdate').textContent,'重新检查');
}));

test('failed check can be retried and then enters the normal update flow',()=>page(async w=>{
  w.api=async path=>path==='/api/check-update'?{}:{checking:false,error:'offline'};
  await w.checkUpdateNow();fallback(w);
  const calls=[];
  w.api=async path=>{calls.push(path);return path==='/api/check-update'?{}:{...available,update_available:true};};
  await w.doUpdateNow();
  assert.deepEqual(calls,['/api/check-update','/api/update-status']);
  assert.equal(w.document.getElementById('updateManual').style.display,'none');
  assert.equal(w.document.getElementById('btnDoUpdate').textContent,'一键更新');
}));

test('retrying a failed download clears stale error and completion UI',()=>page(async w=>{
  w.handleUpdateAvailable(available);
  w.handleUpdateProgress({done:true,message:'prepared'});
  w.handleUpdateProgress({error:'无法启动替换脚本'});fallback(w);
  assert.equal(w.document.getElementById('updateDone').style.display,'none');
  w.api=async()=>({ok:true});await w.doUpdateNow();
  assert.equal(w.document.getElementById('updateManual').style.display,'none');
  assert.equal(w.document.getElementById('updateDone').style.display,'none');
  assert.equal(w.document.getElementById('btnDoUpdate').disabled,true);
  assert.equal(w.document.getElementById('updateProgText').textContent,'正在下载更新…');
}));

test('failure text cannot replace the trusted manual link or inject HTML',()=>page(w=>{
  w.handleUpdateProgress({error:'<img src=x onerror=alert(1)> https://example.invalid/',manual_update_url:'javascript:alert(1)'});
  fallback(w);
  assert.equal(w.document.getElementById('updateProgText').querySelector('img'),null);
}));

test('request rejection and later completion keep manual state consistent',()=>page(async w=>{
  w.handleUpdateAvailable(available);
  w.api=async()=>{throw new Error('connection closed');};
  await w.doUpdateNow();fallback(w);
  w.handleUpdateProgress({done:true,message:'prepared'});
  assert.equal(w.document.getElementById('updateManual').style.display,'none');
  assert.notEqual(w.document.getElementById('updateDone').style.display,'none');
}));

test('checking again can confirm latest and dismiss the old failure',()=>page(async w=>{
  w.api=async path=>path==='/api/check-update'?{}:{checking:false,error:'offline'};
  await w.checkUpdateNow();fallback(w);
  w.api=async()=>({checking:false,update_available:false});
  await w.doUpdateNow();
  assert.equal(w.document.getElementById('updatePanel').classList.contains('show'),false);
  assert.equal(w.document.getElementById('updateManual').style.display,'none');
  assert.equal(w.document.getElementById('btnDoUpdate').disabled,false);
}));

test('duplicate availability does not reset an active retry',()=>page(async w=>{
  w.handleUpdateAvailable(available);w.handleUpdateProgress({error:'offline'});
  w.api=async()=>({ok:true});await w.doUpdateNow();
  w.handleUpdateAvailable(available);
  assert.equal(w.document.getElementById('btnDoUpdate').disabled,true);
  assert.equal(w.document.getElementById('updateProgress').style.display,'flex');
  assert.equal(w.document.getElementById('updateActions').style.display,'none');
  assert.equal(w.document.getElementById('updateManual').style.display,'none');
}));

test('restored failure without a release payload supports rechecking',()=>page(w=>{
  w.handleUpdateProgress({error:'先前的更新请求失败'});fallback(w);
  assert.equal(w.document.getElementById('btnDoUpdate').textContent,'重新检查');
}));
