/* FANBOX view adapter. All content is rendered as text; no source HTML executes. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const jobs = new Map(), drafts = new Map();
  const baseTitle=document.title;
  let options = null, defaults = null, selectedJob = '', offset = 0, total = 0, requestVersion = 0;
  let starting = false, retryRequest = null, searchTimer = null;
  let taskDraft=null,taskUrl='',historyMode=false,consoleMode=null,replayingLogs=false;
  let resumeJob='',resumeVersion=0;
  let recordBatches=null,recordEpoch=0,recordBusy=false;
  const consoleEntries=[],logKeys=new Set(),notified=new Set();
  const statusNames = {queued:'排队中',running:'进行中',preview_ready:'待选择',completed:'已完成',
    partial:'部分完成',failed:'失败',paused:'已暂停',reused:'已复用',degraded:'缩略图',skipped:'已跳过',pending:'待下载',excluded:'按规则排除',
    cancelled:'已停止',interrupted:'已中断',stale:'需重新校验',ok:'通过',missing:'缺失',modified:'内容变化',unreadable:'无法读取',unverified:'缺少校验数据',busy:'使用中'};
  const phases = {scanning:'抓取帖子',downloading:'下载文件',preview:'待选择',finished:'已结束',paused:'已暂停',queued:'排队中'};
  const element = (tag,text,attrs={}) => Object.assign(document.createElement(tag),attrs,text==null?{}:{textContent:text});
  const button = (text,action,key) => {
    const b=element('button',text,{className:'btn sm',type:'button'});
    b.onclick=action;if(key)b.dataset.fbFocus=key;return b;
  };
  const fmt = value => value==null?'未知':value<1024?value+' B':value<1048576?(value/1024).toFixed(1)+' KiB':(value/1048576).toFixed(1)+' MiB';
  function matches(value) {try {const h=new URL(value).hostname.toLowerCase();return h==='fanbox.cc'||h.endsWith('.fanbox.cc');}catch(e){return false;}}
  function draft() {
    if(!drafts.has(selectedJob))drafts.set(selectedJob,{excluded:new Set(),included:new Set(),assets:new Set(),all:true});
    return drafts.get(selectedJob);
  }
  function get(path,model=options) {return path.split('.').reduce((value,key)=>value?.[key],model);}
  function set(path,value,model=options) {const parts=path.split('.');let node=model;parts.slice(0,-1).forEach(key=>node=node[key]);node[parts.at(-1)]=value;if(model===options)sync();}
  const groups = [
    ['保存内容',[
      ['workflow.scope','抓取范围',{source:'当前链接',supporting:'所有赞助',following:'所有关注'}],
      ['workflow.auto_download','抓取后自动下载','bool'],['content.body','帖子正文','bool'],
      ['content.body_formats','正文格式',['html','txt','md']],['content.raw_snapshot','原始 JSON','bool'],
      ['content.cover','封面','bool'],['content.links','链接清单','bool'],['content.comments','评论','bool'],
      ['content.comment_max_pages','评论页数上限','number'],['content.image_quality','图片质量',{original:'原图',thumbnail:'缩略图'}],
      ['content.image_fallback','原图不可用时',{ask:'询问',never:'仅原图',allow:'允许缩略图'}]
    ]],
    ['筛选',[
      ['filters.include_free','免费帖子','bool'],['filters.include_paid','付费帖子','bool'],['filters.max_posts','最多帖子数','nullable'],
      ['filters.fee.enabled','按金额筛选','bool'],['filters.fee.op','金额比较',{'>=':'不低于','=':'等于','<=':'不高于'}],['filters.fee.value','金额（日元）','number'],
      ['filters.fee.minimum','最低赞助金额（日元）','nullable'],['filters.fee.maximum','最高赞助金额（日元）','nullable'],
      ['filters.post_id.enabled','按投稿 ID 筛选','bool'],['filters.post_id.op','ID 比较',{'>':'大于','<':'小于'}],['filters.post_id.value','投稿 ID','text'],
      ['filters.published.enabled','按日期筛选','bool'],['filters.published.start','起始日期','date'],['filters.published.end','截止日期','date'],
      ...['image','audio','video','archive','source','other'].map((type,i)=>['filters.resource_types.'+type,['图片','音频','视频','压缩包','源文件','其他附件'][i],'bool']),
      ...[['title','标题'],['attachment_name','附件原名']].flatMap(([kind,label])=>[
        [`filters.${kind}.include_enabled`,label+'包含筛选','bool'],[`filters.${kind}.include`,label+'包含（每行一项）','list'],
        [`filters.${kind}.exclude_enabled`,label+'排除筛选','bool'],[`filters.${kind}.exclude`,label+'排除（每行一项）','list']])
    ]],
    ['目录与命名',[
      ['naming.post_dir','帖子目录','text'],['naming.images','图片命名','text'],['naming.attachments','附件命名','text'],
      ['naming.layout','目录方式',{post_directory:'按帖子归档',legacy_full:'完整路径模板'}],['naming.date_format','日期格式','text'],
      ['naming.timezone','日期时区','text'],
      ['naming.favorites','命名收藏（每行一项）','list'],
      ['naming.zero_pad','序号补零','bool'],['naming.pad_width','序号位数','number'],
      ['naming.conflict','同名文件',{uniquify:'添加序号',overwrite:'覆盖',prompt:'询问',skip:'跳过'}]
    ]],
    ['运行策略',[
      ['network.file_concurrency','文件并发','number'],['network.api_interval_seconds','API 间隔（秒）','number'],
      ['network.file_start_interval_seconds','文件启动间隔（秒）','number'],['network.proxy_policy','代理',{inherit:'沿用全局设置',direct:'直连'}],
      ['archive.incremental','复用已验证文件','bool'],['quota.enabled','每日额度','bool'],['quota.limit_gib','额度（GiB）','number'],
      ['quota.timezone','计量时区','text'],['quota.on_limit','额度用尽时',{wait_manual:'暂停',next_day:'次日继续'}]
      ,['notifications.on_complete','完成通知','bool'],['ui.bold_keywords','匹配标题高亮','bool']
    ]],
    ['粉丝卡',[
      ['fan_cards.enabled','下载粉丝卡','bool'],['fan_cards.only','仅下载粉丝卡','bool'],
      ['fan_cards.scope','粉丝卡范围',{current:'当前作者',all_supporting:'所有赞助作者'}],
      ['fan_cards.show_username','在粉丝卡显示我的用户名','bool']
    ]]
  ];
  const occasional=path=>path.startsWith('filters.')||path.startsWith('fan_cards.')||
    ['workflow.scope','workflow.auto_download','content.comments','content.comment_max_pages','content.image_fallback','naming.conflict'].includes(path);
  const resumePaths=new Set(['content.image_fallback','naming.conflict','quota.enabled','quota.limit_gib','quota.timezone','quota.on_limit']);
  function renderSettings(host=$('fanboxSettingsFields'),model=options,allowed=null) {
    if(!model)return;
    const opened=new Set([...host.querySelectorAll('details[open][data-fb-fold]')].map(el=>el.dataset.fbFold));
    const settingsActions=host.id==='fanboxSettingsFields'?$('fanboxSettingsActions'):null;
    host.replaceChildren();let folded,regular=host;
    if(!allowed){folded=element('details',null,{className:'fb-settings-fold'});folded.dataset.fbFold='occasional';
      folded.open=opened.has('occasional')||host.id==='fanboxTaskFields';folded.append(element('summary','单次下载选项'));
      if(host.id==='fanboxTaskFields'){regular=element('details',null,{className:'fb-settings-fold'});regular.dataset.fbFold='defaults';
        regular.open=opened.has('defaults');regular.append(element('summary','其他下载设置'));}}
    function group(title,fields,target){
      if(!fields.length)return;
      const group=element('section',null,{className:'fb-settings-group'});
      group.append(element('h4',title));const grid=element('div',null,{className:'fb-settings-list'});
      fields.forEach(([path,label,type])=>{
        const row=element(Array.isArray(type)?'div':'label',null,{className:'fb-field'});row.append(element('span',label));let input;
        if(Array.isArray(type)) {
          const choices=element('span',null,{className:'fb-choices'});
          row.setAttribute('role','group');row.setAttribute('aria-label',label);
          type.forEach(value=>{const item=element('label'),check=element('input',null,{type:'checkbox',className:'fb-tick',checked:(get(path,model)||[]).includes(value),value});
            check.dataset.fanboxOption=path;check.onchange=()=>set(path,Array.from(choices.querySelectorAll('input:checked')).map(v=>v.value),model);
            item.append(check,document.createTextNode(value.toUpperCase()));choices.append(item);});
          row.append(choices);grid.append(row);return;
        } else if(typeof type==='object') {
          input=element('select',null,{className:'ctl'});
          Object.entries(type).forEach(([key,text])=>input.append(element('option',text,{value:key})));
          input.value=get(path,model);
        } else {
          input=element(type==='list'?'textarea':'input',null,{className:'ctl'});
          if(type==='bool'){input.type='checkbox';input.className='fb-switch';input.checked=!!get(path,model);}
          else {if(input.tagName==='INPUT'){input.type=type==='date'?'datetime-local':(['number','nullable'].includes(type)?'number':'text');input.step='any';}
            let value=get(path,model);if(type==='list')value=(value||[]).join('\n');
            if(type==='date'&&value){const d=new Date(value);value=new Date(d-d.getTimezoneOffset()*60000).toISOString().slice(0,16);}
            input.value=value??'';}
        }
        input.dataset.fanboxOption=path;
        input.addEventListener('change',()=>{
          let value=input.value;
          if(type==='bool')value=input.checked;
          else if(type==='number'||type==='nullable')value=type==='nullable'&&value===''?null:Number(value);
          else if(type==='list')value=value.split(/\r?\n/).map(v=>v.trim()).filter(Boolean);
          else if(type==='date')value=value?new Date(value).toISOString():null;
          else if(Array.isArray(type))value=Array.from(input.selectedOptions).map(o=>o.value);
          set(path,value,model);
          if(path==='naming.favorites')renderSettings(host,model);
          if(model===taskDraft&&path==='workflow.auto_download')$('fanboxTaskConfirm').textContent=value?'确认下载':'确认预览';
          if(path==='notifications.on_complete'&&value&&'Notification' in window&&Notification.permission==='default')Notification.requestPermission();
        });row.append(input);grid.append(row);
      });group.append(grid);target.append(group);
    }
    groups.forEach(([title,fields])=>{
      if(allowed)group(title,fields.filter(([path])=>allowed.has(path)),host);
      else {group(title,fields.filter(([path])=>!occasional(path)),regular);group(title,fields.filter(([path])=>occasional(path)),folded);}
    });
    if(allowed)return;
    const row=element('label',null,{className:'fb-field'}),select=element('select',null,{className:'ctl'});
    row.append(element('span','应用图片命名收藏'));select.append(element('option','选择收藏',{value:''}));
    (model.naming.favorites||[]).forEach(value=>select.append(element('option',value,{value})));
    select.onchange=()=>{if(select.value){set('naming.images',select.value,model);host.querySelector('[data-fanbox-option="naming.images"]').value=select.value;}};
    row.append(select);regular.append(row);
    const preview=element('pre',null,{className:'fb-name-preview',hidden:true});
    const previewButton=button('命名预览',async()=>{try{
      const url=$('urlInput').value.trim().split(/\s+/)[0];
      const result=await api('/api/fanbox/naming-preview',{method:'POST',body:JSON.stringify({options:model,...(url&&matches(url)?{url}:{})})});
      preview.textContent=[result.directory,...result.files].join('\n');preview.hidden=false;
    }catch(e){showToast(e.message,'error');}});
    if(settingsActions){
      const utilities=[...settingsActions.querySelectorAll('#fanboxUsage, #fanboxRecords')];
      settingsActions.replaceChildren(previewButton,...utilities);regular.append(settingsActions,preview);
    }else regular.append(previewButton,preview);
    if(folded)host.append(folded);
    if(regular!==host)host.append(regular);
  }
  function applyConfig(config) {
    $('fanboxEnabled').checked=String(config.FANBOX_ENABLED??1)==='1';
    $('fanboxAnonymous').checked=String(config.FANBOX_ANONYMOUS??0)==='1';
    $('fanboxCookieFile').value=config.FANBOX_COOKIE_FILE||'';
    if(options){const saved=JSON.parse(config.FANBOX_OPTIONS||'{}');options=structuredClone(defaults);merge(options,saved);renderSettings();}
    sync();
  }
  function merge(target,source) {Object.entries(source).forEach(([key,value])=>{
    if(value&&typeof value==='object'&&!Array.isArray(value)&&target[key])merge(target[key],value);else target[key]=value;
  });}
  function configValues() {return options?{FANBOX_OPTIONS:JSON.stringify(options),FANBOX_ENABLED:$('fanboxEnabled').checked?1:0,
    FANBOX_ANONYMOUS:$('fanboxAnonymous').checked?1:0,FANBOX_COOKIE_FILE:$('fanboxCookieFile').value.trim()}:{};}
  function sync() {
    const urls=$('urlInput').value.trim().split(/\s+/).filter(Boolean);
    const pure=urls.length?urls.every(matches):currentPlatform==='Fanbox';
    $('fanboxPreview').hidden=!pure;
    $('fanboxJobsPanel').hidden=!pure||!jobs.size;
    $('btnCopyCommand').style.display=pure?'none':'';
    document.querySelector('.task-args-row').style.display=pure?'none':'';
    if(pure)$('btnStartLabel').textContent='抓取并下载';
    if(consoleMode!==pure){consoleMode=pure;renderConsole();}
    updateTitle();
  }
  function updateTitle(){const active=[...jobs.values()].filter(job=>['running','queued'].includes(job.status));
    document.title=consoleMode&&active.length?`FANBOX · ${active.length} 个任务 · ${baseTitle}`:baseTitle;}
  function accept(job) {
    if(!job?.id||Number(jobs.get(job.id)?.version||0)>Number(job.version||0))return;
    const previous=jobs.get(job.id);
    if(previous?.version===job.version&&(previous.verification?.version||0)>(job.verification?.version||0))return;
    jobs.set(job.id,job);renderJobs();
    updateTitle();
    if(previous&&previous.status!==job.status&&job.status==='completed'&&job.notify&&!notified.has(job.id)) {
      notified.add(job.id);showToast('FANBOX 下载完成','success');
      if('Notification' in window&&Notification.permission==='granted')new Notification('FANBOX 下载完成',{body:job.source});
    }
    if(selectedJob===job.id&&previous?.status!==job.status&&job.status!=='running')loadDetail();
    else if(selectedJob===job.id){
      renderVerification(job.verification);
      if(previous?.verification?.status!==job.verification?.status&&job.verification?.status!=='running')loadDetail();
    }
  }
  async function loadJobs() {try {const data=await api('/api/fanbox/jobs');(data.jobs||[]).forEach(accept);if(data.error)showToast(data.error,'error');}catch(e){showToast(e.message,'error');}}
  function renderJobs() {
    const host=$('fanboxJobs'),focus=document.activeElement?.dataset.fbFocus;
    $('fanboxJobsPanel').hidden=!jobs.size||!consoleMode;host.replaceChildren();
    Array.from(jobs.values()).sort((a,b)=>b.created_at-a.created_at).slice(0,30).forEach(job=>{
      const row=element('article',null,{className:'fb-job'}),counts=job.counts||{},checking=job.verification?.status==='running';
      row.append(element('div',job.source,{className:'fb-job-title'}));
      row.append(element('div',`${statusNames[job.status]||job.status} · ${phases[job.phase]||''} · 帖子 ${counts.posts||0} · 文件 ${(counts.completed||0)+(counts.reused||0)} · 失败 ${(counts.failed||0)+(counts.fan_cards_failed||0)} · 粉丝卡 ${counts.fan_cards||0} · 链接 ${counts.links||0} · ${fmt(counts.bytes_received||0)}`,{className:'fb-metrics'}));
      if(job.error)row.append(element('div',job.error.message,{className:'fb-error'}));
      const actions=element('div',null,{className:'fb-actions'});
      actions.append(button('详情',()=>{historyMode=false;$('fanboxRuns').replaceChildren();openDetail(job.id);},job.id+'-detail'));
      if(['queued','running'].includes(job.status))actions.append(button('暂停',()=>action(job.id,'pause'),job.id+'-pause'));
      else if(job.status==='preview_ready')actions.append(button('选择帖子',()=>openDetail(job.id),job.id+'-select'));
      else if(['paused','partial','failed'].includes(job.status)&&!checking)actions.append(button('继续',()=>resume(job.id),job.id+'-continue'));
      if((counts.failed||0)+(counts.degraded||0)>0&&!checking&&!['running','queued'].includes(job.status))actions.append(button('重试失败文件',()=>action(job.id,'retry_failed'),job.id+'-retry'));
      if(job.output)actions.append(button('打开归档',()=>action(job.id,'open'),job.id+'-open'));
      if(!['running','queued'].includes(job.status)){
        if(checking||(counts.completed||0)+(counts.reused||0)+(counts.degraded||0)>0)actions.append(button(checking?'停止校验':'校验资源文件',()=>action(job.id,checking?'cancel_verification':'verify'),job.id+'-verify'));
        if(!checking)actions.append(button('清空恢复缓存',()=>{if(confirm('清空这个任务的恢复缓存？'))action(job.id,'clear_cache');},job.id+'-cache'));
      }
      if(job.verification)row.append(element('div',`资源校验 · ${statusNames[job.verification.status]||job.verification.status} · ${job.verification.checked}/${job.verification.total}`,{className:'fb-metrics'}));
      row.append(actions);host.append(row);
    });
    if(focus)host.querySelector(`[data-fb-focus="${CSS.escape(focus)}"]`)?.focus({preventScroll:true});
  }
  async function enqueue(url,preview,settings) {
    if(starting)return;starting=true;$('fanboxPreview').disabled=true;
    try {
      await saveSettingsNoAlert();
      const urls=[...new Set(url.split(/\s+/).filter(Boolean))];
      if(!urls.length||!urls.every(matches))throw new Error('请输入 FANBOX 主页或帖子链接');
      if(!retryRequest||retryRequest.url!==url||retryRequest.preview!==preview||JSON.stringify(retryRequest.options)!==JSON.stringify(settings))retryRequest={url,preview,options:structuredClone(settings),request_id:crypto.randomUUID()};
      let last;
      for(const [index,source] of urls.entries()){
        const result=await api('/api/fanbox/create',{method:'POST',body:JSON.stringify({...retryRequest,url:source,request_id:retryRequest.request_id+'-'+index})});
        accept(result.job);last=result.job.id;
      }
      retryRequest=null;if(preview){historyMode=false;$('fanboxRuns').replaceChildren();openDetail(last);}loadTasks();
      return true;
    }catch(e){showToast(e.message,'error');loadJobs();}
    finally{starting=false;$('fanboxPreview').disabled=false;}
  }
  function start(url,preview=null) {
    if(!options){showToast('设置尚未加载','error');return;}
    if(preview===true)return enqueue(url,true,options);
    if($('fanboxTaskDialog').open)return;
    resumeJob='';taskDraft=structuredClone(options);taskUrl=url;$('fanboxTaskTitle').textContent='本次 FANBOX 下载';
    $('fanboxTaskConfirm').textContent=taskDraft.workflow.auto_download?'确认下载':'确认预览';
    renderSettings($('fanboxTaskFields'),taskDraft);$('fanboxTaskDialog').showModal();
  }
  async function resume(id) {
    try{const data=await api('/api/fanbox/job?id='+encodeURIComponent(id));
      resumeJob=id;resumeVersion=data.job.version;taskDraft=structuredClone(data.options);
      $('fanboxTaskTitle').textContent='继续 FANBOX 任务';$('fanboxTaskConfirm').textContent='确认继续';
      renderSettings($('fanboxTaskFields'),taskDraft,resumePaths);$('fanboxTaskDialog').showModal();
    }catch(e){showToast(e.message,'error');}
  }
  async function action(id,name,selection,policies=null,version=null) {
    let success=false;
    try {
      const result=await api('/api/fanbox/action',{method:'POST',body:JSON.stringify({id,action:name,version:version??jobs.get(id)?.version,
        ...(selection?{selection}:{}),...(policies?{options:policies}:{})})});
      if(result.job)accept(result.job);loadTasks();success=true;
      if(result.cache)showToast(`已清理 ${result.cache.removed} 个缓存文件 · 使用中 ${result.cache.busy}`,'success');
    }catch(e){showToast(e.message,'error');}
    await loadJobs();if(selectedJob===id)loadDetail();return success;
  }
  async function openDetail(id) {
    if(!historyMode)$('fanboxHistoryTitle').textContent='FANBOX 下载详情';
    selectedJob=id;offset=0;$('fanboxSearch').value='';draft();$('fanboxDetail').hidden=false;
    if(!$('fanboxHistoryDialog').open)$('fanboxHistoryDialog').showModal();
    try{const records=await api('/api/fanbox/logs?id='+encodeURIComponent(id));records.logs.forEach(acceptLog);}catch(e){showToast(e.message,'error');}
    await loadDetail();
  }
  async function resultData(){return api('/api/fanbox/manifest?id='+encodeURIComponent(selectedJob));}
  async function copyLinks(){try{
    const data=await resultData(),links=[...new Set(data.posts.flatMap(post=>post.links.map(link=>link.url)))];
    await navigator.clipboard.writeText(links.join('\n'));showToast(`已复制 ${links.length} 个链接`,'success');
  }catch(e){showToast(e.message,'error');}}
  async function exportManifest(){try{
    downloadJson(await resultData(),'fanbox-'+selectedJob+'.json');
  }catch(e){showToast(e.message,'error');}}

  function downloadJson(data,name){const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));
    element('a',null,{href:url,download:name}).click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  async function recordCounts(){const data=await api('/api/fanbox/records');
    $('fanboxRecordCounts').textContent=`URL 记录 ${data.urls} · 导入 ${data.imported} · 已校验文件 ${data.verified}`;}
  async function importRecordFile(event){try{
    if(recordBusy)return;const epoch=++recordEpoch;
    recordBatches=null;$('fanboxRecordConfirm').hidden=true;
    const file=event.target.files[0];if(!file)return;if(file.size>16*1024*1024)throw new Error('记录文件超过 16 MiB');
    const records=JSON.parse(await file.text());if(!Array.isArray(records)||records.length>100000)throw new Error('记录文件必须是最多 100000 项的数组');
    const batches=[];let batch=[],bytes=0;
    records.forEach(record=>{const size=new TextEncoder().encode(JSON.stringify(record)).length;
      if(size>16000)throw new Error('单条记录过大');
      if(batch.length&&(bytes+size>58000||batch.length>=500)){batches.push(batch);batch=[];bytes=0;}
      batch.push(record);bytes+=size+1;});if(batch.length)batches.push(batch);
    const total={accepted:0,rejected:0,duplicates:0};
    for(const rows of batches){const report=await api('/api/fanbox/records',{method:'POST',body:JSON.stringify({action:'preview',records:rows})});
      if(epoch!==recordEpoch)return;
      Object.keys(total).forEach(key=>total[key]+=report[key]);}
    recordBatches=batches;$('fanboxRecordReport').textContent=`有效 ${total.accepted} · 重复 ${total.duplicates} · 拒绝 ${total.rejected}`;
    $('fanboxRecordConfirm').hidden=!total.accepted;
  }catch(e){showToast(e.message,'error');}finally{event.target.value='';}}
  async function confirmRecords(){if(recordBusy)return;recordBusy=true;const epoch=recordEpoch,button=$('fanboxRecordConfirm');
    const controls=['fanboxRecordConfirm','fanboxRecordImport','fanboxRecordClear'];controls.forEach(id=>$(id).disabled=true);
    try{let inserted=0;for(const rows of recordBatches||[]){if(epoch!==recordEpoch)break;
        const report=await api('/api/fanbox/records',{method:'POST',body:JSON.stringify({action:'import',records:rows})});inserted+=report.inserted;}
      if(epoch===recordEpoch){recordBatches=null;button.hidden=true;$('fanboxRecordReport').textContent=`已导入 ${inserted} 条`;await recordCounts();}
    }catch(e){showToast(e.message,'error');}finally{recordBusy=false;controls.forEach(id=>$(id).disabled=false);}}
  async function showUsage(){try{const data=await api('/api/fanbox/usage'),host=$('fanboxRuns');host.replaceChildren();
    $('fanboxHistoryTitle').textContent='FANBOX 下载流量 · '+data.timezone;$('fanboxDetail').hidden=true;
    const today=data.days.at(-1)||{},received=data.days.reduce((sum,day)=>sum+day.bytes,0),completed=data.days.reduce((sum,day)=>sum+day.completed_bytes,0);
    host.append(element('p',`今日接收 ${fmt(today.bytes||0)} · 今日完成 ${fmt(today.completed_bytes||0)} · 30 日接收 ${fmt(received)} · 已记录完成 ${fmt(completed)}`));
    const chart=element('div',null,{className:'fb-usage-bars',role:'img'});chart.setAttribute('aria-label','近 30 日接收流量');
    const max=Math.max(1,...data.days.map(day=>day.bytes));data.days.forEach(day=>{const bar=element('span',null,{title:day.date+' · '+fmt(day.bytes)});bar.style.height=Math.max(2,day.bytes/max*100)+'%';chart.append(bar);});host.append(chart);
    const table=element('table',null,{className:'fb-usage-table'}),head=element('tr');['日期','接收流量','完成体积'].forEach(text=>head.append(element('th',text)));table.append(head);
    [...data.days].reverse().forEach(day=>{const row=element('tr');[day.date,fmt(day.bytes),fmt(day.completed_bytes)].forEach(text=>row.append(element('td',text)));table.append(row);});host.append(table);
    $('fanboxHistoryDialog').showModal();}catch(e){showToast(e.message,'error');}}
  function renderVerification(report){$('fanboxVerification').hidden=!report;
    if(!report)return;
    $('fanboxVerificationStatus').textContent=`资源校验 · ${statusNames[report.status]||report.status} · ${report.checked}/${report.total} · 通过 ${report.ok} · 缺失 ${report.missing} · 变化 ${report.modified} · 无法读取 ${report.unreadable} · 无校验数据 ${report.unverified} · 使用中 ${report.busy} · 已读取 ${fmt(report.bytes_read)}`;
    const issues=$('fanboxVerificationIssues');
    if(report.status==='running')issues.replaceChildren();
    if(report.issues){issues.replaceChildren();report.issues.forEach(issue=>issues.append(element('p',`${statusNames[issue.status]||issue.status} · ${issue.path}`)));}
    $('fanboxVerify').textContent=report.status==='running'?'停止校验':'校验资源文件';
  }
  async function loadDetail() {
    if(!selectedJob)return;
    const id=selectedJob,version=++requestVersion,q=$('fanboxSearch').value;
    try {
      const data=await api(`/api/fanbox/job?id=${encodeURIComponent(id)}&offset=${offset}&q=${encodeURIComponent(q)}`);
      if(version!==requestVersion||id!==selectedJob)return;
      accept(data.job);total=data.total;$('fanboxDetailTitle').textContent=historyMode?'已归档内容':'帖子预览';
      $('fanboxSelectAll').checked=draft().all;
      const counts=data.job.counts||{};
      $('fanboxScope').textContent=`${total} 帖 · 文件 ${(counts.completed||0)+(counts.reused||0)} · 失败 ${(counts.failed||0)+(counts.fan_cards_failed||0)} · 粉丝卡 ${counts.fan_cards||0} · ${data.job.scope?.limit_reached?'已达帖子上限':data.job.scope?.list_complete?'列表完整':'列表未完整'}`;
      const reasons={fee_type:'免费/付费',fee_range:'赞助金额',post_id:'投稿 ID',published_at:'日期',keyword_excluded:'排除关键词',keyword_required:'包含关键词'};
      Object.entries(data.job.scope?.filtered||{}).forEach(([key,count])=>$('fanboxScope').append(document.createTextNode(` · ${reasons[key]||'筛选'}排除 ${count}`)));
      $('fanboxOpenArchive').hidden=!data.job.output;
      renderVerification(data.verification);
      $('fanboxVerify').hidden=!(data.verification||(counts.completed||0)+(counts.reused||0)+(counts.degraded||0));
      $('fanboxVerify').disabled=['running','queued'].includes(data.job.status);
      $('fanboxPage').textContent=`${Math.floor(offset/25)+1} / ${Math.max(1,Math.ceil(total/25))}`;
      $('fanboxPrevious').disabled=offset===0;$('fanboxNext').disabled=offset+25>=total;
      $('fanboxDownloadSelected').disabled=['queued','running'].includes(data.job.status)||data.verification?.status==='running'||(!total&&!data.options.fan_cards.enabled);
      $('fanboxDownloadSelected').textContent=!total&&data.options.fan_cards.enabled?'下载粉丝卡':'下载所选';
      $('fanboxDownloadSelected').hidden=historyMode;$('fanboxSelectAll').parentElement.hidden=historyMode;
      const host=$('fanboxPosts');host.replaceChildren();
      data.posts.forEach(post=>{
        const row=element('article',null,{className:'fb-post'}),head=element('div',null,{className:'fb-post-head'});
        const checkbox=element('input',null,{type:'checkbox',checked:draft().all?!draft().excluded.has(post.id):draft().included.has(post.id),disabled:post.access==='restricted'&&!post.resources});
        checkbox.hidden=historyMode;checkbox.setAttribute('aria-label','选择 '+post.title);checkbox.checked=checkbox.checked&&!checkbox.disabled;
        checkbox.onchange=()=>{if(draft().all)checkbox.checked?draft().excluded.delete(post.id):draft().excluded.add(post.id);else checkbox.checked?draft().included.add(post.id):draft().included.delete(post.id);};
        const info=element('div'),title=element('div',null,{className:'fb-post-title'});
        const terms=get('ui.bold_keywords',data.options)?[q,...(data.options.filters.title.include_enabled?data.options.filters.title.include:[])]:[];
        highlight(title,post.title,terms);info.append(title);
        info.append(element('div',`${post.published_at.slice(0,10)} · ${post.access==='restricted'?'受限':post.fee?'付费 · 可访问':'公开'} · ${post.resources} 文件 · ${fmt(post.known_bytes)}${post.unknown_sizes?' + '+post.unknown_sizes+' 个未知大小':''}`,{className:'fb-post-meta'}));
        head.append(checkbox,info);row.append(head);
        const details=element('details');details.append(element('summary','正文 · 文件 · 链接'));
        details.addEventListener('toggle',async()=>{
          if(!details.open||details.dataset.loaded)return;details.dataset.loaded='1';
          try {
            const detail=await api(`/api/fanbox/job?id=${encodeURIComponent(id)}&post_id=${encodeURIComponent(post.id)}`);
            const text=(detail.post.blocks||[]).filter(b=>typeof b.text==='string').map(b=>b.text).join('\n\n');
            details.append(element('pre',text||'—'));
            const comments=(items,depth=0)=>{if(depth>=20)return;(items||[]).forEach(item=>{
              if(typeof item.body==='string')details.append(element('p',item.body));
              const replies=item.replies;comments(Array.isArray(replies)?replies:replies?.items,depth+1);
            });};comments(detail.post.comments);
            detail.assets.forEach(asset=>{
              const line=element('label',null,{className:'fb-asset'}),check=element('input',null,{type:'checkbox',checked:asset.selected&&!draft().assets.has(asset.id),disabled:!asset.selected||post.access==='restricted'&&asset.kind!=='cover'});
              check.onchange=()=>check.checked?draft().assets.delete(asset.id):draft().assets.add(asset.id);
              check.hidden=historyMode;
              line.append(check,element('span',`${asset.name} · ${asset.variant==='original'?'原始文件':'缩略图'} · ${fmt(asset.size)} · ${statusNames[asset.status]||asset.status}${asset.history_hint?' · 导入记录':''} · ${asset.path}${asset.error?' · '+asset.error.message:''}`));details.append(line);
            });
            (detail.post.links||[]).forEach(link=>{
              let safe;try{safe=new URL(link.url);if(!['http:','https:'].includes(safe.protocol))return;}catch(e){return;}
              const line=element('p'),anchor=element('a',link.url,{href:safe.href,target:'_blank',rel:'noopener noreferrer'});line.append(anchor);details.append(line);
            });
          }catch(e){details.append(element('div',e.message,{className:'fb-error'}));details.dataset.loaded='';}
        });row.append(details);host.append(row);
      });
      (data.fan_cards||[]).forEach(card=>host.append(element('p',`粉丝卡 · ${card.creator_id||'赞助列表'} · ${statusNames[card.status]||card.status} · ${card.path||card.error?.message||''}`)));
    }catch(e){showToast(e.message,'error');}
  }
  async function openHistory(url) {
    try {
      historyMode=true;const data=await api('/api/fanbox/history?source='+encodeURIComponent(url));
      $('fanboxRuns').replaceChildren();$('fanboxHistoryTitle').textContent='FANBOX 下载历史';
      data.runs.forEach(job=>{accept(job);$('fanboxRuns').append(button(`${new Date(job.created_at*1000).toLocaleString()} · ${statusNames[job.status]||job.status} · ${job.counts?.posts||0} 帖`,()=>openDetail(job.id)));});
      if(data.runs.length)await openDetail(data.runs[0].id);
      else showToast('该链接没有可用的归档记录','error');
    }catch(e){showToast(e.message,'error');}
  }
  function highlight(host,value,terms){const spans=[],seen=new Set(),lower=value.toLowerCase();
    for(const term of terms){if(!term)continue;let start=0,at;while((at=lower.indexOf(term.toLowerCase(),start))>=0&&spans.length<10000){
      const end=at+term.length,key=at+':'+end;if(!seen.has(key)){seen.add(key);spans.push([at,end]);}start=end;}}
    spans.sort((a,b)=>a[0]-b[0]);const merged=[];for(const span of spans){const last=merged.at(-1);if(last&&span[0]<=last[1])last[1]=Math.max(last[1],span[1]);else merged.push([...span]);}
    let offset=0;for(const [start,end] of merged){host.append(document.createTextNode(value.slice(offset,start)),element('mark',value.slice(start,end)));offset=end;}
    host.append(document.createTextNode(value.slice(offset)));
  }
  function consoleEntry(entry) {
    if(!replayingLogs){consoleEntries.push(entry);if(consoleEntries.length>1200)consoleEntries.shift();}
    return !!entry.job_id===!!consoleMode;
  }
  function renderConsole() {
    $('logBox').replaceChildren();replayingLogs=true;
    try{consoleEntries.filter(entry=>!!entry.job_id===!!consoleMode).slice(-300).forEach(entry=>_addToBox('logBox',entry));}
    finally{replayingLogs=false;}
  }
  function acceptLog(entry) {
    const key=entry.job_id+':'+entry.seq;if(logKeys.has(key))return;logKeys.add(key);
    if(logKeys.size>5000)logKeys.delete(logKeys.values().next().value);addLog(entry);
  }
  function clearConsole(){for(let i=consoleEntries.length-1;i>=0;i--)if(!!consoleEntries[i].job_id===!!consoleMode)consoleEntries.splice(i,1);}
  async function auth() {try {const value=await api('/api/fanbox/auth');$('fanboxAuth').textContent=value.runtime.available?(value.status==='loaded'?'凭据已载入':'匿名'):'运行依赖缺失';$('fanboxSettingsStatus').textContent=$('fanboxAuth').textContent;}catch(e){showToast(e.message,'error');}}
  async function init() {
    $('fanboxPreview').onclick=()=>start($('urlInput').value.trim(),true);
    $('fanboxHistoryContent').append($('fanboxDetail'));
    document.querySelectorAll('[data-fb-close]').forEach(b=>b.onclick=()=>b.closest('dialog').close());
    $('fanboxTaskConfirm').onclick=async()=>{const b=$('fanboxTaskConfirm');b.disabled=true;try{
      const ok=resumeJob?await action(resumeJob,'continue',null,taskDraft,resumeVersion):await enqueue(taskUrl,!taskDraft.workflow.auto_download,taskDraft);
      if(ok)$('fanboxTaskDialog').close();
    }finally{b.disabled=false;}};
    $('fanboxHistoryDialog').addEventListener('close',()=>{selectedJob='';requestVersion++;historyMode=false;});
    $('fanboxRefresh').onclick=loadJobs;$('fanboxCloseDetail').onclick=()=>$('fanboxHistoryDialog').close();
    $('fanboxOpenArchive').onclick=()=>action(selectedJob,'open');
    $('fanboxVerify').onclick=()=>action(selectedJob,jobs.get(selectedJob)?.verification?.status==='running'?'cancel_verification':'verify');
    $('fanboxCopyLinks').onclick=copyLinks;$('fanboxExportManifest').onclick=exportManifest;
    $('fanboxUsage').onclick=showUsage;
    $('fanboxRecords').onclick=async()=>{try{recordEpoch++;recordBatches=null;$('fanboxRecordReport').textContent='';$('fanboxRecordConfirm').hidden=true;await recordCounts();$('fanboxRecordsDialog').showModal();}catch(e){showToast(e.message,'error');}};
    $('fanboxRecordsDialog').addEventListener('close',()=>{recordEpoch++;recordBatches=null;});
    $('fanboxRecordImport').onclick=()=>$('fanboxRecordFile').click();$('fanboxRecordFile').onchange=importRecordFile;
    $('fanboxRecordConfirm').onclick=confirmRecords;
    $('fanboxRecordExport').onclick=async()=>{try{downloadJson((await api('/api/fanbox/records?export=1')).records,'fanbox-url-records.json');}catch(e){showToast(e.message,'error');}};
    $('fanboxRecordClear').onclick=async()=>{if(recordBusy||!confirm('清空所有 FANBOX URL 记录？'))return;try{recordEpoch++;recordBatches=null;$('fanboxRecordConfirm').hidden=true;$('fanboxRecordReport').textContent='';await api('/api/fanbox/records',{method:'POST',body:JSON.stringify({action:'clear'})});await recordCounts();}catch(e){showToast(e.message,'error');}};
    $('fanboxAuthCheck').onclick=async()=>{await saveSettingsNoAlert();auth();};
    $('fanboxSelectAll').onchange=()=>{draft().all=$('fanboxSelectAll').checked;draft().excluded.clear();draft().included.clear();loadDetail();};
    $('fanboxPrevious').onclick=()=>{offset=Math.max(0,offset-25);loadDetail();};$('fanboxNext').onclick=()=>{offset+=25;loadDetail();};
    $('fanboxSearch').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>{offset=0;loadDetail();},200);};
    $('fanboxDownloadSelected').onclick=()=>{
      if(!draft().all&&!draft().included.size){showToast('请先选择帖子','error');return;}
      action(selectedJob,'download',{...(draft().all?{exclude_post_ids:[...draft().excluded]}:{post_ids:[...draft().included]}),exclude_asset_ids:[...draft().assets],title_query:$('fanboxSearch').value});
    };
    $('urlInput').addEventListener('input',()=>{sync();const lines=$('urlInput').value.trim().split(/\s+/).filter(Boolean);if(lines.length&&lines.every(matches)&&currentPlatform!=='Fanbox')selectPlatform('Fanbox');});
    try {const data=await api('/api/fanbox/options');options=data.options;defaults=data.defaults;
      $('fanboxEnabled').checked=data.enabled;$('fanboxAnonymous').checked=data.anonymous;$('fanboxCookieFile').value=data.cookie_file;renderSettings();sync();auth();loadJobs();
    }catch(e){$('fanboxSettingsStatus').textContent=e.message;}
  }
  window.FanboxUI={matches,start,sync,applyConfig,configValues,event:accept,log:acceptLog,consoleEntry,clearConsole,openHistory,
    ready:values=>(values||[]).forEach(accept)};
  init();
})();
