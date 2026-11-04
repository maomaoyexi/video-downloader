// 本机 DOM 与合成缺失检测结果；不接触用户配置或真实依赖。
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {pathToFileURL} from 'node:url';

const {Window}=await import(process.env.FANBOX_DOM_MODULE||pathToFileURL('temp/fanbox-ui-qa/node_modules/happy-dom/lib/index.js').href);
const template=fs.readFileSync('resource/templates/index.html','utf8').replace(/<script[\s\S]*?<\/script>/g,'');
const source=fs.readFileSync('resource/static/js/dependencies.js','utf8');
const releaseURL='https://github.com/maomaoyexi/video-downloader/releases/latest';
const fixture=()=>({available:true,running:false,action:null,phase:'completed',progress:100,message:'缺失检测完成',error:null,
  catalog_version:'2.7.1',file_count:5,existing_count:3,missing_count:2,error_count:0,unchecked_count:0,
  missing_files:['dependency/ffmpeg.exe','dependency/deno.exe'],missing_truncated:false,recovery_required:false,download_bytes:null});

async function setup(run){
  const w=new Window({url:'http://127.0.0.1:19876',settings:{disableCSSFileLoading:true,disableJavaScriptFileLoading:true}});
  const timers=new Map();let timerId=0,state=fixture();const calls=[],confirmations=[];
  try{
    w.document.write(template);
    w.setTimeout=fn=>{const id=++timerId;timers.set(id,fn);return id;};w.clearTimeout=id=>timers.delete(id);
    w.confirm=message=>{confirmations.push(message);return true;};
    w.api=async(path,options)=>{calls.push({path,options});return path==='/api/dependencies?summary=1'?structuredClone(state):{ok:true};};
    w.eval(source);w.DependencyManagerUI.init();
    await run({w,calls,confirmations,timers,getState:()=>state,setState:value=>{state=value;}});
  }finally{w.DependencyManagerUI?.close();await w.happyDOM.abort();}
}
const settle=async()=>{for(let i=0;i<25;i++)await Promise.resolve();};
const posts=calls=>calls.filter(item=>item.options?.method==='POST');

test('the entry opens as soon as its markup exists even before DOMContentLoaded',async()=>{
  const w=new Window({url:'http://127.0.0.1:19876',settings:{disableCSSFileLoading:true,disableJavaScriptFileLoading:true}});
  const calls=[];
  try{
    w.document.write(template);
    Object.defineProperty(w.document,'readyState',{configurable:true,get:()=> 'loading'});
    w.api=async(path,options)=>{calls.push({path,options});return path==='/api/dependencies?summary=1'?fixture():{ok:true};};
    w.eval(source);
    // body末尾的依赖脚本已加载，但后续资源仍可能阻止DOMContentLoaded。
    w.document.getElementById('openDependencyManager').click();
    assert.equal(w.document.getElementById('dependencyManagerPanel').classList.contains('show'),true,
      '入口已经可见时应立即响应，不能等后续脚本加载完成');
    await settle();
    assert.equal(calls[0]?.path,'/api/dependencies?summary=1');
    assert.deepEqual(posts(calls).map(item=>item.path),['/api/dependencies/check']);
    w.document.dispatchEvent(new w.Event('DOMContentLoaded'));
    await settle();
    assert.equal(posts(calls).length,1,'稍后的DOMContentLoaded不得重复绑定或自动检测');
  }finally{w.DependencyManagerUI?.close();await w.happyDOM.abort();}
});

test('a script loaded before the markup still binds once after DOMContentLoaded',async()=>{
  const w=new Window({url:'http://127.0.0.1:19876',settings:{disableCSSFileLoading:true,disableJavaScriptFileLoading:true}});
  const calls=[];
  try{
    Object.defineProperty(w.document,'readyState',{configurable:true,get:()=> 'loading'});
    w.api=async(path,options)=>{calls.push({path,options});return path==='/api/dependencies?summary=1'?fixture():{ok:true};};
    w.eval(source);
    assert.equal(w.document.getElementById('dependencyManagerPanel'),null);
    // 模拟解析器补齐body；document.write会重建Document并清掉刚注册的监听。
    const parsed=new w.DOMParser().parseFromString(template,'text/html');
    w.document.body.innerHTML=parsed.body.innerHTML;
    w.document.dispatchEvent(new w.Event('DOMContentLoaded'));
    w.document.dispatchEvent(new w.Event('DOMContentLoaded'));
    w.document.getElementById('openDependencyManager').click();
    await settle();
    assert.equal(w.document.getElementById('dependencyManagerPanel').classList.contains('show'),true);
    assert.deepEqual(posts(calls).map(item=>item.path),['/api/dependencies/check']);
  }finally{w.DependencyManagerUI?.close();await w.happyDOM.abort();}
});

test('opening detects all missing files locally without group selection or an update',()=>setup(async({w,calls})=>{
  await w.DependencyManagerUI.open();
  assert.equal(w.document.getElementById('dependencyManagerTitle').textContent,'依赖检测与更新');
  assert.equal(w.document.getElementById('openDependencyManager').textContent,'更新依赖');
  assert.equal(w.document.querySelector('#dependencyManagerPanel input[type=checkbox]'),null);
  assert.deepEqual(posts(calls).map(item=>({path:item.path,body:JSON.parse(item.options.body)})),[{path:'/api/dependencies/check',body:{}}]);
  assert.match(w.document.getElementById('dependencyStatusSummary').textContent,/2.*缺失|缺失.*2/);
  assert.equal(w.document.querySelectorAll('#dependencyMissingFiles li').length,2);
  assert.match(w.document.getElementById('dependencyManagerPanel').textContent,/这里只检测外置组件/);
  assert.match(w.document.getElementById('dependencyManagerPanel').textContent,/源码 Python 运行库按 README 维护/);
}));

test('a status failure keeps rechecking available without allowing an update',()=>setup(async({w,calls,getState})=>{
  w.api=async()=>{throw new Error('合成状态请求失败');};
  await w.DependencyManagerUI.open();
  assert.match(w.document.getElementById('dependencyMessage').textContent,/合成状态请求失败/);
  assert.equal(w.document.getElementById('depUpdateDependencies').disabled,true);
  assert.equal(w.document.getElementById('depCheckDependencies').disabled,false);
  w.api=async(path,options)=>{calls.push({path,options});return path==='/api/dependencies?summary=1'?structuredClone(getState()):{ok:true};};
  w.document.getElementById('depCheckDependencies').click();await settle();
  assert.equal(w.document.getElementById('depUpdateDependencies').disabled,false);
  assert.deepEqual(posts(calls).map(item=>item.path),['/api/dependencies/check']);
}));

test('one explicit confirmation updates the complete package using an empty body',()=>setup(async({w,calls,confirmations})=>{
  await w.DependencyManagerUI.open();
  w.confirm=()=>false;w.document.getElementById('depUpdateDependencies').click();await settle();
  assert.equal(posts(calls).filter(item=>item.path.endsWith('/update')).length,0);
  w.confirm=message=>{confirmations.push(message);return true;};
  w.document.getElementById('depUpdateDependencies').click();await settle();
  const updates=posts(calls).filter(item=>item.path.endsWith('/update'));
  assert.equal(updates.length,1);assert.deepEqual(JSON.parse(updates[0].options.body),{});
  assert.equal(confirmations.length,1);assert.match(confirmations[0],/完整配套依赖包/);
  assert.match(confirmations[0],/先备份再替换/);assert.match(confirmations[0],/单独升级的 yt-dlp/);
  assert.match(confirmations[0],/配置、Cookie 和下载内容会保留/);
  assert.equal(posts(calls).some(item=>item.path.endsWith('/install')),false);
}));

test('rechecking always uses the local check endpoint without update arguments',()=>setup(async({w,calls})=>{
  await w.DependencyManagerUI.open();w.document.getElementById('depCheckDependencies').click();await settle();
  assert.deepEqual(posts(calls).map(item=>({path:item.path,body:JSON.parse(item.options.body)})),[
    {path:'/api/dependencies/check',body:{}},{path:'/api/dependencies/check',body:{}},
  ]);
}));

test('opening during an update only polls and allows explicit cancellation',()=>setup(async({w,calls,setState,timers})=>{
  setState({...fixture(),running:true,action:'install',phase:'downloading',progress:35,download_bytes:1536});
  await w.DependencyManagerUI.open();
  assert.equal(posts(calls).length,0);assert.equal(timers.size,1);
  assert.equal(w.document.getElementById('depCheckDependencies').disabled,true);
  assert.equal(w.document.getElementById('depUpdateDependencies').disabled,true);
  assert.equal(w.document.getElementById('depCancelOperation').hidden,false);
  assert.equal(w.document.getElementById('depCancelOperation').disabled,false);
  assert.equal(w.document.getElementById('dependencyProgressText').textContent,'35%');
  assert.match(w.document.getElementById('dependencyDistributionNote').textContent,/1\.5 KiB/);
  w.document.getElementById('depCancelOperation').click();await settle();
  assert.deepEqual(posts(calls).map(item=>({path:item.path,body:JSON.parse(item.options.body)})),[{path:'/api/dependencies/cancel',body:{}}]);
}));

test('closing stops polling without cancelling and reopening reads fresh state',()=>setup(async({w,calls,setState,timers})=>{
  setState({...fixture(),running:true,action:'install'});await w.DependencyManagerUI.open();assert.equal(timers.size,1);
  w.DependencyManagerUI.close();assert.equal(timers.size,0);assert.equal(posts(calls).length,0);
  setState({...fixture(),missing_count:0,existing_count:5,missing_files:[]});await w.DependencyManagerUI.open();
  assert.equal(w.DependencyManagerUI.isRunning(),false);assert.equal(timers.size,0);
  assert.match(w.document.getElementById('dependencyStatusSummary').textContent,/已齐全/);
  assert.equal(w.document.getElementById('dependencyMissingSection').hidden,true);
  assert.deepEqual(posts(calls).map(item=>item.path),['/api/dependencies/check']);
}));

test('an in-flight check survives closing and reopening without permanently disabling controls',()=>setup(async({w,calls,getState})=>{
  let finish;
  w.api=async(path,options)=>{calls.push({path,options});return path==='/api/dependencies?summary=1'?structuredClone(getState()):new Promise(resolve=>{finish=resolve;});};
  const opening=w.DependencyManagerUI.open();await settle();assert.equal(typeof finish,'function');
  w.DependencyManagerUI.close();await w.DependencyManagerUI.open();
  assert.equal(w.document.getElementById('depUpdateDependencies').disabled,true);
  finish({ok:true});await opening;await settle();
  assert.equal(w.document.getElementById('depUpdateDependencies').disabled,false);
  assert.equal(posts(calls).length,1);
}));

test('missing file paths are bounded and rendered as text while the manual URL stays trusted',()=>setup(async({w,setState})=>{
  setState({...fixture(),file_count:100,existing_count:20,missing_count:80,missing_truncated:true,
    missing_files:['<img src=x onerror=alert(1)>',...Array.from({length:79},(_,index)=>`dependency/file-${index}`)],
    error:'<svg onload=alert(1)>',manual_update_url:'javascript:alert(1)'});
  await w.DependencyManagerUI.open();
  assert.equal(w.document.querySelectorAll('#dependencyMissingFiles li').length,50);
  assert.equal(w.document.querySelector('#dependencyMissingFiles img'),null);
  assert.match(w.document.getElementById('dependencyMissingNote').textContent,/前 50 项／共 80/);
  assert.equal(w.document.getElementById('dependencyMessage').querySelector('svg'),null);
  const link=w.document.getElementById('dependencyManualLink');
  assert.equal(link.href,releaseURL);assert.equal(link.target,'_blank');assert.match(link.rel,/noopener/);
}));

test('recovery never updates automatically and is included in the single update confirmation',()=>setup(async({w,calls,setState,confirmations})=>{
  setState({...fixture(),recovery_required:true});await w.DependencyManagerUI.open();
  assert.equal(w.document.getElementById('dependencyRecoveryNotice').hidden,false);
  assert.equal(w.document.getElementById('depUpdateDependencies').textContent,'更新依赖');
  assert.deepEqual(posts(calls).map(item=>item.path),['/api/dependencies/check']);
  w.document.getElementById('depUpdateDependencies').click();await settle();
  assert.equal(confirmations.length,1);assert.match(confirmations[0],/先恢复/);
  assert.deepEqual(JSON.parse(posts(calls).at(-1).options.body),{});
  assert.equal(posts(calls).at(-1).path,'/api/dependencies/update');
}));

test('unchecked or unreadable files are never described as fully available',()=>setup(async({w,setState})=>{
  setState({...fixture(),missing_count:0,missing_files:[],unchecked_count:2});await w.DependencyManagerUI.open();
  assert.match(w.document.getElementById('dependencyStatusSummary').textContent,/待检测/);
  setState({...fixture(),missing_count:0,missing_files:[],error_count:1});await w.DependencyManagerUI.open();
  assert.match(w.document.getElementById('dependencyStatusSummary').textContent,/检测异常/);
  assert.doesNotMatch(w.document.getElementById('dependencyStatusSummary').textContent,/已齐全/);
}));

test('update errors stay visible and never trigger an automatic update retry',()=>setup(async({w,calls,getState})=>{
  await w.DependencyManagerUI.open();
  w.api=async(path,options)=>{calls.push({path,options});return path==='/api/dependencies?summary=1'?structuredClone(getState()):{error:'合成更新失败',code:'asset_unavailable'};};
  w.document.getElementById('depUpdateDependencies').click();await settle();await settle();
  assert.match(w.document.getElementById('dependencyMessage').textContent,/合成更新失败/);
  assert.equal(posts(calls).filter(item=>item.path.endsWith('/update')).length,1);
  assert.equal(w.document.getElementById('depUpdateDependencies').disabled,false);
}));

test('Escape returns focus and repeated initialization does not duplicate automatic checks',()=>setup(async({w,calls})=>{
  const opener=w.document.getElementById('openDependencyManager');
  w.DependencyManagerUI.init();w.DependencyManagerUI.init();opener.focus();opener.click();await settle();
  assert.equal(posts(calls).length,1);
  w.document.getElementById('dependencyManagerPanel').dispatchEvent(new w.KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
  assert.equal(w.document.getElementById('dependencyManagerPanel').classList.contains('show'),false);
  assert.equal(w.document.activeElement,opener);
}));

test('each successful update refreshes the About status once without polling duplicates',()=>setup(async({w,calls,getState,setState})=>{
  let refreshed=0;w.loadDeps=async()=>{refreshed++;};await w.DependencyManagerUI.open();
  w.api=async(path,options)=>{
    calls.push({path,options});
    if(path==='/api/dependencies/update')setState({...fixture(),action:'install',phase:'completed',message:'更新成功',missing_count:0,existing_count:5,missing_files:[]});
    return path==='/api/dependencies?summary=1'?structuredClone(getState()):{ok:true};
  };
  w.document.getElementById('depUpdateDependencies').click();await settle();assert.equal(refreshed,1);
  await w.DependencyManagerUI.open();await w.DependencyManagerUI.open();assert.equal(refreshed,1);
  w.document.getElementById('depUpdateDependencies').click();await settle();assert.equal(refreshed,2);
}));

test('an About refresh failure cannot turn a successful dependency update into a failure',()=>setup(async({w,calls,getState,setState})=>{
  let refreshed=0;w.loadDeps=async()=>{refreshed++;throw new Error('合成关于页刷新失败');};await w.DependencyManagerUI.open();
  w.api=async(path,options)=>{
    calls.push({path,options});
    if(path==='/api/dependencies/update')setState({...fixture(),action:'install',phase:'completed',message:'依赖更新成功'});
    return path==='/api/dependencies?summary=1'?structuredClone(getState()):{ok:true};
  };
  w.document.getElementById('depUpdateDependencies').click();await settle();
  assert.equal(refreshed,1);
  assert.equal(w.document.getElementById('dependencyMessage').textContent,'依赖更新成功');
  assert.doesNotMatch(w.document.getElementById('dependencyMessage').textContent,/刷新失败/);
  assert.equal(w.document.getElementById('depUpdateDependencies').disabled,false);
}));
