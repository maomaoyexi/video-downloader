// 合成 SSE 和本地 DOM 验证；不启动下载、不读取用户配置或连接服务。
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {execFileSync} from 'node:child_process';
import {pathToFileURL} from 'node:url';

const {Window}=await import(process.env.FANBOX_DOM_MODULE||pathToFileURL('temp/fanbox-ui-qa/node_modules/happy-dom/lib/index.js').href);
const template=fs.readFileSync('resource/templates/index.html','utf8').replace(/<script[\s\S]*?<\/script>/g,'');
const app=fs.readFileSync('resource/static/js/app.js','utf8').replace(/^init\(\);$/m,'');
const audio=fs.readFileSync('resource/static/js/audio-convert.js','utf8');
const defaults=JSON.parse(execFileSync(process.env.PYTHON_EXECUTABLE||'python',[
  '-B','-c','import json;from video_downloader.core.constants import DEFAULT_CONFIG;print(json.dumps(DEFAULT_CONFIG))'
],{encoding:'utf8'}));
const startButtons=['btnStart','btnWithnyLive','btnSubtitleDownload','btnCoverDownload'];

async function page(run){
  const w=new Window({url:'http://localhost:19876',settings:{disableCSSFileLoading:true,disableJavaScriptFileLoading:true}});
  let source;
  try{
    w.document.write(template);
    w.SESSION_TOKEN='fixture-token';
    w.EventSource=class {constructor(){source=this;}close(){}};
    w.setTimeout=()=>1;
    w.eval(app);w.eval(audio);
    w.api=async()=>({recordings:[],presets:[],history:[]});
    w.connectSSE();
    await run(w,(type,data,extra={})=>source.onmessage({data:JSON.stringify({type,data,...extra})}));
  }finally{await w.happyDOM.abort();}
}

for(const [name,state,startDisabled,stopDisabled] of [
  ['running',{running:true,phase:'running'},true,false],
  ['stopping',{running:true,phase:'stopping'},true,true],
  ['suspended',{running:false,phase:'suspended'},true,true],
  ['idle',{running:false,phase:'idle'},false,true],
]){
  for(const event of ['ready','download_state']){
    test(`${event} applies the ${name} task slot to every download entry`,()=>page((w,send)=>{
      send(event,{...state,generation:7});
      for(const id of startButtons)assert.equal(w.document.getElementById(id).disabled,startDisabled,id);
      assert.equal(w.document.getElementById('btnStop').disabled,stopDisabled);
      for(const button of w.document.querySelectorAll('button[onclick^="startAudio"]'))
        assert.equal(button.disabled,startDisabled,button.getAttribute('onclick'));
    }));
  }
}

test('task-scoped state does not occupy the shared download slot',()=>page((w,send)=>{
  send('ready',{running:false,phase:'idle',tasks:[]});
  send('download_state',{running:true,phase:'running'},{task_id:'another-task'});
  for(const id of startButtons)assert.equal(w.document.getElementById(id).disabled,false,id);
}));

test('queued task mode work still permits a new task and enables stop',()=>page((w,send)=>{
  send('ready',{running:false,phase:'idle',tasks:[{id:'task-1',status:'queued',label:'合成任务',items:[]}]});
  for(const id of startButtons)assert.equal(w.document.getElementById(id).disabled,false,id);
  assert.equal(w.document.getElementById('btnStop').disabled,false);
  send('download_state',{running:false,phase:'idle',generation:2});
  assert.equal(w.document.getElementById('btnStop').disabled,false);
  assert.match(w.document.getElementById('taskList').textContent,/合成任务/);
}));

test('legacy ready log arrays remain supported and release the shared slot',()=>page((w,send)=>{
  send('download_state',{running:true,phase:'running',generation:1});
  send('ready',[{time:'12:00:00',msg:'旧格式日志',level:'info'}]);
  for(const id of startButtons)assert.equal(w.document.getElementById(id).disabled,false,id);
  assert.match(w.document.getElementById('logBox').textContent,/旧格式日志/);
}));

test('settings save without the retired log control keeps working switches',()=>page(async w=>{
  w.document.getElementById('sw_log')?.remove();
  w.applyConfig({...structuredClone(defaults),ENABLE_LOG:0,EMBED_META:0,DOWNLOAD_THUMB:1});
  w.toggleSwitch(w.document.getElementById('sw_meta'));
  w.toggleSwitch(w.document.getElementById('sw_thumb'));
  let saved;
  const notices=[];
  w.api=async(path,options)=>{assert.equal(path,'/api/save-config');saved=JSON.parse(options.body);return {ok:true};};
  w.showToast=(message,level)=>notices.push({message,level});
  await w.saveSettings();
  assert.equal(saved.EMBED_META,1);
  assert.equal(saved.DOWNLOAD_THUMB,0);
  assert.equal(Object.hasOwn(saved,'ENABLE_LOG'),false);
  assert.equal(notices.at(-1).level,'success');
}));

test('an early download click cannot overwrite configuration still loading',()=>page(async w=>{
  const calls=[];
  let deliverConfig;
  const saved={...structuredClone(defaults),PROXY_ENABLED:1,YTDLP_DEFAULT_ARGS:'--no-playlist'};
  w.api=async (path,options)=>{
    calls.push([path,options]);
    if(path==='/api/config')return new Promise(resolve=>{deliverConfig=resolve;});
    return {ok:true};
  };
  const pending=w.loadConfig();
  w.document.getElementById('urlInput').value='https://www.youtube.com/watch?v=fixture';
  await w.startDl();
  assert.deepEqual(calls.map(([path])=>path),['/api/config']);
  assert.match(w.document.querySelector('.toast:last-child').textContent,/设置正在加载/);
  deliverConfig({version:'fixture',config:saved});
  await pending;
  await w.saveSettings();
  const payload=JSON.parse(calls.at(-1)[1].body);
  assert.equal(payload.PROXY_ENABLED,1);
  assert.equal(payload.YTDLP_DEFAULT_ARGS,'--no-playlist');
}));

test('a failed config read can be retried without saving default form values',()=>page(async w=>{
  let reads=0;
  let writes=0;
  w.api=async path=>{
    if(path==='/api/config'){
      if(++reads===1)throw new Error('connection interrupted');
      return {version:'fixture',config:structuredClone(defaults)};
    }
    writes++;
    return {ok:true};
  };
  await assert.rejects(w.loadConfig(),/connection interrupted/);
  await w.saveSettings();
  assert.equal(reads,2);
  assert.equal(writes,0);
  await w.saveSettings();
  assert.equal(writes,1);
}));

for(const [start,input,button,endpoint] of [
  ['startSubtitleDownload','subtitleUrlInput','btnSubtitleDownload','/api/download-subtitles'],
  ['startCoverDownload','coverUrlInput','btnCoverDownload','/api/download-covers'],
]){
  test(`${endpoint} reports a rejected submission and lets the user retry`,()=>page(async w=>{
    w.applyConfig(structuredClone(defaults));
    w.document.getElementById(input).value='https://www.youtube.com/watch?v=fixture';
    w.api=async path=>path===endpoint?{error:'未找到 yt-dlp.exe'}:{ok:true};
    await w[start]();
    assert.match(w.document.getElementById('toolStatus').textContent,/未找到 yt-dlp.exe/);
    assert.equal(w.document.getElementById(button).disabled,false);
  }));
}

test('exit rejection keeps the page open and successful exit waits for the server event',()=>page(async (w,send)=>{
  w.confirm=()=>true;
  let attempts=0;
  w.api=async path=>{
    assert.equal(path,'/api/exit');
    if(++attempts===1)throw new Error('依赖正在安装');
    return {ok:true};
  };
  await w.exitApp();
  assert.ok(w.document.getElementById('urlInput'));
  assert.match(w.document.querySelector('.toast:last-child').textContent,/依赖正在安装/);
  await w.exitApp();
  assert.ok(w.document.getElementById('urlInput'));
  assert.equal(w.document.querySelector('.exit-screen'),null);
  send('exit');
  assert.match(w.document.querySelector('.exit-screen').textContent,/工具已关闭/);
}));
