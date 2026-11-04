// 本地缺失检测与完整配套依赖更新；文件和网络操作由后端完成。
(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  let initialized=false,opened=false,pending=false,timer=null,generation=0,inFlightGeneration=null;
  let current={available:false,running:false},statusReady=false,localError='',statusError='',previousFocus=null;
  let updateRequested=false,lastCompletedOperation=null;
  const text=value=>typeof value==='string'?value:value?.message||'依赖操作未完成，请重试或手动下载。';
  const count=name=>Number.isInteger(current[name])&&current[name]>=0?current[name]:null;
  function formatSize(value){
    const units=['B','KiB','MiB','GiB'];let index=0;
    while(value>=1024&&index<units.length-1){value/=1024;index++;}
    return (index?value.toFixed(1):String(value))+' '+units[index];
  }
  function clearPoll(){if(timer!==null){window.clearTimeout(timer);timer=null;}}
  function schedulePoll(){clearPoll();if(opened&&current.running)timer=window.setTimeout(()=>{timer=null;refresh();},750);}
  async function request(path,payload){
    if(typeof window.api!=='function')throw new Error('页面尚未准备好，请稍后重试。');
    return window.api(path,payload===undefined?undefined:{method:'POST',body:JSON.stringify(payload)});
  }
  function refreshAboutOnCompletion(data){
    const completed=data.action==='install'&&!data.running&&data.phase==='completed'&&!data.error;
    if(!completed){
      if(data.action==='install'&&!data.running&&['failed','cancelled'].includes(data.phase))updateRequested=false;
      return;
    }
    const operation=data.operation_id||null;
    if(!updateRequested&&!(current.running&&current.action==='install')&&!(operation&&operation!==lastCompletedOperation))return;
    updateRequested=false;lastCompletedOperation=operation;
    // 关于页状态是观察者；刷新失败不能改写已完成的更新结果。
    if(typeof window.loadDeps==='function')Promise.resolve().then(()=>window.loadDeps()).catch(()=>{});
  }
  function render(){
    if(!$('dependencyManagerPanel'))return;
    const blocked=pending||!!current.running||!statusReady||current.available===false;
    $('depCheckDependencies').disabled=pending||!!current.running;$('depUpdateDependencies').disabled=blocked;
    $('depCancelOperation').hidden=!current.running;$('depCancelOperation').disabled=pending||!current.running||!!current.cancel_requested;
    $('dependencyCatalogVersion').textContent=current.catalog_version?'配套依赖 v'+current.catalog_version:'配套依赖信息尚未就绪';
    const error=localError||statusError||current.error;
    $('dependencyMessage').textContent=error?text(error):(current.message||'点击「重新检测」检查依赖是否缺失。');
    $('dependencyMessage').className=error?'txt-err':'';
    $('dependencyMessage').setAttribute('aria-live',error?'assertive':'polite');
    const total=count('file_count'),existing=count('existing_count'),missing=count('missing_count'),errors=count('error_count'),unchecked=count('unchecked_count');
    const known=[total,existing,missing,errors,unchecked].every(value=>value!==null);
    let summary='尚未完成缺失检测',summaryClass='dependency-summary';
    if(known&&total>0){
      if(errors){summary=`有 ${errors} 个文件检测异常，暂不能确认依赖是否齐全`;summaryClass+=' txt-err';}
      else if(unchecked)summary=`尚有 ${unchecked} 个依赖文件待检测`;
      else if(missing){summary=`检测到 ${missing} 个依赖文件缺失`;summaryClass+=' txt-err';}
      else summary='配套外置依赖文件已齐全';
    }
    $('dependencyStatusSummary').textContent=summary;$('dependencyStatusSummary').className=summaryClass;
    $('dependencyCounts').textContent=known?`共 ${total} 项 · 已存在 ${existing} 项 · 缺失 ${missing} 项`+(errors?` · 异常 ${errors} 项`:'')+(unchecked?` · 待检测 ${unchecked} 项`:''):'';
    const files=Array.isArray(current.missing_files)?current.missing_files.slice(0,50).filter(file=>typeof file==='string'):[];
    const items=files.map(file=>{const item=document.createElement('li');item.textContent=file;return item;});
    $('dependencyMissingFiles').replaceChildren(...items);
    $('dependencyMissingSection').hidden=!(missing>0||files.length);
    $('dependencyMissingNote').textContent=!files.length?'缺失文件路径暂不可用，请重新检测。':current.missing_truncated||missing>files.length?`显示前 ${files.length} 项／共 ${missing??files.length} 项；更新会处理完整配套依赖。`:'';
    $('dependencyRecoveryNotice').hidden=!current.recovery_required;
    $('dependencyRecoveryNotice').textContent=current.recovery_required?'发现未完成的依赖更新。请点击「更新依赖」，先恢复备份再继续；恢复前暂不能启动新任务。':'';
    $('dependencyProgress').hidden=!current.running;
    const progress=$('dependencyProgressBar');
    if(typeof current.progress==='number'&&Number.isFinite(current.progress)){
      const value=Math.max(0,Math.min(100,current.progress));progress.value=value;$('dependencyProgressText').textContent=Math.round(value)+'%';
    }else{progress.removeAttribute('value');$('dependencyProgressText').textContent='进行中';}
    const size=current.download_bytes;
    $('dependencyDistributionNote').textContent='更新时下载当前版本的完整配套依赖包。'+(typeof size==='number'&&Number.isFinite(size)&&size>=0?' 本次下载量：'+formatSize(size)+'。':' 下载量在获取发布包信息后显示。');
  }
  async function refresh(){
    const currentGeneration=generation;
    if(inFlightGeneration===currentGeneration)return false;
    inFlightGeneration=currentGeneration;
    try{
      const data=await request('/api/dependencies?summary=1');
      if(currentGeneration!==generation)return false;
      if(!data||typeof data!=='object'||typeof data.available!=='boolean')throw new Error(data?.error||'无法读取依赖状态，请重试。');
      refreshAboutOnCompletion(data);current=data;statusReady=true;statusError='';render();schedulePoll();return true;
    }catch(error){
      if(currentGeneration!==generation)return false;
      statusReady=false;statusError=text(error);render();schedulePoll();return false;
    }finally{if(inFlightGeneration===currentGeneration)inFlightGeneration=null;}
  }
  async function runAction(action){
    if(pending)return;
    if(action!=='cancel'&&(!statusReady||current.running||current.available===false))return;
    if(action==='update'){
      const recovery=current.recovery_required?'先恢复未完成更新的备份，再继续更新。\n':'';
      if(!window.confirm(recovery+'将下载当前版本的完整配套依赖包，需要更新的组件会先备份再替换。\n单独升级的 yt-dlp、配置、Cookie 和下载内容会保留。\n确认更新依赖？'))return;
    }
    const actionGeneration=generation;
    if(action==='update')updateRequested=true;
    pending=true;localError='';clearPoll();render();
    try{
      const result=await request('/api/dependencies/'+action,{});
      if(action==='update'&&result?.error)updateRequested=false;
      if(actionGeneration!==generation)return;
      if(result?.error)localError=text(result.error);
    }catch(error){if(action==='update')updateRequested=false;if(actionGeneration===generation)localError=text(error);}
    finally{
      try{if(opened)await refresh();}
      finally{pending=false;if(opened){render();schedulePoll();}}
    }
  }
  function init(){
    if(initialized||!$('dependencyManagerPanel'))return;
    initialized=true;
    $('openDependencyManager')?.addEventListener('click',open);
    $('depCloseManager').addEventListener('click',close);
    $('depCheckDependencies').addEventListener('click',async()=>{
      localError='';if(!statusReady||current.available===false)await refresh();await runAction('check');
    });
    $('depUpdateDependencies').addEventListener('click',()=>runAction('update'));
    $('depCancelOperation').addEventListener('click',()=>runAction('cancel'));
    $('dependencyManagerPanel').addEventListener('click',event=>{if(event.target===$('dependencyManagerPanel'))close();});
    $('dependencyManagerPanel').addEventListener('keydown',event=>{
      if(event.key==='Escape'){event.preventDefault();close();return;}
      if(event.key!=='Tab')return;
      const focusable=[...$('dependencyManagerPanel').querySelectorAll('button:not(:disabled),a[href]')].filter(element=>!element.hidden);
      const first=focusable[0],last=focusable[focusable.length-1];
      if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}
      else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
    });
  }
  async function open(){
    init();if(!$('dependencyManagerPanel'))return;
    if(opened){await refresh();return;}
    clearPoll();generation++;const openGeneration=generation;
    opened=true;statusReady=false;localError='';statusError='';previousFocus=document.activeElement;
    $('dependencyManagerPanel').classList.add('show');render();$('depCloseManager').focus();
    if(await refresh()&&opened&&openGeneration===generation&&!current.running&&!pending&&current.available)await runAction('check');
  }
  function close(){
    clearPoll();generation++;opened=false;$('dependencyManagerPanel')?.classList.remove('show');
    if(previousFocus?.isConnected)previousFocus.focus({preventScroll:true});
  }
  window.DependencyManagerUI={init,open,close,isRunning:()=>!!current.running};
  // 脚本位于body末尾；入口已存在时立即绑定，不等待后续资源结束。
  init();
  if(!initialized&&document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});
})();
