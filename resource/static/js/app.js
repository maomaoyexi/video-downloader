/**
 * 多平台视频下载工具 WebUI - 主脚本
 *
 * SESSION_TOKEN 由服务端模板注入。
 * 图标定义在 icons.js 中（本脚本之前加载）。
 */

let evtSource = null;
let currentPlatform = "YouTube";
let lastUrlPlatform = "YouTube";
let download_running = false;
const SESSION_TOKEN = window.SESSION_TOKEN || "";

const PLATFORMS = [
  {name:"YouTube",color:"#FF0000"},
  {name:"Bilibili",color:"#FB7299"},
  {name:"Twitch",color:"#9146FF"},
  {name:"Niconico",color:"#4B4B4D"},
  {name:"NicoChannel",color:"#FF6B35"},
  {name:"Fantia",color:"#E6399B"},
  {name:"TwitCasting",color:"#00A0D1"},
  {name:"Twitter",color:"#1DA1F2"},
  {name:"Withny",color:"#22C55E"}
];
const PAGE_TITLES = {
  download: '下载任务', logs: '运行日志', settings: '下载设置', history: '下载历史',
  tools: '实用工具', help: '使用帮助', about: '关于软件'
};

function $(id){return document.getElementById(id);}

// ========== 图标系统（使用 icons.js 中的 ICONS） ==========

function svgIcon(name){
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name]||''}</svg>`;
}

/**
 * 将 [data-ico] 占位元素替换为对应 SVG 图标（幂等操作）。
 * @param {HTMLElement} [root] - 搜索根节点，默认为 document。
 */
function hydrateIcons(root){
  (root || document).querySelectorAll('[data-ico]:not([data-ico-done])').forEach(el => {
    el.innerHTML = svgIcon(el.dataset.ico);
    el.setAttribute('data-ico-done', '1');
  });
}

/**
 * 设置品牌连接状态指示点。
 * @param {boolean} online - 是否在线。
 */
function setConn(online){
  const m = $('brandMark');
  if(m){ m.classList.toggle('online', !!online); m.classList.toggle('offline', !online); }
}

/** 根据当前时间更新问候语。 */
function updateGreeting(){
  const el = $('greeting');
  if(!el) return;
  const h = new Date().getHours();
  const g = h < 5 ? '夜深了' : h < 11 ? '早上好' : h < 13 ? '中午好' : h < 18 ? '下午好' : '晚上好';
  el.textContent = `${g}，想下载点什么？`;
}

function setActivePage(page) {
  document.querySelectorAll('.tab').forEach(tab => tab.classList.toggle('active', tab.dataset.page === page));
  document.querySelectorAll('.page').forEach(section => section.classList.toggle('active', section.id === 'page-' + page));
  const pageTitle = $('pageTitle');
  if(pageTitle) pageTitle.textContent = PAGE_TITLES[page] || '视频下载工具';
  // 进入下载历史页时清除“新增记录”提示绿点
  if(page === 'history') setHistoryDot(false);
}

/**
 * 设置下载历史新记录提示绿点的显隐。
 * @param {boolean} show - 是否显示绿点。
 */
function setHistoryDot(show) {
  const dot = $('historyDot');
  if(dot) dot.classList.toggle('show', show);
}

function init() {
  initTheme();
  hydrateIcons();
  updateGreeting();
  if(typeof initAudioConverter === 'function') initAudioConverter();
  if(typeof initAudioVolumeTools === 'function') initAudioVolumeTools();

  // 平台选择芯片组
  const pc = $('platforms');
  PLATFORMS.forEach((p,i) => {
    const b = document.createElement('button');
    b.className = 'plat-btn' + (i===0?' active':'');
    b.dataset.name = p.name;
    const dot = document.createElement('span');
    dot.className = 'plat-dot';
    dot.style.setProperty('--dot', p.color);
    b.append(dot, document.createTextNode(p.name));
    b.onclick = () => selectPlatform(p.name);
    pc.appendChild(b);
  });

  // 选项填充
  fillSelect('s_resolution', [['best','无限制'],['2160','4K (2160p)'],['1440','2K (1440p)'],['1080','1080P'],['720','720P'],['480','480P'],['360','360P']]);
  fillSelect('s_codec', [['best','极致画质'],['h264','兼容优先(H.264)'],['av1','AV1优先'],['vp9','VP9优先']]);
  fillSelect('s_audio', [['best','最高音质'],['192','均衡(192k)'],['128','最小体积(128k)']]);
  fillSelect('s_format', [['mp4','MP4'],['mkv','MKV'],['webm','WebM']]);
  fillSelect('s_audiomode', [['0','不单独处理音频'],['1','分离音画输出'],['2','同时输出音频'],['3','只输出音频']]);
  fillSelect('s_audiofmt', [['m4a','m4a(原生)'],['mp3','MP3'],['wav','WAV']]);
  fillSelect('s_hwaccel', [['cpu','CPU软编码'],['h264_nvenc','N卡 NVENC'],['h264_qsv','Intel QSV'],['h264_amf','AMD AMF']]);
  fillSelect('s_browser', [['chrome','Chrome'],['edge','Edge'],['firefox','Firefox'],['brave','Brave'],['opera','Opera']]);

  // 标签页切换事件绑定
  document.querySelectorAll('.tab').forEach(t => {
    t.onclick = () => {
      setActivePage(t.dataset.page);
    };
  });

  // 回车触发下载；Shift/Ctrl+回车换行；输入法组词期间的回车不触发
  const urlInput = $('urlInput');
  urlInput.addEventListener('keydown', e => {
    if(e.key === 'Enter' && !e.shiftKey && !e.ctrlKey && !e.altKey && !e.metaKey && !e.isComposing) {
      e.preventDefault();
      startDl();
    }
  });
  // 随内容自适应高度（粘贴多行也会触发 input 事件）
  urlInput.addEventListener('input', autoGrowUrlInput);

  // 加载配置
  loadConfig();
  loadDeps();

  // 建立 SSE 事件流连接
  connectSSE();

  // 页面关闭前提示用户下载仍在进行中
  window.addEventListener('beforeunload', (e) => {
    if(download_running) {
      e.preventDefault();
      e.returnValue = '正在下载中！关闭页面后下载将继续在后台运行。如需彻底关闭工具，请先点击「✕ 退出」按钮。';
      return e.returnValue;
    }
  });
}

/**
 * 填充 select 下拉选项。
 * @param {string} id - select 元素 ID。
 * @param {Array<Array<string>>} opts - [value, label] 选项数组。
 */
function fillSelect(id, opts) {
  const s = $(id);
  opts.forEach(([v,l]) => { const o=document.createElement('option');o.value=v;o.textContent=l;s.appendChild(o); });
}

function selectPlatform(name) {
  currentPlatform = name;
  if(name !== 'Withny') lastUrlPlatform = name;
  document.querySelectorAll('.plat-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.name===name);
  });
  // Bilibili 1080p Cookie 提示显隐
  const hintEl = $('bilibiliHint');
  if (hintEl) hintEl.style.display = name === 'Bilibili' ? 'block' : 'none';
  // Twitter/X Cookie 提示显隐
  const twHintEl = $('twitterHint');
  if (twHintEl) twHintEl.style.display = name === 'Twitter' ? 'block' : 'none';
  // NicoChannel Firefox 登录提示显隐
  const ncHintEl = $('nicochannelHint');
  if (ncHintEl) ncHintEl.style.display = name === 'NicoChannel' ? 'block' : 'none';
  const withnyHintEl = $('withnyHint');
  if (withnyHintEl) withnyHintEl.style.display = name === 'Withny' ? 'block' : 'none';
  const withnyMode = name === 'Withny';
  const liveButton = $('btnWithnyLive');
  if(liveButton) liveButton.style.display = withnyMode ? 'inline-flex' : 'none';
  const input = $('urlInput');
  input.disabled = withnyMode;
  input.placeholder = withnyMode
    ? 'Withny 使用浏览器导出的“包含内容”HAR，请点击右侧按钮选择文件…'
    : '粘贴视频 / 播放列表 / 频道 / 直播链接，回车开始下载（每行一个链接，Shift/Ctrl+回车换行）…';
  const startLabel = $('btnStart').lastChild;
  if(startLabel) startLabel.textContent = withnyMode ? '选择 HAR 并下载' : '开始下载';
}

/** 切换开关状态。 */
function toggleSwitch(el) { el.classList.toggle('on'); }
/** 判断开关是否处于开启状态。 */
function isOn(id) { return $(id).classList.contains('on'); }

/**
 * 通用 API 请求封装。
 * 自动附加 Session Token 和 JSON Content-Type 头。
 *
 * @param {string} path - API 路径。
 * @param {RequestInit} [opts] - fetch 选项。
 * @returns {Promise<object>} 解析后的 JSON 响应。
 */
async function api(path, opts={}) {
  const headers = Object.assign({'Content-Type':'application/json', 'X-Session-Token':SESSION_TOKEN}, opts.headers || {});
  const r = await fetch(path, Object.assign({}, opts, {headers}));
  const text = await r.text();
  let data = {};
  try { data = text ? JSON.parse(text) : {}; } catch(e) { data = {error:text || `请求失败 (${r.status})`}; }
  if(!r.ok) throw new Error(data.error || `请求失败 (${r.status})`);
  return data;
}

/**
 * 工具箱通用操作入口。
 * 调用后端 /api/tool 接口并显示状态反馈。
 *
 * @param {string} name - 操作名称（如 'gen-template', 'update-ytdlp'）。
 */
async function toolAction(name) {
  const labels = {
    'gen-template': '正在生成批量下载模板…',
    'gen-cookie-template': '正在生成 Cookie 模板…',
    'update-ytdlp': '正在更新 yt-dlp…',
    'clean-temp': '正在清理临时文件…',
    'open-downloads': '正在打开下载目录…',
    'open-logs': '正在打开日志目录…'
  };
  showToolStatus(labels[name] || '正在执行…', 'working');
  try {
    const r = await api('/api/tool', {method:'POST', body:JSON.stringify({action:name})});
    if(r.error) {
      showToolStatus('操作失败: ' + r.error, 'error');
      showToast(r.error, 'error');
      return;
    }
    const msg = r.message || '操作完成';
    addLog('logBox', {time:new Date().toTimeString().slice(0,8), msg:msg, level:'success'});
    showToolStatus(msg, 'success');
    showToast(msg, 'success');
  } catch(e) {
    showToolStatus('请求失败: ' + e.message, 'error');
    showToast(e.message, 'error');
  }
}

// 浏览文件夹
// browseFolder → 已由 audio-convert.js 中的 browseAudioDir() 替代

async function loadConfig() {
  const cfg = await api('/api/config');
  $('ver').textContent = cfg.version;
  $('aboutVer').textContent = cfg.version;
  applyConfig(cfg.config);
}

function applyConfig(s) {
  selectPlatform(s.PLATFORM);
  $('s_resolution').value = s.RESOLUTION;
  $('s_codec').value = s.CODEC;
  $('s_audio').value = s.AUDIO_QUALITY;
  $('s_format').value = s.OUTPUT_FORMAT;
  if(s.AUDIO_MODE !== undefined) { $('s_audiomode').value = s.AUDIO_MODE; onAudioModeChange(); }
  if(s.AUDIO_FORMAT !== undefined) $('s_audiofmt').value = s.AUDIO_FORMAT;
  $('s_threads').value = s.THREADS; $('thr_val').textContent = s.THREADS;
  $('s_speed').value = s.SPEED_LIMIT; $('spd_val').textContent = s.SPEED_LIMIT===0?'不限':s.SPEED_LIMIT;
  setSwitch('sw_proxy', s.PROXY_ENABLED);
  $('s_proxytype').value = s.PROXY_TYPE;
  $('s_proxyaddr').value = s.PROXY_ADDR;
  $('s_proxyport').value = s.PROXY_PORT;
  setSwitch('sw_cookies', s.USE_COOKIES);
  $('s_cookiemode').value = s.COOKIE_MODE;
  $('s_browser').value = s.BROWSER_NAME;
  $('s_profile').value = s.BROWSER_PROFILE;
  $('s_hwaccel').value = s.HWACCEL;
  if(s.LIVE_STREAM_METHOD !== undefined) $('s_live_stream_method').value = s.LIVE_STREAM_METHOD;
  setSwitch('sw_meta', s.EMBED_META);
  setSwitch('sw_thumb', s.DOWNLOAD_THUMB);
  setSwitch('sw_winfn', s.WIN_FILENAMES);
  setSwitch('sw_strict', s.STRICT_FILENAME);
  setSwitch('sw_nicocmt', s.NICO_COMMENTS);
  setSwitch('sw_nicorec', s.NICO_RECODE);
  setSwitch('sw_log', s.ENABLE_LOG);
  if(s.BILI_MULTIP_POLICY !== undefined) $('s_bili_policy').value = s.BILI_MULTIP_POLICY;
  // 音频输出格式设置（audio-convert.js 负责 UI 初始化）
  if(s.AUDIO_OUTPUT_FORMAT !== undefined && $('audioOutFormat')) $('audioOutFormat').value = s.AUDIO_OUTPUT_FORMAT;
  setSwitch('sw_audioDelSrc', s.DEL_SRC_AFTER_CONVERT);
  setSwitch('sw_audioRecursive', s.AUDIO_RECURSIVE);
  toggleCookieMode();
}

/** 根据值设置开关的开关状态。 */
function setSwitch(id, val) {
  if(val) $(id).classList.add('on'); else $(id).classList.remove('on');
}

/** 音频模式切换时更新格式选择器的可用状态。 */
function onAudioModeChange() {
  const mode = $('s_audiomode').value;
  const fmtEl = $('s_audiofmt');
  // 模式 0（不处理音频）和模式 1（分离音画）不需要音频输出格式选择
  if(mode === '0' || mode === '1') {
    fmtEl.disabled = true;
    fmtEl.style.opacity = '0.4';
  } else {
    fmtEl.disabled = false;
    fmtEl.style.opacity = '1';
  }
}

/** Cookie 模式切换时显示/隐藏浏览器相关设置行。 */
function toggleCookieMode() {
  const browserMode = $('s_cookiemode').value === '2';
  $('row_browser').style.display = browserMode ? 'flex' : 'none';
  $('row_profile').style.display = browserMode ? 'flex' : 'none';
}

/** 从设置表单中收集当前全部配置项。 */
function collectCfg() {
  return {
    PLATFORM: currentPlatform === 'Withny' ? lastUrlPlatform : currentPlatform,
    RESOLUTION: $('s_resolution').value,
    CODEC: $('s_codec').value,
    AUDIO_QUALITY: $('s_audio').value,
    OUTPUT_FORMAT: $('s_format').value,
    AUDIO_MODE: $('s_audiomode').value,
    AUDIO_FORMAT: $('s_audiofmt').value,
    THREADS: parseInt($('s_threads').value),
    SPEED_LIMIT: parseInt($('s_speed').value),
    PROXY_ENABLED: isOn('sw_proxy')?1:0,
    PROXY_TYPE: $('s_proxytype').value,
    PROXY_ADDR: $('s_proxyaddr').value,
    PROXY_PORT: $('s_proxyport').value,
    USE_COOKIES: isOn('sw_cookies')?1:0,
    COOKIE_MODE: parseInt($('s_cookiemode').value),
    BROWSER_NAME: $('s_browser').value,
    BROWSER_PROFILE: $('s_profile').value,
    HWACCEL: $('s_hwaccel').value,
    LIVE_STREAM_METHOD: $('s_live_stream_method').value,
    EMBED_META: isOn('sw_meta')?1:0,
    DOWNLOAD_THUMB: isOn('sw_thumb')?1:0,
    WIN_FILENAMES: isOn('sw_winfn')?1:0,
    STRICT_FILENAME: isOn('sw_strict')?1:0,
    NICO_COMMENTS: isOn('sw_nicocmt')?1:0,
    NICO_RECODE: isOn('sw_nicorec')?1:0,
    ENABLE_LOG: isOn('sw_log')?1:0,
    BILI_MULTIP_POLICY: $('s_bili_policy').value,
  };
}

/** 保存当前设置并在成功后弹出提示。 */
async function saveSettings() {
  const cfg = collectCfg();
  try {
    await api('/api/save-config', {method:'POST', body:JSON.stringify(cfg)});
    alert('设置已保存！');
  } catch(e) {
    alert('设置保存失败: ' + e.message);
  }
}

/** 静默保存设置，不弹窗提示。 */
async function saveSettingsNoAlert() {
  const cfg = collectCfg();
  return api('/api/save-config', {method:'POST', body:JSON.stringify(cfg)});
}

async function resetSettings() {
  if(!confirm('确定恢复默认设置？')) return;
  await api('/api/reset-config', {method:'POST'});
  location.reload();
}

async function loadDeps() {
  const d = await api('/api/deps');
  const names = {'yt-dlp':'yt-dlp',ffmpeg:'ffmpeg',ffprobe:'ffprobe',fantiadl:'fantiadl(可选)',withny_dl:'withny-dl(Withny直播，可选)',nicochannel_plugin:'nicochannel插件(可选)'};
  const box = $('depStatus');
  box.innerHTML = '';
  for(const [k,v] of Object.entries(d)) {
    const el = document.createElement('span');
    el.className = 'dep-item ' + (v?'dep-ok':'dep-miss');
    const ico = document.createElement('span');
    ico.className = 'icon';
    ico.dataset.ico = v ? 'check' : 'x';
    el.append(ico, document.createTextNode(names[k]));
    box.appendChild(el);
  }
  hydrateIcons(box);
}

/**
 * 清理单个链接：去除前后空白、反引号、引号（最多 3 轮）。
 * @param {string} url - 待清理的链接字符串。
 * @returns {string} 清理后的链接。
 */
function cleanOneUrl(url) {
  for(let i=0;i<3;i++) {
    const old = url;
    url = url.trim().replace(/^[`'"]+|[`'"]+$/g, '');
    if(url === old) break;
  }
  return url.trim();
}

/** 链接输入框随内容自适应高度（CSS 限制最多 3 行，超出后固定滚动）。 */
function autoGrowUrlInput() {
  const el = $('urlInput');
  if(!el) return;
  el.style.height = 'auto';
  const border = el.offsetHeight - el.clientHeight;
  el.style.height = (el.scrollHeight + border) + 'px';
}

async function startDl() {
  if(currentPlatform === 'Withny') {
    await startWithnyArchive();
    return;
  }
  // 按行拆分，每行一个链接，清理后过滤空行
  const urls = $('urlInput').value.split(/\r?\n/).map(cleanOneUrl).filter(Boolean);
  if(urls.length === 0) { alert('请输入链接'); return; }

  // 多链接：走批量下载（每行一个），跳过单条 Bilibili 分P 选择
  if(urls.length > 1) {
    try { await saveSettingsNoAlert(); } catch(e) { alert('设置保存失败: ' + e.message); return; }
    doStartUrls(urls);
    return;
  }

  // 单链接：沿用单任务流程（含 Bilibili 分P 选择）
  const url = urls[0];
  $('urlInput').value = url;
  autoGrowUrlInput();
  // 自动识别 Bilibili 链接（无需手动切换平台按钮）
  const isBiliUrl = isBilibiliUrl(url);
  if(isBiliUrl && currentPlatform !== 'Bilibili') {
    selectPlatform('Bilibili');
  }
  // 先保存设置
  try { await saveSettingsNoAlert(); } catch(e) { alert('设置保存失败: ' + e.message); return; }
  // Bilibili 多P选择策略（基于 URL 检测，而非平台按钮状态）
  if(isBiliUrl && $('s_bili_policy').value === 'select' && !isBilibiliLive(url)) {
    try {
      $('statusText').textContent = '正在获取分P列表...';
      const pl = await api('/api/bili-playlist', {method:'POST', body:JSON.stringify({url})});
      $('statusText').textContent = '就绪';
      if(pl.error) { alert(pl.error); return; }
      if(pl.note) { addLog('logBox', {time: new Date().toTimeString().slice(0,8), msg: '[分P检测] ' + pl.note, level: 'info'}); }
      if(pl.parts && pl.parts.length > 1) {
        addLog('logBox', {time: new Date().toTimeString().slice(0,8), msg: `[分P检测] 检测到 ${pl.total} 个分P，等待选择...`, level: 'info'});
        pendingPartCallback = (parts) => doStartDl(url, parts);
        showPartSelector(pl.parts);
        return;
      }
    } catch(e) {
      addLog('logBox', {time: new Date().toTimeString().slice(0,8), msg: '[分P检测] 获取列表失败，将下载全部: ' + e.message, level: 'warn'});
      $('statusText').textContent = '就绪';
    }
  }
  doStartDl(url);
}

async function startWithnyArchive() {
  $('btnStart').disabled = true;
  $('btnWithnyLive').disabled = true;
  try {
    const result = await api('/api/start-withny-archive', {method:'POST', body:'{}'});
    if(result.error) {
      alert(result.error);
      $('btnStart').disabled = false;
      $('btnWithnyLive').disabled = false;
      return;
    }
    if(result.cancelled) {
      $('btnStart').disabled = false;
      $('btnWithnyLive').disabled = false;
      return;
    }
    download_running = true;
    $('btnStop').disabled = false;
    $('statOk').textContent = '0';
    $('statFail').textContent = '0';
    $('statTotal').textContent = '1';
  } catch(e) {
    alert('Withny 下载启动失败: ' + e.message);
    $('btnStart').disabled = false;
    $('btnWithnyLive').disabled = false;
  }
}

async function startWithnyLive() {
  $('btnStart').disabled = true;
  $('btnWithnyLive').disabled = true;
  try {
    const result = await api('/api/start-withny-live', {method:'POST', body:'{}'});
    if(result.error) {
      alert(result.error);
      $('btnStart').disabled = false;
      $('btnWithnyLive').disabled = false;
      return;
    }
    if(result.cancelled) {
      $('btnStart').disabled = false;
      $('btnWithnyLive').disabled = false;
      return;
    }
    download_running = true;
    $('btnStop').disabled = false;
    $('statOk').textContent = '0';
    $('statFail').textContent = '0';
    $('statTotal').textContent = '1';
  } catch(e) {
    alert('Withny 直播录制启动失败: ' + e.message);
    $('btnStart').disabled = false;
    $('btnWithnyLive').disabled = false;
  }
}

/**
 * 判断是否为 Bilibili 视频链接（支持 BV/AV/b23.tv）。
 * @param {string} url - 待检测链接。
 * @returns {boolean} 是否为 Bilibili 链接。
 */
function isBilibiliUrl(url) {
  try {
    const host = new URL(url).hostname.toLowerCase();
    return host === 'www.bilibili.com' || host === 'bilibili.com' || host.endsWith('.bilibili.com') || host === 'b23.tv';
  } catch(e) { return false; }
}

/**
 * 判断是否为 Bilibili 直播链接。
 * @param {string} url - 待检测链接。
 * @returns {boolean} 是否为 Bilibili 直播链接。
 */
function isBilibiliLive(url) {
  try { return new URL(url).hostname.includes('live.bilibili.com'); } catch(e) { return false; }
}

async function doStartDl(url, biliParts, tcPassword) {
  const body = {url};
  if(biliParts) body.bili_parts = biliParts;
  if(tcPassword) body.tc_password = tcPassword;
  const r = await api('/api/start', {method:'POST', body:JSON.stringify(body)});
  if(r.error) { alert(r.error); return; }
  download_running = true;
  $('btnStart').disabled = true;
  $('btnStop').disabled = false;
  $('statOk').textContent = '0';
  $('statFail').textContent = '0';
  $('statTotal').textContent = '1';
  setHistoryDot(true);
}

async function doStartUrls(urls) {
  const r = await api('/api/start-urls', {method:'POST', body:JSON.stringify({urls})});
  if(r.error) { alert(r.error); return; }
  download_running = true;
  $('btnStart').disabled = true;
  $('btnStop').disabled = false;
  $('statOk').textContent = '0';
  $('statFail').textContent = '0';
  $('statTotal').textContent = r.total || String(urls.length);
  setHistoryDot(true);
}

async function startBatch() {
  if(!confirm('将从 urls.txt 文件读取链接进行批量下载，是否继续？')) return;
  showToolStatus('正在启动批量下载…', 'working');
  try { await saveSettingsNoAlert(); } catch(e) { showToolStatus('设置保存失败: ' + e.message, 'error'); return; }
  doStartBatch();
}

async function doStartBatch(biliPartsMap) {
  const body = {};
  if(biliPartsMap) body.bili_parts_map = biliPartsMap;
  const r = await api('/api/batch-txt', {method:'POST', body:JSON.stringify(body)});
  if(r.error) { alert(r.error); return; }
  download_running = true;
  $('btnStart').disabled = true;
  $('btnStop').disabled = false;
  $('statOk').textContent = '0';
  $('statFail').textContent = '0';
  $('statTotal').textContent = r.total || '0';
  setHistoryDot(true);
}

async function stopDl() {
  const r = await api('/api/stop', {method:'POST'});
  if(r.error) { alert(r.error); return; }
  if(r.stopping) {
    download_running = true;
    $('btnStart').disabled = true;
    $('btnStop').disabled = true;
    $('statusText').textContent = '正在停止...';
  }
}

// doWavConvert → 已由 audio-convert.js 中的 startAudioConvert() 替代

/** 展开/折叠批量任务统计详情。 */
function toggleTaskStats() {
  const detail = $('taskStatsDetail');
  const btn = $('btnStatsToggle');
  if(!detail || !btn) return;
  const collapsed = detail.style.display === 'none';
  detail.style.display = collapsed ? '' : 'none';
  btn.textContent = collapsed ? '▼' : '▶';
  btn.style.color = collapsed ? 'var(--text-highlighted)' : 'var(--text-toned)';
}

/** 触发统计数字弹出动画。 */
function popStat(id) {
  const el = $(id);
  if(!el) return;
  el.classList.remove('stat-pop');
  void el.offsetWidth; // 强制重绘以触发动画
  el.classList.add('stat-pop');
}

/** 根据批量统计数据更新汇总区域显隐和内容。 */
function updateStatsVisibility() {
  const wrap = $('taskStatsWrap');
  const detail = $('taskStatsDetail');
  const btn = $('btnStatsToggle');
  const summary = $('statsSummary');
  const ok = parseInt($('statOk').textContent) || 0;
  const fail = parseInt($('statFail').textContent) || 0;
  const total = parseInt($('statTotal').textContent) || 0;
  if(!wrap) return;
  if(total < 2) { wrap.style.display = 'none'; return; }
  wrap.style.display = '';
  if(summary) summary.textContent = `完成 ${ok + fail}/${total}` + (fail > 0 ? ` · 失败 ${fail}` : '');
  // 自动展开条件：总数 ≥ 2 且存在失败记录
  const shouldExpand = total >= 2 && fail > 0;
  if(shouldExpand) {
    detail.style.display = '';
    btn.textContent = '▼';
    btn.style.color = 'var(--text-highlighted)';
  }
}

/** 折叠/展开主日志面板。 */
function toggleLogBox() {
  const wrap = $('logBoxWrap');
  const btn = $('btnLogToggle');
  if(!wrap || !btn) return;
  const collapsed = wrap.style.display === 'none';
  wrap.style.display = collapsed ? '' : 'none';
  btn.innerHTML = collapsed ? '▲' : '▼';
}

/** 清空主日志面板内容。 */
function clearConsole() {
  const logBox = $('logBox');
  if(logBox) logBox.innerHTML = '';
}

function addLog(container, entry) {
  // 写入主面板
  _addToBox(container, entry);
  // 同步写入另一个日志面板（如果存在）
  if (container === 'logBox' && $('toolLogBox')) {
    _addToBox('toolLogBox', entry);
  } else if (container === 'toolLogBox' && $('logBox')) {
    _addToBox('logBox', entry);
  }
}

function _addToBox(id, entry) {
  const box = $(id);
  if(!box) return;
  const line = document.createElement('div');
  line.className = 'log-line log-' + entry.level;
  const timestamp = document.createElement('span');
  timestamp.className = 'log-time';
  timestamp.textContent = `[${entry.time}]`;
  line.appendChild(timestamp);
  line.appendChild(document.createTextNode(` ${entry.msg}`));
  box.appendChild(line);
  box.scrollTop = box.scrollHeight;
  while(box.children.length > 300) box.removeChild(box.firstChild);
}

/** 折叠/展开工具日志面板。 */
function toggleToolLog() {
  const wrap = $('toolLogBoxWrap');
  const btn = $('btnToolLogToggle');
  if(!wrap || !btn) return;
  const collapsed = wrap.style.display === 'none';
  wrap.style.display = collapsed ? '' : 'none';
  btn.innerHTML = collapsed ? '▲' : '▼';
}

/** 清空工具日志面板内容。 */
function clearToolConsole() {
  const box = $('toolLogBox');
  if(box) box.innerHTML = '';
}

// ========== Toast 通知系统 ==========
/**
 * 显示 Toast 通知弹窗。
 * @param {string} msg - 通知消息文本。
 * @param {string} level - 通知级别（'success' | 'error' | 'working'）。
 */
function showToast(msg, level) {
  // 确保 Toast 容器存在
  let container = document.querySelector('.toast-container');
  if(!container) {
    container = document.createElement('div');
    container.className = 'toast-container';
    document.body.appendChild(container);
  }
  const toast = document.createElement('div');
  toast.className = 'toast ' + (level || '');
  const icon = level === 'success' ? 'check' : level === 'error' ? 'x' : 'refresh';
  toast.innerHTML = `<span class="icon">${svgIcon(icon)}</span><span>${msg}</span>`;
  container.appendChild(toast);
  hydrateIcons(toast);
  // 自动消失（3 秒后）
  setTimeout(() => {
    toast.classList.add('removing');
    setTimeout(() => toast.remove(), 260);
  }, 3000);
}

// 工具操作状态内联反馈
function showToolStatus(msg, type) {
  const el = $('toolStatus');
  if(!el) return;
  el.style.display = 'flex';
  el.className = 'tool-status ' + (type || '');
  el.innerHTML = (type === 'working' ? '<span class="status-icon">⏳</span>' : '') + '<span>' + msg + '</span>';
  if(type !== 'working') {
    setTimeout(() => { el.style.display = 'none'; }, 5000);
  }
}

let sseRetryDelay = 1000;
const SSE_MAX_RETRY = 16000;

function connectSSE() {
  if(evtSource) evtSource.close();
  evtSource = new EventSource('/api/events?token=' + encodeURIComponent(SESSION_TOKEN));
  evtSource.onopen = () => {
    setConn(true);
    sseRetryDelay = 1000;     // 连接成功，重置退避时间
  };
  evtSource.onmessage = (e) => {
    const evt = JSON.parse(e.data);
    if(evt.type === 'log') {
      addLog('logBox', evt.data);
    } else if(evt.type === 'progress') {
      const d = evt.data;
      const fill = $('progressFill');
      if(d.percent < 0) {
        // 直播模式：无限动画进度条
        fill.classList.add('live');
        $('progressText').textContent = 'LIVE';
      } else {
        fill.classList.remove('live');
        fill.style.width = (d.percent*100)+'%';
        $('progressText').textContent = Math.round(d.percent*100)+'%';
      }
      $('statusText').textContent = d.status;
      $('speedText').textContent = d.speed;
      $('etaText').textContent = d.eta ? 'ETA '+d.eta : '';
      if(d.percent >= 1 || d.status.includes('失败') || d.status.includes('完成') || d.status.includes('已停止') || d.status.includes('已取消') || d.status.includes('异常终止')) {
        fill.classList.remove('live');
        // 完成脉冲动画
        if(d.percent >= 1) {
          fill.classList.add('complete');
          setTimeout(() => fill.classList.remove('complete'), 700);
        }
      }
    } else if(evt.type === 'download_state') {
      const d = evt.data;
      download_running = Boolean(d.running);
      $('btnStart').disabled = download_running || d.phase === 'suspended';
      $('btnWithnyLive').disabled = download_running || d.phase === 'suspended';
      $('btnStop').disabled = !download_running || d.phase === 'stopping';
    } else if(evt.type === 'stats') {
      const d = evt.data;
      if(d.ok !== undefined) { popStat('statOk'); $('statOk').textContent = d.ok; }
      if(d.fail !== undefined) { popStat('statFail'); $('statFail').textContent = d.fail; }
      if(d.total !== undefined) { popStat('statTotal'); $('statTotal').textContent = d.total; }
      updateStatsVisibility();
    } else if(evt.type === 'password_required') {
      const d = evt.data;
      // 仅 TwitCasting 平台显示密码弹窗，其他平台忽略
      if(d.platform !== 'TwitCasting') return;
      pendingTcUrl = d.url;
      showTcPasswordPrompt(d.reason === 'retry');
    } else if(evt.type === 'history') {
      renderHistory(evt.data);
    } else if(evt.type === 'ready') {
      const readyData = Array.isArray(evt.data) ? {logs:evt.data, running:false} : evt.data;
      (readyData.logs || []).forEach(e => addLog('logBox', e));
      download_running = Boolean(readyData.running);
      $('btnStart').disabled = download_running || readyData.phase === 'suspended';
      $('btnStop').disabled = !download_running || readyData.phase === 'stopping';
      if(readyData.progress) {
        $('statusText').textContent = readyData.progress.status || '就绪';
        $('speedText').textContent = readyData.progress.speed || '';
        $('etaText').textContent = readyData.progress.eta ? 'ETA '+readyData.progress.eta : '';
        const percent = readyData.progress.percent;
        if(percent < 0) {
          $('progressFill').classList.add('live');
          $('progressText').textContent = 'LIVE';
        } else if(percent !== undefined) {
          $('progressFill').classList.remove('live');
          $('progressFill').style.width = (percent*100)+'%';
          $('progressText').textContent = Math.round(percent*100)+'%';
        }
      }
      if(readyData.stats) {
        $('statOk').textContent = readyData.stats.ok || 0;
        $('statFail').textContent = readyData.stats.fail || 0;
        $('statTotal').textContent = readyData.stats.total || 0;
        updateStatsVisibility();
      }
      if(readyData.update) {
        if(readyData.update.update_available) handleUpdateAvailable(readyData.update);
        if(readyData.update.downloading || readyData.update.update_done || readyData.update.error) {
          handleUpdateProgress({
            percent: readyData.update.download_progress,
            speed: readyData.update.download_speed,
            done: readyData.update.update_done,
            error: readyData.update.error
          });
        }
      }
      loadPresets();
      loadHistory();
    } else if(evt.type === 'update_available') {
      handleUpdateAvailable(evt.data);
    } else if(evt.type === 'update_progress') {
      handleUpdateProgress(evt.data);
    } else if(evt.type === 'exit') {
      document.body.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100vh;color:#aaa;font-size:1.2rem;flex-direction:column;gap:12px"><div style="font-size:3rem">👋</div><div>工具已关闭，可安全关闭此页面</div></div>';
      try { evtSource.close(); } catch(e){}
    }
  };
  evtSource.onerror = () => {
    setConn(false);
    evtSource.close();
    // 指数退避重连：1s → 2s → 4s → 8s → 16s（上限）
    setTimeout(connectSSE, sseRetryDelay);
    sseRetryDelay = Math.min(sseRetryDelay * 2, SSE_MAX_RETRY);
  };
}

async function exitApp() {
  if(!confirm('确定要彻底关闭工具吗？\\n正在进行的下载将被终止。')) return;
  try {
    await api('/api/exit', {method:'POST'});
  } catch(e) {}
  document.body.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100vh;color:#aaa;font-size:1.2rem;flex-direction:column;gap:12px"><div style="font-size:3rem">👋</div><div>正在关闭...</div></div>';
  setTimeout(() => {
    try { window.close(); } catch(e) {}
    document.body.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100vh;color:#aaa;font-size:1.2rem;flex-direction:column;gap:12px"><div style="font-size:3rem">👋</div><div>工具已关闭，可安全关闭此页面</div></div>';
  }, 1000);
}

init();

// ========== 预设功能（设置页下拉选择） ==========
async function loadPresets() {
  const data = await api('/api/presets');
  updatePresetSelect(data.presets || []);
}

function updatePresetSelect(presets) {
  const sel = $('presetSelect');
  const currentVal = sel.value;
  sel.innerHTML = '<option value="">-- 选择预设快速应用 --</option>' +
    presets.map(name => `<option value="${escAttr(name)}" ${name===currentVal?'selected':''}>${escHtml(name)}</option>`).join('');
}

function showSavePreset() {
  $('presetSaveRow').style.display = 'flex';
  $('presetNameInput').value = '';
  $('presetNameInput').focus();
}

function hideSavePreset() {
  $('presetSaveRow').style.display = 'none';
}

async function savePresetFromInput() {
  const name = $('presetNameInput').value.trim();
  if(!name) { alert('请输入预设名称'); return; }
  await saveSettingsNoAlert();
  const r = await api('/api/save-preset', {method:'POST', body:JSON.stringify({name})});
  if(r && r.ok) {
    hideSavePreset();
    updatePresetSelect(r.presets);
    $('presetSelect').value = name;
    addLog('logBox', {time:new Date().toTimeString().slice(0,8), msg:`[预设] 已保存: ${name}`, level:'success'});
  }
}

async function loadPresetFromSelect() {
  const name = $('presetSelect').value;
  if(!name) return;
  const r = await api('/api/load-preset', {method:'POST', body:JSON.stringify({name})});
  if(r && r.ok) {
    applyConfig(r.config);
    addLog('logBox', {time:new Date().toTimeString().slice(0,8), msg:`[预设] 已加载: ${name}`, level:'success'});
  }
}

async function deletePresetFromSelect() {
  const name = $('presetSelect').value;
  if(!name) { alert('请先选择要删除的预设'); return; }
  if(!confirm(`确定删除预设「${name}」吗？`)) return;
  const r = await api('/api/delete-preset', {method:'POST', body:JSON.stringify({name})});
  if(r && r.ok) {
    updatePresetSelect(r.presets);
    addLog('logBox', {time:new Date().toTimeString().slice(0,8), msg:`[预设] 已删除: ${name}`, level:'warn'});
  }
}

// ========== 下载历史 ==========
async function loadHistory() {
  const data = await api('/api/history');
  renderHistory(data.history || []);
}

function renderHistory(history) {
  const list = $('historyList');
  const count = $('historyCount');
  if(count) count.textContent = `共 ${history.length} 条记录`;
  if(!history.length) {
    list.innerHTML = '<div class="empty-state"><span class="icon" data-ico="inbox"></span><span class="empty-title">暂无下载记录</span><span>完成的下载会出现在这里。</span></div>';
    hydrateIcons(list);
    return;
  }
  list.innerHTML = history.map(h => {
    const statusCls = h.status === 'success' ? 'success' : 'fail';
    const statusText = h.status === 'success' ? '成功' : '失败';
    // 有封面时显示封面图；封面缺失或加载失败时，露出下方的成功/失败标记
    const cover = h.filepath
      ? `<img class="history-cover" loading="lazy" alt="封面"
             src="/api/cover?path=${encodeURIComponent(h.filepath)}&token=${encodeURIComponent(SESSION_TOKEN)}"
             onload="this.classList.add('show')" onerror="this.remove()"
             onclick="openCover(this.src)">`
      : '';
    return `
    <div class="history-item">
      <div class="history-cover-wrap">
        ${cover}
        <span class="cover-status ${statusCls}">${statusText}</span>
      </div>
      <div class="history-info">
        <div class="history-title" title="${escAttr(h.title)}">${escHtml(h.title)}</div>
        <div class="history-meta">${h.time} · <span class="history-platform ${h.platform}">${escHtml(h.platform)}</span> · <span class="url">${escHtml(h.url)}</span></div>
      </div>
    </div>`;
  }).join('');
}

// 点击历史封面在遮罩层放大查看
function openCover(src) {
  const overlay = document.createElement('div');
  overlay.className = 'cover-overlay';
  overlay.onclick = () => overlay.remove();
  const img = document.createElement('img');
  img.src = src;
  img.alt = '封面预览';
  overlay.appendChild(img);
  document.body.appendChild(overlay);
}

async function clearHistoryUI() {
  if(!confirm('确定清空所有下载历史吗？此操作不可撤销。')) return;
  const r = await api('/api/clear-history', {method:'POST'});
  if(r && r.ok) loadHistory();
}

/** HTML 转义，防止 XSS。 */
function escHtml(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}
function escAttr(s) {
  return escHtml(String(s)).replace(/'/g, '&#39;').replace(/"/g, '&quot;');
}

// ========== 自动更新功能 ==========
let updateInfo = null;

function handleUpdateAvailable(data) {
  updateInfo = data;
  $('updateBadge').style.display = 'inline-block';
  $('updateCurVer').textContent = data.current_version || '';
  $('updateNewVer').textContent = data.latest_version || '';
  $('updateNotes').textContent = data.release_notes || '暂无更新说明';
  // 自动弹出更新面板
  showUpdatePanel();
}

function handleUpdateProgress(data) {
  if(data.error) {
    $('updateProgText').textContent = '更新失败: ' + data.error;
    $('updateProgText').style.color = 'var(--red)';
    $('updateProgress').classList.add('show');
    $('updateActions').style.display = '';
    $('btnDoUpdate').disabled = false;
    $('btnDoUpdate').textContent = '重试';
    return;
  }
  // 显示更新进度条
  $('updateProgress').classList.add('show');
  $('updateActions').style.display = 'none';
  const pct = Math.round(data.percent || 0);
  $('updateProgFill').style.width = pct + '%';
  $('updateProgPct').textContent = pct + '%';
  $('updateProgSpeed').textContent = data.speed || '';
  if(data.done) {
    $('updateProgress').classList.remove('show');
    $('updateDone').classList.add('show');
    if(data.message) {
      $('updateDoneMsg').textContent = data.message;
    }
  }
}

function showUpdatePanel() {
  $('updatePanel').classList.add('show');
}

function hideUpdatePanel() {
  $('updatePanel').classList.remove('show');
}

async function doUpdateNow() {
  if(!updateInfo || !updateInfo.download_url) {
    alert('暂无下载链接，请稍后重试');
    return;
  }
  $('btnDoUpdate').disabled = true;
  $('btnDoUpdate').textContent = '更新中...';
  $('updateProgText').textContent = '正在下载更新...';
  $('updateProgText').style.color = 'var(--orange)';
  $('updateProgress').classList.add('show');
  $('updateProgFill').style.width = '0%';
  $('updateProgPct').textContent = '0%';
  try {
    const result = await api('/api/do-update', {method:'POST', body:'{}'});
    if(result.error) {
      handleUpdateProgress({error:result.error});
    }
  } catch(e) {
    handleUpdateProgress({error:'更新请求失败: ' + e.message});
  }
}

// ========== Bilibili 分P 选择对话框 ==========
let pendingPartCallback = null;
let pendingTcUrl = null;

async function fetchBiliPlaylist(url) {
  return await api('/api/bili-playlist', {method:'POST', body:JSON.stringify({url})});
}

function showPartSelector(parts) {
  const list = document.getElementById('partList');
  list.replaceChildren(...parts.map(p => {
    const label = document.createElement('label');
    label.className = 'part-item';
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.value = String(p.index ?? '');
    checkbox.checked = true;
    checkbox.addEventListener('change', updatePartCount);
    const index = document.createElement('span');
    index.className = 'part-index';
    index.textContent = `P${p.index ?? ''}`;
    const title = document.createElement('span');
    title.className = 'part-title';
    title.title = String(p.title ?? '');
    title.textContent = String(p.title ?? '');
    const duration = document.createElement('span');
    duration.className = 'part-duration';
    duration.textContent = fmtDuration(p.duration);
    label.append(checkbox, index, title, duration);
    return label;
  }));
  updatePartCount();
  document.getElementById('partSelectorOverlay').style.display = 'flex';
}

function closePartSelector() {
  document.getElementById('partSelectorOverlay').style.display = 'none';
  pendingPartCallback = null;
}

function toggleAllParts(selectAll) {
  document.querySelectorAll('#partList input[type="checkbox"]').forEach(cb => {
    cb.checked = selectAll;
  });
  updatePartCount();
}

function updatePartCount() {
  const cbs = document.querySelectorAll('#partList input[type="checkbox"]');
  const checked = document.querySelectorAll('#partList input[type="checkbox"]:checked').length;
  document.getElementById('partCount').textContent = `已选 ${checked}/${cbs.length}`;
}

function confirmPartSelection() {
  const checked = document.querySelectorAll('#partList input[type="checkbox"]:checked');
  if(checked.length === 0) { alert('请至少选择一个分P'); return; }
  const indices = Array.from(checked).map(cb => cb.value).join(',');
  const cb = pendingPartCallback;  // 先保存回调引用
  closePartSelector();             // closePartSelector 会清除 pendingPartCallback
  if(cb) {                         // 使用之前保存的引用
    cb(indices);
  }
}

// -- TwitCasting 密码弹窗 ---
function showTcPasswordPrompt(isRetry) {
  const input = document.getElementById('tcPasswordInput');
  if(input) input.value = '';
  const msg = document.getElementById('tcPasswordMsg');
  if(msg) {
    msg.textContent = isRetry
      ? '下载失败，密码可能不正确，请重新输入密码后重试。'
      : '该视频/直播受密码保护或为会员限定内容，请输入密码后下载。';
  }
  document.getElementById('tcPasswordOverlay').style.display = 'flex';
  setTimeout(() => { if(document.getElementById('tcPasswordInput')) document.getElementById('tcPasswordInput').focus(); }, 100);
}

function closeTcPasswordPrompt() {
  document.getElementById('tcPasswordOverlay').style.display = 'none';
  pendingTcUrl = null;
}

function confirmTcPassword() {
  const pw = document.getElementById('tcPasswordInput').value.trim();
  if(!pw) { alert('请输入密码'); return; }
  const url = pendingTcUrl;
  closeTcPasswordPrompt();
  if(!url) return;
  // 批量下载运行中 → 提交密码到等待中的批量线程；否则启动新的单链接下载
  if(download_running) {
    api('/api/submit-password', {method:'POST', body:JSON.stringify({url: url, password: pw})});
  } else {
    doStartDl(url, null, pw);
  }
}

function fmtDuration(sec) {
  if(!sec || sec <= 0) return '';
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return m > 0 ? `${m}:${String(s).padStart(2,'0')}` : `${s}s`;
}

// 页面加载3秒后主动检查更新（后端也会静默检查，双保险）
setTimeout(() => {
  api('/api/check-update').catch(()=>{});
}, 3000);
