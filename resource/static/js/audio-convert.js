/**
 * 音频格式转换器 — 基于 ffmpeg
 *
 * 支持 9 种输出格式，每种格式配置正确的编码器和质量参数。
 * 高内聚：所有音频转换逻辑集中在本模块。
 * 低耦合：仅依赖全局函数 $(), api(), icon(), showToolStatus, showToast, addLog, syncToolTiles。
 */

const AUDIO_FORMATS = {
  mp3: {
    name: 'MP3',
    ext: 'mp3',
    codec: 'libmp3lame',
    desc: '最通用的有损格式，所有设备兼容',
    qualityType: 'bitrate',
    qualities: [
      { label: '320 kbps — 极致',  value: '320' },
      { label: '256 kbps — 高品质', value: '256' },
      { label: '192 kbps — 均衡',  value: '192' },
      { label: '128 kbps — 节省空间', value: '128' },
    ],
    defaultQuality: '320',
  },
  aac: {
    name: 'AAC (M4A)',
    ext: 'm4a',
    codec: 'aac',
    desc: 'Apple 生态首选，同码率优于 MP3',
    qualityType: 'bitrate',
    qualities: [
      { label: '320 kbps — 极致',  value: '320' },
      { label: '256 kbps — 高品质', value: '256' },
      { label: '192 kbps — 均衡',  value: '192' },
      { label: '128 kbps — 节省空间', value: '128' },
    ],
    defaultQuality: '256',
  },
  wav: {
    name: 'WAV',
    ext: 'wav',
    codec: 'pcm_s16le',
    desc: '无损无压缩，录音棚级音质，文件较大',
    qualityType: 'none',
    qualities: [],
    defaultQuality: null,
  },
  flac: {
    name: 'FLAC',
    ext: 'flac',
    codec: 'flac',
    desc: '无损压缩，体积约为 WAV 的 50–60%',
    qualityType: 'compression',
    qualities: [
      { label: 'Level 5 — 均衡压缩',    value: '5' },
      { label: 'Level 8 — 高压缩',      value: '8' },
      { label: 'Level 12 — 极限压缩',   value: '12' },
      { label: 'Level 0 — 最快速度',    value: '0' },
    ],
    defaultQuality: '5',
  },
  ogg: {
    name: 'OGG Vorbis',
    ext: 'ogg',
    codec: 'libvorbis',
    desc: '开源有损格式，游戏/流媒体常用',
    qualityType: 'quality',
    qualities: [
      { label: 'q10 — 极致',   value: '10' },
      { label: 'q7 — 高品质',   value: '7' },
      { label: 'q5 — 均衡',    value: '5' },
      { label: 'q3 — 节省空间', value: '3' },
    ],
    defaultQuality: '7',
  },
  opus: {
    name: 'Opus',
    ext: 'opus',
    codec: 'libopus',
    desc: '最先进的编解码器，语音/音乐皆优',
    qualityType: 'bitrate',
    qualities: [
      { label: '256 kbps — 音乐',    value: '256' },
      { label: '192 kbps — 高品质',  value: '192' },
      { label: '128 kbps — 均衡',    value: '128' },
      { label: '96 kbps — 语音',     value: '96' },
      { label: '64 kbps — 节省空间',  value: '64' },
    ],
    defaultQuality: '192',
  },
  wma: {
    name: 'WMA',
    ext: 'wma',
    codec: 'wmav2',
    desc: 'Windows Media 音频，老旧设备兼容',
    qualityType: 'bitrate',
    qualities: [
      { label: '320 kbps — 极致',  value: '320' },
      { label: '192 kbps — 高品质', value: '192' },
      { label: '128 kbps — 均衡',  value: '128' },
    ],
    defaultQuality: '192',
  },
  ac3: {
    name: 'AC3 (Dolby Digital)',
    ext: 'ac3',
    codec: 'ac3',
    desc: '杜比数字环绕声，DVD / 蓝光音轨',
    qualityType: 'bitrate',
    qualities: [
      { label: '640 kbps — 蓝光', value: '640' },
      { label: '448 kbps — DVD',  value: '448' },
      { label: '384 kbps — 均衡', value: '384' },
      { label: '256 kbps — 节省', value: '256' },
    ],
    defaultQuality: '448',
  },
  alac: {
    name: 'ALAC (Apple Lossless)',
    ext: 'm4a',
    codec: 'alac',
    desc: 'Apple 无损格式，iTunes / iOS 原生支持',
    qualityType: 'none',
    qualities: [],
    defaultQuality: null,
  },
};

// 格式有序列表（用于 UI 渲染）
const AUDIO_FORMAT_LIST = Object.entries(AUDIO_FORMATS).map(([id, f]) => ({ id, ...f }));

// ========== UI 渲染 ==========

function initAudioConverter() {
  const sel = $('audioOutFormat');
  if(!sel) return;

  // 填充格式下拉选项
  sel.innerHTML = AUDIO_FORMAT_LIST.map(f =>
    `<option value="${f.id}">${f.name} (.${f.ext}) — ${f.desc}</option>`
  ).join('');

  // 设置默认格式
  sel.value = 'mp3';
  updateAudioQualityUI();

  // 绑定格式切换 → 刷新质量选项列表
  sel.addEventListener('change', updateAudioQualityUI);
}

function updateAudioQualityUI() {
  const fmtId = $('audioOutFormat').value;
  const fmt = AUDIO_FORMATS[fmtId];
  const qualityRow = $('audioQualityRow');
  const qualitySel = $('audioQuality');

  if(!fmt || fmt.qualityType === 'none') {
    qualityRow.style.display = 'none';
    return;
  }

  qualityRow.style.display = '';
  qualitySel.innerHTML = fmt.qualities.map(q =>
    `<option value="${q.value}" ${q.value === fmt.defaultQuality ? 'selected' : ''}>${q.label}</option>`
  ).join('');
}

// ========== 目录浏览器 ==========

async function browseAudioDir() {
  try {
    const r = await api('/api/browse-folder', { method: 'POST' });
    if(r.path) {
      $('audioDir').value = r.path;
      showToolStatus('已选择目录: ' + r.path, 'success');
    } else if(r.error) {
      showToolStatus(r.error, 'error');
    }
  } catch(e) {
    showToolStatus('浏览失败: ' + e.message, 'error');
  }
}

// ========== 格式转换 ==========

async function startAudioConvert() {
  const dir = $('audioDir').value.trim();
  if(!dir) { showToolStatus('请输入或选择音频文件目录', 'error'); return; }

  const fmtId = $('audioOutFormat').value;
  const fmt = AUDIO_FORMATS[fmtId];
  if(!fmt) { showToolStatus('请选择目标格式', 'error'); return; }

  const recursive = isOn('sw_audioRecursive');

  // 构建转换请求参数
  const payload = {
    dir: dir,
    output_format: fmtId,
    codec: fmt.codec,
    extension: fmt.ext,
    recursive: recursive,
    del_src: isOn('sw_audioDelSrc'),
  };

  // 质量参数（按格式类型不同而不同）
  if(fmt.qualityType !== 'none') {
    const qualVal = $('audioQuality').value;
    switch(fmt.qualityType) {
      case 'bitrate':
        payload.bitrate = qualVal + 'k';
        break;
      case 'compression':
        payload.compression_level = parseInt(qualVal);
        break;
      case 'quality':
        payload.quality = parseInt(qualVal);
        break;
    }
  }

  const fmtName = fmt.name;
  showToolStatus(`正在启动音频转换 → ${fmtName}…`, 'working');

  try {
    const result = await api('/api/audio-convert', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    if(result.error) throw new Error(result.error);
    const msg = result.message || `音频转换已启动，目标格式: ${fmtName}`;
    addLog({ time: new Date().toTimeString().slice(0,8), msg: msg, level: 'success' });
    showToolStatus(msg, 'success');
    showToast(msg, 'success');
  } catch(e) {
    showToolStatus('转换启动失败: ' + e.message, 'error');
    showToast(e.message, 'error');
  }
}

// ========== 对话框显隐 ==========

function showAudioConverter() {
  const dlg = $('audioConvertDialog');
  if(dlg) {
    dlg.classList.add('show');
    updateAudioQualityUI();
    syncToolTiles();
  }
}

function hideAudioConverter() {
  const dlg = $('audioConvertDialog');
  if(dlg) { dlg.classList.remove('show'); syncToolTiles(); }
}
