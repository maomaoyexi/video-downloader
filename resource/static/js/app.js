/* ============================================================
   多平台视频下载工具 WebUI - 主脚本
   从 web_page.py 内联脚本提取，方便独立修改
   SESSION_TOKEN 由服务端模板注入
   ============================================================ */

let evtSource = null;
let currentPlatform = "YouTube";
let download_running = false;
const SESSION_TOKEN = window.SESSION_TOKEN || "";

const PLATFORMS = [
  {name:"YouTube",color:"#FF0000"},
  {name:"Bilibili",color:"#FB7299"},
  {name:"Twitch",color:"#9146FF"},
  {name:"Niconico",color:"#00A0D1"},
  {name:"Fantia",color:"#E6399B"}
];

function $(id){return document.getElementById(id);}

function init() {
  // 平台按钮
  const pc = $('platforms');
  PLATFORMS.forEach((p,i) => {
    const b = document.createElement('button');
    b.className = 'plat-btn' + (i===0?' active':'');
    b.style.background = p.color;
    b.textContent = p.name;
    b.dataset.name = p.name;
    b.onclick = () => selectPlatform(p.name);
    pc.appendChild(b);
  });

  // 选项填充
  fillSelect('s_resolution', [['best','无限制'],['2160','4K (2160p)'],['1440','2K (1440p)'],['1080','1080P'],['720','720P'],['480','480P'],['360','360P']]);
  fillSelect('s_codec', [['best','极致画质'],['h264','兼容优先(H.264)'],['av1','AV1优先'],['vp9','VP9优先']]);
  fillSelect('s_audio', [['best','最高音质'],['192','均衡(192k)'],['128','最小体积(128k)']]);
  fillSelect('s_format', [['mp4','MP4'],['mkv','MKV'],['webm','WebM']]);
  fillSelect('s_audiose', [['none','不分离'],['m4a','m4a(原生)'],['mp3','MP3'],['flac','FLAC'],['wav','WAV']]);
  fillSelect('s_hwaccel', [['cpu','CPU软编码'],['h264_nvenc','N卡 NVENC'],['h264_qsv','Intel QSV'],['h264_amf','AMD AMF']]);
  fillSelect('s_browser', [['chrome','Chrome'],['edge','Edge'],['firefox','Firefox'],['brave','Brave'],['opera','Opera']]);

  // 标签页切换
  document.querySelectorAll('.tab').forEach(t => {
    t.onclick = () => {
      document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));
      document.querySelectorAll('.page').forEach(x=>x.classList.remove('active'));
      t.classList.add('active');
      $('page-'+t.dataset.page).classList.add('active');
    };
  });

  // 回车下载
  $('urlInput').addEventListener('keydown', e => { if(e.key==='Enter') startDl(); });

  // 加载配置
  loadConfig();
  loadDeps();

  // SSE
  connectSSE();

  // 页面关闭前提示
  window.addEventListener('beforeunload', (e) => {
    // 如果正在下载，提示用户
    if(download_running) {
      e.preventDefault();
      e.returnValue = '正在下载中！关闭页面后下载将继续在后台运行。如需彻底关闭工具，请先点击「✕ 退出」按钮。';
      return e.returnValue;
    }
  });
}

function fillSelect(id, opts) {
  const s = $(id);
  opts.forEach(([v,l]) => { const o=document.createElement('option');o.value=v;o.textContent=l;s.appendChild(o); });
}

function selectPlatform(name) {
  currentPlatform = name;
  document.querySelectorAll('.plat-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.name===name);
  });
  // Bilibili 1080p Cookie 提示
  const hintEl = $('bilibiliHint');
  if (hintEl) hintEl.style.display = name === 'Bilibili' ? 'block' : 'none';
}

function toggleSwitch(el) { el.classList.toggle('on'); }
function isOn(id) { return $(id).classList.contains('on'); }

async function api(path, opts={}) {
  const headers = Object.assign({'Content-Type':'application/json', 'X-Session-Token':SESSION_TOKEN}, opts.headers || {});
  const r = await fetch(path, Object.assign({}, opts, {headers}));
  const text = await r.text();
  let data = {};
  try { data = text ? JSON.parse(text) : {}; } catch(e) { data = {error:text || `请求失败 (${r.status})`}; }
  if(!r.ok) throw new Error(data.error || `请求失败 (${r.status})`);
  return data;
}

// 工具箱通用操作
async function toolAction(name) {
  const r = await api('/api/tool', {method:'POST', body:JSON.stringify({action:name})});
  if(r.error) { alert(r.error); return; }
  if(r.message) { addLog('toolLog', {time:new Date().toTimeString().slice(0,8), msg:r.message, level:'success'}); }
}

// 浏览文件夹
async function browseFolder() {
  const r = await api('/api/browse-folder', {method:'POST'});
  if(r.path) {
    $('wav_dir').value = r.path;
  } else if(r.error) {
    alert(r.error);
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
  $('s_audiose').selectedIndex = s.AUDIO_SEP_MODE;
  setSwitch('sw_merge', s.MERGE_MODE);
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
  setSwitch('sw_meta', s.EMBED_META);
  setSwitch('sw_thumb', s.DOWNLOAD_THUMB);
  setSwitch('sw_audiodl', s.AUDIO_DOWNLOAD);
  setSwitch('sw_winfn', s.WIN_FILENAMES);
  setSwitch('sw_strict', s.STRICT_FILENAME);
  setSwitch('sw_nicocmt', s.NICO_COMMENTS);
  setSwitch('sw_nicorec', s.NICO_RECODE);
  setSwitch('sw_log', s.ENABLE_LOG);
  if(s.BILI_MULTIP_POLICY !== undefined) $('s_bili_policy').value = s.BILI_MULTIP_POLICY;
  if(s.MP3_BITRATE !== undefined) $('wav_bitrate').value = String(s.MP3_BITRATE);
  setSwitch('sw_delwav', s.DEL_WAV_AFTER_CONVERT);
  toggleCookieMode();
}

function setSwitch(id, val) {
  if(val) $(id).classList.add('on'); else $(id).classList.remove('on');
}

function toggleCookieMode() {
  const browserMode = $('s_cookiemode').value === '2';
  $('row_browser').style.display = browserMode ? 'flex' : 'none';
  $('row_profile').style.display = browserMode ? 'flex' : 'none';
}

async function saveSettings() {
  const cfg = {
    PLATFORM: currentPlatform,
    RESOLUTION: $('s_resolution').value,
    CODEC: $('s_codec').value,
    AUDIO_QUALITY: $('s_audio').value,
    OUTPUT_FORMAT: $('s_format').value,
    MERGE_MODE: isOn('sw_merge')?1:0,
    AUDIO_SEP_MODE: $('s_audiose').selectedIndex,
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
    AUDIO_DOWNLOAD: isOn('sw_audiodl')?1:0,
    WIN_FILENAMES: isOn('sw_winfn')?1:0,
    STRICT_FILENAME: isOn('sw_strict')?1:0,
    NICO_COMMENTS: isOn('sw_nicocmt')?1:0,
    NICO_RECODE: isOn('sw_nicorec')?1:0,
    ENABLE_LOG: isOn('sw_log')?1:0,
  };
  try {
    await api('/api/save-config', {method:'POST', body:JSON.stringify(cfg)});
    alert('设置已保存！');
  } catch(e) {
    alert('设置保存失败: ' + e.message);
  }
}

async function saveSettingsNoAlert() {
  const cfg = {
    PLATFORM: currentPlatform,
    RESOLUTION: $('s_resolution').value,
    CODEC: $('s_codec').value,
    AUDIO_QUALITY: $('s_audio').value,
    OUTPUT_FORMAT: $('s_format').value,
    MERGE_MODE: isOn('sw_merge')?1:0,
    AUDIO_SEP_MODE: $('s_audiose').selectedIndex,
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
    AUDIO_DOWNLOAD: isOn('sw_audiodl')?1:0,
    WIN_FILENAMES: isOn('sw_winfn')?1:0,
    STRICT_FILENAME: isOn('sw_strict')?1:0,
    NICO_COMMENTS: isOn('sw_nicocmt')?1:0,
    NICO_RECODE: isOn('sw_nicorec')?1:0,
    ENABLE_LOG: isOn('sw_log')?1:0,
  };
  return api('/api/save-config', {method:'POST', body:JSON.stringify(cfg)});
}

async function resetSettings() {
  if(!confirm('确定恢复默认设置？')) return;
  await api('/api/reset-config', {method:'POST'});
  location.reload();
}

async function loadDeps() {
  const d = await api('/api/deps');
  const names = {'yt-dlp':'yt-dlp',ffmpeg:'ffmpeg',ffprobe:'ffprobe',fantiadl:'fantiadl(可选)'};
  const box = $('depStatus');
  box.innerHTML = '';
  for(const [k,v] of Object.entries(d)) {
    const el = document.createElement('span');
    el.className = 'dep-item ' + (v?'dep-ok':'dep-miss');
    el.textContent = (v?'✓ ':'✗ ') + names[k];
    box.appendChild(el);
  }
}

async function startDl() {
  let url = $('urlInput').value;
  // 清理URL：去除前后空白、反引号、引号
  for(let i=0;i<3;i++) {
    const old = url;
    url = url.trim().replace(/^[`'"]+|[`'"]+$/g, '');
    if(url === old) break;
  }
  url = url.trim();
  $('urlInput').value = url;
  if(!url) { alert('请输入链接'); return; }
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

// 判断是否为 Bilibili 视频链接（BV/AV/b23.tv）
function isBilibiliUrl(url) {
  try {
    const host = new URL(url).hostname.toLowerCase();
    return host === 'www.bilibili.com' || host === 'bilibili.com' || host.endsWith('.bilibili.com') || host === 'b23.tv';
  } catch(e) { return false; }
}

// 判断是否为Bilibili直播链接
function isBilibiliLive(url) {
  try { return new URL(url).hostname.includes('live.bilibili.com'); } catch(e) { return false; }
}

async function doStartDl(url, biliParts) {
  const body = {url};
  if(biliParts) body.bili_parts = biliParts;
  const r = await api('/api/start', {method:'POST', body:JSON.stringify(body)});
  if(r.error) { alert(r.error); return; }
  download_running = true;
  $('btnStart').disabled = true;
  $('btnStop').disabled = false;
  $('statOk').textContent = '0';
  $('statFail').textContent = '0';
  $('statTotal').textContent = '0';
}

async function startBatch() {
  if(!confirm('将从 urls.txt 文件读取链接进行批量下载，是否继续？')) return;
  try { await saveSettingsNoAlert(); } catch(e) { alert('设置保存失败: ' + e.message); return; }
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

async function saveSettingsNoAlert() {
  const cfg = collectCfg();
  return api('/api/save-config', {method:'POST', body:JSON.stringify(cfg)});
}

function collectCfg() {
  return {
    PLATFORM: currentPlatform,
    RESOLUTION: $('s_resolution').value,
    CODEC: $('s_codec').value,
    AUDIO_QUALITY: $('s_audio').value,
    OUTPUT_FORMAT: $('s_format').value,
    MERGE_MODE: isOn('sw_merge')?1:0,
    AUDIO_SEP_MODE: $('s_audiose').selectedIndex,
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
    AUDIO_DOWNLOAD: isOn('sw_audiodl')?1:0,
    WIN_FILENAMES: isOn('sw_winfn')?1:0,
    STRICT_FILENAME: isOn('sw_strict')?1:0,
    NICO_COMMENTS: isOn('sw_nicocmt')?1:0,
    NICO_RECODE: isOn('sw_nicorec')?1:0,
    ENABLE_LOG: isOn('sw_log')?1:0,
    BILI_MULTIP_POLICY: $('s_bili_policy').value,
  };
}

async function doWavConvert() {
  const dir = $('wav_dir').value.trim();
  if(!dir) { alert('请输入目录路径'); return; }
  try {
    const result = await api('/api/wav2mp3', {method:'POST', body:JSON.stringify({
      dir, bitrate:parseInt($('wav_bitrate').value),
      recursive:isOn('sw_recursive'), del_src:isOn('sw_delwav')
    })});
    if(result.error) throw new Error(result.error);
  } catch(e) {
    alert('转换启动失败: ' + e.message);
  }
}

function clearConsole() {
  const logBox = $('logBox');
  if(logBox) logBox.innerHTML = '';
  const toolLog = $('toolLog');
  if(toolLog) toolLog.innerHTML = '';
}

function addLog(container, entry) {
  const box = $(container);
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

function connectSSE() {
  if(evtSource) evtSource.close();
  evtSource = new EventSource('/api/events?token=' + encodeURIComponent(SESSION_TOKEN));
  evtSource.onmessage = (e) => {
    const evt = JSON.parse(e.data);
    if(evt.type === 'log') {
      addLog('logBox', evt.data);
      addLog('toolLog', evt.data);
    } else if(evt.type === 'progress') {
      const d = evt.data;
      const fill = $('progressFill');
      if(d.percent < 0) {
        // 直播模式：动画进度条
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
      }
    } else if(evt.type === 'download_state') {
      const d = evt.data;
      download_running = Boolean(d.running);
      $('btnStart').disabled = download_running || d.phase === 'suspended';
      $('btnStop').disabled = !download_running || d.phase === 'stopping';
    } else if(evt.type === 'stats') {
      const d = evt.data;
      if(d.ok !== undefined) $('statOk').textContent = d.ok;
      if(d.fail !== undefined) $('statFail').textContent = d.fail;
      if(d.total !== undefined) $('statTotal').textContent = d.total;
      if(d.current !== undefined && d.total > 0) {
        $('statusText').textContent = `批量下载 ${d.current}/${d.total}`;
      }
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
    evtSource.close();
    setTimeout(connectSSE, 3000);
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
    list.innerHTML = '<div style="color:#888;text-align:center;padding:60px">暂无下载记录</div>';
    return;
  }
  list.innerHTML = history.map(h => `
    <div class="history-item">
      <span class="history-platform ${h.platform}">${h.platform}</span>
      <div class="history-info">
        <div class="history-title" title="${escAttr(h.title)}">${escHtml(h.title)}</div>
        <div class="history-meta">${h.time} · <span style="color:#666">${escHtml(h.url)}</span></div>
      </div>
      <span class="history-status ${h.status}">${h.status === 'success' ? '成功' : '失败'}</span>
    </div>
  `).join('');
}

async function clearHistoryUI() {
  if(!confirm('确定清空所有下载历史吗？此操作不可撤销。')) return;
  const r = await api('/api/clear-history', {method:'POST'});
  if(r && r.ok) loadHistory();
}

// 工具函数
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
  // 自动弹出面板
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
  // 显示进度条
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

// ========== Bilibili 分P选择对话框 ==========
let pendingPartCallback = null;

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
  closePartSelector();             // closePartSelector 会清掉 pendingPartCallback
  if(cb) {                         // 使用之前保存的引用
    cb(indices);
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
