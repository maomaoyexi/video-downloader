/**
 * 音频音量处理器 — 基于 ffmpeg
 *
 * 包含响度归一化（EBU R128 loudnorm）和音量调整两大功能。
 * 高内聚：所有音频音量处理逻辑集中在本模块。
 * 低耦合：仅依赖全局函数 $(), api(), icon(), showToolStatus, showToast, addLog, syncToolTiles。
 */

// ========== 输出格式定义 ==========

const VOLUME_OUTPUT_FORMATS = {
  same: { name: '保持原格式', ext: '', desc: '与源文件格式一致' },
  mp3:  { name: 'MP3', ext: 'mp3', desc: '通用有损格式' },
  m4a:  { name: 'AAC (M4A)', ext: 'm4a', desc: 'Apple 生态首选' },
  wav:  { name: 'WAV', ext: 'wav', desc: '无损无压缩' },
  flac: { name: 'FLAC', ext: 'flac', desc: '无损压缩' },
  ogg:  { name: 'OGG Vorbis', ext: 'ogg', desc: '开源有损格式' },
  opus: { name: 'Opus', ext: 'opus', desc: '先进编解码器' },
};

// ========== UI 初始化 ==========

function initAudioVolumeTools() {
  // 填充两个对话框的输出格式下拉选项
  const fmtHtml = Object.entries(VOLUME_OUTPUT_FORMATS).map(([id, f]) =>
    `<option value="${id}">${f.name} — ${f.desc}</option>`
  ).join('');

  const loudnormFmt = $('loudnormOutFormat');
  if (loudnormFmt) loudnormFmt.innerHTML = fmtHtml;

  const volumeFmt = $('volumeOutFormat');
  if (volumeFmt) volumeFmt.innerHTML = fmtHtml;

  // 绑定响度参数滑块的数值回显
  bindRangeValue('loudnormI', 'loudnormIVal', ' LUFS');
  bindRangeValue('loudnormLRA', 'loudnormLRAVal', ' LU');
  bindRangeValue('loudnormTP', 'loudnormTPVal', ' dBTP');

  // 绑定音量增益滑块事件
  const gainSlider = $('volumeGain');
  if (gainSlider) {
    gainSlider.addEventListener('input', updateVolumeGainUI);
    updateVolumeGainUI();
  }
}

/**
 * 把滑块当前值回显到指定元素。
 * @param {string} sliderId - 滑块元素 ID。
 * @param {string} valueId - 数值显示元素 ID。
 * @param {string} unit - 单位后缀。
 */
function bindRangeValue(sliderId, valueId, unit) {
  const slider = $(sliderId), out = $(valueId);
  if (!slider || !out) return;
  const paint = () => { out.textContent = slider.value + unit; };
  slider.addEventListener('input', paint);
  paint();
}

// ========== 响度归一化 ==========

function showAudioLoudnorm() {
  const dlg = $('audioLoudnormDialog');
  if (dlg) {
    dlg.classList.add('show');
    syncToolTiles();
  }
}

function hideAudioLoudnorm() {
  const dlg = $('audioLoudnormDialog');
  if (dlg) { dlg.classList.remove('show'); syncToolTiles(); }
}

async function browseLoudnormDir() {
  try {
    const r = await api('/api/browse-folder', { method: 'POST' });
    if (r.path) {
      $('loudnormDir').value = r.path;
      showToolStatus('已选择目录: ' + r.path, 'success');
    } else if (r.error) {
      showToolStatus(r.error, 'error');
    }
  } catch (e) {
    showToolStatus('浏览失败: ' + e.message, 'error');
  }
}

async function startAudioLoudnorm() {
  const dir = $('loudnormDir').value.trim();
  if (!dir) { showToolStatus('请输入或选择音频文件目录', 'error'); return; }

  const mode = $('loudnormMode').value;
  const iTarget = parseFloat($('loudnormI').value);
  const lraTarget = parseFloat($('loudnormLRA').value);
  const tpTarget = parseFloat($('loudnormTP').value);
  const outputDir = $('loudnormOutDir').value.trim();
  const outputFormat = $('loudnormOutFormat').value;
  const recursive = isOn('sw_loudnormRecursive');

  // 参数校验
  if (isNaN(iTarget) || iTarget < -70 || iTarget > -5) {
    showToolStatus('目标响度 (I) 范围: -70 ~ -5 LUFS', 'error'); return;
  }
  if (isNaN(lraTarget) || lraTarget < 1 || lraTarget > 20) {
    showToolStatus('响度范围 (LRA) 范围: 1 ~ 20 LU', 'error'); return;
  }
  if (isNaN(tpTarget) || tpTarget < -9 || tpTarget > 0) {
    showToolStatus('真峰值 (TP) 范围: -9 ~ 0 dBTP', 'error'); return;
  }

  const modeLabel = mode === 'double' ? '双次精准处理' : '单次标准处理';
  showToolStatus(`正在启动响度统一 (${modeLabel})…`, 'working');

  try {
    const result = await api('/api/audio-loudnorm', {
      method: 'POST',
      body: JSON.stringify({
        dir: dir,
        recursive: recursive,
        mode: mode,
        i_target: iTarget,
        lra_target: lraTarget,
        tp_target: tpTarget,
        output_dir: outputDir,
        output_format: outputFormat,
      }),
    });
    if (result.error) throw new Error(result.error);
    const msg = result.message || `响度统一已启动 (${modeLabel})，共 ${result.total} 个文件`;
    addLog({ time: new Date().toTimeString().slice(0, 8), msg: msg, level: 'success' });
    showToolStatus(msg, 'success');
    showToast(msg, 'success');
  } catch (e) {
    showToolStatus('响度统一启动失败: ' + e.message, 'error');
    showToast(e.message, 'error');
  }
}

// ========== 音量调整 ==========

function updateVolumeGainUI() {
  const slider = $('volumeGain');
  const valDisplay = $('volumeGainVal');
  const limiterRow = $('volumeLimiterRow');
  if (!slider) return;

  const gain = parseFloat(slider.value);
  if (valDisplay) {
    valDisplay.textContent = gain > 0 ? `+${gain.toFixed(1)} dB` : `${gain.toFixed(1)} dB`;
    valDisplay.style.color = gain > 0 ? 'var(--warn)' : gain < 0 ? 'var(--ok)' : 'var(--fg3)';
  }

  // 仅在正增益时显示限幅器选项
  if (limiterRow) {
    limiterRow.style.display = gain > 0 ? '' : 'none';
  }
}

function showAudioVolume() {
  const dlg = $('audioVolumeDialog');
  if (dlg) {
    dlg.classList.add('show');
    updateVolumeGainUI();
    syncToolTiles();
  }
}

function hideAudioVolume() {
  const dlg = $('audioVolumeDialog');
  if (dlg) { dlg.classList.remove('show'); syncToolTiles(); }
}

async function browseVolumeDir() {
  try {
    const r = await api('/api/browse-folder', { method: 'POST' });
    if (r.path) {
      $('volumeDir').value = r.path;
      showToolStatus('已选择目录: ' + r.path, 'success');
    } else if (r.error) {
      showToolStatus(r.error, 'error');
    }
  } catch (e) {
    showToolStatus('浏览失败: ' + e.message, 'error');
  }
}

async function startAudioVolume() {
  const dir = $('volumeDir').value.trim();
  if (!dir) { showToolStatus('请输入或选择音频文件目录', 'error'); return; }

  const gainDb = parseFloat($('volumeGain').value);
  const limiterEnabled = gainDb > 0 && isOn('sw_volumeLimiter');
  const outputDir = $('volumeOutDir').value.trim();
  const outputFormat = $('volumeOutFormat').value;
  const recursive = isOn('sw_volumeRecursive');

  if (isNaN(gainDb) || gainDb < -30 || gainDb > 30) {
    showToolStatus('音量增益范围: -30 ~ +30 dB', 'error'); return;
  }
  if (gainDb === 0) {
    showToolStatus('增益为 0 dB，无需处理', 'error'); return;
  }

  const gainLabel = gainDb > 0 ? `+${gainDb.toFixed(1)}dB` : `${gainDb.toFixed(1)}dB`;
  const limiterLabel = limiterEnabled ? '，限幅器: 开启' : '';
  showToolStatus(`正在启动音量调整 (${gainLabel}${limiterLabel})…`, 'working');

  try {
    const result = await api('/api/audio-volume', {
      method: 'POST',
      body: JSON.stringify({
        dir: dir,
        recursive: recursive,
        gain_db: gainDb,
        limiter_enabled: limiterEnabled,
        output_dir: outputDir,
        output_format: outputFormat,
      }),
    });
    if (result.error) throw new Error(result.error);
    const msg = result.message || `音量调整已启动 (${gainLabel})，共 ${result.total} 个文件`;
    addLog({ time: new Date().toTimeString().slice(0, 8), msg: msg, level: 'success' });
    showToolStatus(msg, 'success');
    showToast(msg, 'success');
  } catch (e) {
    showToolStatus('音量调整启动失败: ' + e.message, 'error');
    showToast(e.message, 'error');
  }
}
