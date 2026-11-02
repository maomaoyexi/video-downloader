// Isolated application E2E test. Requires playwright@1.58.2 in temp/fanbox-ui-qa.
// Runs with synthetic data in a fresh headless profile; never attaches to a user browser.
import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {pathToFileURL} from 'node:url';
const {chromium}=await import(process.env.FANBOX_PLAYWRIGHT_MODULE||pathToFileURL('temp/fanbox-ui-qa/node_modules/playwright/index.mjs').href);
const root=process.cwd(),data=JSON.parse(execFileSync('python',['-c','import json;from video_downloader.core.constants import DEFAULT_CONFIG,VERSION;from video_downloader.platforms.fanbox.options import normalize_options;print(json.dumps(dict(config=DEFAULT_CONFIG,version=VERSION,options=normalize_options())))'],{encoding:'utf8'}));
let config=structuredClone(data.config),options=data.options,created=[],jobs=[];
function configuredFanboxOptions(){
  const value=structuredClone(options),saved=JSON.parse(config.FANBOX_OPTIONS||'{}');
  const merge=(target,source)=>Object.entries(source).forEach(([key,item])=>{
    if(item&&typeof item==='object'&&!Array.isArray(item)&&target[key])merge(target[key],item);
    else target[key]=item;
  });
  merge(value,saved);return value;
}
let recordCount=0;
const job={id:'a'.repeat(32),source:'https://www.fanbox.cc/@sample',status:'preview_ready',version:1,created_at:1793376000,phase:'preview',counts:{posts:1,completed:1},scope:{list_complete:true}};
const server=http.createServer(async(req,res)=>{
  const url=new URL(req.url,'http://localhost');let body='';for await(const chunk of req)body+=chunk;
  if(url.pathname.startsWith('/api/')){
    const name=url.pathname;
    if(name==='/api/events'){res.writeHead(200,{'Content-Type':'text/event-stream'});res.write('data: '+JSON.stringify({type:'ready',data:{logs:[],tasks:[],fanbox_jobs:jobs,download:{running:false}}})+'\n\n');return;}
    let result={};
    if(name==='/api/config')result={version:data.version,config};
    if(name==='/api/save-config'){config={...config,...JSON.parse(body)};result={ok:true};}
    if(name==='/api/fanbox/options')result={options:configuredFanboxOptions(),defaults:options,
      enabled:!!Number(config.FANBOX_ENABLED??1),anonymous:!!Number(config.FANBOX_ANONYMOUS??0),cookie_file:config.FANBOX_COOKIE_FILE||''};
    if(name==='/api/fanbox/auth')result={runtime:{available:true},status:'anonymous'};
    if(name==='/api/fanbox/naming-preview')result={directory:'sample/post',files:['images/001.png','attachments/file.zip']};
    if(name==='/api/fanbox/jobs')result={jobs};
    if(name==='/api/fanbox/create'){created.push(JSON.parse(body));jobs=[job];result={job};}
    if(name==='/api/fanbox/job')result={job,options,verification:job.verification,posts:[{id:'1',title:'Sample post',fee:500,published_at:'2026-10-31',access:'accessible',resources:0,known_bytes:0}],total:1};
    if(name==='/api/fanbox/action'){job.verification={version:1,status:'completed',job_version:1,checked:1,total:1,ok:1,missing:0,modified:0,unreadable:0,unverified:0,busy:0,bytes_read:100,issues:[]};result={job};}
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
    if(name==='/api/help/error-manual')result={title:'错误与排查手册',text:fs.readFileSync(path.join(root,'docs/错误码.txt'),'utf8'),source:'docs/错误码.txt'};
    if(name==='/api/live/capabilities')result={platforms:{YouTube:{catch_up:'supported',live_edge:true},Twitch:{catch_up:'supported',live_edge:true}}};
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
await page.addInitScript(()=>{
  window.__helpClipboardWrites=[];
  Object.defineProperty(navigator,'clipboard',{configurable:true,value:{
    writeText:async text=>{
      if(window.__helpClipboardDenied)throw new Error('synthetic clipboard denied');
      window.__helpClipboardWrites.push(text);
    },
    readText:async()=>window.__helpClipboardWrites.at(-1)||''
  }});
});
async function settleLiveLayout(){
  await page.evaluate(async()=>{
    await document.fonts.ready;
    await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
  });
}
async function openLivePlatforms(){
  for(const id of ['livePlatformModes','liveCommentPlatforms']){
    const details=page.locator('#set-live details').filter({has:page.locator('#'+id)});
    if(await details.getAttribute('open')===null)await details.locator('summary').click();
  }
  await settleLiveLayout();
}
async function closeLiveDetails(){
  for(const details of await page.locator('#set-live details[open]').all())await details.locator('summary').click();
}
async function switchOn(id,enabled){
  const control=page.locator('#'+id);
  if(await control.evaluate(node=>node.classList.contains('on'))!==enabled)await control.click();
}
async function reloadSettings(){
  await page.reload();
  await page.locator('[data-fanbox-option="fan_cards.scope"]').waitFor({state:'attached'});
  await page.locator('.ni[data-page="settings"]').click();
  await page.locator('[data-live-platform="Twitch"]').waitFor({state:'attached'});
  await settleLiveLayout();
}
async function verifyAboutReleaseNotes(){
  await page.locator('.ni[data-page="about"]').click();
  const title=page.locator('#aboutReleaseTitle'),details=page.locator('#aboutReleaseDetails');
  assert.equal(await title.textContent(),data.version.split(' ')[0]+' 本版更新');
  assert.equal(await page.locator('#aboutReleaseNotes .about-release-summary>li').count(),4);
  assert.equal(await details.evaluate(el=>el.open),false,'详细更新默认收起');
  await details.locator('summary').click();
  assert.equal(await details.locator('ol>li').count(),6,'本版六项FANBOX修复应完整显示');
  assert.equal(await details.locator('.about-release-body').isVisible(),true);
  await details.locator('summary').focus();await page.keyboard.press('Space');
  assert.equal(await details.evaluate(el=>el.open),false);
  await page.keyboard.press('Enter');assert.equal(await details.evaluate(el=>el.open),true);
  await details.locator('summary').click();
  for(const theme of ['light','dark']){
    await page.evaluate(theme=>document.documentElement.dataset.theme=theme,theme);
    for(const width of [1440,375]){
      await page.setViewportSize({width,height:900});await settleLiveLayout();
      await page.locator('#aboutReleaseNotes').evaluate(el=>el.scrollIntoView({behavior:'instant',block:'start'}));
      const layout=await page.locator('.pad').evaluate(el=>({client:el.clientWidth,scroll:el.scrollWidth}));
      assert.ok(layout.scroll<=layout.client+1,`${theme}/${width}: 本版更新不能撑宽关于页`);
      await page.screenshot({path:path.resolve(root,'..','debug','验证记录',`关于软件-v2.7.1-更新日志-${theme}-${width}.png`),animations:'disabled'});
    }
  }
  await page.setViewportSize({width:1440,height:1000});
  await page.evaluate(()=>document.documentElement.dataset.theme='light');
  await page.locator('.ni[data-page="download"]').click();
  await page.locator('.pad').evaluate(el=>el.scrollTo({top:0,behavior:'instant'}));
  console.log('通过：关于页当前版本更新摘要、六项修复详情、默认折叠/键盘操作、明暗主题和窄屏均正确');
}
async function verifyHelpSupport(){
  const requests=[],capture=request=>requests.push({method:request.method(),url:request.url()});
  page.on('request',capture);
  const manual=page.locator('#helpManualPanel'),manualButton=page.locator('#helpOpenManual');
  assert.equal(await manual.isVisible(),false);
  assert.equal(await page.locator('#helpSupportPanel').isVisible(),false);
  await page.route('**/api/help/error-manual',route=>route.fulfill({status:404,contentType:'application/json',body:JSON.stringify({error:'完整错误手册暂不可用，请查看 docs/错误码.txt'})}));
  await manualButton.click();
  await page.waitForFunction(()=>document.querySelector('#helpManualStatus').textContent.includes('加载失败'));
  assert.equal(await page.locator('#helpManualText').isVisible(),false);
  assert.ok((await page.locator('#helpManualStatus').textContent()).includes('docs/错误码.txt'));
  await page.locator('#helpCloseManual').click();
  assert.equal(await manualButton.getAttribute('aria-expanded'),'false');
  await page.unroute('**/api/help/error-manual');
  await manualButton.click();
  await page.locator('#helpManualText').waitFor({state:'visible'});
  assert.equal(await page.locator('#helpManualText').textContent(),fs.readFileSync(path.join(root,'docs/错误码.txt'),'utf8'),'应显示完整手册原文');
  const reads=requests.filter(item=>item.url.endsWith('/api/help/error-manual')).length;
  await page.locator('#helpCloseManual').click();await manualButton.click();await settleLiveLayout();
  assert.equal(requests.filter(item=>item.url.endsWith('/api/help/error-manual')).length,reads,'重新展开可复用已加载手册');
  await page.locator('#helpMissingTitle').evaluate(el=>el.scrollIntoView({behavior:'instant',block:'start'}));
  await page.screenshot({path:path.resolve(root,'..','debug','验证记录','未知错误-完整手册.png'),animations:'disabled'});
  await page.locator('#helpCloseManual').click();

  await page.locator('#helpOpenOrganizer').click();
  assert.equal(await page.locator('#helpReportVersion').inputValue(),data.version);
  assert.equal(await page.locator('#helpCopyReport').isDisabled(),true);
  await page.locator('#helpReportPlatform').fill('FANBOX');
  await page.locator('#helpReportSource').fill('FANBOX');
  await page.locator('#helpReportCode').fill('DEMO_UNKNOWN_42');
  await page.locator('#helpReportError').fill('<img src=x onerror="window.__helpXss=true"> HTTP 403\nCookie: sid=DEMO_COOKIE; auth=DEMO_AUTH');
  await page.locator('#helpReportLogs').fill('Authorization: Bearer DEMO_BEARER\nhttps://user:DEMO_PASS@example.invalid/path?sig=DEMO_SIG#DEMO_FRAGMENT');
  await page.locator('#helpGenerateReport').click();
  let report=await page.locator('#helpReportOutput').inputValue();
  assert.ok(report.includes('DEMO_UNKNOWN_42')&&report.includes('原因：尚未确认'));
  assert.ok(report.includes('<img src=x onerror="window.__helpXss=true"> HTTP 403'));
  for(const value of ['DEMO_COOKIE','DEMO_AUTH','DEMO_BEARER','DEMO_PASS','DEMO_SIG','DEMO_FRAGMENT'])assert.ok(!report.includes(value));
  assert.equal(await page.locator('#helpReportOutputPanel img').count(),0);
  assert.equal(await page.evaluate(()=>Boolean(window.__helpXss)),false,'用户报错应按纯文本显示');
  await page.locator('#helpCopyReport').click();
  assert.equal(await page.evaluate(()=>window.__helpClipboardWrites.at(-1)),report);
  await page.locator('#helpReportSource').fill('FFmpeg');
  assert.equal(await page.locator('#helpCopyReport').isDisabled(),true,'输入变化后需重新生成结果');
  await page.locator('#helpOpenFeedback').click();
  await page.locator('#helpReportSteps').fill('打开下载任务，输入链接并开始');
  await page.locator('#helpReportExpected').fill('保存媒体文件');
  await page.locator('#helpReportActual').fill('任务失败并返回错误');
  await page.locator('#helpGenerateReport').click();
  report=await page.locator('#helpReportOutput').inputValue();
  for(const title of ['# 问题反馈模板','## 操作步骤','## 预期结果','## 实际结果'])assert.ok(report.includes(title));
  await page.evaluate(()=>window.__helpClipboardDenied=true);await page.locator('#helpCopyReport').click();
  await page.waitForFunction(()=>document.querySelector('#helpReportStatus').textContent.includes('Ctrl+C'));
  assert.ok(await page.locator('#helpReportOutput').evaluate(el=>el.selectionEnd===el.value.length),'复制失败时提供手动复制选择');
  await page.evaluate(()=>window.__helpClipboardDenied=false);

  await page.locator('#helpReportPlatform').fill('Bilibili');
  await page.locator('#helpReportCode').fill('4294967294');
  await page.locator('#helpReportError').fill('ffmpeg exited with code 4294967294');
  await page.locator('#helpReportLogs').fill('ERROR: unable to open input file');
  await page.locator('#helpGenerateReport').click();
  await manualButton.click();
  for(const theme of ['light','dark']){
    await page.evaluate(theme=>document.documentElement.dataset.theme=theme,theme);
    for(const width of [1440,375]){
      await page.setViewportSize({width,height:900});await settleLiveLayout();
      const layout=await page.locator('.pad').evaluate(el=>({client:el.clientWidth,scroll:el.scrollWidth}));
      assert.ok(layout.scroll<=layout.client+1,`${theme}/${width}: 完整手册和反馈表单不能横向溢出`);
      await page.locator('#helpReportOutputPanel').evaluate(el=>el.scrollIntoView({behavior:'instant',block:'center'}));
      await page.screenshot({path:path.resolve(root,'..','debug','验证记录',`未知错误-反馈预览-${theme}-${width}.png`),animations:'disabled'});
    }
  }
  await page.locator('#helpCloseSupport').click();
  await page.locator('#helpCloseManual').click();
  assert.equal(await page.locator('#helpSupportPanel').isVisible(),false);
  assert.ok(requests.every(item=>item.method==='GET'),'整理和生成反馈不得自动上传或提交');
  assert.ok(requests.every(item=>new URL(item.url).origin===new URL(page.url()).origin),'报错文字不应产生外部请求');
  page.off('request',capture);
  await page.setViewportSize({width:1440,height:1000});
  await page.evaluate(()=>document.documentElement.dataset.theme='light');
  console.log('通过：未收录报错可查看完整手册、失败后重试、本地整理和反馈预览、常见凭据遮盖、安全文本显示、手动复制回退；无自动上传或外部请求');
}
async function verifyHelpGuide(){
  await page.locator('.ni[data-page="help"]').click();
  const topics=page.locator('#helpGuide .help-topic'),toggle=page.locator('#helpToggleAll');
  assert.equal(await page.locator('#page-help .doc.two').count(),0,'帮助页不再同时平铺两列长文');
  assert.equal(await page.locator('#helpGuide .help-group').count(),3);
  assert.equal(await topics.count(),17,'原主题和本轮新增帮助都应完整保留');
  assert.deepEqual(await topics.evaluateAll(items=>items.map(el=>el.id)),[
    'help-start','help-args','help-cookies','help-tasks','help-presets','help-tools',
    'help-live','help-bilibili','help-rplay','help-fanbox','help-withny','help-other-platforms',
    'help-files','help-redownload','help-errors','help-faq','help-fixes'
  ]);
  for(const group of await page.locator('#helpGuide .help-group').all()){
    const count=await group.locator('.help-topic').count();
    assert.equal(await group.locator('.help-count').textContent(),count+' 个主题','主题计数应与实际内容一致');
  }
  assert.deepEqual(await page.locator('#helpGuide .help-topic[open]').evaluateAll(items=>items.map(el=>el.id)),['help-start']);
  assert.equal(await page.locator('#help-start .help-topic-body').isVisible(),true);
  assert.equal(await page.locator('#help-cookies .help-topic-body').isVisible(),false);
  const cookieSummary=page.locator('#help-cookies>summary');
  await cookieSummary.locator('.help-topic-title').click();
  assert.equal(await page.locator('#help-cookies').evaluate(el=>el.open),true);
  const box=await cookieSummary.boundingBox();
  await cookieSummary.click({position:{x:box.width-5,y:box.height/2}});
  assert.equal(await page.locator('#help-cookies').evaluate(el=>el.open),false,'点击标题留白也能收起');
  await cookieSummary.focus();await page.keyboard.press('Enter');
  assert.equal(await page.locator('#help-cookies .help-topic-body').isVisible(),true);
  await page.keyboard.press('Space');
  assert.equal(await page.locator('#help-cookies .help-topic-body').isVisible(),false);
  await page.locator('#help-errors>summary').click();
  const errorEntries=page.locator('#help-errors .help-error-entry');
  assert.equal(await errorEntries.count(),18,'常见报错应按来源分组呈现');
  const errorFields=await errorEntries.evaluateAll(items=>items.map(el=>({
    labels:[...el.querySelectorAll('dt')].map(node=>node.textContent),
    values:[...el.querySelectorAll('dd')].map(node=>node.textContent.trim())
  })));
  assert.ok(errorFields.every(item=>item.labels.join('|')==='含义|常见原因|处理步骤|重试建议'&&
    item.values.length===4&&item.values.every(Boolean)),'每条错误均须完整提供四项解释');
  assert.equal(await page.locator('#help-errors .help-error-entry[open]').count(),0,'错误细节默认收起');
  assert.equal(await page.locator('#help-error-ffmpeg-exit .help-error-details').isVisible(),false);
  const ffmpegSummary=page.locator('#help-error-ffmpeg-exit>summary');
  await ffmpegSummary.locator('.help-error-name').click();
  assert.equal(await page.locator('#help-error-ffmpeg-exit .help-error-details').isVisible(),true);
  assert.deepEqual(await page.locator('#help-error-ffmpeg-exit dt').allTextContents(),['含义','常见原因','处理步骤','重试建议']);
  assert.ok((await page.locator('#help-error-ffmpeg-exit dd').first().textContent()).includes('不能唯一定位故障'));
  await ffmpegSummary.focus();await page.keyboard.press('Space');
  assert.equal(await page.locator('#help-error-ffmpeg-exit').evaluate(el=>el.open),false);
  await page.keyboard.press('Enter');
  assert.equal(await page.locator('#help-error-ffmpeg-exit').evaluate(el=>el.open),true);
  assert.ok((await page.locator('#help-error-http-403').textContent()).includes('不能仅凭 403 判断 Cookie 过期'));
  assert.ok((await page.locator('#help-errors>.help-topic-body>.help-note').textContent()).includes('任务状态不是错误码'));
  assert.ok((await page.locator('#help-args').textContent()).includes('任务成功提交或加入队列后'));
  assert.ok((await page.locator('#help-fanbox').textContent()).includes('按当前全局选项'));
  assert.ok((await page.locator('#help-live').textContent()).includes('正数延后、负数提前'));
  assert.ok((await page.locator('#help-redownload').textContent()).includes('不生成编号副本'));
  assert.ok((await page.locator('#help-faq').textContent()).includes('首次具体报错'));
  await verifyHelpSupport();
  await toggle.click();
  assert.equal(await page.locator('#helpGuide .help-topic[open]').count(),17);
  assert.equal(await toggle.textContent(),'全部收起');
  await cookieSummary.click();
  await page.waitForFunction(()=>document.querySelector('#helpToggleAll').textContent==='全部展开');
  await toggle.click();await toggle.click();
  assert.equal(await page.locator('#helpGuide .help-topic[open]').count(),0);
  await page.locator('.help-nav a[href="#help-troubleshooting"]').click();await settleLiveLayout();
  const anchor=await page.locator('#help-troubleshooting').evaluate(el=>{
    const pad=document.querySelector('.pad'),box=el.getBoundingClientRect(),pane=pad.getBoundingClientRect();
    return {top:box.top,paneTop:pane.top,paneBottom:pane.bottom,scroll:pad.scrollTop};
  });
  assert.ok(anchor.scroll>0&&anchor.top>=anchor.paneTop-1&&anchor.top<anchor.paneBottom,'分类链接应定位到对应分组');
  await toggle.click();
  assert.equal(await page.locator('#helpGuide .help-topic[open]').count(),17);
  await errorEntries.evaluateAll(items=>items.forEach(el=>{el.open=true;}));
  assert.ok(!(await page.locator('#help-fixes').textContent()).includes('六项仍待修复'));
  assert.ok((await page.locator('#help-fixes').textContent()).includes('旧 v2.7.0 发布附件未重新打包'));
  for(const theme of ['light','dark']){
    await page.evaluate(theme=>document.documentElement.dataset.theme=theme,theme);
    for(const width of [1920,1440,1100,768,375]){
      await page.setViewportSize({width,height:900});await settleLiveLayout();
      const layout=await page.locator('#helpGuide').evaluate(el=>{
        const pad=document.querySelector('.pad');
        return {width:el.getBoundingClientRect().width,pane:pad.clientWidth,scroll:pad.scrollWidth,
          groupWidths:[...el.querySelectorAll('.help-group')].map(node=>node.getBoundingClientRect().width)};
      });
      assert.ok(layout.width<=1081&&layout.scroll<=layout.pane+1,`${theme}/${width}: 帮助长文与目录树不能撑宽页面`);
      assert.ok(layout.groupWidths.every(width=>Math.abs(width-layout.width)<1),`${theme}/${width}: 分组应保持单列对齐`);
    }
  }
  await page.setViewportSize({width:1440,height:1000});
  await page.reload();await page.locator('[data-fanbox-option="fan_cards.scope"]').waitFor({state:'attached'});
  await page.locator('.ni[data-page="help"]').click();
  await page.evaluate(()=>document.documentElement.dataset.theme='light');
  await settleLiveLayout();
  assert.deepEqual(await page.locator('#helpGuide .help-topic[open]').evaluateAll(items=>items.map(el=>el.id)),['help-start'],
    '刷新后默认只展开快速开始');
  await page.screenshot({path:path.resolve(root,'..','debug','验证记录','使用帮助-分组折叠-浅色.png'),animations:'disabled'});
  await page.locator('#help-errors>summary').click();
  await page.locator('#help-error-ffmpeg-exit>summary').click();
  await page.locator('#help-error-ffmpeg-exit').evaluate(el=>el.scrollIntoView({behavior:'instant',block:'center'}));
  await page.screenshot({path:path.resolve(root,'..','debug','验证记录','使用帮助-错误速查-浅色.png'),animations:'disabled'});
  await page.setViewportSize({width:375,height:900});
  await page.locator('#help-error-ffmpeg-exit').evaluate(el=>el.scrollIntoView({behavior:'instant',block:'start'}));
  await page.screenshot({path:path.resolve(root,'..','debug','验证记录','使用帮助-错误速查-窄屏.png'),animations:'disabled'});
  await page.setViewportSize({width:1440,height:1000});
  await page.locator('#help-errors>summary').click();
  await page.locator('#help-troubleshooting').evaluate(el=>el.scrollIntoView({behavior:'instant',block:'start'}));
  await page.screenshot({path:path.resolve(root,'..','debug','验证记录','使用帮助-文件排查.png'),animations:'disabled'});
  await page.locator('.pad').evaluate(el=>el.scrollTo({top:0,behavior:'instant'}));
  await page.evaluate(()=>document.documentElement.dataset.theme='dark');await settleLiveLayout();
  await page.screenshot({path:path.resolve(root,'..','debug','验证记录','使用帮助-分组折叠-深色.png'),animations:'disabled'});
  await page.setViewportSize({width:375,height:900});await settleLiveLayout();
  await page.screenshot({path:path.resolve(root,'..','debug','验证记录','使用帮助-分组折叠-窄屏.png'),animations:'disabled'});
  await page.setViewportSize({width:1440,height:1000});
  await page.evaluate(()=>document.documentElement.dataset.theme='light');
  await page.locator('.ni[data-page="download"]').click();
  console.log('通过：帮助页3组17主题、18条分组错误速查及四项解释、默认折叠/整行与键盘切换、全部展开/收起、分类定位、刷新默认状态、明暗主题和5种尺寸；参数/工具/FANBOX/重下/弹幕/反馈说明完整');
}
try{
  await page.emulateMedia({reducedMotion:'no-preference'});
  await page.goto('http://127.0.0.1:'+server.address().port);await page.locator('[data-fanbox-option="fan_cards.scope"]').waitFor({state:'attached'});
  await verifyAboutReleaseNotes();
  await verifyHelpGuide();
  await page.locator('.ni[data-page="tools"]').click();
  const toolEntry=await page.locator('#page-tools .tiles>.tile').evaluateAll(items=>items.map(el=>({
    title:el.textContent.trim(),delay:Number.parseFloat(getComputedStyle(el).animationDelay)*1000
  })));
  console.log('实用工具入场延迟：'+JSON.stringify(toolEntry));
  assert.equal(toolEntry.length,12);
  assert.ok(toolEntry.every((entry,index)=>index===0||entry.delay>toolEntry[index-1].delay),
    '工具卡片应按逐行顺序依次出现，末尾卡片不能提前到第一张同时显示');
  let lastToolEntryStart=-1;
  for(const theme of ['light','dark']){
    await page.evaluate(theme=>document.documentElement.dataset.theme=theme,theme);
    for(const width of [1440,1100,375]){
      await page.locator('.ni[data-page="download"]').click();
      await page.setViewportSize({width,height:900});
      await page.locator('.ni[data-page="tools"]').click();await settleLiveLayout();
      const entry=await page.locator('#page-tools .tiles>.tile').evaluateAll(items=>items.map(el=>{
        const animation=el.getAnimations().find(item=>item.animationName==='content-rise');
        const box=el.getBoundingClientRect();
        return {start:animation?.startTime===null||!animation?null:animation.startTime+animation.effect.getTiming().delay,
          left:box.left,top:box.top};
      }));
      assert.ok(entry.every((item,index)=>item.start!==null&&(index===0||item.start>entry[index-1].start)),
        `${theme}/${width}: 实际入场时间必须依次递增`);
      assert.ok(entry[0].start>lastToolEntryStart,'离开后重新进入应重新播放入场动画');
      lastToolEntryStart=entry[0].start;
      for(let i=1;i<entry.length;i++){
        assert.ok(entry[i].top>=entry[i-1].top-.5&&
          (Math.abs(entry[i].top-entry[i-1].top)>.5||entry[i].left>entry[i-1].left),
          `${theme}/${width}: 卡片应按从左到右、从上到下的视觉顺序出现`);
      }
    }
  }
  await page.emulateMedia({reducedMotion:'reduce'});
  const reducedToolEntry=await page.locator('#page-tools .tiles>.tile').evaluateAll(items=>items.map(el=>({
    delay:Number.parseFloat(getComputedStyle(el).animationDelay),duration:Number.parseFloat(getComputedStyle(el).animationDuration)
  })));
  assert.ok(reducedToolEntry.every(item=>item.delay===0&&item.duration<=.000001),'减少动态效果时应取消依次入场');
  await page.emulateMedia({reducedMotion:'no-preference'});
  await page.setViewportSize({width:1440,height:1000});
  await page.evaluate(()=>document.documentElement.dataset.theme='light');
  console.log('通过：12张实用工具卡片按视觉顺序入场，明暗主题、5/4/2列和重新进入均正确，减少动态效果设置保留');
  await page.locator('.ni[data-page="download"]').click();
  const argsFold=page.locator('#taskArgsFold'),argsToggle=page.locator('#taskArgsToggle');
  const taskArgs=page.locator('#task_ytdlp_args');
  assert.equal(await argsFold.evaluate(el=>el.open),false,'本次参数默认收起');
  assert.equal(await taskArgs.isVisible(),false);
  await argsToggle.locator('span').click();
  assert.equal(await taskArgs.isVisible(),true,'点击按钮文字应展开');
  await taskArgs.fill('--sleep-requests 1');
  const toggleSize=await argsToggle.boundingBox();
  await argsToggle.click({position:{x:toggleSize.width-3,y:toggleSize.height/2}});
  assert.equal(await argsFold.evaluate(el=>el.open),false,'点击按钮留白应收起');
  assert.equal(await taskArgs.inputValue(),'--sleep-requests 1','收起不能清空参数');
  await argsToggle.focus();await page.keyboard.press('Enter');
  assert.equal(await argsFold.evaluate(el=>el.open),true);
  await page.keyboard.press('Space');
  assert.equal(await argsFold.evaluate(el=>el.open),false);

  const starts=[],startRoutes=/\/api\/(?:start|start-urls|batch-txt)$/;
  let rejectStart=true;
  await page.route(startRoutes,async route=>{
    starts.push({path:new URL(route.request().url()).pathname,body:route.request().postDataJSON()});
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(rejectStart?{error:'合成启动失败'}:{task:{id:'synthetic-task'}})});
  });
  async function startWithFoldedArgs(urls,endpoint){
    const response=page.waitForResponse(res=>new URL(res.url()).pathname===endpoint);
    if(endpoint==='/api/batch-txt'){
      await page.locator('.ni[data-page="tools"]').click();
      page.once('dialog',dialog=>dialog.accept());
      await page.locator('.tile[onclick="startBatch()"]').click();
    }else{
      await page.locator('#urlInput').fill(urls);await page.locator('#btnStart').click();
    }
    await response;await settleLiveLayout();
    assert.equal(starts.at(-1).path,endpoint);
    assert.equal(starts.at(-1).body.custom_args,'--sleep-requests 1','收起后仍应提交一次性参数');
    assert.equal(await argsFold.evaluate(el=>el.open),false);
  }
  await startWithFoldedArgs('https://www.youtube.com/watch?v=sample','/api/start');
  assert.equal(await taskArgs.inputValue(),'--sleep-requests 1','启动失败应保留参数');
  rejectStart=false;
  await startWithFoldedArgs('https://www.youtube.com/watch?v=sample','/api/start');
  await page.waitForFunction(()=>document.getElementById('task_ytdlp_args').value==='');
  for(const [urls,endpoint] of [['https://www.youtube.com/watch?v=one\nhttps://www.youtube.com/watch?v=two','/api/start-urls'],['','/api/batch-txt']]){
    await argsToggle.click();await taskArgs.fill('--sleep-requests 1');await argsToggle.click();
    await startWithFoldedArgs(urls,endpoint);
    await page.waitForFunction(()=>document.getElementById('task_ytdlp_args').value==='');
    if(endpoint==='/api/batch-txt')await page.locator('.ni[data-page="download"]').click();
  }
  assert.ok(!Object.hasOwn(config,'task_ytdlp_args'),'本次参数不能写入全局配置');
  await page.unroute(startRoutes);
  await page.locator('#urlInput').fill('https://sample.fanbox.cc');
  await page.waitForFunction(()=>getComputedStyle(document.querySelector('.task-args-row')).display==='none');
  assert.equal(await argsToggle.isVisible(),false,'纯 FANBOX 应连同按钮一起隐藏');
  await page.locator('#urlInput').fill('https://www.youtube.com/watch?v=sample');
  await argsToggle.waitFor({state:'visible'});
  for(const theme of ['light','dark']){
    await page.evaluate(theme=>document.documentElement.dataset.theme=theme,theme);
    for(const width of [1440,375]){
      await page.setViewportSize({width,height:900});await settleLiveLayout();
      await argsToggle.click();assert.equal(await taskArgs.isVisible(),true);
      const layout=await page.locator('.pad').evaluate(el=>({client:el.clientWidth,scroll:el.scrollWidth}));
      assert.ok(layout.scroll<=layout.client+1,`${theme}/${width}: 本次参数不能撑宽页面`);
      await argsToggle.click();assert.equal(await taskArgs.isVisible(),false);
    }
  }
  await page.setViewportSize({width:1440,height:1000});
  await page.evaluate(()=>document.documentElement.dataset.theme='light');
  await argsToggle.click();await page.reload();
  await page.locator('[data-fanbox-option="fan_cards.scope"]').waitFor({state:'attached'});
  assert.equal(await argsFold.evaluate(el=>el.open),false,'刷新后仍默认收起');
  assert.equal(await taskArgs.isVisible(),false);
  await page.locator('.compose-wrap').screenshot({path:path.resolve(root,'..','debug','验证记录','本次参数-默认收起.png')});
  await argsToggle.click();
  await page.waitForFunction(()=>getComputedStyle(document.querySelector('#taskArgsToggle>.ico')).transform==='none');
  await page.locator('.compose-wrap').screenshot({path:path.resolve(root,'..','debug','验证记录','本次参数-展开.png')});
  await argsToggle.click();
  console.log('通过：本次参数默认收起、整按钮/键盘切换、值保留、单条/多链接/TXT批量提交、失败保留/成功清空、FANBOX隐藏恢复、明暗主题和窄屏');
  await page.locator('.ni[data-page="settings"]').click();
  const taskSectionText=await page.locator('#set-tasks>.settings-section-body').evaluate(el=>
    [...el.childNodes].filter(node=>node.nodeType===Node.TEXT_NODE).map(node=>node.textContent.trim()).filter(Boolean));
  assert.deepEqual(taskSectionText,[],'任务与并发的配置行之间不应出现多余正文字符');
  await page.setViewportSize({width:1920,height:1000});
  const initialOutput=await page.locator('#set-output').evaluate(el=>el.getBoundingClientRect().width);
  assert.ok(initialOutput<=661,`输出与画质也应使用660px紧凑内容区，实际 ${initialOutput}px`);
  await page.locator('[data-live-platform="Twitch"]').waitFor({state:'attached'});
  assert.equal(await page.locator('#liveCommentPlatforms select').count(),7);
  assert.equal(await page.locator('#livePlatformModes select').count(),2);
  assert.equal(await page.locator('#set-live .lc-group').count(),3,'正式直播设置应采用已确认的紧凑单列分组');
  assert.equal(await page.locator('#set-live details[open]').count(),0,'长说明和平台覆盖默认收起');
  assert.equal(await page.locator('body.live-preview-shell').count(),0,'正式页面不能带样板外壳');
  assert.equal(await page.evaluate(()=>typeof window.LIVE_PREVIEW_DATA),'undefined','正式页面不应注入预览数据');
  assert.equal(await page.locator('.ni:disabled').count(),0,'正式导航保持可操作');
  assert.equal(await page.locator('.settings-toc-item:disabled').count(),0,'正式目录保持可操作');
  assert.equal(await page.locator('[onclick="saveSettings()"]').isEnabled(),true,'保存入口必须是真实可用的入口');
  await openLivePlatforms();

  // 输出与其余设置的短选项共用紧凑宽度，长路径与说明保留空间。
  for(const theme of ['light','dark']){
    await page.evaluate(t=>document.documentElement.dataset.theme=t,theme);
    for(const width of [1920,1440,1280,1101,1100,1024,901,900,768,640,375,320]){
      await page.setViewportSize({width,height:1000});
      await settleLiveLayout();
      await page.waitForFunction(()=>{
        const probe=document.createElement('span');probe.style.cssText='position:fixed;visibility:hidden;color:var(--fg2)';document.body.append(probe);
        const expected=getComputedStyle(probe).color;probe.remove();
        return [...document.querySelectorAll('.ni:not(.on),.ni:not(.on)>.ico,.settings-toc-item:not(.on),.settings-toc-item i,.settings-toc-item>.settings-section-chevron')]
          .every(node=>getComputedStyle(node).color===expected);
      },null,{timeout:5000});
      const navigation=await page.evaluate(()=>{
        const probe=document.createElement('span');probe.style.cssText='position:fixed;visibility:hidden;color:var(--fg2)';document.body.append(probe);
        const expected=getComputedStyle(probe).color;probe.remove();
        const nodes=[...document.querySelectorAll('.ni:not(.on),.ni:not(.on)>.ico,.settings-toc-item:not(.on),.settings-toc-item i,.settings-toc-item>.settings-section-chevron')];
        return {expected,states:nodes.map(node=>({color:getComputedStyle(node).color,opacity:getComputedStyle(node).opacity}))};
      });
      assert.ok(navigation.states.every(state=>state.color===navigation.expected&&state.opacity==='1'),`${theme}/${width}: 未选中导航文字、编号和图标保持清晰：${JSON.stringify(navigation)}`);
      await page.locator('#set-output').scrollIntoViewIfNeeded();
      if(process.env.OUTPUT_LAYOUT_SCREENSHOT&&theme==='light'&&width===Number(process.env.OUTPUT_LAYOUT_SCREENSHOT_WIDTH||1920)){
        fs.mkdirSync(path.dirname(process.env.OUTPUT_LAYOUT_SCREENSHOT),{recursive:true});
        await page.locator('#set-output').screenshot({path:process.env.OUTPUT_LAYOUT_SCREENSHOT});
      }
      const output=await page.locator('#set-output').evaluate(el=>{
        const box=node=>{const r=node.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,right:r.right,bottom:r.bottom};};
        return {section:box(el),client:el.clientWidth,scroll:el.scrollWidth,
          controls:[...el.querySelectorAll('select')].map(box),
          video:box(document.getElementById('s_resolution')),audio:box(document.getElementById('s_audio')),
          meta:box(document.getElementById('sw_meta')),thumb:box(document.getElementById('sw_thumb')),
          other:box(document.getElementById('s_live_stream_method'))};
      });
      assert.ok(output.controls.every(box=>box.width<=341),`${theme}/${width}: output selects must stay compact: ${JSON.stringify(output.controls)}`);
      assert.ok(output.controls.every(box=>box.width>=100&&box.height===34),`${theme}/${width}: native controls must remain usable`);
      assert.ok(output.scroll<=output.client+1,`${theme}/${width}: output section overflow`);
      assert.ok(output.controls.every(box=>box.x>=output.section.x-1&&box.right<=output.section.right+1),`${theme}/${width}: control outside section`);
      assert.ok(output.section.width<=661,`${theme}/${width}: 输出标题和内容应同样收为660px以内`);
      assert.ok(output.audio.y>output.video.bottom&&Math.abs(output.audio.x-output.video.x)<1,
        `${theme}/${width}: 视频与音频配置应按单列顺序对齐`);
      assert.ok(output.thumb.y>output.meta.bottom-1,`${theme}/${width}: 附加开关也应逐行排列`);
      assert.ok(output.other.width<=341,`${theme}/${width}: live selects must stay compact: ${output.other.width}`);

      const settings=await page.locator('#page-settings').evaluate(el=>{
        const box=node=>{const r=node.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,right:r.right,bottom:r.bottom};};
        const visible=node=>node.getClientRects().length>0;
        const context=document.createElement('canvas').getContext('2d');
        const natural=select=>{
          const style=getComputedStyle(select);
          context.font=`${style.fontStyle} ${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
          const spacing=parseFloat(style.letterSpacing)||0;
          const text=Math.max(...[...select.options].map(option=>context.measureText(option.label).width+Math.max(0,[...option.label].length-1)*spacing));
          return Math.ceil(text+['paddingLeft','paddingRight','borderLeftWidth','borderRightWidth'].reduce((sum,key)=>sum+(parseFloat(style[key])||0),0)+4);
        };
        const fromIds=ids=>ids.map(id=>document.getElementById(id)).filter(Boolean);
        const naturalGroups=[
          fromIds(['presetSelect']),fromIds(['s_proxytype']),fromIds(['s_cookiemode','s_browser','s_rplay_auth']),
          fromIds(['s_subtitle_type','s_subtitle_lang_preset']),fromIds(['s_bili_policy']),fromIds(['s_task_order']),
          ...[...el.querySelectorAll('#set-output .output-settings-group')].map(group=>[...group.querySelectorAll('select')]),
          ...[...el.querySelectorAll('#fanboxSettingsFields .fb-settings-list')].map(group=>[...group.querySelectorAll('select')])
        ].filter(nodes=>nodes.length);
        return {
          sections:[...el.querySelectorAll('.settings-stack>.settings-section')].filter(visible).map(node=>({id:node.id,...box(node),client:node.clientWidth,scroll:node.scrollWidth})),
          numbers:[...el.querySelectorAll('input[type=number]')].filter(visible).map(node=>({id:node.id||node.dataset.fanboxOption,...box(node)})),
          selects:[...el.querySelectorAll('select')].filter(visible).map(node=>({id:node.id||node.dataset.fanboxOption,...box(node),wrappers:node.parentElement.matches('.sel'),arrows:node.parentElement.querySelectorAll(':scope>.cv').length})),
          outputTitles:[...el.querySelectorAll('#set-output h3,#set-output h4')].map(node=>node.textContent),
          naturalGroups:naturalGroups.map(nodes=>({expected:Math.max(...nodes.map(natural)),fields:nodes.filter(visible).map(node=>({
            id:node.id||node.dataset.fanboxOption,width:box(node).width,
            available:box(node.parentElement.parentElement).right-box(node.parentElement).x
          }))})),
          fanbox:box(document.getElementById('set-fanbox')),
          pageClient:document.querySelector('.pad').clientWidth,pageScroll:document.querySelector('.pad').scrollWidth
        };
      });
      assert.equal(settings.sections.length,10,`${theme}/${width}: 全部10个设置区应保持可用`);
      assert.ok(settings.sections.every(section=>section.width<=661&&section.scroll<=section.client+1),
        `${theme}/${width}: 所有设置标题、分隔线与内容应界定在紧凑区域，不能溢出：${JSON.stringify(settings.sections)}`);
      assert.ok(settings.selects.every(select=>select.wrappers&&select.arrows===1&&select.width<=341&&select.height===34),
        `${theme}/${width}: 设置区每个原生下拉应有一个装饰箭头并保持紧凑：${JSON.stringify(settings.selects)}`);
      assert.ok(settings.numbers.every(number=>Math.abs(number.width-100)<1),`${theme}/${width}: 设置数字输入框统一100px：${JSON.stringify(settings.numbers)}`);
      assert.ok(settings.outputTitles.some(title=>title.includes('视频'))&&settings.outputTitles.some(title=>title.includes('音频')),
        `${theme}/${width}: 视频/音频单列仍应有清楚分组标题`);
      assert.ok(settings.pageScroll<=settings.pageClient+1,`${theme}/${width}: 页面不可横向撑宽`);
      assert.ok(settings.naturalGroups.every(group=>group.fields.every(field=>
        Math.abs(field.width-Math.min(group.expected,field.available))<=1)),
        `${theme}/${width}: 其余下拉也应以同组最长文字为自然宽度，不得固定拉长：${JSON.stringify(settings.naturalGroups)}`);

      const compact=await page.locator('#page-settings').evaluate(el=>{
        const box=node=>{const r=node.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,right:r.right,bottom:r.bottom};};
        const visible=node=>node.getClientRects().length>0;
        const live=document.getElementById('set-live'),body=live.querySelector('.settings-section-body');
        const list=document.getElementById('liveCommentPlatforms');
        const context=document.createElement('canvas').getContext('2d');
        const textWidth=select=>{
          const style=getComputedStyle(select);
          context.font=`${style.fontStyle} ${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
          const spacing=parseFloat(style.letterSpacing)||0;
          const text=Math.max(...[...select.options].map(option=>context.measureText(option.label).width+Math.max(0,[...option.label].length-1)*spacing));
          return Math.ceil(text+['paddingLeft','paddingRight','borderLeftWidth','borderRightWidth'].reduce((sum,key)=>sum+(parseFloat(style[key])||0),0)+4);
        };
        const groups=[['s_live_stream_method','s_live_mode'].map(id=>document.getElementById(id)),
          [document.getElementById('s_live_danmaku_formats')],
          [...document.querySelectorAll('#livePlatformModes select')],
          [...document.querySelectorAll('#liveCommentPlatforms select')]];
        return {
          live:box(live),body:box(body),liveScroll:live.scrollWidth,liveClient:live.clientWidth,
          liveSelects:[...live.querySelectorAll('select')].filter(visible).map(node=>({id:node.id||node.getAttribute('data-live-comment-platform')||node.getAttribute('data-live-platform'),...box(node)})),
          shortSelects:[...el.querySelectorAll('.settings-section-body>.row>.sel>select')].filter(visible).map(node=>({id:node.id,...box(node)})),
          hints:[...body.querySelectorAll('.lc-hint')].filter(visible).map(box),
          stream:box(document.getElementById('s_live_stream_method')),mode:box(document.getElementById('s_live_mode')),
          platformRows:[...list.querySelectorAll('.live-platform-row')].map(row=>({...box(row),label:box(row.querySelector('.lb')),select:box(row.querySelector('select'))})),
          numbers:[...live.querySelectorAll('input[type=number]')].map(node=>({id:node.id,...box(node)})),
          rows:[...live.querySelectorAll('.lc-row')].filter(visible).map(row=>({label:box(row.querySelector('.lc-label')),control:box(row.querySelector('select,input,.sw'))})),
          groups:groups.map(nodes=>({ids:nodes.map(node=>node.id||node.dataset.livePlatform||node.dataset.liveCommentPlatform),widths:nodes.map(node=>box(node).width),expected:Math.max(...nodes.map(textWidth))})),
          groupPadding:[...live.querySelectorAll('.lc-group')].map(group=>({left:getComputedStyle(group).paddingLeft,right:getComputedStyle(group).paddingRight})),
          arrowCounts:[...live.querySelectorAll('select')].map(node=>node.parentElement.querySelectorAll(':scope>.cv').length),
          path:box(document.getElementById('s_rplay_profile')),args:box(document.getElementById('s_ytdlp_default_args')),
          pageClient:document.querySelector('.pad').clientWidth,pageScroll:document.querySelector('.pad').scrollWidth
        };
      });
      assert.ok(compact.live.width<=661&&compact.body.width<=661,`${theme}/${width}: live标题、分隔线和表单应统一为660px以内`);
      assert.ok(compact.liveSelects.every(box=>box.width>=100&&box.width<=341&&box.height===34),
        `${theme}/${width}: live/platform selects must remain compact and usable: ${JSON.stringify(compact.liveSelects)}`);
      assert.ok(compact.shortSelects.every(box=>box.width<=341),`${theme}/${width}: other short settings must share the width limit: ${JSON.stringify(compact.shortSelects)}`);
      assert.ok(compact.numbers.length===6&&compact.numbers.every(box=>Math.abs(box.width-100)<1),`${theme}/${width}: 直播数字框统一100px`);
      assert.ok(compact.liveScroll<=compact.liveClient+1&&compact.pageScroll<=compact.pageClient+1,`${theme}/${width}: compact settings must not overflow`);
      assert.ok(compact.liveSelects.every(box=>box.x>=compact.body.x-1&&box.right<=compact.body.right+1),`${theme}/${width}: live control outside body`);
      assert.ok(compact.hints.every(box=>box.x>=compact.body.x-1&&box.right<=compact.body.right+1),`${theme}/${width}: explanatory text outside body`);
      assert.ok(compact.mode.y>=compact.stream.bottom-1,`${theme}/${width}: 录制方式按单列逐行排列`);
      assert.ok(compact.platformRows[1].y>=compact.platformRows[0].bottom-1,`${theme}/${width}: 平台默认值也使用单列`);
      assert.ok(compact.groupPadding.every(group=>group.left==='0px'&&group.right==='0px'),`${theme}/${width}: 不再使用大卡片左右留白`);
      assert.ok(compact.groups.every(group=>group.widths.every(value=>Math.abs(value-group.expected)<=1)),
        `${theme}/${width}: 下拉框必须按最长选项留出必要内边距，同组等宽：${JSON.stringify(compact.groups)}`);
      assert.ok(compact.arrowCounts.length===12&&compact.arrowCounts.every(count=>count===1),`${theme}/${width}: 每个下拉框都应有且只有一个方向箭头`);
      if(width>560){
        assert.ok(compact.rows.every(row=>row.label.right<=row.control.x+1&&Math.abs(row.control.x-compact.stream.x)<1),`${theme}/${width}: 标签在左且控件列对齐`);
      }else{
        assert.ok(compact.rows.every(row=>row.control.y>=row.label.bottom-1),`${theme}/${width}: 窄屏标签可换到控件上方`);
        assert.ok(compact.platformRows.every(row=>row.select.y>=row.label.bottom-1),`${theme}/${width}: 窄屏平台标签与控件正常换行`);
      }
      if(width>=1101){
        assert.ok(compact.path.width>300&&compact.args.width>320,`${theme}/${width}: long paths and custom arguments must retain reading space`);
      }
    }
  }

  await page.locator('[data-live-comment-platform="Bilibili"]').selectOption('off');
  await page.locator('[data-live-platform="YouTube"]').selectOption('live_edge');
  const liveConfig=await page.evaluate(()=>collectCfg());
  assert.equal(JSON.parse(liveConfig.LIVE_DANMAKU_PLATFORMS).Bilibili,'off');
  assert.equal(JSON.parse(liveConfig.LIVE_PLATFORM_MODES).YouTube,'live_edge');
  await page.locator('[data-live-comment-platform="Bilibili"]').selectOption('inherit');
  await page.locator('[data-live-platform="YouTube"]').selectOption('auto');

  // 原生下拉列表的真实展开状态驱动方向，不以focus或点击次数猜测。
  await page.setViewportSize({width:1440,height:1100});
  const stream=page.locator('#s_live_stream_method');
  const arrowState=()=>stream.evaluate(node=>({open:node.matches(':open'),transform:getComputedStyle(node.parentElement.querySelector('.cv')).transform}));
  assert.deepEqual(await arrowState(),{open:false,transform:'matrix(0, -1, 1, 0, 0, 0)'});
  await stream.focus();
  assert.equal((await arrowState()).open,false,'只聚焦不能把箭头误判为展开');
  await stream.click();
  assert.deepEqual(await arrowState(),{open:true,transform:'none'});
  await page.screenshot({path:path.resolve(root,'..','debug','验证记录','直播正式接入-下拉展开.png')});
  await stream.press('Escape');
  assert.deepEqual(await arrowState(),{open:false,transform:'matrix(0, -1, 1, 0, 0, 0)'});
  await stream.press('Alt+ArrowDown');
  assert.deepEqual(await arrowState(),{open:true,transform:'none'});
  await stream.press('Enter');
  assert.deepEqual(await arrowState(),{open:false,transform:'matrix(0, -1, 1, 0, 0, 0)'});

  // 通过正式保存函数写入合成HTTP接口，再刷新校验，防止接入的仍是只读样板。
  const originalConfig=structuredClone(config);
  for(const [id,value] of [['s_live_timeout','17'],['s_live_retries','3'],['s_live_watchdog','75'],['s_live_free_mb','768'],['s_live_bitrate','9000'],['s_live_danmaku_offset','250']])await page.locator('#'+id).fill(value);
  await page.locator('#s_live_mode').selectOption('catch_up');
  await page.locator('#s_live_danmaku_formats').selectOption('ass');
  for(const id of ['sw_live_danmaku','sw_live_danmaku_anon'])if(!(await page.locator('#'+id).evaluate(node=>node.classList.contains('on'))))await page.locator('#'+id).click();
  await page.locator('[data-live-comment-platform="Bilibili"]').selectOption('off');
  await page.locator('[data-live-platform="YouTube"]').selectOption('live_edge');
  await page.evaluate(()=>saveSettingsNoAlert());
  const savedFields={LIVE_DOWNLOAD_TIMEOUT:17,LIVE_MAX_RETRIES:3,LIVE_WATCHDOG_SECONDS:75,LIVE_MIN_FREE_MB:768,LIVE_ESTIMATED_BITRATE_KBPS:9000,LIVE_DANMAKU_OFFSET_MS:250,LIVE_MODE:'catch_up',LIVE_DANMAKU_FORMATS:'ass',LIVE_DANMAKU_ENABLED:1,LIVE_DANMAKU_ANONYMIZE:1};
  for(const [key,value] of Object.entries(savedFields))assert.equal(config[key],value,`${key}应由正式保存函数提交`);
  assert.equal(JSON.parse(config.LIVE_DANMAKU_PLATFORMS).Bilibili,'off');
  assert.equal(JSON.parse(config.LIVE_PLATFORM_MODES).YouTube,'live_edge');
  await page.reload();await page.locator('[data-fanbox-option="fan_cards.scope"]').waitFor({state:'attached'});await page.locator('.ni[data-page="settings"]').click();
  await page.waitForFunction(()=>document.getElementById('s_live_timeout').value==='17');
  await page.locator('[data-live-platform="Twitch"]').waitFor({state:'attached'});
  const reloaded=await page.evaluate(()=>collectCfg());
  for(const [key,value] of Object.entries(savedFields))assert.equal(reloaded[key],value,`${key}刷新后应保留`);
  assert.equal(JSON.parse(reloaded.LIVE_DANMAKU_PLATFORMS).Bilibili,'off');
  assert.equal(JSON.parse(reloaded.LIVE_PLATFORM_MODES).YouTube,'live_edge');
  assert.equal(await page.locator('#set-live details[open]').count(),0,'刷新后平台详情仍默认收起，内部值继续保留');
  config=originalConfig;
  await page.reload();await page.locator('[data-fanbox-option="fan_cards.scope"]').waitFor({state:'attached'});await page.locator('.ni[data-page="settings"]').click();
  await page.locator('[data-live-platform="Twitch"]').waitFor({state:'attached'});await settleLiveLayout();

  // 其余设置的真实保存函数与依赖行也要在布局调整后继续工作。
  const otherOriginalConfig=structuredClone(config);
  for(const [id,value] of [['s_resolution','1080'],['s_codec','h264'],['s_audio','192'],['s_format','mkv'],['s_audiomode','2'],['s_audiofmt','mp3'],['s_hwaccel','h264_nvenc']])await page.locator('#'+id).selectOption(value);
  for(const [id,steps] of [['s_threads',11],['s_speed',3]]){
    await page.locator('#'+id).press('Home');
    for(let i=0;i<steps;i++)await page.locator('#'+id).press('ArrowRight');
  }
  await switchOn('sw_proxy',true);
  await page.locator('#s_proxytype').selectOption('socks5');
  await page.locator('#s_proxyaddr').fill('127.0.0.9');
  await page.locator('#s_proxyport').fill('1088');
  await switchOn('sw_cookies',true);
  await page.locator('#s_cookiemode').selectOption('1');
  assert.equal(await page.locator('#row_browser').isVisible(),false,'文件Cookie模式应隐藏浏览器行');
  await page.locator('#s_cookiemode').selectOption('2');
  assert.equal(await page.locator('#row_browser').isVisible(),true,'浏览器Cookie模式应显示浏览器行');
  assert.equal(await page.locator('#row_profile').isVisible(),true);
  await page.locator('#s_browser').selectOption('firefox');
  await page.locator('#s_profile').fill('synthetic-profile');
  await page.locator('#s_rplay_profile').fill('synthetic-rplay');
  await switchOn('sw_subtitles',false);
  assert.equal(await page.locator('#s_subtitle_type').isDisabled(),true);
  await switchOn('sw_subtitles',true);
  await page.locator('#s_subtitle_type').selectOption('manual');
  await page.locator('#s_subtitle_lang_preset').selectOption('custom');
  assert.equal(await page.locator('#row_subtitle_custom').isVisible(),true);
  await page.locator('#s_subtitle_langs').fill('ja.*,en.*');
  await switchOn('sw_winfn',false);await switchOn('sw_strict',true);
  await page.locator('#s_bili_policy').selectOption('select');
  await switchOn('sw_youtube_po_token',true);
  await switchOn('sw_task_mixed',false);
  assert.equal(await page.locator('#s_task_live_parallel').isDisabled(),true);
  assert.equal(await page.locator('#s_task_download_parallel').isDisabled(),true);
  await switchOn('sw_task_mixed',true);
  for(const [id,value] of [['s_task_parallel','4'],['s_task_live_parallel','3'],['s_task_download_parallel','2'],['s_task_download_speed','1.5']])await page.locator('#'+id).fill(value);
  await page.locator('#s_task_order').selectOption('download_first');
  await page.locator('#s_ytdlp_default_args').fill('--sleep-requests 1');
  await switchOn('sw_log',false);
  await page.locator('#fanboxAnonymous').check();
  await page.locator('#fanboxCookieFile').fill('fixture-cookies.txt');
  await page.locator('#fanboxSettingsFields [data-fanbox-option="network.file_concurrency"]').fill('3');
  await page.locator('#fanboxSettingsFields [data-fanbox-option="network.file_concurrency"]').press('Tab');
  const favorites=page.locator('#fanboxSettingsFields [data-fanbox-option="naming.favorites"]');
  await favorites.fill('images/{title}.jpg\nimages/{post_id}.jpg');await favorites.press('Tab');
  await settleLiveLayout();
  await page.waitForFunction(()=>[...document.querySelectorAll('#fanboxSettingsFields select')]
    .every(node=>node.parentElement.matches('.sel')&&node.parentElement.querySelectorAll(':scope>.cv').length===1));
  await page.locator('#fanboxSettingsFields [data-fanbox-option="naming.images"]').fill('images/{title}.jpg');
  await page.locator('#fanboxSettingsFields [data-fanbox-option="naming.images"]').press('Tab');
  await page.evaluate(()=>saveSettingsNoAlert());
  const otherSaved={RESOLUTION:'1080',CODEC:'h264',AUDIO_QUALITY:'192',OUTPUT_FORMAT:'mkv',AUDIO_MODE:'2',AUDIO_FORMAT:'mp3',
    HWACCEL:'h264_nvenc',THREADS:12,SPEED_LIMIT:3,PROXY_ENABLED:1,PROXY_TYPE:'socks5',PROXY_ADDR:'127.0.0.9',PROXY_PORT:'1088',
    USE_COOKIES:1,COOKIE_MODE:2,BROWSER_NAME:'firefox',BROWSER_PROFILE:'synthetic-profile',RPLAY_FIREFOX_PROFILE:'synthetic-rplay',
    DOWNLOAD_SUBTITLES:1,SUBTITLE_TYPE:'manual',SUBTITLE_LANGS:'ja.*,en.*',WIN_FILENAMES:0,STRICT_FILENAME:1,
    BILI_MULTIP_POLICY:'select',YOUTUBE_PO_TOKEN_ENABLED:1,TASK_MAX_PARALLEL:4,TASK_LIVE_PARALLEL:3,TASK_DOWNLOAD_PARALLEL:2,
    TASK_DOWNLOAD_SPEED_LIMIT:1.5,TASK_ORDER:'download_first',TASK_MIXED_PARALLEL:1,YTDLP_DEFAULT_ARGS:'--sleep-requests 1',ENABLE_LOG:0,
    FANBOX_ANONYMOUS:1,FANBOX_COOKIE_FILE:'fixture-cookies.txt'};
  for(const [key,value] of Object.entries(otherSaved))assert.equal(config[key],value,`${key}应提交真实保存入口`);
  const savedFanbox=JSON.parse(config.FANBOX_OPTIONS);
  assert.equal(savedFanbox.network.file_concurrency,3);
  assert.deepEqual(savedFanbox.naming.favorites,['images/{title}.jpg','images/{post_id}.jpg']);
  assert.equal(savedFanbox.naming.images,'images/{title}.jpg');
  await reloadSettings();
  const otherReloaded=await page.evaluate(()=>collectCfg());
  for(const [key,value] of Object.entries(otherSaved))assert.equal(otherReloaded[key],value,`${key}刷新后应保留`);
  const reloadedFanbox=JSON.parse(otherReloaded.FANBOX_OPTIONS);
  assert.equal(reloadedFanbox.network.file_concurrency,3);
  assert.deepEqual(reloadedFanbox.naming.favorites,['images/{title}.jpg','images/{post_id}.jpg']);
  assert.equal(reloadedFanbox.naming.images,'images/{title}.jpg');
  assert.equal(await page.locator('#row_browser').isVisible(),true);
  assert.equal(await page.locator('#row_subtitle_custom').isVisible(),true);
  config=otherOriginalConfig;await reloadSettings();
  assert.equal(await page.locator('#row_subtitle_custom').isVisible(),false,'恢复默认后自定义字幕行继续隐藏');
  assert.equal(await page.locator('#presetSaveRow').isVisible(),false,'预设另存行不能被紧凑布局强行显示');

  await page.setViewportSize({width:1440,height:3000});await page.evaluate(()=>applyTheme('light',false));await settleLiveLayout();
  for(const [id,name] of [['set-output','输出画质'],['set-network','网络代理'],['set-cookie','Cookie登录'],['set-platform','平台专项'],['set-tasks','任务并发']]){
    await page.locator('#'+id).scrollIntoViewIfNeeded();
    await page.locator('#'+id).screenshot({path:path.resolve(root,'..','debug','验证记录',`全设置紧凑-${name}.png`)});
  }
  await page.setViewportSize({width:1440,height:1100});

  await page.evaluate(()=>document.documentElement.dataset.theme='light');
  await page.locator('#set-live').scrollIntoViewIfNeeded();
  await closeLiveDetails();
  const livePreview=process.env.LIVE_LAYOUT_SCREENSHOT||path.resolve(root,'..','debug','验证记录','直播正式接入-预览.png');
  fs.mkdirSync(path.dirname(livePreview),{recursive:true});
  await page.locator('#set-live').screenshot({path:livePreview});
  for(const [mode,disabled] of [['0',true],['1',true],['2',false],['3',false]]){
    await page.locator('#s_audiomode').selectOption(mode);
    assert.equal(await page.locator('#s_audiofmt').isDisabled(),disabled);
  }
  await page.locator('#s_audiomode').selectOption(String(data.config.AUDIO_MODE));
  for(const [id,key] of [['sw_meta','EMBED_META'],['sw_thumb','DOWNLOAD_THUMB']]){
    const original=await page.evaluate(key=>collectCfg()[key],key);
    await page.locator('#'+id).click();
    assert.equal(await page.evaluate(key=>collectCfg()[key],key),original?0:1);
    await page.locator('#'+id).click();
    assert.equal(await page.evaluate(key=>collectCfg()[key],key),original);
  }
  await page.setViewportSize({width:1440,height:1000});
  await page.evaluate(()=>document.documentElement.dataset.theme='dark');
  await page.locator('#set-fanbox').scrollIntoViewIfNeeded();

  const checkboxes=await page.locator('#set-fanbox .fb-switch').evaluateAll(items=>items.filter(el=>el.getClientRects().length).map(el=>({width:el.getBoundingClientRect().width,height:el.getBoundingClientRect().height})));
  assert.ok(checkboxes.every(box=>box.width===32&&box.height===18));
  assert.equal(await page.locator('#fanboxSettingsFields [data-fb-fold="occasional"]').getAttribute('open'),null);
  await page.locator('#fanboxSettingsFields [data-fb-fold="occasional"]>summary').click();
  const rows=await page.locator('#fanboxSettingsFields .fb-field').evaluateAll(items=>items.filter(el=>el.getClientRects().length).map(el=>el.getBoundingClientRect().y));
  assert.ok(rows.every((y,i)=>i===0||y>rows[i-1]));
  await page.locator('.ni[data-page="download"]').click();await page.locator('#urlInput').fill('https://sample.fanbox.cc');
  await page.locator('#btnStart').click();await page.locator('#fanboxTaskDialog').waitFor({state:'visible'});
  assert.equal(await page.locator('#fanboxTaskDialog .fb-field select').evaluateAll(nodes=>nodes.some(node=>node.parentElement.matches('.sel'))),false,
    'FANBOX任务弹窗应保留原控件布局，设置页包装规则不能越界');
  await page.locator('#fanboxTaskFields [data-fanbox-option="filters.fee.maximum"]').fill('1000');
  await page.locator('#fanboxTaskFields [data-fanbox-option="filters.fee.maximum"]').press('Tab');

  await page.locator('#fanboxTaskConfirm').click();await page.locator('#fanboxTaskDialog').waitFor({state:'hidden'});
  assert.equal(created[0].options.filters.fee.maximum,1000);
  assert.equal(JSON.parse(config.FANBOX_OPTIONS).filters.fee.maximum,null);
  await page.locator('.ni[data-page="history"]').click();await page.locator('.fb-history').click();await page.locator('#fanboxHistoryDialog .fb-post').waitFor({state:'attached'});
  assert.equal(await page.locator('#fanboxDownloadSelected').isVisible(),false);assert.equal(await page.locator('#fanboxSelectAll').isVisible(),false);
  await page.locator('#fanboxVerify').click();await page.locator('#fanboxVerification').waitFor();
  assert.ok((await page.locator('#fanboxVerificationStatus').textContent()).includes('通过 1'));
  await page.locator('#fanboxHistoryDialog [data-fb-close]').click();
  for(const theme of ['light','dark']){
    await page.evaluate(t=>document.documentElement.dataset.theme=t,theme);
    for(const width of [320,768,1440]){
      await page.setViewportSize({width,height:900});await page.evaluate(()=>setActivePage('settings'));await page.locator('#set-fanbox').scrollIntoViewIfNeeded();
      const overflow=await page.locator('#set-fanbox').evaluate(el=>({client:el.clientWidth,scroll:el.scrollWidth}));
      assert.ok(overflow.scroll<=overflow.client+1,`${theme}/${width}: settings overflow ${JSON.stringify(overflow)}`);
      const toolbar=page.locator('#fanboxSettingsActions');
      await toolbar.getByRole('button',{name:'命名预览',exact:true}).click();
      await page.locator('#fanboxSettingsFields .fb-name-preview').waitFor({state:'visible'});
      const layout=await toolbar.evaluate(el=>{
        const boxes=[...el.children].map(button=>button.getBoundingClientRect());
        const fold=document.querySelector('#fanboxSettingsFields [data-fb-fold="occasional"]');
        return {display:getComputedStyle(el).display,ys:boxes.map(box=>box.y),right:Math.max(...boxes.map(box=>box.right)),
          edge:el.getBoundingClientRect().right,previewEnd:el.nextElementSibling.getBoundingClientRect().bottom,foldTop:fold.getBoundingClientRect().top};
      });
      assert.equal(layout.display,'flex');
      assert.ok(layout.ys.every(y=>Math.abs(y-layout.ys[0])<1),`${theme}/${width}: buttons must share a row`);
      assert.ok(layout.right<=layout.edge+1&&layout.previewEnd<=layout.foldTop,`${theme}/${width}: tools must precede one-run options`);

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
  assert.deepEqual(errors,[]);console.log('通过：全部设置区24组主题/尺寸紧凑单列、动态下拉/箭头与长文本空间、各类配置保存刷新、条件隐藏和FANBOX重建；原任务历史与6组弹窗布局保持；无 JS 错误');
}finally{
  // End the synthetic SSE stream before closing the browser. Otherwise test
  // workers can retain an active connection while the browser is shutting down.
  server.closeAllConnections();await new Promise(resolve=>server.close(resolve));await browser.close();
}
