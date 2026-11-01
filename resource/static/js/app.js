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
let downloadGeneration = null;
let activeTaskYtdlpArgs = "";
let liveWatchJobs = [];
const liveRecordings = new Map();
let tasksCache = [];
let expandedTasks = new Set();
let taskModeEnabled = true;
let taskSnapshotVersion = 0;
let taskLoadRequest = 0;
const seenTaskPrompts = new Set();
let networkPollTimer = null;
let networkResultId = '';
let networkApplying = false;
let networkEventVersion = 0;
let livePlatformModes = {};
let liveCommentPlatforms = {};
let liveCapabilities = null;
let liveNoticeResolver = null;
let liveNoticeKind = "";
const LIVE_NOTICE_MUTE_KEY = 'video-dl-live-notice-muted';
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
  {name:"Withny",color:"#22C55E"},
  {name:"Rplay",color:"#F43F5E"},
  {name:"Fanbox",color:"#0096FA"}
];
const PLATFORM_COLORS = Object.fromEntries(PLATFORMS.map(p => [p.name, p.color]));

const PAGE_TITLES = {
  download: '下载任务', settings: '下载设置', history: '下载历史',
  tools: '实用工具', help: '使用帮助', about: '关于软件'
};

// 后端日志级别 → .ln 修饰类
const LOG_LEVEL_CLASS = {success:'s', warn:'w', error:'e', info:''};
const LEGACY_ALL_SUBTITLE_LANGS = 'all,-live_chat';
const DEFAULT_SUBTITLE_LANGS = 'zh.*,zh-Hans,zh-Hant';
const SUBTITLE_LANG_PRESETS = [
  [LEGACY_ALL_SUBTITLE_LANGS, '全部字幕'],
  [DEFAULT_SUBTITLE_LANGS, '中文（默认）'],
  ['ja.*', '日语'],
  ['en.*', '英语'],
  ['ko.*', '韩语'],
  ['custom', '自定义']
];

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
  fillSelect('s_live_mode', [['auto','自动（推荐）'],['catch_up','追开播（条件）'],['live_edge','从当前时刻'],['wait','蹲开播（开播后自动录制）']]);
  fillSelect('s_task_order', [['none','不排序（默认）'],['live_first','直播录制优先'],['download_first','下载任务优先']]);
  fillSelect('s_browser', [['chrome','Chrome'],['edge','Edge'],['firefox','Firefox'],['brave','Brave'],['opera','Opera']]);
  $('s_browser').addEventListener('change', onBrowserChanged);
  fillSelect('s_subtitle_lang_preset', SUBTITLE_LANG_PRESETS);
  fillSelect('tool_subtitle_lang_preset', SUBTITLE_LANG_PRESETS);

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
  loadLiveWatch();
  api('/api/live/recordings').then(data => (data.recordings || []).reverse().forEach(renderLiveRecording)).catch(() => {});
  loadTasks();
  loadNetworkStatus();
  initSettingsToc();
  loadLiveCapabilities();

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
  s.innerHTML = '';
  opts.forEach(([v,l]) => { const o=document.createElement('option');o.value=v;o.textContent=l;s.appendChild(o); });
}

function selectPlatform(name) {
  currentPlatform = name;
  if(name !== 'Withny') lastUrlPlatform = name;
  document.querySelectorAll('#platforms .chip').forEach(b => b.classList.toggle('on', b.dataset.name===name));
  // 平台专项提示
  $('bilibiliHint').style.display    = name === 'Bilibili' ? '' : 'none';
  $('twitterHint').style.display     = name === 'Twitter' ? '' : 'none';
  $('twitcastingHint').style.display = name === 'TwitCasting' ? '' : 'none';
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
  if(window.FanboxUI)window.FanboxUI.sync();
}

/** 切换开关状态。 */
function toggleSwitch(el) {
  el.classList.toggle('on');
  if(el.getAttribute('role') === 'switch') el.setAttribute('aria-checked', String(el.classList.contains('on')));
}
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
  if(window.FanboxUI)window.FanboxUI.applyConfig(s);
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
  $('s_rplay_auth').value = s.RPLAY_AUTH_SOURCE || 'none';
  $('s_rplay_profile').value = s.RPLAY_FIREFOX_PROFILE || '';
  onBrowserChanged();
  $('s_hwaccel').value = s.HWACCEL;
  if(s.LIVE_STREAM_METHOD !== undefined) $('s_live_stream_method').value = s.LIVE_STREAM_METHOD;
  if(s.LIVE_MODE !== undefined) $('s_live_mode').value = s.LIVE_MODE;
  if(s.LIVE_PLATFORM_MODES !== undefined) {
    livePlatformModes = parseLivePlatformModes(s.LIVE_PLATFORM_MODES);
    renderLivePlatformModes();
  }
  if(s.LIVE_DOWNLOAD_TIMEOUT !== undefined) $('s_live_timeout').value = s.LIVE_DOWNLOAD_TIMEOUT || 0;
  setSwitch('sw_live_danmaku', s.LIVE_DANMAKU_ENABLED);
  setSwitch('sw_live_danmaku_anon', s.LIVE_DANMAKU_ANONYMIZE);
  $('s_live_danmaku_formats').value = s.LIVE_DANMAKU_FORMATS || 'srt,ass';
  $('s_live_danmaku_offset').value = s.LIVE_DANMAKU_OFFSET_MS || 0;
  try { liveCommentPlatforms = JSON.parse(s.LIVE_DANMAKU_PLATFORMS || '{}'); } catch(e) { liveCommentPlatforms = {}; }
  renderLiveCommentPlatforms();
  for(const [key, id] of Object.entries({LIVE_MAX_RETRIES:'s_live_retries', LIVE_WATCHDOG_SECONDS:'s_live_watchdog', LIVE_MIN_FREE_MB:'s_live_free_mb', LIVE_ESTIMATED_BITRATE_KBPS:'s_live_bitrate'})) {
    if(s[key] !== undefined) $(id).value = s[key];
  }
  if(s.TASK_MODE !== undefined) {
    taskModeEnabled = String(s.TASK_MODE) === '1';
    setSwitch('sw_task_mode', s.TASK_MODE);
    renderTasks(tasksCache);
  }
  if(s.TASK_MAX_PARALLEL !== undefined) $('s_task_parallel').value = s.TASK_MAX_PARALLEL;
  if(s.TASK_LIVE_PARALLEL !== undefined) $('s_task_live_parallel').value = s.TASK_LIVE_PARALLEL;
  setSwitch('sw_task_mixed', s.TASK_MIXED_PARALLEL === undefined ? 1 : s.TASK_MIXED_PARALLEL);
  if(s.TASK_DOWNLOAD_PARALLEL !== undefined) $('s_task_download_parallel').value = s.TASK_DOWNLOAD_PARALLEL;
  if(s.TASK_DOWNLOAD_SPEED_LIMIT !== undefined) $('s_task_download_speed').value = s.TASK_DOWNLOAD_SPEED_LIMIT;
  onTaskMixedChange();
  if(s.TASK_ORDER !== undefined) $('s_task_order').value = s.TASK_ORDER;
  setSwitch('sw_meta', s.EMBED_META);
  setSwitch('sw_thumb', s.DOWNLOAD_THUMB);
  setSwitch('sw_subtitles', s.DOWNLOAD_SUBTITLES);
  $('s_subtitle_type').value = s.SUBTITLE_TYPE || 'all';
  applySubtitleLanguageValue('s', s.SUBTITLE_LANGS || DEFAULT_SUBTITLE_LANGS);
  onSubtitleToggle();
  setSwitch('sw_winfn', s.WIN_FILENAMES);
  setSwitch('sw_strict', s.STRICT_FILENAME);
  setSwitch('sw_nicocmt', s.NICO_COMMENTS);
  setSwitch('sw_nicorec', s.NICO_RECODE);
  setSwitch('sw_tc_remember', s.TC_REMEMBER_PASSWORD);
  setSwitch('sw_tc_xlsx', s.TC_SAVE_PASSWORD_XLSX);
  onTcPasswordChange();
  setSwitch('sw_youtube_po_token', s.YOUTUBE_PO_TOKEN_ENABLED);
  $('s_ytdlp_default_args').value = s.YTDLP_DEFAULT_ARGS || '';
  setSwitch('sw_log', s.ENABLE_LOG);
  if(s.BILI_MULTIP_POLICY !== undefined) $('s_bili_policy').value = s.BILI_MULTIP_POLICY;
  // 音频输出格式设置（audio-convert.js 负责 UI 初始化）
  if(s.AUDIO_OUTPUT_FORMAT !== undefined && $('audioOutFormat')) $('audioOutFormat').value = s.AUDIO_OUTPUT_FORMAT;
  setSwitch('sw_audioDelSrc', false); // Destructive choice is explicit for each session.
  setSwitch('sw_audioRecursive', s.AUDIO_RECURSIVE);
  if(typeof updateAudioQualityUI === 'function') updateAudioQualityUI();
  toggleCookieMode();
  paintRange($('s_threads'));
  paintRange($('s_speed'));
}

/** 根据值设置开关的开关状态。 */
function setSwitch(id, val) {
  if(val) $(id).classList.add('on'); else $(id).classList.remove('on');
  if($(id).getAttribute('role') === 'switch') $(id).setAttribute('aria-checked', String(!!val));
}

/** 音频模式切换时更新格式选择器的可用状态。 */
function onAudioModeChange() {
  const mode = $('s_audiomode').value;
  // 模式 0（不处理音频）和模式 1（分离音画）不需要音频输出格式选择
  $('s_audiofmt').disabled = (mode === '0' || mode === '1');
}

function applySubtitleLanguageValue(scope, value) {
  const select = $(scope === 's' ? 's_subtitle_lang_preset' : 'tool_subtitle_lang_preset');
  const input = $(scope === 's' ? 's_subtitle_langs' : 'tool_subtitle_langs');
  const normalized = (value || DEFAULT_SUBTITLE_LANGS).trim() || DEFAULT_SUBTITLE_LANGS;
  const preset = SUBTITLE_LANG_PRESETS.find(item => item[0] === normalized);
  select.value = preset ? normalized : 'custom';
  input.value = normalized;
  onSubtitleLanguagePresetChange(scope);
}

function onSubtitleLanguagePresetChange(scope) {
  const select = $(scope === 's' ? 's_subtitle_lang_preset' : 'tool_subtitle_lang_preset');
  const input = $(scope === 's' ? 's_subtitle_langs' : 'tool_subtitle_langs');
  const row = $(scope === 's' ? 'row_subtitle_custom' : 'tool_subtitle_custom_row');
  const custom = select.value === 'custom';
  row.style.display = custom ? 'flex' : 'none';
  if(!custom) input.value = select.value;
}

function getSubtitleLanguageValue(scope) {
  const select = $(scope === 's' ? 's_subtitle_lang_preset' : 'tool_subtitle_lang_preset');
  const input = $(scope === 's' ? 's_subtitle_langs' : 'tool_subtitle_langs');
  return select.value === 'custom' ? input.value.trim() : select.value;
}

function onSubtitleToggle() {
  const enabled = isOn('sw_subtitles');
  $('s_subtitle_type').disabled = !enabled;
  $('s_subtitle_lang_preset').disabled = !enabled;
  $('s_subtitle_langs').disabled = !enabled;
}

/** Cookie 模式切换时显示/隐藏浏览器相关设置行。 */
function toggleCookieMode() {
  const browserMode = $('s_cookiemode').value === '2';
  $('row_browser').style.display = browserMode ? 'flex' : 'none';
  $('row_profile').style.display = browserMode ? 'flex' : 'none';
}

/** Firefox Profile 通常带随机前缀；留空交给 yt-dlp 自动选择最近使用项。 */
function onBrowserChanged() {
  const profile = $('s_profile');
  if($('s_browser').value === 'firefox') {
    if(profile.value.trim().toLowerCase() === 'default') profile.value = '';
    profile.placeholder = '留空自动探测最近使用的 Firefox Profile';
  } else {
    if(!profile.value.trim()) profile.value = 'Default';
    profile.placeholder = '例如 Default 或 Profile 1';
  }
}


function parseLivePlatformModes(value) {
  if(value && typeof value === 'object') return value;
  try {
    const parsed = JSON.parse(value || '{}');
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch(e) { return {}; }
}

function renderLiveCommentPlatforms(preserve = false) {
  const host = $('liveCommentPlatforms');
  if(!host) return;
  if(preserve) host.querySelectorAll('[data-live-comment-platform]').forEach(el => {
    liveCommentPlatforms[el.dataset.liveCommentPlatform] = el.value;
  });
  const names = ['Bilibili','YouTube','Twitch','TwitCasting','NicoChannel','Niconico','Withny'];
  host.innerHTML = names.map(name => `<label class="live-platform-row"><span class="lb">${name}</span>
    <span class="sel"><select class="ctl" data-live-comment-platform="${name}" aria-label="${name} 弹幕默认">
    <option value="inherit">跟随全局</option><option value="on">默认抓取</option><option value="off">默认不抓取</option>
    </select></span></label>`).join('');
  host.querySelectorAll('select').forEach(el => { el.value = liveCommentPlatforms[el.dataset.liveCommentPlatform] || 'inherit'; });
}

function renderLivePlatformModes() {
  const host = $('livePlatformModes');
  if(!host) return;
  const caps = liveCapabilities || {
    YouTube: {catch_up:'supported', live_edge:true},
    Twitch: {catch_up:'supported', live_edge:true}
  };
  const rows = Object.entries(caps).filter(([name, c]) =>
    c && ['supported','conditional'].includes(c.catch_up) && c.live_edge && ['YouTube','Twitch'].includes(name)
  );
  if(!rows.length) {
    host.innerHTML = '<div class="live-platform-empty">当前没有同时支持追开播和当前录制的平台</div>';
    return;
  }
  host.innerHTML = rows.map(([name]) => `
    <label class="live-platform-row">
      <span class="lb">${name}</span>
      <span class="sel"><select class="ctl" data-live-platform="${name}">
        <option value="auto">自动（条件允许时追开播）</option>
        <option value="catch_up">追开播</option>
        <option value="live_edge">从当前时刻</option>
      </select><svg class="ico s14 cv"><use href="#i-chevron"></use></svg></span>
    </label>`).join('');
  host.querySelectorAll('select[data-live-platform]').forEach(select => {
    select.value = livePlatformModes[select.dataset.livePlatform] || 'auto';
  });
}

async function loadLiveCapabilities() {
  try {
    const r = await api('/api/live/capabilities');
    if(r && r.platforms) {
      liveCapabilities = r.platforms;
      renderLivePlatformModes();
      renderLiveCommentPlatforms(true);
    }
  } catch(e) { /* 使用静态兜底 */ }
}

function collectLivePlatformModes() {
  const result = {};
  document.querySelectorAll('#livePlatformModes select[data-live-platform]').forEach(select => {
    result[select.dataset.livePlatform] = select.value;
  });
  return result;
}

function initSettingsToc() {
  const toc = $('settingsToc');
  if(!toc) return;
  const items = Array.from(toc.querySelectorAll('.settings-toc-item'));
  const sections = items.map(item => $(item.dataset.target)).filter(Boolean);
  const setActive = target => {
    items.forEach(item => item.classList.toggle('on', item.dataset.target === target));
  };
  items.forEach(item => {
    item.onclick = () => {
      const target = $(item.dataset.target);
      if(!target) return;
      setActive(item.dataset.target);
      target.scrollIntoView({behavior:'smooth', block:'start'});
    };
  });
  try {
    if(localStorage.getItem('video-dl-settings-toc-collapsed') === '1') {
      toc.classList.add('collapsed');
    }
  } catch(e) {}
  const toggle = $('settingsTocToggle');
  if(toggle) {
    toggle.onclick = () => {
      toc.classList.toggle('collapsed');
      try {
        localStorage.setItem('video-dl-settings-toc-collapsed', toc.classList.contains('collapsed') ? '1' : '0');
      } catch(e) {}
    };
  }
  // 页面自身就是滚动容器，用 IntersectionObserver 更新当前章节。
  if('IntersectionObserver' in window) {
    const observer = new IntersectionObserver(entries => {
      const visible = entries.filter(entry => entry.isIntersecting)
        .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
      if(visible) setActive(visible.target.id);
    }, {root: document.querySelector('.pad'), threshold:[0.15, 0.4, 0.7]});
    sections.forEach(section => observer.observe(section));
  }
}

/** 从设置表单中收集当前全部配置项。 */
function collectCfg() {
  return {
    PLATFORM: currentPlatform === 'Withny' ? lastUrlPlatform : currentPlatform,
    ...(window.FanboxUI?window.FanboxUI.configValues():{}),
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
    RPLAY_AUTH_SOURCE: $('s_rplay_auth').value,
    RPLAY_FIREFOX_PROFILE: $('s_rplay_profile').value.trim(),
    BROWSER_PROFILE: $('s_profile').value,
    HWACCEL: $('s_hwaccel').value,
    LIVE_STREAM_METHOD: $('s_live_stream_method').value,
    LIVE_MODE: $('s_live_mode').value,
    LIVE_PLATFORM_MODES: JSON.stringify(collectLivePlatformModes()),
    LIVE_DOWNLOAD_TIMEOUT: parseInt($('s_live_timeout').value) || 0,
    LIVE_DANMAKU_ENABLED: isOn('sw_live_danmaku') ? 1 : 0,
    LIVE_DANMAKU_ANONYMIZE: isOn('sw_live_danmaku_anon') ? 1 : 0,
    LIVE_DANMAKU_FORMATS: $('s_live_danmaku_formats').value,
    LIVE_DANMAKU_OFFSET_MS: Number($('s_live_danmaku_offset').value),
    LIVE_DANMAKU_PLATFORMS: JSON.stringify(Object.fromEntries(Array.from(document.querySelectorAll('[data-live-comment-platform]')).filter(el => el.value !== 'inherit').map(el => [el.dataset.liveCommentPlatform, el.value]))),
    LIVE_MAX_RETRIES: Number($('s_live_retries').value),
    LIVE_WATCHDOG_SECONDS: Number($('s_live_watchdog').value),
    LIVE_MIN_FREE_MB: Number($('s_live_free_mb').value),
    LIVE_ESTIMATED_BITRATE_KBPS: Number($('s_live_bitrate').value),
    TASK_MODE: isOn('sw_task_mode') ? 1 : 0,
    TASK_MAX_PARALLEL: Math.max(1, Math.min(5, parseInt($('s_task_parallel').value) || 2)),
    TASK_MIXED_PARALLEL: isOn('sw_task_mixed') ? 1 : 0,
    TASK_LIVE_PARALLEL: Math.max(2, Math.min(5, parseInt($('s_task_live_parallel').value) || 2)),
    TASK_DOWNLOAD_PARALLEL: Math.max(1, Math.min(5, parseInt($('s_task_download_parallel').value) || 1)),
    TASK_DOWNLOAD_SPEED_LIMIT: Math.max(0, Math.min(100000, parseFloat($('s_task_download_speed').value) || 0)),
    TASK_ORDER: $('s_task_order').value,
    EMBED_META: isOn('sw_meta')?1:0,
    DOWNLOAD_THUMB: isOn('sw_thumb')?1:0,
    DOWNLOAD_SUBTITLES: isOn('sw_subtitles')?1:0,
    SUBTITLE_TYPE: $('s_subtitle_type').value,
    SUBTITLE_LANGS: getSubtitleLanguageValue('s') || DEFAULT_SUBTITLE_LANGS,
    WIN_FILENAMES: isOn('sw_winfn')?1:0,
    STRICT_FILENAME: isOn('sw_strict')?1:0,
    NICO_COMMENTS: isOn('sw_nicocmt')?1:0,
    NICO_RECODE: isOn('sw_nicorec')?1:0,
    TC_REMEMBER_PASSWORD: isOn('sw_tc_remember')?1:0,
    TC_SAVE_PASSWORD_XLSX: isOn('sw_tc_remember') && isOn('sw_tc_xlsx')?1:0,
    YOUTUBE_PO_TOKEN_ENABLED: isOn('sw_youtube_po_token')?1:0,
    YTDLP_DEFAULT_ARGS: $('s_ytdlp_default_args').value.trim(),
    ENABLE_LOG: isOn('sw_log')?1:0,
    BILI_MULTIP_POLICY: $('s_bili_policy').value,
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

function onTaskMixedChange() {
  const disabled = !isOn('sw_task_mixed');
  $('s_task_live_parallel').disabled = disabled;
  $('s_task_download_parallel').disabled = disabled;
}

function describeNetworkSettings(settings) {
  const limit = settings.TASK_DOWNLOAD_SPEED_LIMIT;
  return `${settings.TASK_MAX_PARALLEL} 个任务；每任务 ${settings.TASK_LIVE_PARALLEL} 路直播 + ${settings.TASK_DOWNLOAD_PARALLEL} 路视频；每链接 ${settings.THREADS} 分片线程；视频${limit ? '限速 ' + limit + ' MiB/s' : '不限速'}。全局限速设为不限。`;
}

function renderNetworkTest(data) {
  if(!data) return;
  clearTimeout(networkPollTimer);
  $('btnNetworkTest').disabled = Boolean(data.running) || networkApplying;
  $('btnNetworkCancel').disabled = !data.running;
  $('networkTestStatus').textContent = data.message || '尚未检测';
  const result = data.phase === 'completed' ? data.result : null;
  networkResultId = result?.id || '';
  $('networkProfiles').style.display = result ? '' : 'none';
  $('networkTestMetrics').textContent = '';
  $('networkTestNotes').textContent = '';
  if(result) {
    const m = result.metrics;
    const fmt = (value, unit) => Number.isFinite(value) ? value + unit : '未测得';
    $('networkTestMetrics').textContent = [
      `线路：${result.route} · ${m.duration_seconds} 秒 · 下载 ${m.downloaded_mib} MiB · ${m.sample_count} 个 HTTP 样本`,
      `吞吐观测区间：${fmt(m.download_low_mbps, ' Mbps')} – ${fmt(m.download_high_mbps, ' Mbps')}`,
      `单连接：${fmt(m.single_mbps, ' Mbps')} · 多连接：${fmt(m.parallel_mbps, ' Mbps')}`,
      `HTTP 首字节延迟（含握手）：${fmt(m.http_latency_ms, ' ms')} · 抖动：${fmt(m.http_jitter_ms, ' ms')}`,
      `负载延迟：${fmt(m.loaded_latency_ms, ' ms')} · HTTP 请求失败率：${(m.request_failure_rate * 100).toFixed(1)}% · ${m.confidence === 'limited' ? '样本有限' : '样本正常'}`
    ].join('\n');
    $('networkTestNotes').textContent = (result.notes || []).join(' ');
    for(const [mode, name] of [['performance','Performance'],['reliable','Reliable']]) {
      const profile = result.profiles[mode];
      $('network' + name + 'Summary').textContent = profile.summary;
      $('network' + name + 'Settings').textContent = describeNetworkSettings(profile.settings);
      $('btnNetwork' + name).disabled = networkApplying;
    }
  }
  if(data.running) networkPollTimer = setTimeout(loadNetworkStatus, 700);
}

async function loadNetworkStatus() {
  const version = networkEventVersion;
  try {
    const result = await api('/api/network-test');
    if(version === networkEventVersion) renderNetworkTest(result);
  } catch(e) {
    $('networkTestStatus').textContent = '读取检测状态失败：' + e.message;
    $('btnNetworkTest').disabled = false;
  }
}

async function startNetworkTest() {
  $('btnNetworkTest').disabled = true;
  try {
    await saveSettingsNoAlert();
    const result = await api('/api/network-test/start', {method:'POST', body:'{}'});
    if(result.error) showToast(result.error, 'error');
    await loadNetworkStatus();
  } catch(e) {
    showToast('网络检测启动失败：' + e.message, 'error');
    $('btnNetworkTest').disabled = false;
  }
}

async function cancelNetworkTest() {
  try {
    await api('/api/network-test/cancel', {method:'POST', body:'{}'});
    await loadNetworkStatus();
  } catch(e) { showToast('取消检测失败：' + e.message, 'error'); }
}

async function applyNetworkProfile(mode) {
  if(!networkResultId || networkApplying) return;
  const resultId = networkResultId;
  networkApplying = true;
  $('btnNetworkPerformance').disabled = $('btnNetworkReliable').disabled = true;
  $('btnNetworkTest').disabled = true;
  try {
    // Preserve unrelated edits; the server then patches only tuning fields and
    // rejects recommendations measured with different proxy settings.
    await saveSettingsNoAlert();
    const result = await api('/api/network-test/apply', {method:'POST', body:JSON.stringify({mode, result_id:resultId})});
    if(result.error) { showToast(result.error, 'error'); return; }
    applyConfig(result.config);
    showToast((mode === 'performance' ? '高性能' : '高可靠') + '配置已保存，将用于新任务', 'success');
  } catch(e) { showToast('应用自动配置失败：' + e.message, 'error'); }
  finally { networkApplying = false; loadNetworkStatus(); }
}

async function loadDeps() {
  const d = await api('/api/deps');
  const names = {'yt-dlp':'yt-dlp', ffmpeg:'ffmpeg', ffprobe:'ffprobe',
    fantiadl:'fantiadl', withny_dl:'withny-dl', nicochannel_plugin:'nicochannel 插件',
    youtube_po_token:'YouTube PO Token Provider', live_comment_export:'弹幕字幕导出',
    live_comment_transport:'直播评论连接', live_comment_niconico:'Niconico 评论协议'};
  const optional = {fantiadl:1, withny_dl:1, nicochannel_plugin:1, youtube_po_token:1,
    live_comment_export:1, live_comment_transport:1, live_comment_niconico:1};
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
  if(window.FanboxUI&&urls.every(window.FanboxUI.matches))return window.FanboxUI.start(urls.join('\n'));
  const taskArgs = $('task_ytdlp_args').value.trim();
  activeTaskYtdlpArgs = taskArgs;

  // 多链接：走批量下载（每行一个），跳过单条 Bilibili 分P 选择
  if(urls.length > 1) {
    if($('s_live_mode').value === 'wait') {
      showToast('蹲开播仅支持单条链接，请逐条添加', 'error');
      return;
    }
    try { await saveSettingsNoAlert(); } catch(e) { showToast('设置保存失败: ' + e.message, 'error'); return; }
    doStartUrls(urls, taskArgs);
    return;
  }

  // 单链接：沿用单任务流程（含 Bilibili 分P 选择）
  const url = urls[0];
  $('urlInput').value = url;
  autoGrowUrlInput();
  // 自动识别 Bilibili 链接（无需手动切换平台按钮）
  const isBiliUrl = isBilibiliUrl(url);
  const isNicoChannelLiveUrl = isNicoChannelLive(url);
  if(isNicoChannelLiveUrl && currentPlatform !== 'NicoChannel') selectPlatform('NicoChannel');
  if(isBiliUrl && currentPlatform !== 'Bilibili') selectPlatform('Bilibili');
  // 先保存设置
  try { await saveSettingsNoAlert(); } catch(e) { showToast('设置保存失败: ' + e.message, 'error'); return; }
  // Bilibili 多P选择策略（基于 URL 检测，而非平台按钮状态）
  if(isBiliUrl && $('s_bili_policy').value === 'select' && !isBilibiliLive(url) && !isNicoChannelLiveUrl) {
    try {
      setStatus('正在获取分P列表…', 'live');
      const pl = await api('/api/bili-playlist', {method:'POST', body:JSON.stringify({url})});
      setStatus('就绪', 'idle');
      if(pl.error) { showToast(pl.error, 'error'); return; }
      if(pl.note) { addLog({time: nowTime(), msg: '[分P检测] ' + pl.note, level: 'info'}); }
      if(pl.parts && pl.parts.length > 1) {
        addLog({time: nowTime(), msg: `[分P检测] 检测到 ${pl.total} 个分P，等待选择…`, level: 'info'});
        pendingPartCallback = (parts) => doStartDl(url, parts, undefined, taskArgs);
        showPartSelector(pl.parts);
        return;
      }
    } catch(e) {
      addLog({time: nowTime(), msg: '[分P检测] 获取列表失败，将下载全部: ' + e.message, level: 'warn'});
      setStatus('就绪', 'idle');
    }
  }
  doStartDl(url, undefined, undefined, taskArgs);
}

function nowTime(){ return new Date().toTimeString().slice(0,8); }

async function startWithnyArchive() {
  $('btnStart').disabled = true;
  $('btnWithnyLive').disabled = true;
  try {
    await saveSettingsNoAlert();
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
    if(result.task) {
      $('btnStart').disabled = false;
      $('btnWithnyLive').disabled = false;
      loadTasks();
    } else markStarted('1');
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
    await saveSettingsNoAlert();
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
    if(result.task) {
      $('btnStart').disabled = false;
      $('btnWithnyLive').disabled = false;
      loadTasks();
    } else markStarted('1');
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
function isNicoChannelLive(url) {
  try {
    const parsed = new URL(url);
    const host = parsed.hostname.toLowerCase();
    const segments = parsed.pathname.split('/').filter(Boolean);
    return (host === 'nicochannel.jp' || host.endsWith('.nicochannel.jp')) &&
      segments.length === 3 && segments[1].toLowerCase() === 'live' && /^sm\w+$/i.test(segments[2]);
  } catch(e) { return false; }
}

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
  $('statSkip').textContent = '0';
  $('statTotal').textContent = total;
  updateStatsVisibility();
}

function clearStartedTaskArgs(value) {
  if($('task_ytdlp_args').value.trim() === value) $('task_ytdlp_args').value = '';
}

async function doStartDl(url, biliParts, tcPassword, customArgs) {
  if(window.FanboxUI?.matches(url))return window.FanboxUI.start(url);
  const liveMode = await prepareLiveTask(url);
  if(liveMode === false) return;
  const body = {url};
  if(liveMode) body.live_mode = liveMode;
  if(biliParts) body.bili_parts = biliParts;
  if(tcPassword) body.tc_password = tcPassword;
  const taskArgs = customArgs === undefined ? activeTaskYtdlpArgs : customArgs;
  if(taskArgs) body.custom_args = taskArgs;
  const r = await api('/api/start', {method:'POST', body:JSON.stringify(body)});
  if(r.error) { showToast(r.error, 'error'); return; }
  if(r.waiting) {
    showToast('已加入等待开播列表', 'success');
    loadLiveWatch();
    return;
  }
  if(r.task) {
    showToast('已加入任务队列', 'success');
    loadTasks();
    clearStartedTaskArgs(taskArgs);
    return;
  }
  clearStartedTaskArgs(taskArgs);
  // SSE owns task state: preparation may already have failed or been stopped
  // before this response arrives. Do not overwrite that newer state here.
}

async function doStartUrls(urls, customArgs) {
  const body = {urls};
  if(customArgs) body.custom_args = customArgs;
  const r = await api('/api/start-urls', {method:'POST', body:JSON.stringify(body)});
  if(r.error) { showToast(r.error, 'error'); return; }
  if(r.task) {
    showToast('已加入任务队列', 'success');
    loadTasks();
  }
  clearStartedTaskArgs(customArgs || '');
}

async function startBatch() {
  if(!confirm('将从 urls.txt 文件读取链接进行批量下载，是否继续？')) return;
  activeTaskYtdlpArgs = $('task_ytdlp_args').value.trim();
  showToolStatus('正在启动批量下载…', 'working');
  try { await saveSettingsNoAlert(); } catch(e) { showToolStatus('设置保存失败: ' + e.message, 'error'); return; }
  doStartBatch(undefined, activeTaskYtdlpArgs);
}

async function doStartBatch(biliPartsMap, customArgs) {
  const body = {};
  if(biliPartsMap) body.bili_parts_map = biliPartsMap;
  if(customArgs) body.custom_args = customArgs;
  const r = await api('/api/batch-txt', {method:'POST', body:JSON.stringify(body)});
  if(r.error) { showToast(r.error, 'error'); return; }
  if(r.task) {
    showToast('批量任务已加入队列', 'success');
    loadTasks();
  }
  clearStartedTaskArgs(customArgs || '');
}

async function stopDl() {
  const r = await api('/api/stop', {method:'POST'});
  if(r.error) { showToast(r.error, 'error'); return; }
  if(r.stopped) {
    download_running = false;
    $('btnStart').disabled = false;
    $('btnStop').disabled = true;
    $('topline').style.width = '0';
    setStatus('已停止', 'idle');
  } else if(r.stopping) {
    download_running = true;
    $('btnStart').disabled = true;
    $('btnStop').disabled = true;
    setStatus('正在停止…', 'live');
  } else if(r.cancelled !== undefined) {
    showToast('已取消活跃任务', 'success');
    loadTasks();
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
  if(status.includes('已停止') || status.includes('已取消') || status.includes('已跳过') || status.includes('就绪')) return 'idle';
  return 'live';
}

/** 渲染进度：顶部细线 + 进度条 + 百分比。 */
function renderProgress(d) {
  const fill = $('progressFill');
  const topline = $('topline');
  const pctText = $('progressText');
  const stage = d.stage === 'audio' ? 'audio' : 'video';
  fill.classList.toggle('stage-audio', stage === 'audio');
  topline.classList.toggle('stage-audio', stage === 'audio');
  fill.title = stage === 'audio' ? '音频下载 / 处理进度' : '视频下载进度';
  if(d.percent < 0) {
    // 直播模式：无限进度动画
    fill.classList.add('live');
    fill.classList.remove('progressing', 'complete');
    fill.dataset.completed = '';
    pctText.textContent = 'LIVE';
    topline.style.width = '100%';
  } else if(d.percent !== undefined) {
    fill.classList.remove('live');
    const pct = Math.max(0, Math.min(100, Math.round(d.percent * 100)));
    fill.style.width = pct + '%';
    fill.classList.toggle('progressing', pct > 0 && pct < 100 && download_running);
    pctText.textContent = pct + '%';
    topline.style.width = download_running ? pct + '%' : '0';

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
  const skipped = parseInt($('statSkip').textContent) || 0;
  const total = parseInt($('statTotal').textContent) || 0;
  setStatValue('statDone', ok + fail + skipped);
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
function clearConsole() { $('logBox').innerHTML = '';window.FanboxUI?.clearConsole(); }
/** 清空工具日志面板内容。 */
function clearToolConsole() { $('toolLogBox').innerHTML = ''; }

/** 复制最近一次实际传递给 yt-dlp 的下载命令。 */
async function copyCurrentCommand() {
  try {
    const result = await api('/api/current-command');
    if(result.error) { showToast(result.error, 'error'); return; }
    const command = result.command || '';
    if(!command) { showToast('当前还没有可复制的 yt-dlp 下载命令', 'error'); return; }
    if(navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(command);
    } else {
      const textarea = document.createElement('textarea');
      textarea.value = command;
      textarea.style.position = 'fixed';
      textarea.style.opacity = '0';
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      textarea.remove();
    }
    showToast(result.redacted ? '命令已复制（密码等敏感参数已隐藏）' : '当前下载命令已复制', 'success');
  } catch(e) {
    showToast('复制命令失败: ' + e.message, 'error');
  }
}

/** 写入一条日志，两个面板保持同步。 */
function addLog(entry) {
  if(!window.FanboxUI||window.FanboxUI.consoleEntry(entry))_addToBox('logBox', entry);
  if(!entry.job_id)_addToBox('toolLogBox', entry);
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

function showSubtitleDownloader() {
  const panel = $('subtitleDownloadDialog');
  panel.classList.add('show');
  const source = $('urlInput').value.trim();
  if(source && !$('subtitleUrlInput').value.trim()) $('subtitleUrlInput').value = source;
  $('tool_subtitle_type').value = $('s_subtitle_type').value || 'all';
  applySubtitleLanguageValue('tool', getSubtitleLanguageValue('s'));
  syncToolTiles();
}

function hideSubtitleDownloader() {
  $('subtitleDownloadDialog').classList.remove('show');
  syncToolTiles();
}

async function startSubtitleDownload() {
  const button = $('btnSubtitleDownload');
  if(button.disabled) return;
  const urls = $('subtitleUrlInput').value.split(/\r?\n/).map(value => value.trim()).filter(Boolean);
  if(!urls.length) {
    showToolStatus('请输入至少一个视频链接', 'error');
    return;
  }
  const langs = getSubtitleLanguageValue('tool') || DEFAULT_SUBTITLE_LANGS;
  let submitted = false;
  button.disabled = true;
  showToolStatus('正在启动字幕下载...', 'working');
  try {
    await saveSettingsNoAlert();
    const result = await api('/api/download-subtitles', {method:'POST', body:JSON.stringify({
      urls: urls,
      subtitle_type: $('tool_subtitle_type').value,
      subtitle_langs: langs
    })});
    submitted = true;
    showToolStatus(`已提交字幕下载（${result.total || urls.length} 个链接）`, 'success');
  } catch(e) {
    showToolStatus('字幕下载启动失败: ' + e.message, 'error');
    showToast(e.message, 'error');
  } finally {
    if(!submitted) button.disabled = false;
  }
}

function showCoverDownloader() {
  $('coverDownloadDialog').classList.add('show');
  const source = $('urlInput').value.trim();
  if(source && !$('coverUrlInput').value.trim()) $('coverUrlInput').value = source;
  syncToolTiles();
}

function hideCoverDownloader() {
  $('coverDownloadDialog').classList.remove('show');
  syncToolTiles();
}

async function startCoverDownload() {
  const button = $('btnCoverDownload');
  if(button.disabled) return;
  const urls = $('coverUrlInput').value.split(/\r?\n/).map(value => value.trim()).filter(Boolean);
  if(!urls.length) {
    showToolStatus('请输入至少一个视频链接', 'error');
    return;
  }
  let submitted = false;
  button.disabled = true;
  showToolStatus('正在启动封面下载...', 'working');
  try {
    await saveSettingsNoAlert();
    const result = await api('/api/download-covers', {method:'POST', body:JSON.stringify({urls: urls})});
    submitted = true;
    showToolStatus(`已提交封面下载（${result.total || urls.length} 个链接）`, 'success');
  } catch(e) {
    showToolStatus('封面下载启动失败: ' + e.message, 'error');
    showToast(e.message, 'error');
  } finally {
    if(!submitted) button.disabled = false;
  }
}

// ========== 蹲开播任务 ==========
const LIVE_WATCH_LABELS = {
  probing: '探测中', waiting: '等待开播', waiting_near: '临近开播',
  starting: '启动录制', triggered: '已触发录制', error: '探测错误',
  expired: '已结束/超时', cancelled: '已取消'
};
const LIVE_WATCH_TERMINAL = new Set(['triggered', 'expired', 'cancelled']);

function fmtWatchTime(ts) {
  if(!ts) return '';
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString('zh-CN', {hour12:false});
}

function renderLiveWatch(jobs) {
  liveWatchJobs = Array.isArray(jobs) ? jobs : [];
  const sect = $('liveWatchSect');
  const list = $('liveWatchList');
  if(!sect || !list) return;
  if(!liveWatchJobs.length) {
    sect.style.display = 'none';
    list.innerHTML = '';
    return;
  }
  sect.style.display = '';
  const active = liveWatchJobs.filter(j => !LIVE_WATCH_TERMINAL.has(j.status));
  $('liveWatchCount').textContent = active.length
    ? `等待中 ${active.length} 个 · 共 ${liveWatchJobs.length} 个`
    : `共 ${liveWatchJobs.length} 个`;
  list.innerHTML = liveWatchJobs.slice(0, 12).map(job => {
    const status = LIVE_WATCH_LABELS[job.status] || job.status;
    const title = job.probe && job.probe.title ? job.probe.title : job.url;
    const next = job.status === 'waiting' || job.status === 'waiting_near'
      ? `下次探测 ${fmtWatchTime(job.next_probe_at)}`
      : (job.last_error || '');
    const blip = job.status === 'triggered' ? 'ok'
      : (job.status === 'error' || job.status === 'expired') ? 'err'
      : (job.status === 'waiting' || job.status === 'waiting_near' || job.status === 'probing') ? 'live' : 'idle';
    const esc = s => { const d = document.createElement('div'); d.textContent = s == null ? '' : String(s); return d.innerHTML; };
    const canCancel = !LIVE_WATCH_TERMINAL.has(job.status);
    return `<div class="srow" style="gap:10px;align-items:center;flex-wrap:wrap">
      <span class="st"><span class="blip ${blip}"></span>${esc(job.platform)} · ${esc(title)}</span>
      <span class="dim">${esc(status)}${next ? ' · ' + esc(next) : ''}</span>
      ${canCancel ? `<button class="btn sm gh" data-cancel="${esc(job.id)}">取消</button>` : ''}
    </div>`;
  }).join('');
  list.querySelectorAll('button[data-cancel]').forEach(btn => {
    btn.onclick = () => cancelLiveWatch(btn.dataset.cancel);
  });
}

async function loadLiveWatch() {
  try {
    const r = await api('/api/live/watch-jobs');
    renderLiveWatch(r.jobs || []);
  } catch(e) { /* 保持静默，避免影响下载页 */ }
}

async function cancelLiveWatch(jobId) {
  try {
    const r = await api('/api/live/watch-cancel', {method:'POST', body:JSON.stringify({id:jobId})});
    if(r.error) { showToast(r.error, 'error'); return; }
    showToast('已取消等待', 'success');
    loadLiveWatch();
  } catch(e) { showToast('取消等待失败: ' + e.message, 'error'); }
}

// ========== 多任务列表 ==========
const TASK_STATUS_LABELS = {
  queued: '排队中', running: '运行中', completed: '已完成',
  failed: '失败', cancelled: '已取消', waiting: '等待开播',
  stopped: '已停止（已收尾）', timed_out: '已到录制时限', partial: '部分录制，请查看报告'
};

function escapeTaskText(value) {
  const div = document.createElement('div');
  div.textContent = value == null ? '' : String(value);
  return div.innerHTML;
}

function taskStatusLabel(status) {
  return TASK_STATUS_LABELS[status] || status;
}

function toggleTask(taskId) {
  if(expandedTasks.has(taskId)) expandedTasks.delete(taskId);
  else expandedTasks.add(taskId);
  renderTasks(tasksCache);
}

async function loadTasks() {
  const version = taskSnapshotVersion;
  const request = ++taskLoadRequest;
  try {
    const r = await api('/api/tasks');
    if(version === taskSnapshotVersion && request === taskLoadRequest) renderTasks(r.tasks || []);
  } catch(e) { /* 保持页面安静 */ }
}

async function cancelTask(taskId) {
  try {
    const r = await api('/api/tasks/cancel', {method:'POST', body:JSON.stringify({id:taskId})});
    if(r.error) { showToast(r.error, 'error'); return; }
    showToast('已请求取消任务', 'success');
    loadTasks();
  } catch(e) { showToast('取消任务失败: ' + e.message, 'error'); }
}

async function clearFinishedTasks() {
  try {
    const r = await api('/api/tasks/clear', {method:'POST', body:'{}'});
    if(r.error) { showToast(r.error, 'error'); return; }
    loadTasks();
  } catch(e) { showToast('清理任务失败: ' + e.message, 'error'); }
}

function renderTasks(tasks) {
  const focusKey = document.activeElement?.dataset?.taskFocus;
  const logScrolls = new Map(Array.from(document.querySelectorAll('[data-task-log]')).map(log => [
    log.dataset.taskLog, {top:log.scrollTop, atBottom:log.scrollHeight - log.scrollTop - log.clientHeight < 8}
  ]));
  const passwordInputs = Array.from(document.querySelectorAll('.task-password')).map(input => ({
    id: input.id, value: input.value, focused: document.activeElement === input,
    start: input.selectionStart, end: input.selectionEnd
  }));
  tasksCache = Array.isArray(tasks) ? tasks : [];
  const taskIds = new Set(tasksCache.map(task => task.id));
  for(const id of expandedTasks) if(!taskIds.has(id)) expandedTasks.delete(id);
  const promptIds = new Set(tasksCache.flatMap(task => (task.prompts || []).map(prompt => prompt.request_id)));
  for(const id of seenTaskPrompts) if(!promptIds.has(id)) seenTaskPrompts.delete(id);
  tasksCache.forEach(task => (task.prompts || []).forEach(prompt => {
    if(!seenTaskPrompts.has(prompt.request_id)) {
      seenTaskPrompts.add(prompt.request_id);
      expandedTasks.add(task.id);
    }
  }));
  const panel = $('taskModePanel');
  const host = $('taskList');
  $('legacyDownloadStatus').style.display = taskModeEnabled && !download_running ? 'none' : '';
  if(!panel || !host) return;
  if(!tasksCache.length) {
    panel.style.display = taskModeEnabled ? '' : 'none';
    host.innerHTML = taskModeEnabled
      ? '<div class="task-empty">暂无任务。每次点击「开始下载」会在这里创建一个任务。</div>'
      : '';
    $('taskCount').textContent = '';
    if(!download_running) $('btnStop').disabled = true;
    return;
  }
  panel.style.display = '';
  const active = tasksCache.filter(t => t.status === 'queued' || t.status === 'running');
  $('taskCount').textContent = active.length
    ? `运行/排队 ${active.length} 个 · 共 ${tasksCache.length} 个`
    : `共 ${tasksCache.length} 个`;
  if(active.length) $('btnStop').disabled = false;
  else if(!download_running) $('btnStop').disabled = true;
  if(!download_running) {
    const totals = tasksCache.reduce((sum, task) => {
      for(const key of ['ok','fail','skipped','total']) sum[key] += Number(task.stats?.[key] || 0);
      return sum;
    }, {ok:0, fail:0, skipped:0, total:0});
    setStatValue('statOk', totals.ok);
    setStatValue('statFail', totals.fail);
    setStatValue('statSkip', totals.skipped);
    setStatValue('statTotal', totals.total);
    updateStatsVisibility();
  }

  host.innerHTML = tasksCache.map(task => {
    const status = task.status || 'queued';
    const pct = Math.max(0, Math.min(100, Number(task.progress) || 0));
    const open = expandedTasks.has(task.id);
    const rowClass = ['task-row', status, task.indeterminate ? 'indeterminate' : '', open ? 'open' : ''].join(' ');
    const statusText = taskStatusLabel(status);
    const meta = [
      statusText,
      task.speed ? task.speed : '',
      task.eta ? 'ETA ' + task.eta : '',
      task.content_kind ? '内容归档' : task.kind === 'live' ? '直播' : '下载',
      task.prompts?.length ? '等待确认' : ''
    ].filter(Boolean).join(' · ');
    const percentText = task.indeterminate ? '进行中' : `${Math.round(pct)}%`;
    const canCancel = status === 'queued' || status === 'running';
    const urls = (task.items || []).map(item =>
      `<div class="tdline"><span class="tdlabel">${escapeTaskText(taskStatusLabel(item.status))}</span><span class="tdurl">${escapeTaskText(item.urls[0])}<br>${escapeTaskText(item.message)} · ${item.indeterminate ? '录制中' : Math.round(item.progress) + '%'}${item.speed ? ' · ' + escapeTaskText(item.speed) : ''}</span></div>`
    ).join('');
    const prompts = (task.prompts || []).map(prompt => {
      if(prompt.type === 'archive_choice_required') {
        const remaining = Math.max(0, Math.ceil((prompt.expires_at - Date.now()) / 1000));
        return `<div class="task-prompt"><p>${escapeTaskText(prompt.url)} 已有归档记录。${remaining} 秒后默认跳过。</p>
          <button class="btn sm gh" data-task-focus="${prompt.request_id}-skip" onclick="submitTaskArchive('${task.id}','${prompt.request_id}',false)">跳过</button>
          <button class="btn sm" data-task-focus="${prompt.request_id}-retry" onclick="submitTaskArchive('${task.id}','${prompt.request_id}',true)">重新下载</button></div>`;
      }
      return `<div class="task-prompt"><p>${escapeTaskText(prompt.url)}：${prompt.reason === 'retry' ? '密码可能不正确，请重试' : '请输入访问密码'}</p>
        <input class="ctl task-password" type="password" autocomplete="off" id="task-password-${prompt.request_id}" aria-label="访问密码">
        <button class="btn sm" data-task-focus="${prompt.request_id}-submit" onclick="submitTaskPassword('${task.id}','${prompt.request_id}',false)">提交</button>
        <button class="btn sm gh" data-task-focus="${prompt.request_id}-skip" onclick="submitTaskPassword('${task.id}','${prompt.request_id}',true)">跳过</button></div>`;
    }).join('');
    const stats = task.stats || {};
    const histories = (task.history || []).slice(-6).map(item =>
      `<div class="tdline"><span class="tdlabel">${escapeTaskText(item.status)}</span><span>${escapeTaskText(item.title || item.url || '')}</span></div>`
    ).join('');
    const logs = (task.logs || []).slice(-20).map(line => {
      const cls = line.level === 'error' ? 'le' : (line.level === 'warn' ? 'lw' : '');
      return `<div class="${cls}">[${escapeTaskText(line.time)}] ${escapeTaskText(line.msg)}</div>`;
    }).join('');
    const errorLine = task.error
      ? `<div class="tdline"><span class="tdlabel">错误</span><span class="txt-err">${escapeTaskText(task.error)}</span></div>` : '';
    return `<div class="${rowClass}" style="--p:${pct}%">
      <div class="task-summary" data-task-focus="${task.id}" role="button" tabindex="0" aria-expanded="${open}" onclick="toggleTask('${task.id}')" onkeydown="if(event.target===this && (event.key==='Enter' || event.key===' ')){event.preventDefault();toggleTask('${task.id}')}">
        <span class="tname">${escapeTaskText(task.label || task.title || '任务')}</span>
        <span class="tmeta">${escapeTaskText(meta)}</span>
        <span class="tpct">${percentText}</span>
        ${canCancel ? `<button class="btn sm gh task-cancel" data-task-focus="${task.id}-cancel" onclick="event.stopPropagation();cancelTask('${task.id}')">取消</button>` : ''}
        <span class="tchev">›</span>
      </div>
      <div class="task-detail">
        <div class="tdline"><span class="tdlabel">状态</span><span>${escapeTaskText(task.message || statusText)}</span></div>
        ${errorLine}
        ${task.content_kind ? `<div class="tdline"><span class="tdlabel">内容</span><span>帖子 ${Number(task.content_stats?.posts)||0} · 文件 ${(Number(task.content_stats?.completed)||0)+(Number(task.content_stats?.reused)||0)} · 失败 ${Number(task.content_stats?.failed)||0} · 链接 ${Number(task.content_stats?.links)||0}</span></div>` : ''}
        <div class="tdline"><span class="tdlabel">链接统计</span><span>成功 ${stats.ok || 0} · 失败 ${stats.fail || 0} · 跳过 ${stats.skipped || 0} · 共 ${stats.total || task.url_count}</span></div>
        ${prompts}
        ${urls}
        ${histories}
        ${logs ? `<div class="task-log" data-task-log="${task.id}">${logs}</div>` : ''}
      </div>
    </div>`;
  }).join('');
  passwordInputs.forEach(saved => {
    const input = $(saved.id);
    if(!input) return;
    input.value = saved.value;
    if(saved.focused) {
      input.focus({preventScroll:true});
      input.setSelectionRange(saved.start, saved.end);
    }
  });
  if(focusKey) host.querySelector(`[data-task-focus="${CSS.escape(focusKey)}"]`)?.focus({preventScroll:true});
  host.querySelectorAll('[data-task-log]').forEach(log => {
    const saved = logScrolls.get(log.dataset.taskLog);
    log.scrollTop = !saved || saved.atBottom ? log.scrollHeight : saved.top;
  });
}

async function submitTaskArchive(taskId, requestId, redownload) {
  try {
    const result = await api('/api/archive-choice', {method:'POST', body:JSON.stringify({task_id:taskId, request_id:requestId, redownload})});
    if(result.error) showToast(result.error, 'error');
    loadTasks();
  } catch(e) { showToast('归档选择提交失败: ' + e.message, 'error'); }
}

async function submitTaskPassword(taskId, requestId, skip) {
  const prompt = tasksCache.find(t => t.id === taskId)?.prompts?.find(p => p.request_id === requestId);
  if(!prompt) return;
  const password = $('task-password-' + requestId)?.value || '';
  if(!skip && !password.trim()) { showToast('请输入密码', 'error'); return; }
  try {
    const result = await api('/api/submit-password', {method:'POST', body:JSON.stringify({
      task_id:taskId, item_id:prompt.item_id, request_id:requestId, url:prompt.url, password, skip
    })});
    if(result.error) showToast(result.error, 'error');
    else if($('task-password-' + requestId)) $('task-password-' + requestId).value = '';
    loadTasks();
  } catch(e) { showToast('密码提交失败: ' + e.message, 'error'); }
}

// ========== 直播任务检查与提醒 ==========
function getMutedLiveNotices() {
  try { return JSON.parse(localStorage.getItem(LIVE_NOTICE_MUTE_KEY) || '{}') || {}; }
  catch(e) { return {}; }
}

function isLiveNoticeMuted(kind) {
  return Boolean(getMutedLiveNotices()[kind]);
}

function setLiveNoticeMuted(kind) {
  try {
    const muted = getMutedLiveNotices();
    muted[kind] = true;
    localStorage.setItem(LIVE_NOTICE_MUTE_KEY, JSON.stringify(muted));
  } catch(e) {}
}

function clearLiveNoticeMutes() {
  try { localStorage.removeItem(LIVE_NOTICE_MUTE_KEY); } catch(e) {}
  showToast('已恢复全部直播提醒', 'success');
}

function formatLiveDateTime(ts) {
  if(!ts) return '';
  return new Date(ts * 1000).toLocaleString('zh-CN', {hour12:false});
}

function formatLiveElapsed(seconds) {
  if(seconds == null) return '';
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return h > 0 ? `${h} 小时 ${m} 分` : (m > 0 ? `${m} 分 ${sec} 秒` : `${sec} 秒`);
}

/** 只有明显的直播入口才做探测；否则普通 VOD 不走直播检查。 */
function isLiveCandidateUrl(url) {
  try {
    const u = new URL(url);
    const host = u.hostname.toLowerCase();
    const path = u.pathname.toLowerCase();
    const segs = path.split('/').filter(Boolean);
    if((host === 'rplay.live' || host === 'www.rplay.live') && u.protocol === 'https:' &&
       !u.username && !u.password && (!u.port || u.port === '443') &&
       /^\/(live|creatorhome)\/[0-9a-fA-F]{24}\/?$/.test(u.pathname) &&
       (segs[0] !== 'creatorhome' || !['contents','replays','playlists'].includes(u.searchParams.get('page')))) return true;
    if(host === 'live.bilibili.com' || host.endsWith('.live.bilibili.com')) return true;
    if(host === 'b23.tv' || host.endsWith('.b23.tv')) return true;
    if(host.includes('youtube.com') && (path.endsWith('/live') || path.startsWith('/live/'))) return true;
    if(host.includes('twitch.tv') && segs.length === 1 && !['videos','clips','directory'].includes(segs[0])) return true;
    if(host.includes('live.nicovideo.jp')) return true;
    if(host.includes('nicochannel.jp') && segs.length >= 3 && segs[1] === 'live') return true;
    if(host.includes('twitcasting.tv') && (segs.length === 1 || (segs.length >= 3 && segs[1] === 'movie'))) return true;
    if((host.includes('x.com') || host.includes('twitter.com')) && path.startsWith('/i/spaces/')) return true;
  } catch(e) {}
  return $('s_live_mode') && $('s_live_mode').value === 'wait';
}

function closeLiveNotice() {
  const overlay = $('liveNoticeOverlay');
  if(overlay) overlay.classList.remove('show');
}

function resolveLiveNotice(value) {
  const resolver = liveNoticeResolver;
  const kind = liveNoticeKind;
  if($('liveNoticeMute') && $('liveNoticeMute').checked && kind) setLiveNoticeMuted(kind);
  liveNoticeResolver = null;
  liveNoticeKind = "";
  closeLiveNotice();
  if(resolver) resolver(value);
}

function onLiveNoticeModeChange() {
  const select = $('liveNoticeMode');
  const warning = $('liveNoticeWarning');
  if(!select || !warning) return;
  const option = select.options[select.selectedIndex];
  warning.style.display = option && option.dataset.reason ? '' : 'none';
  if(option && option.dataset.reason) warning.textContent = option.dataset.reason;
}

function confirmLiveNotice() {
  const kind = liveNoticeKind;
  if($('liveNoticeMute') && $('liveNoticeMute').checked && kind) setLiveNoticeMuted(kind);
  let value = false;
  if(kind === 'wait_offer') value = 'wait';
  else if(kind === 'live_started') value = $('liveNoticeMode').value || 'auto';
  resolveLiveNotice(value);
}

/** 显示一次直播提醒；返回选择结果（wait/模式名/false）。 */
function showLiveNotice(opts) {
  return new Promise(resolve => {
    liveNoticeResolver = resolve;
    liveNoticeKind = opts.kind || '';
    $('liveNoticeTitle').textContent = opts.title || '直播任务';
    $('liveNoticeSummary').textContent = opts.summary || '';
    $('liveNoticeMeta').textContent = opts.meta || '';
    const modeRow = $('liveNoticeModeRow');
    const modeSelect = $('liveNoticeMode');
    const warning = $('liveNoticeWarning');
    const modes = (opts.modes || []).filter(mode => mode.available);
    if(modes.length) {
      modeRow.style.display = '';
      modeSelect.innerHTML = modes.map(mode =>
        `<option value="${mode.value}" data-reason="${(mode.reason || '').replace(/"/g, '&quot;')}">${mode.label}</option>`
      ).join('');
      const preferred = modes.some(mode => mode.value === opts.recommended)
        ? opts.recommended : modes[0].value;
      modeSelect.value = preferred;
      onLiveNoticeModeChange();
    } else {
      modeRow.style.display = 'none';
      modeSelect.innerHTML = '';
    }
    warning.style.display = opts.warning ? '' : 'none';
    warning.textContent = opts.warning || '';
    $('liveNoticeMute').checked = isLiveNoticeMuted(opts.kind);
    $('btnLiveNoticeConfirm').textContent = opts.confirmLabel || '继续';
    $('liveNoticeOverlay').classList.add('show');
  });
}

/** 任务开始前检查；返回 null=普通下载，false=取消，字符串=要使用的直播模式。 */
async function prepareLiveTask(url) {
  const selectedMode = ($('s_live_mode') && $('s_live_mode').value) || 'auto';
  if(!isLiveCandidateUrl(url) && selectedMode !== 'wait') return null;
  let data;
  try {
    data = await api('/api/live/inspect', {method:'POST', body:JSON.stringify({url, live_mode:selectedMode})});
  } catch(e) {
    showToast('直播状态检查失败: ' + e.message, 'error');
    return false;
  }
  if(!data.is_live_target) return null;
  if(data.status === 'ended') {
    showToast('直播已结束，将按普通视频下载', 'warn');
    return null;
  }
  if(data.error) {
    if(isLiveNoticeMuted('live_error')) { showToast(data.error, 'error'); return false; }
    await showLiveNotice({
      kind: 'live_error', title: '无法开始直播任务',
      summary: data.error, meta: data.platform ? `平台：${data.platform}` : '',
      confirmLabel: '知道了'
    });
    return false;
  }
  const title = `${data.platform || ''} · ${data.title || url}`;
  if(data.status === 'offline' || data.status === 'upcoming') {
    if(!data.can_wait) {
      const message = `直播尚未开始，且该平台不支持蹲开播${data.wait_reason ? '：' + data.wait_reason : ''}`;
      if(isLiveNoticeMuted('live_error')) { showToast(message, 'error'); return false; }
      await showLiveNotice({
        kind: 'live_error', title: '暂不能开始录制',
        summary: message, meta: title, confirmLabel: '知道了'
      });
      return false;
    }
    if(isLiveNoticeMuted('wait_offer')) return 'wait';
    const scheduled = data.scheduled_start ? `预约开始：${formatLiveDateTime(data.scheduled_start)}` : '';
    const choice = await showLiveNotice({
      kind: 'wait_offer', title: '直播尚未开始',
      summary: '是否以蹲开播方式等待？开播后将自动开始录制。',
      meta: [title, scheduled].filter(Boolean).join(' · '),
      confirmLabel: '蹲开播'
    });
    return choice === 'wait' ? 'wait' : false;
  }
  if(data.status === 'live') {
    if(isLiveNoticeMuted('live_started')) {
      return data.recommended_mode || data.effective_mode || 'auto';
    }
    const started = data.started_at ? `开播于 ${formatLiveDateTime(data.started_at)}` : '已开播';
    const elapsed = data.live_duration_seconds != null ? ` · 已开播 ${formatLiveElapsed(data.live_duration_seconds)}` : '';
    const choice = await showLiveNotice({
      kind: 'live_started', title: '直播已开始',
      summary: '请选择本次录制方式。',
      meta: `${title} · ${started}${elapsed}`,
      modes: data.modes || [],
      recommended: data.recommended_mode || data.effective_mode || 'auto',
      warning: data.warning || '',
      confirmLabel: '开始录制'
    });
    return choice || false;
  }
  const message = data.error || `无法确认直播状态（${data.status || 'unknown'}）`;
  if(isLiveNoticeMuted('live_error')) { showToast(message, 'error'); return false; }
  await showLiveNotice({
    kind: 'live_error', title: '无法开始直播任务',
    summary: message, meta: title, confirmLabel: '知道了'
  });
  return false;
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
    if(evt.type === 'fanbox_log') {window.FanboxUI?.log(evt.data);return;}
    if(evt.type === 'fanbox_job') {
      if(window.FanboxUI)window.FanboxUI.event(evt.data);
    } else if(evt.type === 'log') {
      addLog(evt.data);
    } else if(evt.type === 'audio_tool_result') {
      showToolStatus(evt.data.message, evt.data.level === 'success' ? 'success' : 'error');
      showToast(evt.data.message, evt.data.level);
    } else if(evt.type === 'progress') {
      if(evt.task_id) return;
      renderProgress(evt.data);
    } else if(evt.type === 'download_state') {
      if(evt.task_id) return;
      const d = evt.data;
      syncAudioToolState(d);
      download_running = Boolean(d.running);
      downloadGeneration = d.generation;
      $('btnStart').disabled = download_running || d.phase === 'suspended';
      $('btnWithnyLive').disabled = download_running || d.phase === 'suspended';
      $('btnStop').disabled = !download_running || d.phase === 'stopping';
      if($('btnSubtitleDownload')) $('btnSubtitleDownload').disabled = download_running || d.phase === 'suspended';
      if($('btnCoverDownload')) $('btnCoverDownload').disabled = download_running || d.phase === 'suspended';
      if(!download_running) $('topline').style.width = '0';
      if(!download_running) closeArchiveChoice();
      renderTasks(tasksCache);
    } else if(evt.type === 'stats') {
      if(evt.task_id) return;
      const d = evt.data;
      if(d.ok !== undefined) setStatValue('statOk', d.ok);
      if(d.fail !== undefined) setStatValue('statFail', d.fail);
      setStatValue('statSkip', d.skipped || 0);
      if(d.total !== undefined) setStatValue('statTotal', d.total);
      updateStatsVisibility();
    } else if(evt.type === 'archive_choice_required') {
      if(evt.task_id) return;
      showArchiveChoice(evt.data);
    } else if(evt.type === 'archive_choice_closed') {
      if(evt.task_id) return;
      closeArchiveChoice(evt.data.request_id);
    } else if(evt.type === 'password_required') {
      if(evt.task_id) return;
      const d = evt.data;
      // 仅 TwitCasting 平台显示密码弹窗，其他平台忽略
      if(d.platform !== 'TwitCasting') return;
      pendingTcUrl = d.url;
      pendingTcTaskId = evt.task_id || '';
      showTcPasswordPrompt(d.reason === 'retry');
    } else if(evt.type === 'history') {
      if(evt.data && evt.data.length && !$('page-history').classList.contains('active')) setHistoryDot(true);
      renderHistory(evt.data);
    } else if(evt.type === 'live_recording') {
      renderLiveRecording(evt.data || {});
    } else if(evt.type === 'live_watch') {
      renderLiveWatch(evt.data && evt.data.jobs ? evt.data.jobs : []);
    } else if(evt.type === 'task_snapshot') {
      taskSnapshotVersion++;
      renderTasks(evt.data && evt.data.tasks ? evt.data.tasks : []);
    } else if(evt.type === 'network_test') {
      networkEventVersion++;
      renderNetworkTest(evt.data);
    } else if(evt.type === 'ready') {
      taskSnapshotVersion++;
      const readyData = Array.isArray(evt.data) ? {logs:evt.data, running:false} : evt.data;
      syncAudioToolState(readyData);
      downloadGeneration = readyData.generation;
      (readyData.logs || []).forEach(e => addLog(e));
      download_running = Boolean(readyData.running);
      $('btnStart').disabled = download_running || readyData.phase === 'suspended';
      $('btnStop').disabled = !download_running || readyData.phase === 'stopping';
      if($('btnSubtitleDownload')) $('btnSubtitleDownload').disabled = download_running || readyData.phase === 'suspended';
      if($('btnCoverDownload')) $('btnCoverDownload').disabled = download_running || readyData.phase === 'suspended';
      if(readyData.progress) renderProgress(readyData.progress);
      if(Array.isArray(readyData.live_watch)) renderLiveWatch(readyData.live_watch);
      api('/api/live/recordings').then(data => (data.recordings || []).reverse().forEach(renderLiveRecording)).catch(() => {});
      if(readyData.stats) {
        $('statOk').textContent = readyData.stats.ok || 0;
        $('statFail').textContent = readyData.stats.fail || 0;
        $('statSkip').textContent = readyData.stats.skipped || 0;
        $('statTotal').textContent = readyData.stats.total || 0;
        updateStatsVisibility();
      }
      if(Array.isArray(readyData.tasks)) renderTasks(readyData.tasks);
      if(window.FanboxUI)window.FanboxUI.ready(readyData.fanbox_jobs);
      if(readyData.network_test) {
        networkEventVersion++;
        renderNetworkTest(readyData.network_test);
      }
      if(readyData.archive_prompt) showArchiveChoice(readyData.archive_prompt);
      else closeArchiveChoice();
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
  const skipped = h.status === 'skipped';
  const labels = {stopped:'已停止（已收尾）', timeout:'已到时限', gaps:'有缺口', earliest:'最早可用'};
  const label = ok ? '成功' : skipped ? '跳过' : labels[h.status] || '失败';
  const color = ok ? 'var(--ok)' : skipped || labels[h.status] ? 'var(--fg3)' : 'var(--err)';
  const cover = h.filepath
    ? `<img loading="lazy" alt="封面"
           src="/api/cover?path=${encodeURIComponent(h.filepath)}&token=${encodeURIComponent(SESSION_TOKEN)}"
           onload="this.classList.add('show')" onerror="this.remove()" onclick="openCover(this.src)">`
    : '';
  return `<div class="thumb">${icon('alert','s20')}${cover}` +
         `<span class="hstat"><span class="pd" style="background:${color}"></span>${label}</span></div>`;
}

function renderLiveRecording(data) {
  if(!data.job_id) return;
  liveRecordings.set(data.job_id, {...(liveRecordings.get(data.job_id) || {}), ...data});
  while(liveRecordings.size > 20) liveRecordings.delete(liveRecordings.keys().next().value);
  $('liveRecordingSect').style.display = '';
  const conclusions = {complete:'文件验证通过', from_earliest_available:'平台最早可用内容', gaps:'有缺口或边界诊断，请检查报告', failed:'录制或文件验证失败', cancelled_before_recording:'未开始录制，已停止等待'};
  $('liveRecordingList').innerHTML = Array.from(liveRecordings.values()).reverse().map(job => {
    const state = job.conclusion ? conclusions[job.conclusion] || job.conclusion : `录制中 · 分段 ${job.part || 1}`;
    const reason = {user:'已停止（已收尾）', timeout:'已到录制时限', crash:'进程崩溃', disk_full:'磁盘不足'}[job.stop_reason] || '';
    const reportLink = job.report ? `<p><a target="_blank" rel="noopener" href="/api/live/report?job_id=${encodeURIComponent(job.job_id)}&token=${encodeURIComponent(SESSION_TOKEN)}">查看完整性报告</a></p>` : '';
    const commentLabels = {exported:'弹幕已导出', partial:'弹幕已保留；同步估算或采集缺口请查看报告', empty:'本次未收到可导出的弹幕', failed:'弹幕导出失败，媒体保留', unavailable:'弹幕来源不可用'};
    const comments = commentLabels[job.comments?.status] || '';
    const sync = job.comments?.sync;
    const syncText = sync && (sync.clock_verified_count || sync.clock_estimated_count || sync.unmapped_count) ? (sync.clock_verified_count > 0 ? `弹幕时间轴：已校准 ${sync.clock_verified_count} 条，估算 ${sync.clock_estimated_count || 0} 条` : '弹幕同步精度尚未确认，请查看报告') : '';
    const exportButton = job.conclusion && job.comments?.status && job.comments.status !== 'disabled' ? `<button class="btn sm" data-comment-export="${escHtml(job.job_id)}">按当前格式和偏移重新导出弹幕</button>` : '';
    return `<div class="notice"><b>${escHtml(job.engine || '直播')} ${job.degraded ? '· 已降级' : ''}</b><p>${escHtml(reason ? reason + ' · ' + state : state)}</p>${job.reason ? `<p>${escHtml(job.reason)}</p>` : ''}${comments ? `<p>${escHtml(comments)}</p>` : ''}${syncText ? `<p>${escHtml(syncText)}</p>` : ''}<small class="mono">${escHtml(job.report || job.report_dir || '')}</small>${reportLink}${exportButton}</div>`;
  }).join('');
  $('liveRecordingList').querySelectorAll('[data-comment-export]').forEach(button => button.addEventListener('click', async () => {
    button.disabled = true;
    try {
      const result = await api('/api/live/comments-export', {method:'POST', body:JSON.stringify({job_id:button.dataset.commentExport, settings:{LIVE_DANMAKU_FORMATS:$('s_live_danmaku_formats').value, LIVE_DANMAKU_OFFSET_MS:Number($('s_live_danmaku_offset').value)}})});
      if(result.error) { showToast(result.error, 'error'); return; }
      renderLiveRecording({job_id:button.dataset.commentExport, comments:result.comments});
      showToast('弹幕重新导出完成', 'success');
    } catch(e) { showToast('弹幕导出失败：' + e.message, 'error'); }
    finally { button.disabled = false; }
  }));
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
  const seenFanbox=new Set();
  historyCache = (history || []).filter(h=>{if(h.platform!=='Fanbox')return true;if(seenFanbox.has(h.url))return false;seenFanbox.add(h.url);return true;});
  const list = $('historyList');
  $('historyCount').textContent = `共 ${historyCache.length} 条`;

  if(!historyCache.length) {
    list.innerHTML = `<div class="empty">${icon('inbox','s28')}<span class="et">还没有下载记录</span>` +
      `<span style="font-size:12.5px">完成的任务会出现在这里，带封面缩略图。</span></div>`;
    return;
  }

  if(historyView === 'grid') {
    list.innerHTML = '<div class="hgrid">' + historyCache.map(h => `
      <div class="hcard${h.platform==='Fanbox'?' fb-history':''}" ${h.platform==='Fanbox'?`role="button" tabindex="0" data-fanbox-url="${escAttr(h.url)}"`:''}>
        ${h.platform==='Fanbox'?'<div class="fb-history-icon">FANBOX</div>':thumbHtml(h)}
        <div>
          <div class="hti" title="${escAttr(h.title||h.url)}">${escHtml(h.title||h.url)}</div>
          <div class="hme">${escHtml(String(h.time).slice(5,16))} · ${platformHtml(h.platform)}</div>
        </div>
      </div>`).join('') + '</div>';
  } else {
    list.innerHTML = '<div class="hlist">' + historyCache.map(h => `
      <div class="hitem${h.platform==='Fanbox'?' fb-history':''}" ${h.platform==='Fanbox'?`role="button" tabindex="0" data-fanbox-url="${escAttr(h.url)}"`:''}>
        ${h.platform==='Fanbox'?'<div class="fb-history-icon">FANBOX</div>':thumbHtml(h)}
        <div style="min-width:0">
          <div class="hti" title="${escAttr(h.title||h.url)}">${escHtml(h.title||h.url)}</div>
          <div class="hme">${escHtml(h.time)} · ${platformHtml(h.platform)} · ${escHtml(shortUrl(h.url))}</div>
        </div>
      </div>`).join('') + '</div>';
  }
  list.querySelectorAll('[data-fanbox-url]').forEach(row=>{
    row.onclick=()=>window.FanboxUI?.openHistory(row.dataset.fanboxUrl);
    row.onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();row.click();}};
  });
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
let pendingTcTaskId = '';

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

// ========== 下载归档确认 ==========
let archiveChoice = null;
let archiveChoiceTimer = null;

function closeArchiveChoice(requestId) {
  if(requestId && archiveChoice?.request_id !== requestId) return;
  clearInterval(archiveChoiceTimer);
  archiveChoiceTimer = null;
  archiveChoice = null;
  $('archiveChoiceOverlay').classList.remove('show');
}

function showArchiveChoice(data) {
  if(data.generation !== undefined && downloadGeneration !== null && data.generation !== downloadGeneration) return;
  if(archiveChoice?.request_id === data.request_id) return;
  closeArchiveChoice();
  archiveChoice = data;
  $('archiveChoiceMsg').textContent = `此链接有 ${data.count} 条视频已被归档跳过。是否重新下载？不操作将自动跳过并继续队列。`;
  $('archiveChoiceUrl').textContent = data.url;
  $('btnArchiveSkip').disabled = false;
  $('btnArchiveRedownload').disabled = false;
  const updateCountdown = () => {
    const remaining = Math.max(0, Math.ceil((data.expires_at - Date.now()) / 1000));
    $('btnArchiveSkip').textContent = `跳过（${remaining} 秒）`;
    if(!remaining) closeArchiveChoice(data.request_id);
  };
  updateCountdown();
  if(!archiveChoice) return;
  $('archiveChoiceOverlay').classList.add('show');
  $('btnArchiveSkip').focus();
  archiveChoiceTimer = setInterval(updateCountdown, 250);
}

async function chooseArchiveRedownload(redownload) {
  const choice = archiveChoice;
  if(!choice || $('btnArchiveSkip').disabled) return;
  $('btnArchiveSkip').disabled = true;
  $('btnArchiveRedownload').disabled = true;
  try {
    const result = await api('/api/archive-choice', {method:'POST', body:JSON.stringify({
      request_id: choice.request_id, redownload,
      ...(choice.task_id ? {task_id: choice.task_id} : {})
    })});
    if(result.error) showToast(result.error, 'error');
    closeArchiveChoice(choice.request_id);
  } catch(e) {
    showToast('归档选择提交失败: ' + e.message, 'error');
    if(archiveChoice?.request_id === choice.request_id) {
      $('btnArchiveSkip').disabled = false;
      $('btnArchiveRedownload').disabled = false;
    }
  }
}

document.addEventListener('keydown', e => {
  if(e.key === 'Escape' && archiveChoice) {
    e.preventDefault();
    chooseArchiveRedownload(false);
  }
});

function onTcPasswordChange() {
  const enabled = isOn('sw_tc_remember');
  const control = $('sw_tc_xlsx');
  if(!enabled) setSwitch('sw_tc_xlsx', 0);
  control.setAttribute('aria-disabled', enabled ? 'false' : 'true');
  control.tabIndex = enabled ? 0 : -1;
  control.style.opacity = enabled ? '' : '0.45';
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
  pendingTcTaskId = '';
}

function confirmTcPassword() {
  const pw = $('tcPasswordInput').value.trim();
  if(!pw) { showToast('请输入密码', 'error'); return; }
  const url = pendingTcUrl;
  const taskId = pendingTcTaskId;
  closeTcPasswordPrompt();
  if(!url) return;
  // 批量下载/任务运行中 → 提交密码到等待中的执行器；否则启动新的单链接下载
  if(download_running || taskId) {
    api('/api/submit-password', {method:'POST', body:JSON.stringify({
      url: url, password: pw, ...(taskId ? {task_id: taskId} : {})
    })});
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
