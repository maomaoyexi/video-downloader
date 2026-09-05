/**
 * 多平台视频下载工具 WebUI - 主脚本
 *
 * SESSION_TOKEN 由服务端模板注入。
 * 图标为 index.html 内联的 SVG sprite，用 <use href="#i-xxx"> 引用。
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
const PLATFORM_COLORS = Object.fromEntries(PLATFORMS.map(p => [p.name, p.color]));

const PAGE_TITLES = {
  download: '下载任务', settings: '下载设置', history: '下载历史',
  tools: '实用工具', help: '使用帮助', about: '关于软件'
};

// 后端日志级别 → .ln 修饰类
const LOG_LEVEL_CLASS = {success:'s', warn:'w', error:'e', info:''};

const HISTORY_VIEW_KEY = 'video-dl-history-view';
let historyView = 'list';
let historyCache = [];

function $(id){return document.getElementById(id);}

/** 移除并重新添加类，让一次性动画可以重复播放。 */
function replayAnimation(el, className) {
  if(!el) return;
  el.classList.remove(className);
  void el.offsetWidth;
  el.classList.add(className);
}

/** 生成 sprite 图标标记。 */
function icon(name, cls){
  return `<svg class="ico ${cls||''}"><use href="#i-${name}"></use></svg>`;
}

/**
 * 设置品牌标记的连接状态。
 * @param {boolean} online - 是否在线。
 */
function setConn(online){
  const m = $('brandMark');
  if(m) m.classList.toggle('offline', !online);
}

function setActivePage(page) {
  document.querySelectorAll('.ni').forEach(t => t.classList.toggle('on', t.dataset.page === page));
  document.querySelectorAll('.page').forEach(s => s.classList.toggle('active', s.id === 'page-' + page));
  document.querySelectorAll('[data-top]').forEach(el => {
    el.style.display = el.dataset.top === page ? '' : 'none';
  });
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

/** 让滑块轨道按当前值填充（CSS 读取 --p）。 */
function paintRange(el) {
  const min = parseFloat(el.min || 0), max = parseFloat(el.max || 100);
  const pct = max === min ? 0 : (parseFloat(el.value) - min) / (max - min) * 100;
  el.style.setProperty('--p', pct + '%');
}

function initRanges() {
  document.querySelectorAll('input[type=range]').forEach(el => {
    paintRange(el);
    el.addEventListener('input', () => paintRange(el));
  });
}

function init() {
  initTheme();
  setActivePage('download');
  if(typeof initAudioConverter === 'function') initAudioConverter();
  if(typeof initAudioVolumeTools === 'function') initAudioVolumeTools();

  // 平台选择芯片组
  const pc = $('platforms');
  PLATFORMS.forEach((p,i) => {
    const b = document.createElement('button');
    b.className = 'chip' + (i===0?' on':'');
    b.dataset.name = p.name;
    const dot = document.createElement('span');
    dot.className = 'pd';
    dot.style.background = p.color;
    b.append(dot, document.createTextNode(p.name));
    b.onclick = () => selectPlatform(p.name);
    pc.appendChild(b);
  });
  // 关于页的平台清单（只读）
  $('aboutPlatforms').innerHTML = PLATFORMS
    .map(p => `<span class="chip"><span class="pd" style="background:${p.color}"></span>${p.name}</span>`).join('');

  // 选项填充
  fillSelect('s_resolution', [['best','无限制'],['2160','4K (2160p)'],['1440','2K (1440p)'],['1080','1080P'],['720','720P'],['480','480P'],['360','360P']]);
  fillSelect('s_codec', [['best','极致画质'],['h264','兼容优先(H.264)'],['av1','AV1优先'],['vp9','VP9优先']]);
  fillSelect('s_audio', [['best','最高音质'],['192','均衡(192k)'],['128','最小体积(128k)']]);
  fillSelect('s_format', [['mp4','MP4'],['mkv','MKV'],['webm','WebM']]);
  fillSelect('s_audiomode', [['0','不单独处理音频'],['1','分离音画输出'],['2','同时输出音频'],['3','只输出音频']]);
  fillSelect('s_audiofmt', [['m4a','m4a(原生)'],['mp3','MP3'],['wav','WAV']]);
  fillSelect('s_hwaccel', [['cpu','CPU软编码'],['h264_nvenc','N卡 NVENC'],['h264_qsv','Intel QSV'],['h264_amf','AMD AMF']]);
  fillSelect('s_browser', [['chrome','Chrome'],['edge','Edge'],['firefox','Firefox'],['brave','Brave'],['opera','Opera']]);

  // 导航切换
  document.querySelectorAll('.ni').forEach(t => { t.onclick = () => setActivePage(t.dataset.page); });

  // 设置页两个滑块的数值回显
  $('s_threads').addEventListener('input', e => { $('thr_val').textContent = e.target.value; });
  $('s_speed').addEventListener('input', e => { $('spd_val').textContent = e.target.value === '0' ? '不限' : e.target.value + ' MB/s'; });
  initRanges();

  // 历史视图偏好
  try { historyView = localStorage.getItem(HISTORY_VIEW_KEY) === 'grid' ? 'grid' : 'list'; } catch(e) {}
  syncHistoryViewButtons();

  // 回车触发下载；Shift/Ctrl+回车换行；输入法组词期间的回车不触发
  const urlInput = $('urlInput');
  urlInput.addEventListener('keydown', e => {
    if(e.key === 'Enter' && !e.shiftKey && !e.ctrlKey && !e.altKey && !e.metaKey && !e.isComposing) {
      e.preventDefault();
      startDl();
    }
  });
  urlInput.addEventListener('input', autoGrowUrlInput);

  loadConfig();
  loadDeps();
  connectSSE();

  // 页面关闭前提示用户下载仍在进行中
  window.addEventListener('beforeunload', (e) => {
    if(download_running) {
      e.preventDefault();
      e.returnValue = '正在下载中！关闭页面后下载将继续在后台运行。如需彻底关闭工具，请先点击「退出工具」按钮。';
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
  document.querySelectorAll('#platforms .chip').forEach(b => b.classList.toggle('on', b.dataset.name===name));
  // 平台专项提示
  $('bilibiliHint').style.display    = name === 'Bilibili' ? '' : 'none';
  $('twitterHint').style.display     = name === 'Twitter' ? '' : 'none';
  $('nicochannelHint').style.display = name === 'NicoChannel' ? '' : 'none';
  $('withnyHint').style.display      = name === 'Withny' ? '' : 'none';

  const withnyMode = name === 'Withny';
  $('btnWithnyLive').style.display = withnyMode ? 'inline-flex' : 'none';
  const input = $('urlInput');
  input.disabled = withnyMode;
  input.placeholder = withnyMode
    ? 'Withny 使用浏览器导出的「包含内容」HAR，点右侧按钮选择文件…'
    : '粘贴视频 / 播放列表 / 频道 / 直播链接，每行一个…';
  $('btnStartLabel').textContent = withnyMode ? '选择 HAR 并下载' : '开始下载';
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
    addLog({time:new Date().toTimeString().slice(0,8), msg:msg, level:'success'});
    showToolStatus(msg, 'success');
    showToast(msg, 'success');
  } catch(e) {
    showToolStatus('请求失败: ' + e.message, 'error');
    showToast(e.message, 'error');
  }
}

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
  $('s_speed').value = s.SPEED_LIMIT; $('spd_val').textContent = s.SPEED_LIMIT===0?'不限':s.SPEED_LIMIT+' MB/s';
  setSwitch('sw_proxy', s.PROXY_ENABLED);
  $('s_proxytype').value = s.PROXY_TYPE;
  $('s_proxyaddr').value = s.PROXY_ADDR;
  $('s_proxyport').value = s.PROXY_PORT;
  setSwitch('sw_cookies', s.USE_COOKIES);
  $('s_cookiemode').value = s.COOKIE_MODE;
  $('s_browser').value = s.BROWSER_NAME;
  $('s_profile').value = s.BROWSER_PROFILE;
  $('s_hwaccel').value = s.HWACCEL;
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
  // YouTube 直播设置
  if (s.YOUTUBE_LIVE_MODE !== undefined) {
    $('s_youtube_live_mode').value = s.YOUTUBE_LIVE_MODE;
  } else {
    $('s_youtube_live_mode').value = 'dvr_from_start';
  }
  var liveWait = s.YOUTUBE_LIVE_WAIT_INTERVAL || 60;
  $('s_youtube_live_wait').value = liveWait;
  $('live_wait_val').textContent = liveWait + '秒';
  setSwitch('sw_live_mpegts', s.YOUTUBE_LIVE_USE_MPEGTS !== undefined ? s.YOUTUBE_LIVE_USE_MPEGTS : 1);
  setSwitch('sw_live_retries', s.YOUTUBE_LIVE_RETRIES_INFINITE !== undefined ? s.YOUTUBE_LIVE_RETRIES_INFINITE : 1);
  toggleCookieMode();
  paintRange($('s_threads'));
  paintRange($('s_speed'));
}

/** 根据值设置开关的开关状态。 */
function setSwitch(id, val) {
  if(val) $(id).classList.add('on'); else $(id).classList.remove('on');
}

/** 音频模式切换时更新格式选择器的可用状态。 */
function onAudioModeChange() {
  const mode = $('s_audiomode').value;
  // 模式 0（不处理音频）和模式 1（分离音画）不需要音频输出格式选择
  $('s_audiofmt').disabled = (mode === '0' || mode === '1');
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
    EMBED_META: isOn('sw_meta')?1:0,
    DOWNLOAD_THUMB: isOn('sw_thumb')?1:0,
    WIN_FILENAMES: isOn('sw_winfn')?1:0,
    STRICT_FILENAME: isOn('sw_strict')?1:0,
    NICO_COMMENTS: isOn('sw_nicocmt')?1:0,
    NICO_RECODE: isOn('sw_nicorec')?1:0,
    ENABLE_LOG: isOn('sw_log')?1:0,
    BILI_MULTIP_POLICY: $('s_bili_policy').value,
    YOUTUBE_LIVE_MODE: $('s_youtube_live_mode').value,
    YOUTUBE_LIVE_WAIT_INTERVAL: parseInt($('s_youtube_live_wait').value),
    YOUTUBE_LIVE_USE_MPEGTS: isOn('sw_live_mpegts') ? 1 : 0,
    YOUTUBE_LIVE_RETRIES_INFINITE: isOn('sw_live_retries') ? 1 : 0,
  };
}

/** 保存当前设置并在成功后提示。 */
async function saveSettings() {
  try {
    await api('/api/save-config', {method:'POST', body:JSON.stringify(collectCfg())});
    showToast('设置已保存', 'success');
  } catch(e) {
    showToast('设置保存失败: ' + e.message, 'error');
  }
}

/** 静默保存设置，不弹窗提示。 */
async function saveSettingsNoAlert() {
  return api('/api/save-config', {method:'POST', body:JSON.stringify(collectCfg())});
}

async function resetSettings() {
  if(!confirm('确定恢复默认设置？')) return;
  await api('/api/reset-config', {method:'POST'});
  location.reload();
}

async function loadDeps() {
  const d = await api('/api/deps');
  const names = {'yt-dlp':'yt-dlp', ffmpeg:'ffmpeg', ffprobe:'ffprobe',
    fantiadl:'fantiadl', withny_dl:'withny-dl', nicochannel_plugin:'nicochannel 插件'};
  const optional = {fantiadl:1, withny_dl:1, nicochannel_plugin:1};
  $('depStatus').innerHTML = Object.entries(d).map(([k,v]) =>
    `<span class="dep${v?'':' miss'}">${icon(v?'check':'x','s14')}${names[k]||k}` +
    `<span class="st">${v ? '已就绪' : (optional[k] ? '可选 · 未安装' : '缺失')}</span></span>`
  ).join('');
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

/** 链接输入框随内容自适应高度，并在状态条上回显链接数量。 */
function autoGrowUrlInput() {
  const el = $('urlInput');
  if(!el) return;
  el.style.height = 'auto';
  el.style.height = (el.scrollHeight + el.offsetHeight - el.clientHeight) + 'px';
  const n = el.value.split(/\r?\n/).map(cleanOneUrl).filter(Boolean).length;
  $('composeTip').textContent = n ? `${n} 个链接` : 'Enter 开始 · Shift+Enter 换行';
}

async function startDl() {
  if(currentPlatform === 'Withny') {
    await startWithnyArchive();
    return;
  }
  // 按行拆分，每行一个链接，清理后过滤空行
  const urls = $('urlInput').value.split(/\r?\n/).map(cleanOneUrl).filter(Boolean);
  if(urls.length === 0) { showToast('请输入链接', 'error'); return; }

  // 多链接：走批量下载（每行一个），跳过单条 Bilibili 分P 选择
  if(urls.length > 1) {
    try { await saveSettingsNoAlert(); } catch(e) { showToast('设置保存失败: ' + e.message, 'error'); return; }
    doStartUrls(urls);
    return;
  }

  // 单链接：沿用单任务流程（含 Bilibili 分P 选择）
  const url = urls[0];
  $('urlInput').value = url;
  autoGrowUrlInput();
  // 自动识别 Bilibili 链接（无需手动切换平台按钮）
  const isBiliUrl = isBilibiliUrl(url);
  if(isBiliUrl && currentPlatform !== 'Bilibili') selectPlatform('Bilibili');
  // 先保存设置
  try { await saveSettingsNoAlert(); } catch(e) { showToast('设置保存失败: ' + e.message, 'error'); return; }
  // Bilibili 多P选择策略（基于 URL 检测，而非平台按钮状态）
  if(isBiliUrl && $('s_bili_policy').value === 'select' && !isBilibiliLive(url)) {
    try {
      setStatus('正在获取分P列表…', 'live');
      const pl = await api('/api/bili-playlist', {method:'POST', body:JSON.stringify({url})});
      setStatus('就绪', 'idle');
      if(pl.error) { showToast(pl.error, 'error'); return; }
      if(pl.note) { addLog({time: nowTime(), msg: '[分P检测] ' + pl.note, level: 'info'}); }
      if(pl.parts && pl.parts.length > 1) {
        addLog({time: nowTime(), msg: `[分P检测] 检测到 ${pl.total} 个分P，等待选择…`, level: 'info'});
        pendingPartCallback = (parts) => doStartDl(url, parts);
        showPartSelector(pl.parts);
        return;
      }
    } catch(e) {
      addLog({time: nowTime(), msg: '[分P检测] 获取列表失败，将下载全部: ' + e.message, level: 'warn'});
      setStatus('就绪', 'idle');
    }
  }
  doStartDl(url);
}

function nowTime(){ return new Date().toTimeString().slice(0,8); }

async function startWithnyArchive() {
  $('btnStart').disabled = true;
  $('btnWithnyLive').disabled = true;
  try {
    const result = await api('/api/start-withny-archive', {method:'POST', body:'{}'});
    if(result.error) {
      showToast(result.error, 'error');
      $('btnStart').disabled = false;
      $('btnWithnyLive').disabled = false;
      return;
    }
    if(result.cancelled) {
      $('btnStart').disabled = false;
      $('btnWithnyLive').disabled = false;
      return;
    }
    markStarted('1');
  } catch(e) {
    showToast('Withny 下载启动失败: ' + e.message, 'error');
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
      showToast(result.error, 'error');
      $('btnStart').disabled = false;
      $('btnWithnyLive').disabled = false;
      return;
    }
    if(result.cancelled) {
      $('btnStart').disabled = false;
      $('btnWithnyLive').disabled = false;
      return;
    }
    markStarted('1');
  } catch(e) {
    showToast('Withny 直播录制启动失败: ' + e.message, 'error');
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

/** 任务启动后统一重置按钮与统计。 */
function markStarted(total) {
  download_running = true;
  $('btnStart').disabled = true;
  $('btnStop').disabled = false;
  $('statOk').textContent = '0';
  $('statFail').textContent = '0';
  $('statTotal').textContent = total;
  updateStatsVisibility();
}

async function doStartDl(url, biliParts, tcPassword) {
  const body = {url};
  if(biliParts) body.bili_parts = biliParts;
  if(tcPassword) body.tc_password = tcPassword;
  const r = await api('/api/start', {method:'POST', body:JSON.stringify(body)});
  if(r.error) { showToast(r.error, 'error'); return; }
  markStarted('1');
}

async function doStartUrls(urls) {
  const r = await api('/api/start-urls', {method:'POST', body:JSON.stringify({urls})});
  if(r.error) { showToast(r.error, 'error'); return; }
  markStarted(r.total || String(urls.length));
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
  if(r.error) { showToast(r.error, 'error'); return; }
  markStarted(r.total || '0');
}

async function stopDl() {
  const r = await api('/api/stop', {method:'POST'});
  if(r.error) { showToast(r.error, 'error'); return; }
  if(r.stopping) {
    download_running = true;
    $('btnStart').disabled = true;
    $('btnStop').disabled = true;
    setStatus('正在停止…', 'live');
  }
}

// ========== 进度与状态 ==========

/**
 * 更新状态行。
 * @param {string} text - 状态文字。
 * @param {string} blip - 状态点：live / idle / ok / err。
 */
function setStatus(text, blip) {
  const statusText = $('statusText');
  if(statusText.textContent !== text) {
    statusText.textContent = text;
    replayAnimation(statusText, 'status-change');
  }
  $('idleText').style.display = text === '就绪' ? '' : 'none';
  if(blip) $('statusBlip').className = 'blip ' + blip;
}

/** 根据状态文本推断状态点颜色。 */
function blipFor(status) {
  if(!status) return 'idle';
  if(status.includes('失败') || status.includes('异常')) return 'err';
  if(status.includes('完成')) return 'ok';
  if(status.includes('已停止') || status.includes('已取消') || status.includes('就绪')) return 'idle';
  return 'live';
}

/** 渲染进度：顶部细线 + 进度条 + 百分比。 */
function renderProgress(d) {
  const fill = $('progressFill');
  const pctText = $('progressText');
  if(d.percent < 0) {
    // 直播模式：无限进度动画
    fill.classList.add('live');
    fill.classList.remove('progressing', 'complete');
    fill.dataset.completed = '';
    pctText.textContent = 'LIVE';
    $('topline').style.width = '100%';
  } else if(d.percent !== undefined) {
    fill.classList.remove('live');
    const pct = Math.max(0, Math.min(100, Math.round(d.percent * 100)));
    fill.style.width = pct + '%';
    fill.classList.toggle('progressing', pct > 0 && pct < 100 && download_running);
    pctText.textContent = pct + '%';
    $('topline').style.width = download_running ? pct + '%' : '0';

    // 只在首次到达 100% 时播放完成脉冲，后续 SSE 同值不会反复闪烁。
    if(pct >= 100 && fill.dataset.completed !== '1') {
      fill.dataset.completed = '1';
      replayAnimation(fill, 'complete');
      setTimeout(() => fill.classList.remove('complete'), 700);
    } else if(pct < 100) {
      fill.dataset.completed = '';
      fill.classList.remove('complete');
    }
  }
  pctText.classList.toggle('dim', !download_running);
  if(d.status !== undefined) setStatus(d.status, blipFor(d.status));
  if(d.speed !== undefined) $('speedText').textContent = d.speed || '';
  if(d.eta !== undefined) $('etaText').textContent = d.eta ? '剩余 ' + d.eta : '';
}

/** 更新统计值，并在数字变化时播放弹出动画。 */
function setStatValue(id, value) {
  const el = $(id);
  const next = String(value);
  if(el.textContent === next) return;
  el.textContent = next;
  replayAnimation(el, 'stat-pop');
}

/** 批量统计行：仅在总数 ≥ 2 时出现。 */
function updateStatsVisibility() {
  const ok = parseInt($('statOk').textContent) || 0;
  const fail = parseInt($('statFail').textContent) || 0;
  const total = parseInt($('statTotal').textContent) || 0;
  setStatValue('statDone', ok + fail);
  $('taskStatsWrap').style.display = total < 2 ? 'none' : '';
}

// ========== 日志 ==========

/** 折叠/展开主日志面板。 */
function toggleLogBox() { toggleConsole('logConsole', 'logBox', 'btnLogToggle'); }
/** 折叠/展开工具日志面板。 */
function toggleToolLog() { toggleConsole('toolConsole', 'toolLogBox', 'btnToolLogToggle'); }

function toggleConsole(consoleId, boxId, btnId) {
  const box = $(boxId), btn = $(btnId), con = $(consoleId);
  const collapsed = box.style.display === 'none';
  box.style.display = collapsed ? '' : 'none';
  con.classList.toggle('collapsed', !collapsed);
  btn.innerHTML = icon(collapsed ? 'chevron' : 'chevron-up', 's14') + (collapsed ? '折叠' : '展开');
}

/** 清空主日志面板内容。 */
function clearConsole() { $('logBox').innerHTML = ''; }
/** 清空工具日志面板内容。 */
function clearToolConsole() { $('toolLogBox').innerHTML = ''; }

/** 写入一条日志，两个面板保持同步。 */
function addLog(entry) {
  _addToBox('logBox', entry);
  _addToBox('toolLogBox', entry);
}

function _addToBox(id, entry) {
  const box = $(id);
  if(!box) return;
  const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 30;
  const line = document.createElement('div');
  line.className = 'ln ' + (LOG_LEVEL_CLASS[entry.level] || '');
  const t = document.createElement('span');
  t.className = 't';
  t.textContent = entry.time;
  const m = document.createElement('span');
  m.className = 'm';
  m.textContent = entry.msg;
  line.append(t, m);
  box.appendChild(line);
  while(box.children.length > 300) box.removeChild(box.firstChild);
  if(atBottom) box.scrollTop = box.scrollHeight;
}

// ========== Toast 通知 ==========
/**
 * 显示 Toast 通知。
 * @param {string} msg - 通知消息文本。
 * @param {string} level - 通知级别（'success' | 'error' | 'working'）。
 */
function showToast(msg, level) {
  let container = document.querySelector('.toast-container');
  if(!container) {
    container = document.createElement('div');
    container.className = 'toast-container';
    document.body.appendChild(container);
  }
  const toast = document.createElement('div');
  toast.className = 'toast ' + (level || '');
  toast.innerHTML = icon(level === 'success' ? 'check' : level === 'error' ? 'x' : 'refresh', 's14');
  toast.appendChild(document.createTextNode(msg));
  container.appendChild(toast);
  setTimeout(() => {
    toast.classList.add('removing');
    setTimeout(() => toast.remove(), 260);
  }, 3000);
}

// 工具操作状态内联反馈
function showToolStatus(msg, type) {
  const el = $('toolStatus');
  if(!el) return;
  el.style.display = '';
  el.className = 'tool-status ' + (type || '');
  el.textContent = msg;
  if(type !== 'working') setTimeout(() => { el.style.display = 'none'; }, 5000);
}

// ========== SSE ==========
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
      addLog(evt.data);
    } else if(evt.type === 'progress') {
      renderProgress(evt.data);
    } else if(evt.type === 'download_state') {
      const d = evt.data;
      download_running = Boolean(d.running);
      $('btnStart').disabled = download_running || d.phase === 'suspended';
      $('btnWithnyLive').disabled = download_running || d.phase === 'suspended';
      $('btnStop').disabled = !download_running || d.phase === 'stopping';
      if(!download_running) $('topline').style.width = '0';
    } else if(evt.type === 'stats') {
      const d = evt.data;
      if(d.ok !== undefined) setStatValue('statOk', d.ok);
      if(d.fail !== undefined) setStatValue('statFail', d.fail);
      if(d.total !== undefined) setStatValue('statTotal', d.total);
      updateStatsVisibility();
    } else if(evt.type === 'password_required') {
      const d = evt.data;
      // 仅 TwitCasting 平台显示密码弹窗，其他平台忽略
      if(d.platform !== 'TwitCasting') return;
      pendingTcUrl = d.url;
      showTcPasswordPrompt(d.reason === 'retry');
    } else if(evt.type === 'history') {
      if(evt.data && evt.data.length && !$('page-history').classList.contains('active')) setHistoryDot(true);
      renderHistory(evt.data);
    } else if(evt.type === 'ready') {
      const readyData = Array.isArray(evt.data) ? {logs:evt.data, running:false} : evt.data;
      (readyData.logs || []).forEach(e => addLog(e));
      download_running = Boolean(readyData.running);
      $('btnStart').disabled = download_running || readyData.phase === 'suspended';
      $('btnStop').disabled = !download_running || readyData.phase === 'stopping';
      if(readyData.progress) renderProgress(readyData.progress);
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
      showExitScreen('工具已关闭，可安全关闭此页面');
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

function showExitScreen(msg) {
  document.body.innerHTML = `<div class="exit-screen">${icon('power','s28')}<div>${escHtml(msg)}</div></div>`;
}

async function exitApp() {
  if(!confirm('确定要彻底关闭工具吗？正在进行的下载将被终止。')) return;
  try { await api('/api/exit', {method:'POST'}); } catch(e) {}
  showExitScreen('正在关闭…');
  setTimeout(() => {
    try { window.close(); } catch(e) {}
    showExitScreen('工具已关闭，可安全关闭此页面');
  }, 1000);
}

init();

// ========== 预设 ==========
async function loadPresets() {
  const data = await api('/api/presets');
  updatePresetSelect(data.presets || []);
}

function updatePresetSelect(presets) {
  const sel = $('presetSelect');
  const currentVal = sel.value;
  sel.innerHTML = '<option value="">— 选择预设快速应用 —</option>' +
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
  if(!name) { showToast('请输入预设名称', 'error'); return; }
  await saveSettingsNoAlert();
  const r = await api('/api/save-preset', {method:'POST', body:JSON.stringify({name})});
  if(r && r.ok) {
    hideSavePreset();
    updatePresetSelect(r.presets);
    $('presetSelect').value = name;
    addLog({time:nowTime(), msg:`[预设] 已保存: ${name}`, level:'success'});
    showToast(`预设「${name}」已保存`, 'success');
  }
}

async function loadPresetFromSelect() {
  const name = $('presetSelect').value;
  if(!name) return;
  const r = await api('/api/load-preset', {method:'POST', body:JSON.stringify({name})});
  if(r && r.ok) {
    applyConfig(r.config);
    addLog({time:nowTime(), msg:`[预设] 已加载: ${name}`, level:'success'});
  }
}

async function deletePresetFromSelect() {
  const name = $('presetSelect').value;
  if(!name) { showToast('请先选择要删除的预设', 'error'); return; }
  if(!confirm(`确定删除预设「${name}」吗？`)) return;
  const r = await api('/api/delete-preset', {method:'POST', body:JSON.stringify({name})});
  if(r && r.ok) {
    updatePresetSelect(r.presets);
    addLog({time:nowTime(), msg:`[预设] 已删除: ${name}`, level:'warn'});
  }
}

// ========== 下载历史 ==========
async function loadHistory() {
  const data = await api('/api/history');
  renderHistory(data.history || []);
}

/** 切换列表 / 网格视图，偏好存 localStorage。 */
function setHistoryView(view) {
  historyView = view === 'grid' ? 'grid' : 'list';
  try { localStorage.setItem(HISTORY_VIEW_KEY, historyView); } catch(e) {}
  syncHistoryViewButtons();
  renderHistory(historyCache);
}

function syncHistoryViewButtons() {
  $('viewList').classList.toggle('on', historyView === 'list');
  $('viewGrid').classList.toggle('on', historyView === 'grid');
}

/** 缩略图（含左下角成功/失败标记）。缺封面时露出提示图标。 */
function thumbHtml(h) {
  const ok = h.status === 'success';
  const color = ok ? 'var(--ok)' : 'var(--err)';
  const cover = h.filepath
    ? `<img loading="lazy" alt="封面"
           src="/api/cover?path=${encodeURIComponent(h.filepath)}&token=${encodeURIComponent(SESSION_TOKEN)}"
           onload="this.classList.add('show')" onerror="this.remove()" onclick="openCover(this.src)">`
    : '';
  return `<div class="thumb">${icon('alert','s20')}${cover}` +
         `<span class="hstat"><span class="pd" style="background:${color}"></span>${ok?'成功':'失败'}</span></div>`;
}

function platformHtml(name) {
  const color = PLATFORM_COLORS[name] || 'var(--fg3)';
  return `<span class="hpl"><span class="pd" style="background:${color}"></span>${escHtml(name)}</span>`;
}

/** 去掉协议头，历史元信息里只留可读部分。 */
function shortUrl(url) {
  return String(url || '').replace(/^https?:\/\//, '').replace(/^www\./, '');
}

function renderHistory(history) {
  historyCache = history || [];
  const list = $('historyList');
  $('historyCount').textContent = `共 ${historyCache.length} 条`;

  if(!historyCache.length) {
    list.innerHTML = `<div class="empty">${icon('inbox','s28')}<span class="et">还没有下载记录</span>` +
      `<span style="font-size:12.5px">完成的任务会出现在这里，带封面缩略图。</span></div>`;
    return;
  }

  if(historyView === 'grid') {
    list.innerHTML = '<div class="hgrid">' + historyCache.map(h => `
      <div class="hcard">
        ${thumbHtml(h)}
        <div>
          <div class="hti" title="${escAttr(h.title)}">${escHtml(h.title)}</div>
          <div class="hme">${escHtml(String(h.time).slice(5,16))} · ${platformHtml(h.platform)}</div>
        </div>
      </div>`).join('') + '</div>';
  } else {
    list.innerHTML = '<div class="hlist">' + historyCache.map(h => `
      <div class="hitem">
        ${thumbHtml(h)}
        <div style="min-width:0">
          <div class="hti" title="${escAttr(h.title)}">${escHtml(h.title)}</div>
          <div class="hme">${escHtml(h.time)} · ${platformHtml(h.platform)} · ${escHtml(shortUrl(h.url))}</div>
        </div>
      </div>`).join('') + '</div>';
  }
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
  d.textContent = s === undefined || s === null ? '' : s;
  return d.innerHTML;
}
function escAttr(s) {
  return escHtml(String(s)).replace(/'/g, '&#39;').replace(/"/g, '&quot;');
}

// ========== 自动更新 ==========
let updateInfo = null;

function handleUpdateAvailable(data) {
  updateInfo = data;
  $('updateBadge').style.display = 'inline-flex';
  replayAnimation($('updateBadge'), 'attention');
  $('updateBadgeText').textContent = '有新版本 ' + (data.latest_version || '');
  $('updateCurVer').textContent = data.current_version || '';
  $('updateNewVer').textContent = data.latest_version || '';
  $('updateNotes').textContent = data.release_notes || '暂无更新说明';
  showUpdatePanel();
}

function handleUpdateProgress(data) {
  if(data.error) {
    $('updateProgText').textContent = '更新失败: ' + data.error;
    $('updateProgText').className = 'txt-err';
    $('updateProgress').style.display = 'flex';
    $('updateActions').style.display = '';
    $('btnDoUpdate').disabled = false;
    $('btnDoUpdate').textContent = '重试';
    return;
  }
  $('updateProgress').style.display = 'flex';
  $('updateActions').style.display = 'none';
  const pct = Math.round(data.percent || 0);
  $('updateProgFill').style.width = pct + '%';
  $('updateProgPct').textContent = pct + '%';
  $('updateProgSpeed').textContent = data.speed || '';
  if(data.done) {
    $('updateProgress').style.display = 'none';
    $('updateDone').style.display = 'flex';
    if(data.message) $('updateDoneMsg').textContent = data.message;
  }
}

function showUpdatePanel() { $('updatePanel').classList.add('show'); }
function hideUpdatePanel() { $('updatePanel').classList.remove('show'); }

/**
 * 关于页「检查更新」。
 * /api/check-update 只负责起线程，结果轮询 /api/update-status 拿。
 * 有新版本时后端也会走 SSE 推送，这里只补一句“已是最新”的反馈。
 */
async function checkUpdateNow() {
  showToast('正在检查更新…', 'working');
  try {
    await api('/api/check-update');
    for(let i = 0; i < 20; i++) {
      await new Promise(r => setTimeout(r, 500));
      const s = await api('/api/update-status');
      if(s.checking) continue;
      if(s.error) { showToast('检查更新失败: ' + s.error, 'error'); return; }
      if(s.update_available) handleUpdateAvailable(s);
      else showToast('已是最新版本', 'success');
      return;
    }
    showToast('检查更新超时，请稍后重试', 'error');
  } catch(e) {
    showToast('检查更新失败: ' + e.message, 'error');
  }
}

async function doUpdateNow() {
  if(!updateInfo || !updateInfo.download_url) {
    showToast('暂无下载链接，请稍后重试', 'error');
    return;
  }
  $('btnDoUpdate').disabled = true;
  $('btnDoUpdate').textContent = '更新中…';
  $('updateProgText').textContent = '正在下载更新…';
  $('updateProgText').className = 'dim';
  $('updateProgress').style.display = 'flex';
  $('updateProgFill').style.width = '0%';
  $('updateProgPct').textContent = '0%';
  try {
    const result = await api('/api/do-update', {method:'POST', body:'{}'});
    if(result.error) handleUpdateProgress({error:result.error});
  } catch(e) {
    handleUpdateProgress({error:'更新请求失败: ' + e.message});
  }
}

// ========== Bilibili 分P 选择 ==========
let pendingPartCallback = null;
let pendingTcUrl = null;

function showPartSelector(parts) {
  const list = $('partList');
  list.replaceChildren(...parts.map(p => {
    const label = document.createElement('label');
    label.className = 'pitem';
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.value = String(p.index ?? '');
    checkbox.checked = true;
    checkbox.addEventListener('change', updatePartCount);
    const index = document.createElement('span');
    index.className = 'pi';
    index.textContent = `P${p.index ?? ''}`;
    const title = document.createElement('span');
    title.className = 'pt';
    title.title = String(p.title ?? '');
    title.textContent = String(p.title ?? '');
    const duration = document.createElement('span');
    duration.className = 'pdur';
    duration.textContent = fmtDuration(p.duration);
    label.append(checkbox, index, title, duration);
    return label;
  }));
  updatePartCount();
  $('partSelectorOverlay').classList.add('show');
}

function closePartSelector() {
  $('partSelectorOverlay').classList.remove('show');
  pendingPartCallback = null;
}

function toggleAllParts(selectAll) {
  document.querySelectorAll('#partList input[type="checkbox"]').forEach(cb => { cb.checked = selectAll; });
  updatePartCount();
}

function updatePartCount() {
  const cbs = document.querySelectorAll('#partList input[type="checkbox"]');
  const checked = document.querySelectorAll('#partList input[type="checkbox"]:checked').length;
  $('partCount').textContent = `已选 ${checked} / ${cbs.length}`;
  $('btnPartConfirm').textContent = `下载选中 ${checked} 个分P`;
}

function confirmPartSelection() {
  const checked = document.querySelectorAll('#partList input[type="checkbox"]:checked');
  if(checked.length === 0) { showToast('请至少选择一个分P', 'error'); return; }
  const indices = Array.from(checked).map(cb => cb.value).join(',');
  const cb = pendingPartCallback;  // closePartSelector 会清除 pendingPartCallback
  closePartSelector();
  if(cb) cb(indices);
}

// ========== TwitCasting 密码 ==========
function showTcPasswordPrompt(isRetry) {
  $('tcPasswordInput').value = '';
  $('tcPasswordMsg').textContent = isRetry
    ? '下载失败，密码可能不正确，请重新输入后重试。'
    : '该视频受密码保护或为会员限定内容，输入密码后继续下载。';
  $('tcPasswordOverlay').classList.add('show');
  setTimeout(() => $('tcPasswordInput').focus(), 100);
}

function closeTcPasswordPrompt() {
  $('tcPasswordOverlay').classList.remove('show');
  pendingTcUrl = null;
}

function confirmTcPassword() {
  const pw = $('tcPasswordInput').value.trim();
  if(!pw) { showToast('请输入密码', 'error'); return; }
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

/** 工具页：面板展开时高亮对应磁贴。 */
function syncToolTiles() {
  document.querySelectorAll('.tile[data-panel]').forEach(t => {
    const panel = $(t.dataset.panel);
    t.classList.toggle('on', Boolean(panel && panel.classList.contains('show')));
  });
}

// 页面加载3秒后主动检查更新（后端也会静默检查，双保险）
setTimeout(() => { api('/api/check-update').catch(()=>{}); }, 3000);
