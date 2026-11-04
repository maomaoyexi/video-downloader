// 在独立浏览器和本机合成接口中验证设置目录滚动，避免使用用户登录数据。
import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {pathToFileURL} from 'node:url';

const {chromium}=await import(process.env.FANBOX_PLAYWRIGHT_MODULE||pathToFileURL('temp/fanbox-ui-qa/node_modules/playwright/index.mjs').href);
const root=process.cwd();
const data=JSON.parse(execFileSync('python',['-c','import json;from video_downloader.core.constants import DEFAULT_CONFIG;from video_downloader.platforms.fanbox.options import normalize_options;print(json.dumps(dict(config=DEFAULT_CONFIG,options=normalize_options())))'],{encoding:'utf8'}));
const server=http.createServer(async(req,res)=>{
  const url=new URL(req.url,'http://localhost');
  for await(const chunk of req){}
  if(url.pathname.startsWith('/api/')){
    if(url.pathname==='/api/events'){
      res.writeHead(200,{'Content-Type':'text/event-stream'});
      res.write('data: '+JSON.stringify({type:'ready',data:{logs:[],tasks:[],fanbox_jobs:[],download:{running:false}}})+'\n\n');return;
    }
    const payload={
      '/api/config':{version:'2.7.0',config:data.config},
      '/api/fanbox/options':{options:data.options,defaults:data.options,enabled:true,anonymous:true,cookie_file:''},
      '/api/fanbox/auth':{runtime:{available:true},status:'anonymous'},
      '/api/fanbox/jobs':{jobs:[]},'/api/tasks':{tasks:[]},'/api/history':{history:[]},
      '/api/live/capabilities':{platforms:[]},
    }[url.pathname]||{};
    res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify(payload));return;
  }
  const relative=url.pathname==='/'?'resource/templates/index.html':'resource'+url.pathname;
  if(!relative.startsWith('resource/')||relative.includes('..')){res.writeHead(404);res.end();return;}
  try{
    let body=fs.readFileSync(path.join(root,relative));
    if(relative.endsWith('.html'))body=Buffer.from(body.toString().replaceAll('__SESSION_TOKEN__','test-token'));
    res.setHeader('Content-Type',relative.endsWith('.js')?'application/javascript':relative.endsWith('.css')?'text/css':'text/html');res.end(body);
  }catch{res.writeHead(404);res.end();}
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const browser=await chromium.launch({headless:true,executablePath:process.env.FANBOX_BROWSER_EXECUTABLE||'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
const page=await browser.newPage({viewport:{width:1440,height:900}}),errors=[];
page.on('pageerror',error=>errors.push(error.message));
const active=()=>page.locator('.settings-toc-item.on').getAttribute('data-target');
async function frames(count=3){
  await page.evaluate(async count=>{for(let i=0;i<count;i++)await new Promise(resolve=>requestAnimationFrame(resolve));},count);
}
async function scrollTo(top){
  await page.locator('.pad').evaluate((pad,top)=>pad.scrollTo({top,behavior:'instant'}),top);
  await frames();
}
async function scrollTrace(direction){
  return page.evaluate(async direction=>{
    const pad=document.querySelector('.pad');
    const ids=[...document.querySelectorAll('.settings-toc-item')].map(item=>item.dataset.target);
    const settle=()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
    const samples=[],max=pad.scrollHeight-pad.clientHeight;
    const positions=[];
    for(let distance=0;distance<max;distance+=48)positions.push(direction==='down'?distance:max-distance);
    positions.push(direction==='down'?max:0);
    for(const top of positions){
      pad.scrollTo({top,behavior:'instant'});await settle();
      const item=document.querySelector('.settings-toc-item.on');
      samples.push({top:pad.scrollTop,id:item?.dataset.target,index:ids.indexOf(item?.dataset.target)});
    }
    return samples.filter((entry,index)=>index===0||entry.id!==samples[index-1].id);
  },direction);
}
async function clickAndTrack(target){
  const selectedBefore=await active()===target;
  const collapsedBefore=await page.locator('#'+target).evaluate(el=>el.classList.contains('is-collapsed'));
  await page.evaluate(()=>{
    window.__tocTrace=[];
    window.__tocObserver=new MutationObserver(()=>{
      const id=document.querySelector('.settings-toc-item.on')?.dataset.target;
      if(window.__tocTrace.at(-1)!==id)window.__tocTrace.push(id);
    });
    window.__tocObserver.observe(document.querySelector('#settingsToc'),{subtree:true,attributes:true,attributeFilter:['class']});
  });
  await page.locator(`.settings-toc-item[data-target="${target}"]`).click();
  await page.evaluate(()=>{
    const id=document.querySelector('.settings-toc-item.on')?.dataset.target;
    if(window.__tocTrace.at(-1)!==id)window.__tocTrace.push(id);
  });
  await page.evaluate(async()=>{
    const pad=document.querySelector('.pad');let last=pad.scrollTop,stable=0;
    for(let i=0;i<120&&stable<10;i++){
      await new Promise(resolve=>requestAnimationFrame(resolve));
      stable=Math.abs(pad.scrollTop-last)<.1?stable+1:0;last=pad.scrollTop;
    }
  });
  await frames(12);
  const trace=await page.evaluate(()=>{window.__tocObserver.disconnect();return window.__tocTrace;});
  assert.ok(trace.length>0&&trace.every(id=>id===target),`平滑跳转期间应保留所选章节 ${target}：${JSON.stringify(trace)}`);
  assert.equal(await active(),target);
  await assertCollapsed(target,selectedBefore?!collapsedBefore:false);
}
const collapsedKey='video-dl-settings-collapsed-sections';
const tocToggle=id=>page.locator(`#settingsToc .settings-section-toggle[data-section="${id}"]`);
const headerToggle=id=>page.locator(`#${id}>.settings-section-heading[data-section="${id}"]`);
async function assertCollapsed(id,collapsed){
  assert.equal(await page.locator('#'+id).evaluate(el=>el.classList.contains('is-collapsed')),collapsed);
  assert.equal(await page.locator('#'+id+'-body').evaluate(el=>el.hidden),collapsed);
  for(const toggle of [tocToggle(id),headerToggle(id)]){
    assert.equal(await toggle.getAttribute('aria-expanded'),String(!collapsed));
    assert.equal(await toggle.getAttribute('aria-controls'),id+'-body');
  }
}
async function clickPart(button,selector){
  const position=await button.evaluate((el,selector)=>{
    const parent=el.getBoundingClientRect(),part=el.querySelector(selector).getBoundingClientRect();
    return {x:part.x-parent.x+part.width/2,y:part.y-parent.y+part.height/2};
  },selector);
  await button.click({position});
}
async function clickBlank(button,edge='right'){
  const position=await button.evaluate((el,edge)=>{
    const box=el.getBoundingClientRect();
    return edge==='top'?{x:box.width/2,y:3}:edge==='bottom'?{x:box.width/2,y:box.height-3}:{x:box.width-4,y:box.height/2};
  },edge);
  await button.click({position});
}
async function manualTop(){
  await page.locator('.pad').evaluate(pad=>{
    pad.dispatchEvent(new WheelEvent('wheel',{bubbles:true,deltaY:-1}));
    pad.scrollTo({top:0,behavior:'instant'});
  });
  await frames(5);
}
async function expandAllSections(){
  await page.evaluate(()=>{
    for(const section of document.querySelectorAll('.settings-section.is-collapsed')){
      document.querySelector(`.settings-toc-item[data-target="${section.id}"]`).click();
    }
  });
  await manualTop();
}
async function collapsedSelection(current='set-network'){
  await page.evaluate(current=>{
    for(const section of document.querySelectorAll('.settings-section:not(.is-collapsed)')){
      section.querySelector(':scope > .settings-section-heading').click();
    }
    const button=document.querySelector(`.settings-toc-item[data-target="${current}"]`);
    button.click();button.click();
  },current);
  await frames(18);
  const prepared=await page.locator('.pad').evaluate(pad=>({top:pad.scrollTop,max:pad.scrollHeight-pad.clientHeight,
    current:document.querySelector('.settings-toc-item.on')?.dataset.target,
    collapsed:document.querySelectorAll('.settings-section.is-collapsed').length}));
  assert.equal(prepared.current,current);
  assert.equal(prepared.collapsed,10);
  assert.equal(prepared.top,0);
  assert.ok(prepared.max<=1,'需要复现所有章节收起后无法滚动的场景');
}
async function beginPressTrace(){
  await page.evaluate(()=>{
    const sample=()=>({id:document.querySelector('.settings-toc-item.on')?.dataset.target,top:document.querySelector('.pad').scrollTop});
    window.__pressHighlight=[sample()];
    window.__pressHighlightObserver=new MutationObserver(()=>window.__pressHighlight.push(sample()));
    window.__pressHighlightObserver.observe(document.querySelector('#settingsToc'),{subtree:true,attributes:true,attributeFilter:['class']});
  });
}
async function finishPressTrace(label,allowed){
  const trace=await page.evaluate(()=>{
    window.__pressHighlight.push({id:document.querySelector('.settings-toc-item.on')?.dataset.target,top:document.querySelector('.pad').scrollTop});
    window.__pressHighlightObserver.disconnect();return window.__pressHighlight;
  });
  console.log(label+'：'+JSON.stringify(trace));
  assert.ok(trace.every(entry=>allowed.includes(entry.id)),label+'不得途经第一项或无关章节：'+JSON.stringify(trace));
  return trace;
}
async function waitForClickScroll(){
  await page.evaluate(async()=>{
    const pad=document.querySelector('.pad');let last=pad.scrollTop,stable=0;
    for(let i=0;i<120&&stable<10;i++){
      await new Promise(resolve=>requestAnimationFrame(resolve));
      stable=Math.abs(pad.scrollTop-last)<.1?stable+1:0;last=pad.scrollTop;
    }
  });
  await frames(12);
}
async function pointerPosition(button,part){
  return button.evaluate((el,part)=>{
    const box=el.getBoundingClientRect();
    if(part==='blank')return {x:box.right-4,y:box.y+box.height/2};
    const child=el.querySelector(part).getBoundingClientRect();
    return {x:child.x+child.width/2,y:child.y+child.height/2};
  },part);
}
async function heldToggle(button,part,hold,label){
  await button.scrollIntoViewIfNeeded();await frames(3);
  const before=await active(),target=await button.getAttribute('data-section');
  const isToc=await button.evaluate(el=>el.classList.contains('settings-toc-item'));
  const wasCollapsed=await page.locator('#'+target).evaluate(el=>el.classList.contains('is-collapsed'));
  const position=await pointerPosition(button,part);
  await beginPressTrace();
  await page.mouse.move(position.x,position.y);await page.mouse.down();
  await frames(2);await page.waitForTimeout(Math.max(0,hold-34));
  await page.mouse.up();await waitForClickScroll();
  const trace=await finishPressTrace(label,[before,target]);
  const firstTarget=trace.findIndex(entry=>entry.id===target);
  assert.ok(firstTarget>=0&&trace.slice(firstTarget).every(entry=>entry.id===target),
    label+'选中目标后不得闪回原章节：'+JSON.stringify(trace));
  assert.equal(await active(),target);await assertCollapsed(target,isToc&&before!==target?false:!wasCollapsed);
}
try{
  await page.goto('http://127.0.0.1:'+server.address().port);
  await page.locator('[data-fanbox-option="fan_cards.scope"]').waitFor({state:'attached'});
  await page.locator('.ni[data-page="settings"]').click();
  // 平台内部的 details 改变页面高度时，目录仍应归属实际操作的章节。
  const occasional=page.locator('#fanboxSettingsFields details[data-fb-fold="occasional"]');
  const occasionalSummary=occasional.locator(':scope > summary');
  async function clickOccasional(){
    const box=await occasionalSummary.boundingBox();
    await page.mouse.move(box.x+box.width/2,box.y+box.height/2);
    await page.mouse.down();await frames(2);await page.waitForTimeout(100);
    await page.mouse.up();
    await waitForClickScroll();
  }
  async function scrollAfterFold(deltaY,target){
    await page.locator('.pad').evaluate(pad=>{
      window.__nestedFoldWheel=[];
      pad.addEventListener('wheel',event=>window.__nestedFoldWheel.push({top:pad.scrollTop,trusted:event.isTrusted}),{once:true});
    });
    const box=await page.locator('.pad').boundingBox();
    await page.mouse.move(box.x+box.width-24,box.y+box.height/2);
    await page.mouse.wheel(0,deltaY);await waitForClickScroll();
    const scrolled=await page.locator('.pad').evaluate(pad=>({top:pad.scrollTop,wheel:window.__nestedFoldWheel}));
    console.log('内部折叠后主动滚轮：'+JSON.stringify({deltaY,target,...scrolled}));
    assert.ok(scrolled.wheel.length===1&&scrolled.wheel[0].trusted,'必须用真实滚轮验证折叠后的阅读切换');
    assert.ok((scrolled.top-scrolled.wheel[0].top)*deltaY>0,'真实滚轮应沿输入方向改变阅读位置');
    assert.equal(await active(),target,'主动滚轮后应按阅读位置正常切换目录');
  }
  assert.equal(await occasional.evaluate(el=>el.open),false);
  await occasionalSummary.evaluate(summary=>{
    const pad=document.querySelector('.pad');
    pad.scrollTo({top:pad.scrollTop+summary.getBoundingClientRect().top-pad.getBoundingClientRect().top-pad.clientHeight/2,behavior:'instant'});
  });
  await frames(12);
  assert.equal(await active(),'set-platform','展开单次下载选项前应在平台专项内阅读');
  await beginPressTrace();await clickOccasional();
  await finishPressTrace('平台专项内展开单次下载选项',['set-platform']);
  assert.equal(await occasional.evaluate(el=>el.open),true);
  await scrollAfterFold(10000,'set-advanced');

  // 收起后续章节，覆盖长选项收缩将 scrollTop 压到新页面底部的边界。
  await headerToggle('set-tasks').click();await headerToggle('set-advanced').click();
  await waitForClickScroll();await manualTop();
  await occasionalSummary.evaluate(summary=>{
    const pad=document.querySelector('.pad');
    pad.scrollTo({top:pad.scrollTop+summary.getBoundingClientRect().top-pad.getBoundingClientRect().top-64,behavior:'instant'});
  });
  await frames(12);
  assert.equal(await active(),'set-platform','收起单次下载选项前应在平台专项内阅读');
  const expandedHeight=await page.locator('.pad').evaluate(pad=>pad.scrollHeight);
  await beginPressTrace();await clickOccasional();
  await finishPressTrace('平台专项内收起单次下载选项至页面底部',['set-platform']);
  assert.equal(await occasional.evaluate(el=>el.open),false);
  const foldedPage=await page.locator('.pad').evaluate(pad=>({height:pad.scrollHeight,top:pad.scrollTop,max:pad.scrollHeight-pad.clientHeight}));
  assert.ok(expandedHeight-foldedPage.height>600,'需要覆盖长选项收起造成的真实页面高度收缩');
  assert.ok(foldedPage.max-foldedPage.top<=2,'需要覆盖收起后滚动位置落在新页面底部的边界');
  assert.equal(await active(),'set-platform');

  // 原生 summary 的键盘激活和连续点击也不能让目录误选相邻章节。
  for(const key of ['Enter','Space']){
    for(const open of [true,false]){
      await occasionalSummary.focus();await beginPressTrace();
      await page.keyboard.down(key);await frames(2);await page.waitForTimeout(100);
      await page.keyboard.up(key);await waitForClickScroll();
      await finishPressTrace('单次下载选项 '+key+(open?'展开':'收起'),['set-platform']);
      assert.equal(await occasional.evaluate(el=>el.open),open);
    }
  }
  await beginPressTrace();
  for(let i=0;i<6;i++){
    await occasionalSummary.click();await frames(2);
    assert.equal(await occasional.evaluate(el=>el.open),i%2===0,'连续点击应逐次切换内部选项');
  }
  await waitForClickScroll();
  await finishPressTrace('单次下载选项连续展开收起',['set-platform']);

  for(const width of [375,1100,1440]){
    await page.setViewportSize({width,height:900});await frames(5);
    await occasionalSummary.evaluate(summary=>{
      const pad=document.querySelector('.pad');
      pad.scrollTo({top:pad.scrollTop+summary.getBoundingClientRect().top-pad.getBoundingClientRect().top-pad.clientHeight/2,behavior:'instant'});
    });
    await frames(5);await occasionalSummary.click();await waitForClickScroll();
    assert.equal(await occasional.evaluate(el=>el.open),true);
    assert.equal(await active(),'set-platform',width+'px 内部选项展开收起前应在平台专项内阅读');
    await beginPressTrace();
    await occasionalSummary.click();await waitForClickScroll();
    await occasionalSummary.click();await waitForClickScroll();
    await occasionalSummary.click();await waitForClickScroll();
    await finishPressTrace(width+'px 内部选项展开收起',['set-platform']);
    assert.equal(await occasional.evaluate(el=>el.open),false);
  }

  await occasionalSummary.focus();
  for(let i=0;i<10;i++){
    if(await headerToggle('set-advanced').evaluate(el=>el===document.activeElement))break;
    await page.keyboard.press('Tab');await frames(2);
  }
  assert.equal(await headerToggle('set-advanced').evaluate(el=>el===document.activeElement),true,
    '应使用真实 Tab 将焦点移到高级与诊断标题');
  await frames(5);
  assert.equal(await active(),'set-advanced','内部折叠后 Tab 跨章节应释放原章节的高亮锁');

  await scrollAfterFold(-10000,'set-presets');
  await clickAndTrack('set-output');
  assert.equal(await page.locator('.settings-toc-item.on').count(),1);
  await expandAllSections();
  await collapsedSelection();
  for(const [button,part,label] of [[tocToggle('set-network'),'span','目录文字'],[tocToggle('set-network'),'blank','目录空白'],[headerToggle('set-network'),'b','右侧标题文字'],[headerToggle('set-network'),'blank','右侧标题空白']]){
    await heldToggle(button,part,100,label+'按住100ms展开');
    await heldToggle(button,part,250,label+'按住250ms收起');
  }
  await collapsedSelection();
  await beginPressTrace();
  for(const target of ['set-output','set-live']){
    assert.notEqual(await active(),target,'快速切换应从未选中的目录开始');
    await assertCollapsed(target,true);
    const position=await pointerPosition(tocToggle(target),'span');
    await page.mouse.move(position.x,position.y);await page.mouse.down();await frames(2);await page.mouse.up();
    await assertCollapsed(target,false);
  }
  await waitForClickScroll();
  await finishPressTrace('快速切换不同目录',['set-network','set-output','set-live']);
  assert.equal(await active(),'set-live');
  await collapsedSelection();
  await tocToggle('set-network').focus();await beginPressTrace();
  await page.keyboard.down('Space');await frames(2);await page.waitForTimeout(100);await page.keyboard.up('Space');
  await waitForClickScroll();await finishPressTrace('按住空格激活当前目录',['set-network']);
  await assertCollapsed('set-network',false);
  for(const key of ['Enter','Space']){
    for(const collapsed of [true,false]){
      if(collapsed)await collapsedSelection();else await expandAllSections();
      const target='set-output',button=tocToggle(target);
      await button.focus();await frames(3);
      const before=await active();
      assert.notEqual(before,target,'键盘首次激活应从未选中的目录开始');
      await assertCollapsed(target,collapsed);
      await beginPressTrace();
      await page.keyboard.down(key);await frames(2);await page.waitForTimeout(100);
      await page.keyboard.up(key);await waitForClickScroll();
      const label=`未选中${collapsed?'已收起':'已展开'}目录 ${key} 首次定位`;
      const trace=await finishPressTrace(label,[before,target]);
      const firstTarget=trace.findIndex(entry=>entry.id===target);
      assert.ok(firstTarget>=0&&trace.slice(firstTarget).every(entry=>entry.id===target),
        label+'选中目标后不得闪回原章节：'+JSON.stringify(trace));
      assert.equal(await active(),target);
      await assertCollapsed(target,false);
    }
  }
  await expandAllSections();
  const outputToc=page.locator('.settings-toc-item[data-target="set-output"]');
  assert.notEqual(await active(),'set-output','鼠标首次激活应从未选中的目录开始');
  await assertCollapsed('set-output',false);
  await heldToggle(outputToc,'span',100,'未选中已展开目录按住100ms首次定位');
  await assertCollapsed('set-output',false);
  await clickPart(outputToc,'span');
  assert.equal(await page.locator('#set-output').evaluate(el=>el.classList.contains('is-collapsed')),true,
    '已经选中后再次点击目录文字应收起配置');
  await clickPart(outputToc,'span');
  assert.equal(await page.locator('#set-output').evaluate(el=>el.classList.contains('is-collapsed')),false,
    '再次点击目录文字应展开配置');
  for(const click of [()=>clickPart(outputToc,'i'),()=>clickBlank(outputToc)]){
    await click();await assertCollapsed('set-output',true);
    await click();await assertCollapsed('set-output',false);
  }
  const outputHeading=headerToggle('set-output');
  assert.equal(await outputHeading.evaluate(el=>el.tagName),'BUTTON','右侧标题整行应为原生按钮');
  assert.equal(await outputHeading.locator('button').count(),0,'标题中不应嵌套独立箭头按钮');
  for(const click of [()=>clickPart(outputHeading,'b'),()=>clickPart(outputHeading,'.rule'),()=>clickBlank(outputHeading)]){
    await click();await assertCollapsed('set-output',true);
    await click();await assertCollapsed('set-output',false);
  }
  await clickBlank(outputHeading,'top');await assertCollapsed('set-output',true);
  await clickBlank(outputHeading,'bottom');await assertCollapsed('set-output',false);
  await outputToc.focus();await outputToc.press('Enter');await assertCollapsed('set-output',true);
  await outputToc.press('Space');await assertCollapsed('set-output',false);
  await outputHeading.focus();await outputHeading.press('Enter');await assertCollapsed('set-output',true);
  await outputHeading.press('Space');await assertCollapsed('set-output',false);
  await page.locator('#s_resolution').selectOption('720');await assertCollapsed('set-output',false);
  await manualTop();
  assert.equal(await page.locator('#settingsToc .settings-section-toggle').count(),10,
    '左侧每个目录整行都应为可定位并切换当前章节的按钮');
  assert.equal(await page.locator('.settings-toc-row').count(),0,'目录应直接使用整行按钮，不保留旧小箭头wrapper');
  assert.equal(await page.locator('#settingsToc .settings-toc-item>.settings-section-chevron').count(),10);
  const sample=await scrollTrace('down');
  console.log('向下滚动高亮序列：'+JSON.stringify(sample));
  const backward=sample.find((entry,index)=>index>0&&entry.index<sample[index-1].index);
  assert.equal(backward,undefined,'向下连续滚动时，高亮不应跳回前面的章节：'+JSON.stringify(sample));
  assert.equal(await active(),'set-advanced','到达页面底部应选中最后一章');
  const upward=await scrollTrace('up');
  console.log('向上滚动高亮序列：'+JSON.stringify(upward));
  assert.equal(upward.find((entry,index)=>index>0&&entry.index>upward[index-1].index),undefined,
    '向上连续滚动时，高亮不应跳回后面的章节：'+JSON.stringify(upward));
  assert.equal(await active(),'set-presets','回到页面顶部应选中第一章');

  const longSection=await page.locator('#set-platform').evaluate(el=>{
    const pad=document.querySelector('.pad'),box=el.getBoundingClientRect();
    return {top:box.top-pad.getBoundingClientRect().top+pad.scrollTop,height:box.height};
  });
  assert.ok(longSection.height>600,'合成页面需要保留真实的长章节');
  for(const distance of [100,200,300]){
    await scrollTo(longSection.top+distance);
    assert.equal(await active(),'set-platform','长章节内部滚动应保持章节归属');
  }
  await scrollTo(0);
  await clickAndTrack('set-advanced');
  await clickAndTrack('set-output');
  await clickAndTrack('set-tasks');

  // 响应式重排与切换页面后，按当前实际阅读位置检查目录，而非沿用隐藏页旧状态。
  await page.evaluate(()=>document.getElementById('set-cookie').scrollIntoView({behavior:'instant',block:'start'}));
  await frames();
  for(const width of [1100,375,1440]){
    await page.setViewportSize({width,height:900});await frames(5);
    const expected=await page.evaluate(()=>{
      const pad=document.querySelector('.pad'),top=pad.getBoundingClientRect().top;
      const sections=[...document.querySelectorAll('.settings-toc-item')].map(item=>document.getElementById(item.dataset.target));
      return [...new Set([16,32,64,96].map(offset=>{
        let current=sections[0];for(const section of sections)if(section.getBoundingClientRect().top<=top+offset)current=section;
        return current.id;
      }))];
    });
    assert.ok(expected.includes(await active()),`${width}px 重排后目录应对应阅读位置，预期 ${expected}，实际 ${await active()}`);
  }
  await page.locator('.ni[data-page="download"]').click();await frames();
  await page.locator('.ni[data-page="settings"]').click();await frames(5);
  const returned=await page.evaluate(()=>{
    const pad=document.querySelector('.pad'),top=pad.getBoundingClientRect().top;
    const sections=[...document.querySelectorAll('.settings-toc-item')].map(item=>document.getElementById(item.dataset.target));
    return [...new Set([16,32,64,96].map(offset=>{
      let current=sections[0];for(const section of sections)if(section.getBoundingClientRect().top<=top+offset)current=section;
      return current.id;
    }))];
  });
  assert.ok(returned.includes(await active()),'重新进入设置页后应恢复正确章节');
  await scrollTo(0);
  assert.equal(await active(),'set-presets');

  await page.locator('.pad').evaluate(pad=>{
    window.__tocWheel=[];
    pad.addEventListener('wheel',event=>window.__tocWheel.push({top:pad.scrollTop,delta:event.deltaY,trusted:event.isTrusted}),{once:true});
  });
  await page.locator('.settings-toc-item[data-target="set-advanced"]').click();
  await frames(4);
  await page.mouse.move(1300,400);
  await page.mouse.wheel(0,-900);
  await page.evaluate(async()=>{
    const pad=document.querySelector('.pad');let last=pad.scrollTop,stable=0;
    for(let i=0;i<120&&stable<15;i++){
      await new Promise(resolve=>requestAnimationFrame(resolve));
      stable=Math.abs(pad.scrollTop-last)<.1?stable+1:0;last=pad.scrollTop;
    }
  });
  const interrupted=await page.locator('.pad').evaluate(pad=>({top:pad.scrollTop,max:pad.scrollHeight-pad.clientHeight,wheel:window.__tocWheel}));
  console.log('滚轮中断结果：'+JSON.stringify(interrupted));
  assert.ok(interrupted.wheel.length===1&&interrupted.wheel[0].trusted,'中断测试必须真正向滚动区域发送滚轮输入');
  assert.ok(interrupted.top<=interrupted.wheel[0].top+64,'向上滚轮后不应继续被旧平滑跳转拖向页面底部：'+JSON.stringify(interrupted));
  assert.notEqual(await active(),'set-advanced','手动滚轮打断后应释放所点目录的高亮锁');
  assert.equal(await page.locator('.settings-toc-item.on').count(),1);

  // 同一章的两个折叠入口应同步，且配置控件保留在 DOM 中。
  await expandAllSections();
  const sectionIds=await page.locator('.settings-toc-item').evaluateAll(items=>items.map(item=>item.dataset.target));
  assert.equal(await page.locator('.settings-section-toggle').count(),20,'每章需有目录与标题两个入口');
  assert.equal(await page.locator('.settings-toc-item button').count(),0,'目录整行按钮不应嵌套其他按钮');
  for(const id of sectionIds){
    await assertCollapsed(id,false);
    if(await active()!==id){
      await tocToggle(id).click();await assertCollapsed(id,false);
      assert.equal(await active(),id,'首次点击未选中目录应只选中并保持展开');
    }
    await tocToggle(id).click();await assertCollapsed(id,true);
    await headerToggle(id).click();await assertCollapsed(id,false);
  }
  await page.locator('#s_resolution').selectOption('720');
  await headerToggle('set-output').click();await assertCollapsed('set-output',true);
  assert.equal(await page.locator('#s_resolution').isVisible(),false);
  assert.equal(await page.evaluate(()=>collectCfg().RESOLUTION),'720','折叠不能清空设置');
  await headerToggle('set-output').click();await assertCollapsed('set-output',false);
  assert.equal(await page.locator('#s_resolution').inputValue(),'720');
  assert.equal(await page.locator('#presetSaveRow').isVisible(),false,'原本隐藏的另存行不能因展开而显示');
  await tocToggle('set-output').click();await assertCollapsed('set-output',true);
  await clickAndTrack('set-output');await assertCollapsed('set-output',false);
  assert.equal(await page.locator('#s_resolution').inputValue(),'720');

  await headerToggle('set-output').click();await headerToggle('set-cookie').click();
  assert.ok(await page.evaluate(key=>localStorage.getItem(key)?.includes('set-output')&&localStorage.getItem(key)?.includes('set-cookie'),collapsedKey));
  await page.reload();
  await page.locator('[data-fanbox-option="fan_cards.scope"]').waitFor({state:'attached'});
  await page.locator('.ni[data-page="settings"]').click();
  await assertCollapsed('set-output',true);await assertCollapsed('set-cookie',true);
  await assertCollapsed('set-network',false);
  assert.equal(await page.locator('#presetSaveRow').isVisible(),false);

  // 紧凑目录只显示数字时，整行按钮仍可切换已经折叠的内容。
  await page.locator('#settingsTocToggle').click();
  assert.equal(await page.locator('#settingsToc').evaluate(el=>el.classList.contains('collapsed')),true);
  await clickAndTrack('set-cookie');await assertCollapsed('set-cookie',false);
  await page.locator('#settingsTocToggle').click();
  await page.waitForFunction(()=>!document.querySelector('#settingsToc').classList.contains('collapsed'));

  await page.setViewportSize({width:375,height:900});await frames(5);
  await page.locator('.settings-toc-item[data-target="set-output"]').click();await assertCollapsed('set-output',false);
  await page.locator('#s_resolution').selectOption('720');
  await tocToggle('set-output').click();await assertCollapsed('set-output',true);
  await headerToggle('set-output').click();await assertCollapsed('set-output',false);
  assert.equal(await page.locator('#s_resolution').inputValue(),'720','窄屏折叠同样保留值');
  const mobile=await page.locator('.pad').evaluate(el=>({width:el.clientWidth,scroll:el.scrollWidth}));
  assert.ok(mobile.scroll<=mobile.width+1,'窄屏新折叠入口不应撑宽页面：'+JSON.stringify(mobile));

  await page.setViewportSize({width:1440,height:900});
  await page.evaluate(()=>document.documentElement.dataset.theme='light');
  for(const id of ['set-output','set-live']){
    if(!await page.locator('#'+id).evaluate(el=>el.classList.contains('is-collapsed')))await headerToggle(id).click();
  }
  await page.locator('.pad').evaluate(pad=>{
    pad.dispatchEvent(new WheelEvent('wheel',{bubbles:true,deltaY:-1}));
    pad.scrollTo({top:0,behavior:'instant'});
  });
  await frames(5);
  const preview=process.env.SETTINGS_FOLD_SCREENSHOT||path.resolve(root,'..','debug','验证记录','设置整行折叠-预览.png');
  fs.mkdirSync(path.dirname(preview),{recursive:true});
  await page.locator('#settingsToc').screenshot({path:path.join(path.dirname(preview),'设置整行折叠-目录预览.png')});
  await page.screenshot({path:preview});

  // 清除本次状态并刷新，证明默认展开，也不留下测试偏好。
  await page.evaluate(key=>localStorage.removeItem(key),collapsedKey);
  await page.reload();
  await page.locator('[data-fanbox-option="fan_cards.scope"]').waitFor({state:'attached'});
  await page.locator('.ni[data-page="settings"]').click();
  for(const id of sectionIds)await assertCollapsed(id,false);
  assert.equal(await page.locator('#presetSaveRow').isVisible(),false);
  assert.deepEqual(errors,[]);
  console.log('通过：内部单次下载选项鼠标/Enter/Space/连续点击及375/1100/1440px折叠保持所属章节，真实双向滚轮与Tab跨章恢复目录切换；目录稳定滚动；未选中目录鼠标/键盘首次定位并展开、当前目录文字/数字/空白再次切换、标题文字/横线/留白整行切换；10章状态、键盘、值保留、刷新记忆、紧凑目录与375px布局；无 JS 错误');
}finally{
  server.closeAllConnections();await new Promise(resolve=>server.close(resolve));await browser.close();
}
