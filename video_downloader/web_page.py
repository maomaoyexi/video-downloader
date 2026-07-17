SESSION_TOKEN_PLACEHOLDER = "__SESSION_TOKEN__"


HTML_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>四平台下载工具 WebUI</title>
<style>
:root {
  --bg: #0f1117; --bg2: #1a1d27; --bg3: #242836;
  --ink: #e8eaed; --muted: #9aa0ac; --rule: #2d3142;
  --accent: #4fc3f7; --green: #66bb6a; --red: #ef5350;
  --orange: #ffb74d; --purple: #ba68c8;
}
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:"Segoe UI","Noto Sans CJK SC","Microsoft YaHei",sans-serif; background:var(--bg); color:var(--ink); height:100vh; display:flex; flex-direction:column; overflow:hidden; }
.topbar { background:var(--bg2); border-bottom:1px solid var(--rule); padding:12px 20px; display:flex; align-items:center; gap:15px; }
.topbar h1 { font-size:1.1rem; background:linear-gradient(135deg,var(--accent),var(--green)); -webkit-background-clip:text; -webkit-text-fill-color:transparent; }
.topbar .ver { color:var(--muted); font-size:0.8rem; }
.tabs { display:flex; gap:5px; }
.tab { padding:6px 16px; border-radius:6px; cursor:pointer; font-size:0.85rem; color:var(--muted); background:transparent; border:none; transition:all .15s; }
.tab:hover { background:var(--bg3); color:var(--ink); }
.tab.active { background:var(--accent); color:#000; font-weight:600; }
.btn-exit:hover { background:#d32f2f !important; }
.main { flex:1; overflow-y:auto; padding:20px; }
.page { display:none; max-width:900px; margin:0 auto; }
.page.active { display:block; }

.platforms { display:flex; gap:10px; margin-bottom:15px; flex-wrap:wrap; }
.plat-btn { padding:10px 20px; border-radius:8px; border:2px solid transparent; cursor:pointer; font-weight:600; font-size:0.9rem; color:#fff; transition:all .15s; opacity:.6; }
.plat-btn.active { opacity:1; border-color:#fff; transform:scale(1.05); }
.plat-btn:hover { opacity:.9; }

.url-row { display:flex; gap:10px; margin-bottom:15px; }
.url-input { flex:1; padding:12px 16px; background:var(--bg2); border:1px solid var(--rule); border-radius:8px; color:var(--ink); font-size:0.95rem; outline:none; }
.url-input:focus { border-color:var(--accent); }
.input { padding:10px 14px; background:var(--bg2); border:1px solid var(--rule); border-radius:8px; color:var(--ink); font-size:0.9rem; outline:none; }
.input:focus { border-color:var(--accent); }
.btn { padding:10px 20px; border:none; border-radius:8px; cursor:pointer; font-weight:600; font-size:0.9rem; transition:all .15s; }
.btn-primary { background:var(--accent); color:#000; }
.btn-primary:hover { background:#29b6f6; }
.btn-danger { background:var(--red); color:#fff; }
.btn-danger:hover { background:#c62828; }
.btn:disabled { opacity:.5; cursor:not-allowed; }

.progress-section { background:var(--bg2); border-radius:10px; padding:15px; margin-bottom:15px; }
.progress-bar { height:8px; background:var(--bg3); border-radius:4px; overflow:hidden; margin:8px 0; }
.progress-fill { height:100%; background:linear-gradient(90deg,var(--accent),var(--green)); border-radius:4px; transition:width .3s; width:0; }
.progress-fill.live { width:100% !important; background:linear-gradient(90deg,var(--accent),#ff6b6b,var(--accent)); background-size:200% 100%; animation:livePulse 1.5s ease-in-out infinite; }
@keyframes livePulse { 0%{background-position:200% 0} 100%{background-position:-200% 0} }
.progress-info { display:flex; justify-content:space-between; font-size:0.82rem; color:var(--muted); }

.log-box { background:var(--bg2); border-radius:10px; padding:15px; height:350px; overflow-y:auto; font-family:"Cascadia Code",Consolas,monospace; font-size:0.82rem; line-height:1.6; }
.log-line { margin-bottom:2px; }
.log-time { color:var(--muted); }
.log-success { color:var(--green); }
.log-error { color:var(--red); }
.log-warn { color:var(--orange); }
.log-info { color:var(--accent); }

.settings-group { background:var(--bg2); border-radius:10px; padding:20px; margin-bottom:15px; }
.settings-group h3 { font-size:1rem; color:var(--accent); margin-bottom:15px; padding-bottom:8px; border-bottom:1px solid var(--rule); }
.setting-row { display:flex; align-items:center; padding:8px 0; gap:10px; }
.setting-row label { min-width:140px; font-size:0.88rem; color:var(--muted); }
.setting-row select, .setting-row input[type="text"], .setting-row input[type="number"] { background:var(--bg3); border:1px solid var(--rule); border-radius:6px; color:var(--ink); padding:6px 10px; font-size:0.85rem; outline:none; min-width:160px; }
.setting-row select:focus, .setting-row input:focus { border-color:var(--accent); }
.switch { position:relative; width:44px; height:24px; background:var(--bg3); border-radius:12px; cursor:pointer; transition:background .2s; }
.switch.on { background:var(--green); }
.switch::after { content:''; position:absolute; width:18px; height:18px; background:#fff; border-radius:50%; top:3px; left:3px; transition:transform .2s; }
.switch.on::after { transform:translateX(20px); }
input[type="range"] { flex:1; max-width:200px; accent-color:var(--accent); }

.tools-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(200px,1fr)); gap:12px; margin-bottom:15px; }
.tool-card { background:var(--bg2); border-radius:10px; padding:20px; text-align:center; cursor:pointer; transition:all .15s; border:1px solid var(--rule); }
.tool-card:hover { transform:translateY(-2px); border-color:var(--accent); }
.tool-card .icon { font-size:2rem; margin-bottom:8px; }
.tool-card .name { font-weight:600; font-size:0.9rem; }

/* 帮助页面样式 */
.help-section { margin-bottom:20px; background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.08); border-radius:10px; padding:16px; }
.help-content { color:#ddd; line-height:1.8; font-size:0.92rem; }
.help-content p { margin-bottom:8px; }
.help-content code { background:rgba(99,102,241,0.2); color:#c7d2fe; padding:2px 6px; border-radius:4px; font-family:monospace; font-size:0.88rem; }
.help-content b { color:#fff; }

/* 历史记录样式 */
.history-item { display:flex; gap:12px; padding:12px; border-bottom:1px solid rgba(255,255,255,0.06); align-items:flex-start; }
.history-item:hover { background:rgba(255,255,255,0.03); }
.history-platform { background:var(--accent); color:#fff; font-size:0.7rem; padding:2px 8px; border-radius:4px; white-space:nowrap; font-weight:600; margin-top:2px; }
.history-platform.YouTube { background:#ff0000; }
.history-platform.Twitch { background:#9146ff; }
.history-platform.Nico { background:#00acee; }
.history-platform.Niconico { background:#00acee; }
.history-platform.Fantia { background:#e63e9d; }
.history-info { flex:1; min-width:0; }
.history-title { color:#fff; font-weight:500; margin-bottom:4px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.history-meta { color:#888; font-size:0.8rem; }
.history-status { font-size:0.75rem; padding:2px 8px; border-radius:4px; white-space:nowrap; margin-top:2px; }
.history-status.success { background:rgba(34,197,94,0.2); color:#4ade80; }
.history-status.fail { background:rgba(239,68,68,0.2); color:#f87171; }

/* 预设卡片增强 */
.preset-card { display:flex; flex-direction:column; gap:8px; }
.preset-card .preset-actions { display:flex; gap:6px; margin-top:auto; }
.preset-card .preset-actions button { flex:1; font-size:0.8rem; padding:6px 0; }

.dep-status { display:flex; gap:15px; flex-wrap:wrap; margin-top:10px; }
.dep-item { padding:6px 12px; border-radius:6px; font-size:0.82rem; }
.dep-ok { background:rgba(102,187,106,.15); color:var(--green); }
.dep-miss { background:rgba(239,83,80,.15); color:var(--red); }

.btn-save { background:var(--green); color:#fff; margin-top:10px; }
.btn-save:hover { background:#388e3c; }

.wav-dialog { background:var(--bg2); border-radius:10px; padding:20px; margin-top:15px; display:none; }
.wav-dialog.show { display:block; }

/* 更新提示样式 */
.update-badge { background:var(--red); color:#fff; font-size:0.75rem; padding:3px 10px; border-radius:12px; cursor:pointer; font-weight:600; animation:badgePulse 2s ease-in-out infinite; white-space:nowrap; }
.update-badge:hover { background:#d32f2f; }
@keyframes badgePulse { 0%,100%{box-shadow:0 0 0 0 rgba(239,83,80,.5)} 50%{box-shadow:0 0 0 6px rgba(239,83,80,0)} }
.update-panel { position:fixed; top:60px; right:20px; width:360px; background:var(--bg2); border:1px solid var(--red); border-radius:12px; padding:18px; z-index:9999; box-shadow:0 8px 32px rgba(0,0,0,.5); display:none; }
.update-panel.show { display:block; }
.update-panel h3 { color:var(--red); font-size:1rem; margin-bottom:8px; display:flex; align-items:center; gap:8px; }
.update-panel .ver-info { font-size:0.85rem; color:var(--muted); margin-bottom:8px; }
.update-panel .ver-info b { color:var(--ink); }
.update-panel .notes { background:var(--bg3); border-radius:8px; padding:10px; font-size:0.82rem; color:var(--muted); max-height:150px; overflow-y:auto; margin-bottom:12px; line-height:1.6; white-space:pre-wrap; word-break:break-word; }
.update-progress { margin-bottom:12px; display:none; }
.update-progress.show { display:block; }
.update-progress .bar { height:6px; background:var(--bg3); border-radius:3px; overflow:hidden; margin:6px 0; }
.update-progress .fill { height:100%; background:linear-gradient(90deg,var(--orange),var(--red)); border-radius:3px; transition:width .3s; width:0; }
.update-progress .info { display:flex; justify-content:space-between; font-size:0.78rem; color:var(--muted); }
.update-done { text-align:center; padding:10px 0; display:none; }
.update-done.show { display:block; }
.update-done .icon { font-size:2rem; margin-bottom:6px; }
.update-done .msg { color:var(--green); font-size:0.9rem; font-weight:600; }
.update-actions { display:flex; gap:8px; }
.update-actions .btn { flex:1; text-align:center; padding:8px 0; font-size:0.85rem; }
</style>
</head>
<body>

<div class="topbar">
  <h1>⬇ 四平台极致音画下载工具</h1>
  <div class="tabs">
    <button class="tab active" data-page="download">下载</button>
    <button class="tab" data-page="settings">设置</button>
    <button class="tab" data-page="history">历史</button>
    <button class="tab" data-page="tools">工具箱</button>
    <button class="tab" data-page="help">帮助</button>
    <button class="tab" data-page="about">关于</button>
  </div>
  <div style="margin-left:auto;display:flex;align-items:center;gap:10px;">
    <span class="update-badge" id="updateBadge" style="display:none" onclick="showUpdatePanel()" title="有新版本可用！">⬆ 有更新</span>
    <span class="ver" id="ver"></span>
    <button class="btn-exit" onclick="exitApp()" title="彻底关闭工具" style="background:#ef5350;color:#fff;border:none;padding:6px 14px;border-radius:6px;cursor:pointer;font-size:0.82rem;font-weight:600;">✕ 退出</button>
  </div>
</div>

<!-- 更新提示面板 -->
<div class="update-panel" id="updatePanel">
  <h3>⬆ 发现新版本</h3>
  <div class="ver-info">当前版本: <b id="updateCurVer"></b> &rarr; 最新版本: <b id="updateNewVer" style="color:var(--green)"></b></div>
  <div class="notes" id="updateNotes">正在获取更新内容...</div>
  <div class="update-progress" id="updateProgress">
    <div style="font-size:0.82rem;color:var(--orange)" id="updateProgText">正在下载更新...</div>
    <div class="bar"><div class="fill" id="updateProgFill"></div></div>
    <div class="info"><span id="updateProgPct">0%</span><span id="updateProgSpeed"></span></div>
  </div>
  <div class="update-done" id="updateDone">
    <div class="icon">✅</div>
    <div class="msg" id="updateDoneMsg">更新完成！程序将自动重启。</div>
  </div>
  <div class="update-actions" id="updateActions">
    <button class="btn" style="background:var(--bg3);color:var(--muted)" onclick="hideUpdatePanel()">稍后</button>
    <button class="btn btn-primary" id="btnDoUpdate" onclick="doUpdateNow()">一键更新</button>
  </div>
</div>

<div class="main">
  <!-- 下载页 -->
  <div class="page active" id="page-download">
    <div class="platforms" id="platforms"></div>
    <div class="url-row">
      <input class="url-input" id="urlInput" placeholder="粘贴视频/播放列表/频道/直播链接，回车开始下载...">
      <button class="btn btn-primary" id="btnStart" onclick="startDl()">开始下载</button>
      <button class="btn" style="background:var(--orange);color:#000" onclick="startBatch()" title="从urls.txt批量下载">📋 TXT批量</button>
      <button class="btn btn-danger" id="btnStop" onclick="stopDl()" disabled>停止</button>
    </div>
    <div class="progress-section">
      <div style="display:flex;justify-content:space-between;font-size:0.88rem;">
        <span id="statusText">就绪</span>
        <span id="progressText">0%</span>
      </div>
      <div class="progress-bar"><div class="progress-fill" id="progressFill"></div></div>
      <div class="progress-info">
        <span id="speedText"></span>
        <span id="etaText"></span>
      </div>
    </div>
    <div style="display:flex;gap:10px;margin-bottom:10px;">
      <div style="flex:1;background:var(--bg2);border-radius:8px;padding:10px;text-align:center;">
        <div style="font-size:0.75rem;color:var(--muted)">成功</div>
        <div style="font-size:1.2rem;color:var(--green);font-weight:600" id="statOk">0</div>
      </div>
      <div style="flex:1;background:var(--bg2);border-radius:8px;padding:10px;text-align:center;">
        <div style="font-size:0.75rem;color:var(--muted)">失败</div>
        <div style="font-size:1.2rem;color:var(--red);font-weight:600" id="statFail">0</div>
      </div>
      <div style="flex:1;background:var(--bg2);border-radius:8px;padding:10px;text-align:center;">
        <div style="font-size:0.75rem;color:var(--muted)">总计</div>
        <div style="font-size:1.2rem;color:var(--accent);font-weight:600" id="statTotal">0</div>
      </div>
    </div>
    <div class="log-box" id="logBox"></div>
  </div>

  <!-- 设置页 -->
  <div class="page" id="page-settings">
    <div class="settings-group">
      <h3>💾 配置预设</h3>
      <div class="setting-row">
        <label>选择预设</label>
        <select id="presetSelect" style="flex:1" onchange="loadPresetFromSelect()">
          <option value="">-- 选择预设快速应用 --</option>
        </select>
        <button class="btn" style="background:var(--green);color:#fff;padding:6px 14px;font-size:0.82rem;white-space:nowrap;" onclick="showSavePreset()">💾 保存</button>
        <button class="btn" style="background:var(--red);color:#fff;padding:6px 14px;font-size:0.82rem;white-space:nowrap;" onclick="deletePresetFromSelect()">🗑 删除</button>
      </div>
      <div class="setting-row" id="presetSaveRow" style="display:none">
        <label>预设名称</label>
        <input type="text" id="presetNameInput" style="flex:1" placeholder="输入预设名称，如：4K原画、手机兼容...">
        <button class="btn" style="background:var(--green);color:#fff;padding:6px 14px;font-size:0.82rem;white-space:nowrap;" onclick="savePresetFromInput()">确认</button>
        <button class="btn" style="background:gray;color:#fff;padding:6px 12px;font-size:0.82rem;white-space:nowrap;" onclick="hideSavePreset()">取消</button>
      </div>
      <div style="color:var(--muted);font-size:0.8rem;margin-top:4px;">保存当前所有设置为命名预设，随时一键加载切换</div>
    </div>
    <div class="settings-group">
      <h3>画质与输出</h3>
      <div class="setting-row"><label>分辨率上限</label><select id="s_resolution"></select></div>
      <div class="setting-row"><label>编码模式</label><select id="s_codec"></select></div>
      <div class="setting-row"><label>音频质量</label><select id="s_audio"></select></div>
      <div class="setting-row"><label>输出格式</label><select id="s_format"></select></div>
      <div class="setting-row"><label>音视频合并输出</label><div class="switch" id="sw_merge" onclick="toggleSwitch(this)"></div></div>
      <div class="setting-row"><label>分离音频格式</label><select id="s_audiose"></select></div>
    </div>
    <div class="settings-group">
      <h3>网络与代理</h3>
      <div class="setting-row"><label>并发线程数</label><input type="range" id="s_threads" min="1" max="8" value="4" oninput="document.getElementById('thr_val').textContent=this.value"><span id="thr_val">4</span></div>
      <div class="setting-row"><label>下载限速(MB/s)</label><input type="range" id="s_speed" min="0" max="50" value="0" oninput="document.getElementById('spd_val').textContent=this.value==0?'不限':this.value"><span id="spd_val">不限</span></div>
      <div class="setting-row"><label>启用代理</label><div class="switch" id="sw_proxy" onclick="toggleSwitch(this)"></div></div>
      <div class="setting-row"><label>代理类型</label><select id="s_proxytype"><option value="http">HTTP</option><option value="socks5">SOCKS5</option></select></div>
      <div class="setting-row"><label>代理地址</label><input type="text" id="s_proxyaddr" value="127.0.0.1" style="width:150px"><span>:</span><input type="text" id="s_proxyport" value="7890" style="width:80px"></div>
    </div>
    <div class="settings-group">
      <h3>Cookie 登录</h3>
      <div class="setting-row"><label>启用Cookie</label><div class="switch on" id="sw_cookies" onclick="toggleSwitch(this)"></div></div>
      <div class="setting-row"><label>Cookie模式</label>
        <select id="s_cookiemode" onchange="toggleCookieMode()">
          <option value="1">cookies.txt文件(推荐)</option>
          <option value="2">浏览器提取</option>
        </select>
      </div>
      <div class="setting-row" id="row_browser"><label>浏览器</label><select id="s_browser"></select></div>
      <div class="setting-row" id="row_profile"><label>配置文件名</label><input type="text" id="s_profile" value="Default"></div>
    </div>
    <div class="settings-group">
      <h3>编码与高级</h3>
      <div class="setting-row"><label>硬件加速</label><select id="s_hwaccel"></select></div>
      <div class="setting-row"><label>嵌入元数据</label><div class="switch on" id="sw_meta" onclick="toggleSwitch(this)"></div></div>
      <div class="setting-row"><label>下载封面</label><div class="switch on" id="sw_thumb" onclick="toggleSwitch(this)"></div></div>
      <div class="setting-row"><label>Win文件名兼容</label><div class="switch on" id="sw_winfn" onclick="toggleSwitch(this)"></div></div>
      <div class="setting-row"><label>严格文件名</label><div class="switch" id="sw_strict" onclick="toggleSwitch(this)"></div></div>
      <div class="setting-row"><label>Niconico弹幕</label><div class="switch" id="sw_nicocmt" onclick="toggleSwitch(this)"></div></div>
      <div class="setting-row"><label>Niconico重编码</label><div class="switch" id="sw_nicorec" onclick="toggleSwitch(this)"></div></div>
      <div class="setting-row"><label>启用运行日志</label><div class="switch on" id="sw_log" onclick="toggleSwitch(this)"></div></div>
    </div>
    <button class="btn btn-save" onclick="saveSettings()">💾 保存设置</button>
    <button class="btn" style="background:gray;color:#fff;margin-left:10px" onclick="resetSettings()">↺ 恢复默认</button>
  </div>

  <!-- 历史页 -->
  <div class="page" id="page-history">
    <h2 style="color:#fff;margin-bottom:16px">📜 下载历史</h2>
    <div style="display:flex;gap:10px;margin-bottom:16px;align-items:center">
      <span style="color:#aaa" id="historyCount">共 0 条记录</span>
      <button class="btn" style="background:#ef4444;margin-left:auto" onclick="clearHistoryUI()">🗑 清空历史</button>
    </div>
    <div id="historyList" style="max-height:600px;overflow-y:auto">
      <!-- 历史列表动态生成 -->
    </div>
  </div>

  <!-- 工具箱 -->
  <div class="page" id="page-tools">
    <div class="tools-grid">
      <div class="tool-card" onclick="startBatch()">
        <div class="icon">📋</div><div class="name">TXT批量下载</div>
      </div>
      <div class="tool-card" onclick="toolAction('gen-template')">
        <div class="icon">📝</div><div class="name">生成链接模板</div>
      </div>
      <div class="tool-card" onclick="toolAction('gen-cookie-template')">
        <div class="icon">🍪</div><div class="name">生成Cookie模板</div>
      </div>
      <div class="tool-card" onclick="toolAction('update-ytdlp')">
        <div class="icon">🔄</div><div class="name">更新 yt-dlp</div>
      </div>
      <div class="tool-card" onclick="toolAction('clean-temp')">
        <div class="icon">🗑</div><div class="name">清理临时文件</div>
      </div>
      <div class="tool-card" onclick="document.getElementById('wavDialog').classList.add('show')">
        <div class="icon">🎵</div><div class="name">WAV转MP3</div>
      </div>
      <div class="tool-card" onclick="toolAction('open-downloads')">
        <div class="icon">📂</div><div class="name">打开下载目录</div>
      </div>
      <div class="tool-card" onclick="toolAction('open-logs')">
        <div class="icon">📋</div><div class="name">打开日志目录</div>
      </div>
    </div>
    <div class="wav-dialog" id="wavDialog">
      <h3 style="color:var(--purple);margin-bottom:12px">🎵 WAV 批量转 MP3</h3>
      <div class="setting-row">
        <label>WAV目录路径</label>
        <input type="text" id="wav_dir" style="flex:1" placeholder="点击浏览选择文件夹，或手动输入路径">
        <button class="btn" style="background:var(--purple);color:#fff;padding:6px 12px;margin-left:5px" onclick="browseFolder()">浏览...</button>
      </div>
      <div class="setting-row"><label>MP3比特率</label>
        <select id="wav_bitrate"><option>128</option><option>192</option><option>256</option><option selected>320</option></select><span style="color:var(--muted);font-size:0.82rem">kbps</span>
      </div>
      <div class="setting-row"><label>递归子目录</label><div class="switch" id="sw_recursive" onclick="toggleSwitch(this)"></div></div>
      <div class="setting-row"><label>转换后删除WAV</label><div class="switch" id="sw_delwav" onclick="toggleSwitch(this)"></div></div>
      <button class="btn" style="background:var(--purple);color:#fff;margin-top:10px" onclick="doWavConvert()">开始转换</button>
      <button class="btn" style="background:gray;color:#fff;margin-left:8px" onclick="document.getElementById('wavDialog').classList.remove('show')">关闭</button>
    </div>
    <div class="log-box" id="toolLog" style="height:280px"></div>
  </div>

  <!-- 帮助页 -->
  <div class="page" id="page-help">
    <h2 style="color:#fff;margin-bottom:20px">📖 使用帮助</h2>
    
    <div class="help-section">
      <h3 style="color:var(--accent);margin-bottom:10px">🚀 快速开始</h3>
      <div class="help-content">
        <p><b>单视频下载：</b>在下载页粘贴视频链接，点击「开始下载」即可。工具会自动识别平台。</p>
        <p><b>播放列表/频道：</b>直接粘贴播放列表URL或频道URL，会自动下载全部视频。</p>
        <p><b>TXT批量下载：</b>在工具目录下创建 <code>urls.txt</code>，每行一个链接（支持混合平台），然后点击工具箱的「TXT批量下载」。</p>
      </div>
    </div>

    <div class="help-section">
      <h3 style="color:var(--accent);margin-bottom:10px">⚙️ 设置说明</h3>
      <div class="help-content">
        <p><b>画质设置：</b>分辨率限制最高画质（best为无限制），编码选择优先使用的视频编码。H.264兼容性最好，AV1/VP9体积更小。</p>
        <p><b>输出格式：</b>MP4兼容性最佳，MKV支持多音轨字幕，WebM是开源格式。</p>
        <p><b>音频分离：</b>可单独提取音频为MP3/FLAC/WAV/m4a格式。</p>
        <p><b>代理设置：</b>支持HTTP和SOCKS5代理，格式如 <code>http://127.0.0.1:7890</code>。</p>
        <p><b>硬件加速：</b>根据你的显卡选择编码器，可大幅提升合并速度。</p>
      </div>
    </div>

    <div class="help-section">
      <h3 style="color:var(--accent);margin-bottom:10px">🍪 Cookie配置（必看）</h3>
      <div class="help-content">
        <p><b>为什么需要Cookie？</b>Fantia需要登录才能下载，YouTube/Twitch的年龄限制/会员视频也需要。</p>
        <p><b>方法1 - cookies.txt文件：</b></p>
        <ol style="padding-left:20px;color:#ddd;line-height:1.8">
          <li>浏览器安装「Get cookies.txt LOCALLY」扩展</li>
          <li>登录目标网站，点击扩展导出cookies.txt</li>
          <li>将文件放到工具目录，重命名为 <code>cookies.txt</code></li>
          <li>或者在工具箱点击「生成Cookie模板」查看详细说明</li>
        </ol>
        <p><b>方法2 - 浏览器自动提取（推荐）：</b>在设置中选择你登录过该网站的浏览器，会自动提取Cookie。</p>
      </div>
    </div>

    <div class="help-section">
      <h3 style="color:var(--accent);margin-bottom:10px">🎮 Twitch直播录制</h3>
      <div class="help-content">
        <p><b>录制直播：</b>直接粘贴主播频道URL（如 <code>https://www.twitch.tv/xqc</code>），会从直播开始处自动录制。</p>
        <p><b>录制回放：</b>粘贴视频URL（<code>/videos/</code>开头）即可下载回放。</p>
        <p><b>注意：</b>直播录制需要一直保持工具运行，停止则录制结束。录制文件会自动保存到Twitch/主播名/直播/文件夹。</p>
      </div>
    </div>

    <div class="help-section">
      <h3 style="color:var(--accent);margin-bottom:10px">💾 配置预设</h3>
      <div class="help-content">
        <p>在「设置」页面顶部的「配置预设」区域可以保存当前设置为命名预设，例如：</p>
        <ul style="padding-left:20px;color:#ddd;line-height:1.8">
          <li><b>4K原画</b> - 最高画质，用于收藏</li>
          <li><b>手机兼容</b> - 1080P H.264 MP4，手机直接播放</li>
          <li><b>仅音频</b> - 提取MP3 320kbps，用于音乐/播客</li>
        </ul>
      </div>
    </div>

    <div class="help-section">
      <h3 style="color:var(--accent);margin-bottom:10px">🔧 常见问题</h3>
      <div class="help-content">
        <p><b>下载速度慢？</b>检查代理设置是否正确，或增加并发数。</p>
        <p><b>提示需要登录？</b>配置Cookie（见上方说明）。</p>
        <p><b>断点续传：</b>工具默认启用断点续传，中断后重新下载会自动继续。</p>
        <p><b>更新yt-dlp：</b>工具箱点击「更新yt-dlp」获取最新版本以支持网站更新。</p>
        <p><b>下载的文件在哪？</b>工具目录下按平台名/作者名/分类存放。</p>
      </div>
    </div>

    <div class="help-section">
      <h3 style="color:var(--accent);margin-bottom:10px">📂 目录结构</h3>
      <div class="help-content" style="font-family:monospace;background:#1a1a2e;padding:12px;border-radius:8px;font-size:0.85rem;color:#8fbcbb">
        工具目录/<br>
        ├── YouTube/          # YouTube下载<br>
        │   └── 作者名/<br>
        ├── Twitch/           # Twitch下载<br>
        │   ├── 主播名/<br>
        │   │   └── 直播/     # 直播录制<br>
        ├── Nico/             # Niconico下载<br>
        ├── Fantia/           # Fantia下载<br>
        ├── urls.txt          # TXT批量链接文件<br>
        ├── cookies.txt       # Cookie文件<br>
        ├── presets.json      # 配置预设<br>
        └── download_history.json  # 下载历史<br>
      </div>
    </div>
  </div>

  <!-- 关于 -->
  <div class="page" id="page-about" style="text-align:center;padding-top:40px">
    <div style="font-size:4rem;margin-bottom:10px">⬇</div>
    <h2 style="font-size:1.8rem;background:linear-gradient(135deg,var(--accent),var(--green));-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:8px">四平台极致音画下载工具</h2>
    <p style="color:var(--muted);margin-bottom:5px" id="aboutVer"></p>
    <p style="color:var(--muted);font-size:0.9rem;margin-bottom:20px">支持平台: YouTube / Twitch / Niconico / Fantia</p>
    <p style="color:var(--muted);font-size:0.82rem">基于 yt-dlp + ffmpeg | 原版作者: B站_猫猫葉汐A_spy</p>
    <div class="settings-group" style="max-width:400px;margin:30px auto 0;text-align:left">
      <h3>依赖文件状态</h3>
      <div class="dep-status" id="depStatus"></div>
    </div>
  </div>
</div>

<script>
let evtSource = null;
let currentPlatform = "YouTube";
let download_running = false;
const SESSION_TOKEN = "__SESSION_TOKEN__";

const PLATFORMS = [
  {name:"YouTube",color:"#FF0000"},
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
  setSwitch('sw_winfn', s.WIN_FILENAMES);
  setSwitch('sw_strict', s.STRICT_FILENAME);
  setSwitch('sw_nicocmt', s.NICO_COMMENTS);
  setSwitch('sw_nicorec', s.NICO_RECODE);
  setSwitch('sw_log', s.ENABLE_LOG);
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
  // 先保存设置
  try { await saveSettingsNoAlert(); } catch(e) { alert('设置保存失败: ' + e.message); return; }
  const r = await api('/api/start', {method:'POST', body:JSON.stringify({url})});
  if(r.error) { alert(r.error); return; }
  download_running = true;
  $('btnStart').disabled = true;
  $('btnStop').disabled = false;
  // 重置统计
  $('statOk').textContent = '0';
  $('statFail').textContent = '0';
  $('statTotal').textContent = '0';
}

async function startBatch() {
  if(!confirm('将从 urls.txt 文件读取链接进行批量下载，是否继续？')) return;
  try { await saveSettingsNoAlert(); } catch(e) { alert('设置保存失败: ' + e.message); return; }
  const r = await api('/api/batch-txt', {method:'POST'});
  if(r.error) { alert(r.error); return; }
  download_running = true;
  $('btnStart').disabled = true;
  $('btnStop').disabled = false;
  // 重置统计
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
    WIN_FILENAMES: isOn('sw_winfn')?1:0,
    STRICT_FILENAME: isOn('sw_strict')?1:0,
    NICO_COMMENTS: isOn('sw_nicocmt')?1:0,
    NICO_RECODE: isOn('sw_nicorec')?1:0,
    ENABLE_LOG: isOn('sw_log')?1:0,
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
  return s.replace(/'/g, "\\'").replace(/"/g, '&quot;');
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

// 页面加载3秒后主动检查更新（后端也会静默检查，双保险）
setTimeout(() => {
  api('/api/check-update').catch(()=>{});
}, 3000);
</script>
</body>
</html>"""


def render_html_page(token) -> bytes:
    return HTML_PAGE.replace(SESSION_TOKEN_PLACEHOLDER, token).encode("utf-8")
