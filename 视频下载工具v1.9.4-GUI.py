# -*- coding: utf-8 -*-
"""
四平台极致音画下载工具 v1.9.4 WebUI版
支持 YouTube / Twitch / Niconico / Fantia
使用内置HTTP服务器 + 浏览器界面，无需额外GUI库
新增：自动更新功能（Gitee/GitHub双源检查，一键更新）
"""
import os
import sys
import subprocess
import threading
import json
import re
import configparser
import time
import webbrowser
import queue
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse, parse_qs
from urllib import request as urllib_request, error as urllib_error
import tempfile
from socketserver import ThreadingMixIn

VERSION = "v1.9.4 WebUI"
# 版本号：整数格式，用于自动更新比较
# v1.9.4 = 1*10000 + 9*100 + 4 = 10904
# 发布下一版 v1.9.5 时改为 10905，以此类推
VERSION_NUM = 10904

# ========== 自动更新配置 ==========
GITEE_OWNER = "maomaoyexi"
GITEE_REPO = "video-downloader"
GITHUB_OWNER = "maomaoyexi"
GITHUB_REPO = "video-downloader"
EXE_NAME = "视频下载工具v1.9.4-GUI.exe"

# 路径兼容 PyInstaller
if getattr(sys, 'frozen', False):
    TOOL_DIR = Path(sys.executable).parent
else:
    TOOL_DIR = Path(__file__).parent

EXE_SUFFIX = ".exe" if os.name == "nt" else ""
CONFIG_FILE = TOOL_DIR / "settings.ini"
LOG_DIR = TOOL_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

DEFAULT_CONFIG = {
    "PLATFORM": "YouTube",
    "RESOLUTION": "best",
    "CODEC": "best",
    "AUDIO_QUALITY": "best",
    "OUTPUT_FORMAT": "mp4",
    "MERGE_MODE": 1,
    "AUDIO_SEP_MODE": 1,
    "THREADS": 4,
    "SPEED_LIMIT": 0,
    "PROXY_ENABLED": 0,
    "PROXY_TYPE": "http",
    "PROXY_ADDR": "127.0.0.1",
    "PROXY_PORT": "7890",
    "USE_COOKIES": 1,
    "COOKIE_MODE": 1,
    "BROWSER_NAME": "chrome",
    "BROWSER_PROFILE": "Default",
    "HWACCEL": "cpu",
    "EMBED_META": 1,
    "DOWNLOAD_THUMB": 1,
    "WIN_FILENAMES": 1,
    "STRICT_FILENAME": 0,
    "NICO_COMMENTS": 0,
    "NICO_RECODE": 0,
    "ENABLE_LOG": 1,
    "MP3_BITRATE": 320,
    "DEL_WAV_AFTER_CONVERT": 0,
}

RESOLUTION_OPTIONS = ["best", "2160", "1440", "1080", "720", "480", "360"]
RESOLUTION_LABELS = ["无限制", "4K (2160p)", "2K (1440p)", "1080P", "720P", "480P", "360P"]
CODEC_OPTIONS = ["best", "h264", "av1", "vp9"]
CODEC_LABELS = ["极致画质", "兼容优先(H.264)", "AV1优先", "VP9优先"]
AUDIO_OPTIONS = ["best", "192", "128"]
AUDIO_LABELS = ["最高音质", "均衡(192k)", "最小体积(128k)"]
FORMAT_OPTIONS = ["mp4", "mkv", "webm"]
AUDIO_SEP_OPTIONS = ["m4a", "mp3", "flac", "wav"]
AUDIO_SEP_LABELS = ["m4a(原生)", "MP3", "FLAC", "WAV"]
HWACCEL_OPTIONS = ["cpu", "h264_nvenc", "h264_qsv", "h264_amf"]
HWACCEL_LABELS = ["CPU软编码", "N卡 NVENC", "Intel QSV", "AMD AMF"]
BROWSER_OPTIONS = ["chrome", "edge", "firefox", "brave", "opera"]
PROXY_TYPE_OPTIONS = ["http", "socks5"]
MP3_BITRATE_OPTIONS = [128, 192, 256, 320]

PLATFORM_INFO = [
    {"name": "YouTube", "color": "#FF0000", "domains": ["youtube.com", "youtu.be"]},
    {"name": "Twitch", "color": "#9146FF", "domains": ["twitch.tv"]},
    {"name": "Niconico", "color": "#00A0D1", "domains": ["nicovideo.jp", "nico.ms"]},
    {"name": "Fantia", "color": "#E6399B", "domains": ["fantia.jp"]},
]

# 全局状态
config = {}
download_proc = None
server_instance = None
exit_flag = False
idle_timer = None  # 空闲自动退出计时器
IDLE_TIMEOUT = 30  # 无浏览器连接且无下载时，30秒后自动退出
download_running = False
sse_clients = []
log_history = []
download_lock = threading.Lock()  # 保护下载启动/停止的锁

# ========== 自动更新状态 ==========
UPDATE_STATUS = {
    "checking": False,       # 是否正在检查更新
    "update_available": False,  # 是否有可用更新
    "latest_version": None,  # 最新版本号字符串
    "latest_version_num": 0, # 最新版本号整数
    "release_notes": "",     # 更新说明
    "download_url": None,    # 下载链接
    "downloading": False,    # 是否正在下载
    "download_progress": 0,  # 下载进度 0-100
    "download_speed": "",    # 下载速度
    "downloaded_size": 0,    # 已下载字节数
    "total_size": 0,         # 总字节数
    "update_done": False,    # 更新是否完成
    "error": None,           # 错误信息
}


def cancel_idle_timer():
    """取消空闲自动退出计时器"""
    global idle_timer
    if idle_timer is not None:
        idle_timer.cancel()
        idle_timer = None


def start_idle_timer():
    """启动空闲自动退出计时器（无浏览器连接且无下载时）"""
    global idle_timer, exit_flag
    cancel_idle_timer()
    if download_running or sse_clients:
        return
    def do_idle_exit():
        global exit_flag
        if not download_running and not sse_clients:
            add_log(f"[系统] 浏览器已关闭，{IDLE_TIMEOUT}秒无活动，自动退出", "warn")
            exit_flag = True
    idle_timer = threading.Timer(IDLE_TIMEOUT, do_idle_exit)
    idle_timer.daemon = True
    idle_timer.start()
progress_data = {"percent": 0, "status": "就绪", "speed": "", "eta": ""}
batch_stats = {"ok": 0, "fail": 0, "total": 0, "current": 0}


def load_config():
    global config
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_FILE.exists():
        parser = configparser.ConfigParser()
        parser.read(CONFIG_FILE, encoding="utf-8")
        if parser.has_section("settings"):
            for k, v in parser["settings"].items():
                key = k.upper()
                if key in DEFAULT_CONFIG:
                    default_val = DEFAULT_CONFIG[key]
                    if isinstance(default_val, int):
                        try:
                            cfg[key] = int(v)
                        except ValueError:
                            cfg[key] = default_val
                    else:
                        cfg[key] = v
    config = cfg
    return cfg


def save_config():
    parser = configparser.ConfigParser()
    parser["settings"] = {k: str(v) for k, v in config.items()}
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        parser.write(f)


# ========== 预设管理 ==========
PRESET_FILE = TOOL_DIR / "presets.json"

def load_presets():
    """加载所有预设"""
    if PRESET_FILE.exists():
        try:
            with open(PRESET_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_preset(name):
    """保存当前配置为预设"""
    presets = load_presets()
    presets[name] = dict(config)
    try:
        with open(PRESET_FILE, "w", encoding="utf-8") as f:
            json.dump(presets, f, ensure_ascii=False, indent=2)
        add_log(f"[预设] 已保存: {name}", "success")
        return {"ok": True, "presets": list(presets.keys())}
    except Exception as e:
        add_log(f"[预设] 保存失败: {e}", "error")
        return {"error": str(e)}

def load_preset(name):
    """加载预设"""
    global config
    presets = load_presets()
    if name not in presets:
        return {"error": f"预设不存在: {name}"}
    try:
        preset_data = presets[name]
        for k, v in preset_data.items():
            if k in DEFAULT_CONFIG:
                config[k] = v
        save_config()
        add_log(f"[预设] 已加载: {name}", "success")
        return {"ok": True, "config": config, "presets": list(presets.keys())}
    except Exception as e:
        add_log(f"[预设] 加载失败: {e}", "error")
        return {"error": str(e)}

def delete_preset(name):
    """删除预设"""
    presets = load_presets()
    if name in presets:
        del presets[name]
        try:
            with open(PRESET_FILE, "w", encoding="utf-8") as f:
                json.dump(presets, f, ensure_ascii=False, indent=2)
            add_log(f"[预设] 已删除: {name}", "warn")
        except Exception as e:
            return {"error": str(e)}
    return {"ok": True, "presets": list(presets.keys())}


# ========== 下载历史 ==========
HISTORY_FILE = TOOL_DIR / "download_history.json"

def load_history():
    """加载下载历史"""
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []

def add_history(url, title, platform, status="success"):
    """添加一条下载记录"""
    history = load_history()
    record = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "url": url,
        "title": title or "未知标题",
        "platform": platform,
        "status": status
    }
    history.insert(0, record)
    if len(history) > 500:
        history = history[:500]
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    # 推送历史更新
    for q in sse_clients[:]:
        try:
            q.put({"type": "history", "data": history[:50]})
        except Exception:
            pass
    return history

def clear_history():
    """清空下载历史"""
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)
        add_log("[历史] 已清空下载历史", "warn")
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)}


def add_log(msg, level="info"):
    ts = datetime.now().strftime("%H:%M:%S")
    entry = {"time": ts, "msg": msg, "level": level}
    log_history.append(entry)
    if len(log_history) > 500:
        log_history.pop(0)
    for q in sse_clients[:]:
        try:
            q.put({"type": "log", "data": entry})
        except Exception:
            pass


def update_progress(percent, status=None, speed="", eta=""):
    global progress_data
    progress_data["percent"] = percent
    if status:
        progress_data["status"] = status
    progress_data["speed"] = speed
    progress_data["eta"] = eta
    for q in sse_clients[:]:
        try:
            q.put({"type": "progress", "data": progress_data})
        except Exception:
            pass


def safe_decode(buf):
    """健壮解码：尝试UTF-8，失败则回退到GBK/CP936，最后用replace"""
    if isinstance(buf, str):
        return buf
    for enc in ("utf-8", "gbk", "cp936", "shift_jis", "euc-jp"):
        try:
            return buf.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return buf.decode("utf-8", errors="replace")


def build_ytdlp_cmd(url, is_live=False, platform_override=None):
    cfg = config
    ytdlp = str(TOOL_DIR / f"yt-dlp{EXE_SUFFIX}")
    cmd = [ytdlp, "--no-warnings", "--newline", "--continue", "--encoding", "utf-8"]  # 断点续传，强制UTF-8输出

    platform_name = platform_override if platform_override else cfg["PLATFORM"]
    
    # 检测Niconico直播
    is_nico_live = "live.nicovideo.jp" in url.lower() or "live2.nicovideo.jp" in url.lower()
    
    # Twitch直播录制使用特殊文件名模板
    if is_live or platform_name == "Twitch":
        # 检测是否是直播链接
        live_domains = ["twitch.tv/"]
        is_live_url = any(d in url.lower() for d in live_domains) and "/videos/" not in url.lower() and "/clip/" not in url.lower()
        if is_live_url:
            out_tmpl = str(TOOL_DIR / platform_name / "%(uploader)s" / "直播" / "%(title)s - %(upload_date)s %(id)s.%(ext)s")
            # 直播录制参数
            cmd += ["--live-from-start"]
            is_live = True
        else:
            out_tmpl = str(TOOL_DIR / platform_name / "%(uploader)s" / "%(title)s [%(id)s].%(ext)s")
    elif is_nico_live:
        # Niconico直播（不使用--live-from-start，因为很多Niconico直播不支持从头录制）
        out_tmpl = str(TOOL_DIR / "Niconico" / "直播" / "%(title)s - %(upload_date)s %(id)s.%(ext)s")
        is_live = True
    else:
        out_tmpl = str(TOOL_DIR / platform_name / "%(uploader)s" / "%(title)s [%(id)s].%(ext)s")
    
    cmd += ["-o", out_tmpl]

    archive = TOOL_DIR / f"{platform_name.lower()}_archive.txt"
    cmd += ["--download-archive", str(archive)]

    res = cfg["RESOLUTION"]
    codec = cfg["CODEC"]
    res_str = f"[height<={res}]" if res != "best" else ""

    if codec == "h264":
        vcodec = "[vcodec~='avc1|h264']"
    elif codec == "av1":
        vcodec = "[vcodec~='av01']"
    elif codec == "vp9":
        vcodec = "[vcodec~='vp9']"
    else:
        vcodec = ""

    audio_q = cfg["AUDIO_QUALITY"]
    if audio_q != "best":
        aformat_base = f"bestaudio[abr<={audio_q}]"
    else:
        aformat_base = "bestaudio"

    merge = cfg["MERGE_MODE"]
    sep_mode = cfg["AUDIO_SEP_MODE"]
    fmt = cfg["OUTPUT_FORMAT"]

    # 构建格式选择字符串：视频+音频 / 带过滤的best / 兜底best
    vcodec_part = res_str + vcodec
    vfmt = f"bestvideo{vcodec_part}+{aformat_base}/best{vcodec_part}/best"

    if merge == 1:
        # 合并输出模式
        cmd += ["-f", vfmt, "--merge-output-format", fmt]
        # 如果需要同时分离音频
        if sep_mode > 1:
            ext = AUDIO_SEP_OPTIONS[sep_mode - 1]
            cmd += ["-x", "--audio-format", ext]
    else:
        # 不合并模式
        cmd += ["-f", vfmt]
        if sep_mode == 1:
            cmd += ["--no-merge"]
        else:
            ext = AUDIO_SEP_OPTIONS[sep_mode - 1]
            cmd += ["-x", "--audio-format", ext, "--keep-video"]

    cmd += ["-N", str(cfg["THREADS"])]

    if cfg["SPEED_LIMIT"] > 0:
        cmd += ["-r", f"{cfg['SPEED_LIMIT']}M"]

    if cfg["PROXY_ENABLED"]:
        proxy_url = f"{cfg['PROXY_TYPE']}://{cfg['PROXY_ADDR']}:{cfg['PROXY_PORT']}"
        cmd += ["--proxy", proxy_url]

    if cfg["USE_COOKIES"]:
        if cfg["COOKIE_MODE"] == 1:
            cookie_file = TOOL_DIR / "cookies.txt"
            if cookie_file.exists():
                cmd += ["--cookies", str(cookie_file)]
        else:
            browser = cfg["BROWSER_NAME"]
            profile = cfg["BROWSER_PROFILE"]
            cmd += ["--cookies-from-browser", f"{browser}:{profile}"]

    if cfg["EMBED_META"]:
        cmd += ["--embed-metadata"]
    if cfg["DOWNLOAD_THUMB"]:
        cmd += ["--embed-thumbnail"]
    if cfg["WIN_FILENAMES"]:
        cmd += ["--windows-filenames"]
    if cfg["STRICT_FILENAME"]:
        cmd += ["--restrict-filenames"]

    hwaccel = cfg["HWACCEL"]
    if hwaccel != "cpu":
        cmd += ["--postprocessor-args", f"ffmpeg_i:-c:v {hwaccel}"]

    cmd += ["--ffmpeg-location", str(TOOL_DIR)]

    if platform_name == "Niconico" and cfg["NICO_COMMENTS"]:
        cmd += ["--write-comments"]
    if platform_name == "Niconico" and cfg["NICO_RECODE"]:
        cmd += ["--recode-video", fmt]

    # 注意：--print-to-file 已移除，日志通过stdout实时捕获
    # 如需保存文件日志，在应用层处理

    cmd.append(url)
    return cmd


def clean_url(url):
    """清理URL：去除前后空白、反引号、引号"""
    if not url:
        return ""
    # 反复剥离两端的空白和引号（最多3轮，处理嵌套情况）
    for _ in range(3):
        old = url
        url = url.strip().strip("`'\"")
        if url == old:
            break
    return url.strip()


def detect_platform(url):
    url_lower = url.lower()
    for p in PLATFORM_INFO:
        for d in p["domains"]:
            if d in url_lower:
                return p["name"]
    return None


def start_download(url):
    global download_proc, download_running
    with download_lock:
        if download_running:
            return {"error": "已有下载任务在运行"}
        download_running = True
    
    # 清理URL：去除反引号、引号、前后空白
    url = clean_url(url)
    if not url:
        with download_lock:
            download_running = False
        return {"error": "请输入有效的视频链接"}

    # 自动识别平台（仅用于本次下载，不覆盖用户设置）
    detected = detect_platform(url)
    effective_platform = detected if detected else config["PLATFORM"]
    if detected:
        add_log(f"[自动识别] 检测到{detected}链接", "info")
    else:
        add_log(f"[提示] 未识别平台，使用: {config['PLATFORM']}", "warn")

    for dep in ["yt-dlp", "ffmpeg", "ffprobe"]:
        if not (TOOL_DIR / f"{dep}{EXE_SUFFIX}").exists():
            with download_lock:
                download_running = False
            return {"error": f"缺少依赖: {dep}{EXE_SUFFIX}"}

    cancel_idle_timer()  # 开始下载，取消空闲退出
    
    # 检测是否是直播
    is_live_download = bool(detected and ("live" in url.lower() or detected in ["Twitch", "Niconico"] and "live" in url.lower()))
    is_live_download = is_live_download or "live.nicovideo.jp" in url.lower() or "live2.nicovideo.jp" in url.lower()
    is_live_download = is_live_download or ("twitch.tv/" in url.lower() and "/videos/" not in url.lower() and "/clip/" not in url.lower())
    
    update_progress(0, "正在连接直播..." if is_live_download else "正在下载...")
    add_log(f"[下载] {url}", "info")
    cmd = build_ytdlp_cmd(url, platform_override=effective_platform)

    def run():
        global download_proc, download_running
        video_title = ""
        proc = None
        try:
            import queue
            env = os.environ.copy()
            env["PYTHONUTF8"] = "1"
            env["PYTHONIOENCODING"] = "utf-8"  # 强制子进程stdout/stderr使用UTF-8
            env["PYTHONUNBUFFERED"] = "1"  # 禁用Python缓冲，实时输出进度
            env["NO_COLOR"] = "1"
            # Windows下隐藏子进程控制台窗口
            startupinfo = None
            creationflags = 0
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
                creationflags = subprocess.CREATE_NO_WINDOW
            
            # 创建进程前检查是否已被取消
            if not download_running:
                add_log("[停止] 下载已取消", "warn")
                return
            
            proc = subprocess.Popen(
                cmd, cwd=TOOL_DIR, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                bufsize=0,  # 无缓冲，实时读取输出
                startupinfo=startupinfo,
                creationflags=creationflags
            )
            with download_lock:
                download_proc = proc
            live_connected = False
            live_start_time = time.time()
            # 独立变量跟踪直播状态，避免字符串解析导致的重复
            live_size = ""
            live_speed = ""
            live_frag = ""
            
            def fmt_live_status():
                """统一格式化直播状态文本"""
                elapsed = int(time.time() - live_start_time)
                mins, secs = divmod(elapsed, 60)
                hrs, mins = divmod(mins, 60)
                if hrs > 0:
                    time_str = f"{hrs}:{mins:02d}:{secs:02d}"
                else:
                    time_str = f"{mins}:{secs:02d}"
                parts = []
                if live_size:
                    parts.append(live_size)
                if live_frag:
                    parts.append(live_frag)
                if live_speed:
                    parts.append(live_speed)
                parts.append(f"录制 {time_str}")
                return "直播录制中 - " + " | ".join(parts), live_speed
            
            # 用独立线程+队列读取stdout，大块读取后按\r和\n分割
            # 这比逐字节读取在Windows管道上更可靠
            line_q = queue.Queue()
            read_done = threading.Event()
            
            def reader_thread():
                import os as _os
                fd = proc.stdout.fileno()
                buf = bytearray()
                while True:
                    try:
                        chunk = _os.read(fd, 4096)
                    except OSError:
                        # 管道被关闭（进程终止或停止）
                        chunk = None
                    except Exception:
                        chunk = None
                    if not chunk:
                        if buf:
                            try:
                                line_q.put(safe_decode(buf))
                            except Exception:
                                pass
                        break
                    for b in chunk:
                        if b in (0x0d, 0x0a):  # \r or \n
                            if buf:
                                try:
                                    line_q.put(safe_decode(buf))
                                except Exception:
                                    pass
                                buf = bytearray()
                        else:
                            buf.append(b)
                read_done.set()
            
            threading.Thread(target=reader_thread, daemon=True).start()
            
            while not read_done.is_set() or not line_q.empty():
                if not download_running:
                    break
                try:
                    line = line_q.get(timeout=0.5)
                except queue.Empty:
                    # 超时，更新直播时长显示
                    if live_connected:
                        status_text, spd = fmt_live_status()
                        update_progress(-1, status_text, speed=spd, eta="")
                    continue
                
                line = line.strip()
                if not line:
                    continue
                
                # 检测直播连接成功（只有在确实是直播下载时才触发）
                if is_live_download and not live_connected and ("Connecting to WebSocket" in line or "Downloading m3u8" in line):
                    live_connected = True
                    live_start_time = time.time()
                    update_progress(-1, "直播录制中...")
                
                # 始终显示：错误、警告
                is_error = "ERROR" in line
                is_warning = "WARNING" in line
                # 含百分比的进度行
                has_pct = bool(re.search(r'\d+(?:\.\d+)?%', line))
                
                # 直播进度检测（支持多种格式）：
                # 格式1: yt-dlp "[download]  1.23MiB at 2.50MiB/s" 或 "[download]  1.23MiB 2.50MiB/s"
                # 格式2: ffmpeg "size=    1024kB time=00:00:10.00 bitrate= 838.9kbits/s speed=1.01x"
                #        或 "Lsize=..." 或 "frame=..." 或 "fps=..."
                # 格式3: yt-dlp分片 "[download] Downloading fragment" 或 "[download] Downloaded fragment"
                has_ffmpeg_progress = is_live_download and (
                    re.search(r'(?:size|Lsize)=\s*\S+', line) or
                    (re.search(r'frame=\s*\d+', line) and re.search(r'fps=', line))
                ) and (
                    "time=" in line or "bitrate=" in line or "speed=" in line or "fps=" in line
                )
                has_ytdlp_live = is_live_download and re.search(r'\d+\.?\d*\s*[KMG]iB', line) and re.search(
                    r'\d+\.?\d*\s*[KMG]iB/s', line
                )
                has_fragment = is_live_download and "fragment" in line.lower() and (
                    "Downloading" in line or "Downloaded" in line
                )
                is_live_progress = has_ytdlp_live or has_ffmpeg_progress or has_fragment
                
                # 关键状态行
                is_keyword = any(kw in line for kw in [
                    "Destination:", "Merging formats", "Deleting original",
                    "Extracting URL", "Downloading webpage",
                    "Connecting to WebSocket", "has already been recorded",
                    "video only", "audio only", "Resuming"
                ])
                
                if is_error:
                    add_log(line, "error")
                elif is_warning:
                    add_log(line, "warn")
                elif has_pct:
                    pass  # VOD进度行只更新进度条
                elif is_live_progress and not is_keyword:
                    pass  # 直播进度行只更新状态
                elif is_keyword and len(line) < 200:
                    add_log(line, "info")
                elif live_connected and len(line) < 200 and not any(
                    skip in line for skip in ["[download]", "[hls]", "[fragment]"]
                ):
                    # 直播中其他简短信息也显示
                    add_log(line, "info")

                # 提取视频标题
                title_m = re.search(r'\[download\] Destination: (.+)', line)
                if not title_m:
                    title_m = re.search(r'\[Merger\] Merging formats into "(.+)"', line)
                if title_m:
                    video_title = os.path.basename(title_m.group(1).replace('"', '').replace("'", ""))
                    video_title = re.sub(r'\s*\[[a-zA-Z0-9_-]{6,}\]\.\w+$', '', video_title)

                # 解析百分比进度（VOD视频）
                m = re.search(r'(\d+(?:\.\d+)?)%', line)
                if m:
                    pct = float(m.group(1))
                    speed_m = re.search(r'(\d+(?:\.\d+)?\s*[KMG]iB/s)', line)
                    eta_m = re.search(r'ETA (\d+:\d+)', line)
                    update_progress(
                        pct / 100,
                        speed=speed_m.group(1).replace(" ", "") if speed_m else "",
                        eta=eta_m.group(1) if eta_m else ""
                    )
                elif is_live_progress:
                    if has_ytdlp_live:
                        # yt-dlp格式: "1.23MiB at 2.50MiB/s"
                        size_m = re.search(r'(\d+\.?\d*\s*[KMG]iB)', line)
                        spd_m = re.search(r'(\d+\.?\d*\s*[KMG]iB/s)', line)
                        if size_m:
                            live_size = "已下载 " + size_m.group(1).replace(" ", "")
                        if spd_m:
                            live_speed = spd_m.group(1).replace(" ", "")
                    elif has_ffmpeg_progress:
                        # ffmpeg格式: "size=    1024kB time=00:01:05.00 bitrate= 838.9kbits/s speed=10.4x"
                        # 支持 size= 和 Lsize=，也支持 frame= 开头的行
                        size_m = re.search(r'(?:size|Lsize)=\s*(\d+\.?\d*\s*[kKmMgG][bB]?|N/A)', line)
                        spd_m = re.search(r'speed=\s*(\d+\.?\d*x)', line)
                        fps_m = re.search(r'fps=\s*(\d+)', line)
                        bit_m = re.search(r'bitrate=\s*(\d+\.?\d*\s*kbits/s)', line)
                        time_m = re.search(r'time=(\d+:\d+:\d+\.\d+|\d+:\d+\.\d+)', line)
                        if size_m and size_m.group(1) != 'N/A':
                            live_size = "已下载 " + size_m.group(1).replace(" ", "")
                        if spd_m:
                            live_speed = spd_m.group(1).replace(" ", "")
                        elif fps_m:
                            live_speed = f"{fps_m.group(1)} fps"
                        elif bit_m:
                            live_speed = bit_m.group(1).replace(" ", "")
                        # 如果ffmpeg提供了time，用它来更新起始时间（更准确）
                        if time_m:
                            t_str = time_m.group(1).split('.')[0]  # 去掉小数部分
                            parts_t = t_str.split(':')
                            if len(parts_t) == 3:
                                h, m, s = int(parts_t[0]), int(parts_t[1]), int(parts_t[2])
                                ffmpeg_elapsed = h * 3600 + m * 60 + s
                                # 校准起始时间
                                live_start_time = time.time() - ffmpeg_elapsed
                    elif has_fragment:
                        # 分片下载：提取分片号
                        frag_m = re.search(r'fragment\s+(\d+)', line, re.IGNORECASE)
                        if frag_m:
                            live_frag = f"分片 {frag_m.group(1)}"
                    
                    # 用统一函数格式化并更新
                    status_text, spd = fmt_live_status()
                    update_progress(-1, status_text, speed=spd, eta="")

            # 等待进程结束（如果是被停止的，_kill_proc_tree已经处理了）
            try:
                if proc.poll() is None:
                    proc.wait(timeout=5)
            except Exception:
                pass
            
            # 关闭管道
            try:
                proc.stdout.close()
            except Exception:
                pass
            
            rc = proc.returncode if proc.returncode is not None else -1
            if not download_running:
                add_log("[停止] 下载已取消", "warn")
                update_progress(0, "已停止", "", "")
            elif rc == 0:
                add_log("[完成] 下载成功！", "success")
                update_progress(1, "下载完成", "", "")
                add_history(url, video_title, effective_platform, "success")
            else:
                add_log(f"[错误] 下载结束，退出码: {rc}", "error")
                update_progress(0, f"失败 (退出码 {rc})", "", "")
                add_history(url, video_title, effective_platform, "fail")
        except Exception as e:
            add_log(f"[异常] {e}", "error")
            update_progress(0, "异常终止", "", "")
            try:
                add_history(url, video_title, effective_platform, "fail")
            except Exception:
                pass
            # 异常时确保杀进程
            try:
                _kill_proc_tree(proc)
            except Exception:
                pass
        finally:
            with download_lock:
                download_running = False
                download_proc = None
            # 下载结束，如果浏览器已关闭则启动空闲退出
            if not sse_clients:
                start_idle_timer()

    threading.Thread(target=run, daemon=True).start()
    return {"ok": True}


def _kill_proc_tree(p):
    """安全终止子进程及其子进程树（Windows专用，使用taskkill /F /T）"""
    if p is None:
        return
    try:
        if p.poll() is None:
            pid = p.pid
            # 隐藏窗口参数
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = subprocess.SW_HIDE
            cf = subprocess.CREATE_NO_WINDOW
            
            # 先用taskkill /T（不强制）发送关闭信号
            try:
                subprocess.run(
                    ["taskkill", "/T", "/PID", str(pid)],
                    capture_output=True, timeout=2,
                    startupinfo=si, creationflags=cf
                )
            except Exception:
                pass
            
            # 等待一下看是否优雅退出
            try:
                p.wait(timeout=1)
            except Exception:
                pass
            
            # 如果还在运行，用/F强制终止整个进程树
            if p.poll() is None:
                try:
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(pid)],
                        capture_output=True, timeout=5,
                        startupinfo=si, creationflags=cf
                    )
                except Exception:
                    pass
                
                # 再等待
                try:
                    p.wait(timeout=3)
                except Exception:
                    pass
                
                # 最后兜底
                if p.poll() is None:
                    try:
                        p.kill()
                        p.wait(timeout=2)
                    except Exception:
                        pass
    except Exception:
        pass
    # 关闭管道
    try:
        if p.stdout:
            p.stdout.close()
    except Exception:
        pass


def stop_download():
    global download_proc, download_running
    with download_lock:
        proc = download_proc
        if not download_running:
            return {"ok": True}
        download_running = False
    
    # 锁外执行终止操作，避免阻塞其他API
    if proc is not None:
        _kill_proc_tree(proc)
        add_log("[停止] 已停止下载", "warn")
    else:
        # 进程还在启动中，但已设置download_running=False，启动函数会检测到
        add_log("[停止] 正在取消...", "warn")
    return {"ok": True}


def check_deps():
    deps = {}
    for dep in ["yt-dlp", "ffmpeg", "ffprobe"]:
        deps[dep] = (TOOL_DIR / f"{dep}{EXE_SUFFIX}").exists()
    deps["fantiadl"] = (TOOL_DIR / f"fantiadl{EXE_SUFFIX}").exists()
    return deps


def update_ytdlp():
    ytdlp = TOOL_DIR / f"yt-dlp{EXE_SUFFIX}"
    if not ytdlp.exists():
        return {"error": "未找到yt-dlp.exe"}

    def run():
        try:
            env = os.environ.copy()
            env["PYTHONUTF8"] = "1"
            proc = subprocess.run([str(ytdlp), "-U"], cwd=TOOL_DIR, env=env, capture_output=True, text=True, timeout=120)
            for line in (proc.stdout or "").split("\n"):
                if line.strip():
                    add_log(f"[yt-dlp] {line.strip()}", "info")
            if proc.returncode == 0:
                add_log("[yt-dlp] 更新完成", "success")
            else:
                add_log(f"[yt-dlp] 更新失败: {proc.stderr}", "error")
        except Exception as e:
            add_log(f"[yt-dlp] 更新异常: {e}", "error")
    threading.Thread(target=run, daemon=True).start()
    return {"ok": True}


def clean_temp():
    count = 0
    temp_ext = [".part", ".ytdl", ".temp", ".tmp"]
    for f in TOOL_DIR.rglob("*"):
        if f.is_file() and f.suffix.lower() in temp_ext:
            try:
                f.unlink()
                count += 1
            except Exception:
                pass
    for d in sorted(TOOL_DIR.rglob("*"), reverse=True):
        if d.is_dir():
            try:
                if not any(d.iterdir()):
                    d.rmdir()
            except Exception:
                pass
    add_log(f"[清理] 完成，删除 {count} 个临时文件", "success")
    return {"ok": True, "count": count}


def gen_url_template():
    template = TOOL_DIR / "urls.txt"
    content = """# ============================================
# 混合平台批量下载链接模板
# 每行一个链接，# 开头为注释行
# ============================================

# YouTube
# https://www.youtube.com/watch?v=xxxxxxxxxxx
# https://www.youtube.com/playlist?list=xxxxxxxxxxx

# Twitch
# https://www.twitch.tv/videos/xxxxxxxxxx

# Niconico
# https://www.nicovideo.jp/watch/smxxxxxxxx

# Fantia
# https://fantia.jp/posts/xxxxxxx
"""
    if template.exists():
        add_log(f"urls.txt 已存在", "warn")
        return {"ok": True, "existed": True}
    template.write_text(content, encoding="utf-8")
    add_log(f"已生成 urls.txt 模板", "success")
    return {"ok": True}


def wav_to_mp3(target_dir, recursive, bitrate, del_src):
    ffmpeg = TOOL_DIR / f"ffmpeg{EXE_SUFFIX}"
    if not ffmpeg.exists():
        return {"error": "ffmpeg.exe未找到"}
    target = Path(target_dir)
    if not target.exists():
        return {"error": "目录不存在"}

    config["MP3_BITRATE"] = bitrate
    config["DEL_WAV_AFTER_CONVERT"] = 1 if del_src else 0
    save_config()

    def run():
        pattern = "**/*.wav" if recursive else "*.wav"
        wav_files = sorted([f for f in target.glob(pattern) if f.is_file()])
        if not wav_files:
            add_log("[WAV转MP3] 未找到WAV文件", "warn")
            return
        add_log(f"[WAV转MP3] 找到 {len(wav_files)} 个WAV文件", "info")
        success = skip = fail = 0
        for i, wav in enumerate(wav_files, 1):
            mp3 = wav.with_suffix(".mp3")
            add_log(f"[{i}/{len(wav_files)}] 转换: {wav.name}", "info")
            if mp3.exists():
                add_log("  → 已存在，跳过", "warn")
                skip += 1
                continue
            cmd = [str(ffmpeg), "-y", "-i", str(wav), "-codec:a", "libmp3lame",
                   "-b:a", f"{bitrate}k", "-ac", "2", "-ar", "44100", str(mp3)]
            env = os.environ.copy()
            env["PYTHONUTF8"] = "1"
            try:
                proc = subprocess.run(cmd, cwd=TOOL_DIR, env=env, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL, timeout=600)
                if proc.returncode == 0 and mp3.exists():
                    add_log("  → 完成", "success")
                    success += 1
                    if del_src:
                        try:
                            wav.unlink()
                        except Exception:
                            pass
                else:
                    add_log("  → 失败", "error")
                    fail += 1
                    if mp3.exists():
                        try:
                            mp3.unlink()
                        except Exception:
                            pass
            except Exception as e:
                add_log(f"  → 错误: {e}", "error")
                fail += 1
        add_log(f"[WAV转MP3] 完成: 成功{success} 跳过{skip} 失败{fail}", "success")
    threading.Thread(target=run, daemon=True).start()
    return {"ok": True, "total": len(list(target.glob("**/*.wav" if recursive else "*.wav")))}


def browse_folder():
    """打开文件夹选择对话框"""
    folder = ""
    try:
        # 方法1: 尝试使用 tkinter 的 filedialog
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            folder = filedialog.askdirectory(initialdir=str(TOOL_DIR))
            root.destroy()
        except Exception:
            # 方法2: 使用PowerShell的文件夹浏览器对话框
            ps_cmd = '''
            Add-Type -AssemblyName System.Windows.Forms
            $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
            $dialog.Description = "选择包含WAV文件的文件夹"
            $dialog.ShowNewFolderButton = $true
            if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
                $dialog.SelectedPath
            }
            '''
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                capture_output=True, text=True, encoding="utf-8", timeout=60
            )
            folder = result.stdout.strip()
        
        if folder:
            add_log(f"[浏览文件夹] 已选择: {folder}", "info")
            return {"ok": True, "path": folder}
        return {"ok": True, "path": ""}
    except Exception as e:
        return {"error": f"打开文件夹选择失败: {e}"}


def open_folder(folder_path):
    """在资源管理器中打开文件夹"""
    try:
        path = Path(folder_path)
        path.mkdir(parents=True, exist_ok=True)
        os.startfile(str(path))
        return {"ok": True, "message": f"已打开: {path}"}
    except Exception as e:
        return {"error": f"打开文件夹失败: {e}"}


def gen_cookie_template():
    """生成cookies.txt模板文件"""
    cookie_file = TOOL_DIR / "cookies.txt"
    if cookie_file.exists():
        add_log("[Cookie模板] cookies.txt 已存在，跳过生成", "warn")
        return {"ok": True, "existed": True}
    
    content = """# =====================================================
# Netscape HTTP Cookie File
# 请使用浏览器扩展「Get cookies.txt LOCALLY」导出Cookie
# =====================================================
#
# 使用说明：
# 1. 请勿手动编辑此文件内容，格式错误会导致Cookie失效
# 2. 推荐使用浏览器扩展「Get cookies.txt LOCALLY」导出
# 3. 导出时选择对应平台域名，导出后直接替换本文件
# 4. 文件必须保持 Netscape 格式，编码为 UTF-8 无BOM
#
# 安全提示：
# 1. Cookie包含账号登录凭证，请勿分享给他人
# 2. 平台登出、修改密码后Cookie会自动失效
# 3. Fantia仅支持文件模式Cookie，浏览器提取模式无效
# 4. 建议每月重新导出一次，保证凭证有效性
#
# =====================================================

# 下面是示例格式（请替换为实际导出的内容）：
# .youtube.com	TRUE	/	TRUE	1735689600	LOGIN_INFO	xxxxxxxxxxxxxxxxxxxx
# .twitch.tv	TRUE	/	TRUE	1735689600	auth-token	xxxxxxxxxxxxxxxxxxxx
"""
    try:
        cookie_file.write_text(content, encoding="utf-8")
        add_log("[Cookie模板] 已生成 cookies.txt 模板文件", "success")
        return {"ok": True}
    except Exception as e:
        add_log(f"[Cookie模板] 生成失败: {e}", "error")
        return {"error": str(e)}


def read_urls_file():
    """读取urls.txt中的有效链接"""
    url_file = TOOL_DIR / "urls.txt"
    if not url_file.exists():
        return None, "未找到 urls.txt 文件，请先生成模板"
    
    urls = []
    try:
        with open(url_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    urls.append(line)
    except Exception as e:
        return None, f"读取 urls.txt 失败: {e}"
    
    if not urls:
        return None, "urls.txt 中没有有效链接"
    return urls, None


def batch_txt_download():
    """从urls.txt批量下载（混合平台）"""
    global download_running, batch_stats, download_proc
    with download_lock:
        if download_running:
            return {"error": "已有下载任务在运行"}
        download_running = True
    
    urls, err = read_urls_file()
    if err:
        with download_lock:
            download_running = False
        return {"error": err}
    
    for dep in ["yt-dlp", "ffmpeg", "ffprobe"]:
        if not (TOOL_DIR / f"{dep}{EXE_SUFFIX}").exists():
            with download_lock:
                download_running = False
            return {"error": f"缺少依赖: {dep}{EXE_SUFFIX}"}
    
    cancel_idle_timer()  # 开始批量下载，取消空闲退出
    batch_stats = {"ok": 0, "fail": 0, "total": len(urls), "current": 0}
    stopped = False
    
    def update_stats():
        for q in sse_clients[:]:
            try:
                q.put({"type": "stats", "data": batch_stats})
            except Exception:
                pass
    
    def run():
        try:
            add_log(f"[批量下载] 开始，共 {len(urls)} 个链接", "info")
            update_stats()
            
            for i, url in enumerate(urls, 1):
                if not download_running:
                    add_log("[批量下载] 已停止", "warn")
                    break
                
                # 清理URL
                url = clean_url(url)
                if not url:
                    continue
                
                batch_stats["current"] = i
                update_stats()
                
                # 自动识别平台（不覆盖用户设置）
                detected = detect_platform(url)
                effective_platform = detected if detected else config["PLATFORM"]
                if detected:
                    add_log(f"[{i}/{len(urls)}] [自动识别] {detected}", "info")
                else:
                    add_log(f"[{i}/{len(urls)}] 未识别平台，使用: {config['PLATFORM']}", "warn")
                
                add_log(f"[{i}/{len(urls)}] 下载: {url}", "info")
                update_progress(0, f"批量下载 {i}/{len(urls)}")
                
                cmd = build_ytdlp_cmd(url, platform_override=effective_platform)
                env = os.environ.copy()
                env["PYTHONUTF8"] = "1"
                env["PYTHONIOENCODING"] = "utf-8"  # 强制子进程stdout/stderr使用UTF-8
                env["PYTHONUNBUFFERED"] = "1"  # 禁用Python缓冲，实时输出进度
                env["NO_COLOR"] = "1"
                
                proc = None
                try:
                    import queue as _queue
                    # Windows下隐藏子进程控制台窗口
                    _startupinfo = None
                    _creationflags = 0
                    if os.name == 'nt':
                        _startupinfo = subprocess.STARTUPINFO()
                        _startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                        _startupinfo.wShowWindow = subprocess.SW_HIDE
                        _creationflags = subprocess.CREATE_NO_WINDOW
                    proc = subprocess.Popen(
                        cmd, cwd=TOOL_DIR, env=env,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        bufsize=0,  # 无缓冲，实时读取输出
                        startupinfo=_startupinfo,
                        creationflags=_creationflags
                    )
                    # 把进程赋值给全局变量，让停止按钮可以终止
                    with download_lock:
                        download_proc = proc
                    
                    # chunk读取+线程+队列
                    _line_q = _queue.Queue()
                    _read_done = threading.Event()
                    
                    def _batch_reader():
                        import os as _os
                        _fd = proc.stdout.fileno()
                        _buf = bytearray()
                        while True:
                            try:
                                _chunk = _os.read(_fd, 4096)
                            except OSError:
                                _chunk = None
                            except Exception:
                                _chunk = None
                            if not _chunk:
                                if _buf:
                                    try:
                                        _line_q.put(safe_decode(_buf))
                                    except Exception:
                                        pass
                                break
                            for b in _chunk:
                                if b in (0x0d, 0x0a):
                                    if _buf:
                                        try:
                                            _line_q.put(safe_decode(_buf))
                                        except Exception:
                                            pass
                                        _buf = bytearray()
                                else:
                                    _buf.append(b)
                        _read_done.set()
                    
                    threading.Thread(target=_batch_reader, daemon=True).start()
                    
                    success = True
                    while not _read_done.is_set() or not _line_q.empty():
                        if not download_running:
                            # 停止由stop_download统一处理（_kill_proc_tree），这里只break
                            break
                        try:
                            line = _line_q.get(timeout=0.5)
                        except _queue.Empty:
                            continue
                        
                        line = line.strip()
                        if not line:
                            continue
                        
                        is_error = "ERROR" in line
                        is_warning = "WARNING" in line
                        has_pct = bool(re.search(r'\d+(?:\.\d+)?%', line))
                        
                        if is_error:
                            success = False
                            add_log(f"  {line}", "error")
                        elif is_warning:
                            add_log(f"  {line}", "warn")
                        elif has_pct:
                            pass
                        
                        m = re.search(r'(\d+(?:\.\d+)?)%', line)
                        if m:
                            pct = float(m.group(1))
                            overall = ((i - 1) + pct / 100) / len(urls)
                            update_progress(overall, f"批量下载 {i}/{len(urls)}")
                    
                    # 清理当前进程
                    try:
                        if proc.poll() is None:
                            proc.wait(timeout=5)
                    except Exception:
                        pass
                    try:
                        proc.stdout.close()
                    except Exception:
                        pass
                    
                    with download_lock:
                        download_proc = None
                    
                    if not download_running:
                        stopped = True
                        batch_stats["fail"] += 1
                        add_log(f"[{i}/{len(urls)}] ✗ 已取消", "warn")
                        update_stats()
                        break
                    
                    rc = proc.returncode if proc.returncode is not None else -1
                    if rc == 0 and success:
                        batch_stats["ok"] += 1
                        add_log(f"[{i}/{len(urls)}] ✓ 完成", "success")
                        add_history(url, "", effective_platform, "success")
                    else:
                        batch_stats["fail"] += 1
                        add_log(f"[{i}/{len(urls)}] ✗ 失败 (退出码 {rc})", "error")
                        add_history(url, "", effective_platform, "fail")
                    update_stats()
                    
                except Exception as e:
                    batch_stats["fail"] += 1
                    add_log(f"[{i}/{len(urls)}] ✗ 异常: {e}", "error")
                    try:
                        add_history(url, "", effective_platform, "fail")
                    except Exception:
                        pass
                    update_stats()
                    # 异常时确保杀进程
                    try:
                        if proc is not None:
                            _kill_proc_tree(proc)
                    except Exception:
                        pass
                    with download_lock:
                        download_proc = None
            
            if stopped:
                add_log("[批量下载] 已停止", "warn")
                update_progress(0, "已停止")
            else:
                add_log(f"[批量下载] 完成: 成功{batch_stats['ok']} 失败{batch_stats['fail']} 总计{batch_stats['total']}", "success")
                if batch_stats['ok'] == batch_stats['total']:
                    update_progress(1, "批量下载完成")
                else:
                    update_progress(1, f"批量下载完成 (成功{batch_stats['ok']}/{batch_stats['total']})")
            update_stats()
            
        except Exception as e:
            add_log(f"[批量下载] 异常: {e}", "error")
        finally:
            with download_lock:
                download_running = False
                download_proc = None
            # 批量下载结束，如果浏览器已关闭则启动空闲退出
            if not sse_clients:
                start_idle_timer()
    
    save_config()
    threading.Thread(target=run, daemon=True).start()
    return {"ok": True, "total": len(urls)}


# ========== 自动更新功能 ==========

def version_num_to_str(num):
    """将整数版本号转为字符串，如 10904 -> 'v1.9.4'"""
    major = num // 10000
    minor = (num // 100) % 100
    patch = num % 100
    return f"v{major}.{minor}.{patch}"


def parse_version_tag(tag):
    """从Git标签解析版本号整数，如 'v1.9.4' -> 10904。失败返回0"""
    if not tag:
        return 0
    m = re.match(r'v?(\d+)\.(\d+)\.(\d+)', tag.strip())
    if not m:
        return 0
    return int(m.group(1)) * 10000 + int(m.group(2)) * 100 + int(m.group(3))


def _fetch_url(url, timeout=10):
    """HTTP GET 获取文本内容，带超时和错误处理"""
    req = urllib_request.Request(url, headers={
        "User-Agent": "VideoDownloader-UpdateChecker/1.0",
        "Accept": "application/json, text/plain, */*",
    })
    try:
        with urllib_request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return None


def _download_file(url, dest_path, progress_callback=None):
    """下载文件到指定路径，支持进度回调 callback(downloaded_bytes, total_bytes, speed_bps)"""
    req = urllib_request.Request(url, headers={
        "User-Agent": "VideoDownloader-Updater/1.0",
    })
    try:
        with urllib_request.urlopen(req, timeout=30) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            chunk_size = 8192
            start_time = time.time()
            last_report = 0
            with open(dest_path, "wb") as f:
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    now = time.time()
                    elapsed = now - start_time
                    speed = downloaded / elapsed if elapsed > 0 else 0
                    if progress_callback and (now - last_report >= 0.2 or downloaded == total):
                        progress_callback(downloaded, total, speed)
                        last_report = now
            return True, downloaded
    except Exception as e:
        return False, str(e)


def check_update():
    """检查更新。返回dict: {has_update, latest_version, release_notes, download_url, error}"""
    global UPDATE_STATUS
    UPDATE_STATUS["checking"] = True
    UPDATE_STATUS["error"] = None

    # 尝试多个源
    release_info = None
    errors = []

    # Gitee API
    gitee_url = f"https://gitee.com/api/v5/repos/{GITEE_OWNER}/{GITEE_REPO}/releases/latest"
    try:
        text = _fetch_url(gitee_url, timeout=8)
        if text:
            data = json.loads(text)
            tag = data.get("tag_name", "")
            ver_num = parse_version_tag(tag)
            if ver_num > VERSION_NUM:
                # 查找exe下载链接
                download_url = None
                assets = data.get("assets", [])
                for asset in assets:
                    name = asset.get("name", "").lower()
                    if name.endswith(".exe") and "gui" in name.lower():
                        download_url = asset.get("browser_download_url") or asset.get("url")
                        break
                if not download_url and assets:
                    # 回退到第一个exe资产
                    for asset in assets:
                        if asset.get("name", "").lower().endswith(".exe"):
                            download_url = asset.get("browser_download_url") or asset.get("url")
                            break
                release_info = {
                    "tag": tag,
                    "ver_num": ver_num,
                    "notes": data.get("body", ""),
                    "download_url": download_url,
                }
    except Exception as e:
        errors.append(f"Gitee: {e}")

    # GitHub API (备用)
    if not release_info:
        github_url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
        try:
            text = _fetch_url(github_url, timeout=8)
            if text:
                data = json.loads(text)
                tag = data.get("tag_name", "")
                ver_num = parse_version_tag(tag)
                if ver_num > VERSION_NUM:
                    download_url = None
                    assets = data.get("assets", [])
                    for asset in assets:
                        name = asset.get("name", "").lower()
                        if name.endswith(".exe") and "gui" in name.lower():
                            download_url = asset.get("browser_download_url")
                            break
                    if not download_url and assets:
                        for asset in assets:
                            if asset.get("name", "").lower().endswith(".exe"):
                                download_url = asset.get("browser_download_url")
                                break
                    release_info = {
                        "tag": tag,
                        "ver_num": ver_num,
                        "notes": data.get("body", ""),
                        "download_url": download_url,
                    }
        except Exception as e:
            errors.append(f"GitHub: {e}")

    UPDATE_STATUS["checking"] = False

    if release_info:
        UPDATE_STATUS["update_available"] = True
        UPDATE_STATUS["latest_version"] = release_info["tag"]
        UPDATE_STATUS["latest_version_num"] = release_info["ver_num"]
        UPDATE_STATUS["release_notes"] = release_info["notes"]
        UPDATE_STATUS["download_url"] = release_info["download_url"]
        return {
            "has_update": True,
            "current_version": VERSION,
            "latest_version": release_info["tag"],
            "release_notes": release_info["notes"],
            "download_url": release_info["download_url"],
        }
    else:
        UPDATE_STATUS["update_available"] = False
        return {
            "has_update": False,
            "current_version": VERSION,
            "latest_version": version_num_to_str(VERSION_NUM),
        }


def do_update(download_url=None):
    """执行更新：下载新版本exe，替换当前文件，准备重启"""
    global UPDATE_STATUS, exit_flag

    if UPDATE_STATUS["downloading"]:
        return {"error": "已在下载更新中"}

    url = download_url or UPDATE_STATUS.get("download_url")
    if not url:
        return {"error": "没有可用的下载链接，请先检查更新"}

    UPDATE_STATUS["downloading"] = True
    UPDATE_STATUS["download_progress"] = 0
    UPDATE_STATUS["download_speed"] = ""
    UPDATE_STATUS["error"] = None
    UPDATE_STATUS["update_done"] = False

    def progress_cb(downloaded, total, speed):
        percent = (downloaded / total * 100) if total > 0 else 0
        UPDATE_STATUS["download_progress"] = percent
        UPDATE_STATUS["downloaded_size"] = downloaded
        UPDATE_STATUS["total_size"] = total
        if speed > 0:
            if speed > 1024 * 1024:
                UPDATE_STATUS["download_speed"] = f"{speed / (1024*1024):.1f} MB/s"
            elif speed > 1024:
                UPDATE_STATUS["download_speed"] = f"{speed / 1024:.0f} KB/s"
            else:
                UPDATE_STATUS["download_speed"] = f"{speed:.0f} B/s"
        # 通过SSE推送进度
        for q in sse_clients[:]:
            try:
                q.put({"type": "update_progress", "data": {
                    "percent": percent,
                    "speed": UPDATE_STATUS["download_speed"],
                    "downloaded": downloaded,
                    "total": total,
                }})
            except Exception:
                pass

    def download_and_replace():
        nonlocal url
        try:
            # 下载到临时文件
            tmp_dir = tempfile.gettempdir()
            new_exe_name = EXE_NAME.replace("v1.9.3", UPDATE_STATUS.get("latest_version", "new").lstrip("v"))
            tmp_path = os.path.join(tmp_dir, f"_update_{new_exe_name}")
            add_log(f"[更新] 开始下载新版本 {UPDATE_STATUS.get('latest_version', '')}...", "info")

            ok, result = _download_file(url, tmp_path, progress_callback=progress_cb)
            if not ok:
                # Gitee下载链接可能需要重定向处理，尝试用代理/直接URL
                add_log(f"[更新] 下载失败: {result}", "error")
                UPDATE_STATUS["error"] = f"下载失败: {result}"
                UPDATE_STATUS["downloading"] = False
                return

            UPDATE_STATUS["download_progress"] = 100
            add_log("[更新] 下载完成，准备替换...", "success")

            # 创建替换脚本（批处理），在程序退出后替换文件并重启
            current_exe = sys.executable if getattr(sys, 'frozen', False) else None
            if current_exe and os.name == "nt":
                # PyInstaller打包环境：创建bat脚本替换exe并重启
                replace_bat = os.path.join(tmp_dir, "_update_replace.bat")
                current_dir = os.path.dirname(current_exe)
                target_path = os.path.join(current_dir, os.path.basename(current_exe))
                # 新版本文件名使用最新版本号
                new_target_name = EXE_NAME  # 暂时保留原名，用户可手动改名
                bat_content = f"""@echo off
chcp 65001 >nul
echo 正在更新...
timeout /t 2 /nobreak >nul
:wait
tasklist /fi "imagename eq {os.path.basename(current_exe)}" 2>nul | find /i "{os.path.basename(current_exe)}" >nul
if not errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto wait
)
copy /y "{tmp_path}" "{target_path}" >nul
if errorlevel 1 (
    echo 更新失败！
    pause
    exit /b 1
)
echo 更新完成！正在启动新版本...
start "" "{target_path}"
del "%~f0"
"""
                with open(replace_bat, "w", encoding="gbk") as f:
                    f.write(bat_content)

                UPDATE_STATUS["update_done"] = True
                UPDATE_STATUS["downloading"] = False
                add_log("[更新] 更新已准备就绪，程序将在关闭后自动替换并重启", "success")

                # 通过SSE通知前端
                for q in sse_clients[:]:
                    try:
                        q.put({"type": "update_progress", "data": {
                            "percent": 100,
                            "done": True,
                            "message": "更新下载完成！程序将自动重启以完成更新。",
                        }})
                    except Exception:
                        pass

                # 延迟退出并启动替换脚本
                def do_exit_and_update():
                    time.sleep(1.5)
                    # 通知前端
                    for q in sse_clients[:]:
                        try:
                            q.put({"type": "exit"})
                        except Exception:
                            pass
                    time.sleep(0.5)
                    _kill_proc_tree(download_proc)
                    try:
                        subprocess.Popen(
                            ["cmd.exe", "/c", replace_bat],
                            cwd=tempfile.gettempdir(),
                            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
                        )
                    except Exception:
                        pass
                    os._exit(0)

                threading.Thread(target=do_exit_and_update, daemon=True).start()
            else:
                # 非打包环境（开发模式）：提示用户手动替换
                UPDATE_STATUS["update_done"] = True
                UPDATE_STATUS["downloading"] = False
                add_log(f"[更新] 新版本已下载到: {tmp_path}", "success")
                add_log("[更新] 开发模式，请手动替换文件后重启", "warn")
                for q in sse_clients[:]:
                    try:
                        q.put({"type": "update_progress", "data": {
                            "percent": 100,
                            "done": True,
                            "message": f"新版本已下载到: {tmp_path}，请手动替换后重启。",
                        }})
                    except Exception:
                        pass

        except Exception as e:
            add_log(f"[更新] 更新异常: {e}", "error")
            UPDATE_STATUS["error"] = str(e)
            UPDATE_STATUS["downloading"] = False
            for q in sse_clients[:]:
                try:
                    q.put({"type": "update_progress", "data": {
                        "percent": UPDATE_STATUS["download_progress"],
                        "error": str(e),
                    }})
                except Exception:
                    pass

    threading.Thread(target=download_and_replace, daemon=True).start()
    return {"ok": True, "message": "开始下载更新..."}


def start_check_update_thread(silent=True):
    """在后台线程中检查更新，silent=True时仅在有更新时推送SSE通知"""
    def worker():
        result = check_update()
        if result.get("has_update"):
            add_log(f"[更新] 发现新版本 {result['latest_version']}！", "warn")
            # 通过SSE推送更新通知
            for q in sse_clients[:]:
                try:
                    q.put({"type": "update_available", "data": result})
                except Exception:
                    pass
        elif not silent:
            add_log("[更新] 当前已是最新版本", "info")

    threading.Thread(target=worker, daemon=True).start()


def handle_tool_action(action):
    """统一处理工具箱操作"""
    if action == "update-ytdlp":
        update_ytdlp()
        return {"message": "正在更新 yt-dlp，请查看日志..."}
    elif action == "clean-temp":
        result = clean_temp()
        return {"message": f"清理完成，删除 {result.get('count', 0)} 个临时文件"}
    elif action == "gen-template":
        result = gen_url_template()
        if result.get("existed"):
            return {"message": "urls.txt 已存在"}
        return {"message": "urls.txt 模板已生成"}
    elif action == "gen-cookie-template":
        result = gen_cookie_template()
        if result.get("existed"):
            return {"message": "cookies.txt 已存在"}
        if result.get("error"):
            return {"error": result["error"]}
        return {"message": "cookies.txt 模板已生成"}
    elif action == "batch-txt":
        return batch_txt_download()
    elif action == "open-downloads":
        return open_folder(str(TOOL_DIR))
    elif action == "open-logs":
        return open_folder(str(LOG_DIR))
    return {"error": f"未知操作: {action}"}


# ========== HTML 页面 ==========
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
      <div class="tool-card" onclick="toolAction('batch-txt')">
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
  fillSelect('s_audiose', [['m4a','m4a(原生)'],['mp3','MP3'],['flac','FLAC'],['wav','WAV']]);
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
  const r = await fetch(path, Object.assign({headers:{'Content-Type':'application/json'}}, opts));
  return r.json();
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
  $('s_audiose').selectedIndex = s.AUDIO_SEP_MODE - 1;
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
    AUDIO_SEP_MODE: $('s_audiose').selectedIndex+1,
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
  await api('/api/save-config', {method:'POST', body:JSON.stringify(cfg)});
  alert('设置已保存！');
}

async function saveSettingsNoAlert() {
  const cfg = {
    PLATFORM: currentPlatform,
    RESOLUTION: $('s_resolution').value,
    CODEC: $('s_codec').value,
    AUDIO_QUALITY: $('s_audio').value,
    OUTPUT_FORMAT: $('s_format').value,
    MERGE_MODE: isOn('sw_merge')?1:0,
    AUDIO_SEP_MODE: $('s_audiose').selectedIndex+1,
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
  await api('/api/save-config', {method:'POST', body:JSON.stringify(cfg)});
}

async function resetSettings() {
  if(!confirm('确定恢复默认设置？')) return;
  await api('/api/reset-config');
  location.reload();
}

async function loadDeps() {
  const d = await api('/api/deps');
  const names = {yt_dlp:'yt-dlp',ffmpeg:'ffmpeg',ffprobe:'ffprobe',fantiadl:'fantiadl(可选)'};
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
  await saveSettingsNoAlert();
  const r = await api('/api/start', {method:'POST', body:JSON.stringify({url})});
  if(r.error) { alert(r.error); return; }
  $('btnStart').disabled = true;
  $('btnStop').disabled = false;
  // 重置统计
  $('statOk').textContent = '0';
  $('statFail').textContent = '0';
  $('statTotal').textContent = '0';
}

async function startBatch() {
  if(!confirm('将从 urls.txt 文件读取链接进行批量下载，是否继续？')) return;
  await saveSettingsNoAlert();
  const r = await api('/api/batch-txt', {method:'POST'});
  if(r.error) { alert(r.error); return; }
  $('btnStart').disabled = true;
  $('btnStop').disabled = false;
  // 重置统计
  $('statOk').textContent = '0';
  $('statFail').textContent = '0';
  $('statTotal').textContent = r.total || '0';
}

async function stopDl() {
  await api('/api/stop', {method:'POST'});
  $('btnStart').disabled = false;
  $('btnStop').disabled = true;
}

async function saveSettingsNoAlert() {
  const cfg = collectCfg();
  await api('/api/save-config', {method:'POST', body:JSON.stringify(cfg)});
}

function collectCfg() {
  return {
    PLATFORM: currentPlatform,
    RESOLUTION: $('s_resolution').value,
    CODEC: $('s_codec').value,
    AUDIO_QUALITY: $('s_audio').value,
    OUTPUT_FORMAT: $('s_format').value,
    MERGE_MODE: isOn('sw_merge')?1:0,
    AUDIO_SEP_MODE: $('s_audiose').selectedIndex+1,
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
  await api('/api/wav2mp3', {method:'POST', body:JSON.stringify({
    dir, bitrate:parseInt($('wav_bitrate').value),
    recursive:isOn('sw_recursive'), del_src:isOn('sw_delwav')
  })});
}

function addLog(container, entry) {
  const box = $(container);
  const line = document.createElement('div');
  line.className = 'log-line log-' + entry.level;
  line.innerHTML = `<span class="log-time">[${entry.time}]</span> ${entry.msg}`;
  box.appendChild(line);
  box.scrollTop = box.scrollHeight;
  while(box.children.length > 300) box.removeChild(box.firstChild);
}

function connectSSE() {
  evtSource = new EventSource('/api/events');
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
      if(d.percent >= 1 || d.status.includes('失败') || d.status.includes('完成') || d.status.includes('已停止') || d.status.includes('已取消')) {
        fill.classList.remove('live');
        $('btnStart').disabled = false;
        $('btnStop').disabled = true;
      }
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
      evt.data.forEach(e => addLog('logBox', e));
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
    setTimeout(connectSSE, 3000);
  };
}

async function exitApp() {
  if(!confirm('确定要彻底关闭工具吗？\\n正在进行的下载将被终止。')) return;
  try {
    await fetch('/api/exit', {method:'POST'});
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
  const r = await fetch('/api/presets');
  const data = await r.json();
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
  const r = await fetch('/api/history');
  const data = await r.json();
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
    await api('/api/do-update', {method:'POST', body:JSON.stringify({download_url: updateInfo.download_url})});
  } catch(e) {
    $('updateProgText').textContent = '更新请求失败: ' + e.message;
    $('updateProgText').style.color = 'var(--red)';
    $('btnDoUpdate').disabled = false;
    $('btnDoUpdate').textContent = '重试';
  }
}

// 页面加载3秒后主动检查更新（后端也会静默检查，双保险）
setTimeout(() => {
  fetch('/api/check-update').catch(()=>{});
}, 3000);
</script>
</body>
</html>"""


# ========== HTTP 服务器 ==========
class SSEHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode("utf-8"))
        elif path == "/api/config":
            self._json({"version": VERSION, "config": config})
        elif path == "/api/deps":
            self._json(check_deps())
        elif path == "/api/presets":
            self._json({"presets": list(load_presets().keys())})
        elif path == "/api/history":
            self._json({"history": load_history()[:100]})
        elif path == "/api/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            q = queue.Queue()
            sse_clients.append(q)
            cancel_idle_timer()  # 有浏览器连接，取消空闲退出
            q.put({"type": "ready", "data": log_history[-50:]})
            try:
                while True:
                    try:
                        evt = q.get(timeout=15)
                        data = json.dumps(evt, ensure_ascii=False)
                        self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
                        self.wfile.flush()
                    except queue.Empty:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
            except Exception:
                pass
            finally:
                if q in sse_clients:
                    sse_clients.remove(q)
                # 最后一个浏览器断开且没有下载任务时，启动空闲退出计时器
                if not sse_clients and not download_running:
                    start_idle_timer()
        elif path == "/api/check-update":
            # 手动检查更新（异步执行，先返回状态）
            if not UPDATE_STATUS["checking"]:
                def check_and_notify():
                    result = check_update()
                    if result.get("has_update"):
                        add_log(f"[更新] 发现新版本 {result['latest_version']}！", "warn")
                        for q in sse_clients[:]:
                            try:
                                q.put({"type": "update_available", "data": result})
                            except Exception:
                                pass
                threading.Thread(target=check_and_notify, daemon=True).start()
            self._json({"checking": True})
        elif path == "/api/update-status":
            self._json(UPDATE_STATUS)
        elif path == "/api/stop":
            # GET也支持停止，方便调试
            self._json(stop_download())
        else:
            self.send_error(404)

    def do_POST(self):
        global config
        parsed = urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            data = {}

        if path == "/api/start":
            result = start_download(data.get("url", ""))
            self._json(result)
        elif path == "/api/batch-txt":
            self._json(batch_txt_download())
        elif path == "/api/stop":
            self._json(stop_download())
        elif path == "/api/save-preset":
            self._json(save_preset(data.get("name", "")))
        elif path == "/api/load-preset":
            self._json(load_preset(data.get("name", "")))
        elif path == "/api/delete-preset":
            self._json(delete_preset(data.get("name", "")))
        elif path == "/api/clear-history":
            self._json(clear_history())
        elif path == "/api/save-config":
            for k, v in data.items():
                if k in DEFAULT_CONFIG:
                    config[k] = v
            save_config()
            self._json({"ok": True})
        elif path == "/api/reset-config":
            config = dict(DEFAULT_CONFIG)
            save_config()
            self._json({"ok": True})
        elif path == "/api/tool":
            action = data.get("action", "")
            self._json(handle_tool_action(action))
        elif path == "/api/browse-folder":
            self._json(browse_folder())
        elif path == "/api/update-ytdlp":
            self._json(update_ytdlp())
        elif path == "/api/clean-temp":
            self._json(clean_temp())
        elif path == "/api/gen-template":
            self._json(gen_url_template())
        elif path == "/api/wav2mp3":
            self._json(wav_to_mp3(
                data.get("dir", ""),
                data.get("recursive", False),
                int(data.get("bitrate", 320)),
                data.get("del_src", False)
            ))
        elif path == "/api/do-update":
            download_url = data.get("download_url", None)
            self._json(do_update(download_url))
        elif path == "/api/exit":
            self._json({"ok": True})
            # 延迟退出，确保响应已发送
            def do_exit():
                global exit_flag
                time.sleep(0.5)
                # 终止下载子进程
                _kill_proc_tree(download_proc)
                # 关闭SSE客户端
                for q in sse_clients[:]:
                    try:
                        q.put({"type": "exit"})
                    except Exception:
                        pass
                exit_flag = True
            threading.Thread(target=do_exit, daemon=True).start()
        else:
            self.send_error(404)

    def _json(self, obj):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(obj, ensure_ascii=False).encode("utf-8"))


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def find_free_port():
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    print("正在启动 WebUI 服务器...", flush=True)
    load_config()
    deps = check_deps()
    for dep, ok in deps.items():
        if dep in ["yt-dlp", "ffmpeg", "ffprobe"] and not ok:
            add_log(f"[警告] 缺少依赖: {dep}{EXE_SUFFIX}", "warn")
    add_log(f"[就绪] {VERSION} 已启动", "success")
    if not all(deps.get(d, False) for d in ["yt-dlp", "ffmpeg", "ffprobe"]):
        add_log("[提示] yt-dlp: github.com/yt-dlp/yt-dlp/releases", "warn")
        add_log("[提示] ffmpeg: www.gyan.dev/ffmpeg/builds/ (full_build)", "warn")

    port = find_free_port()
    global server_instance
    server = ThreadedHTTPServer(("127.0.0.1", port), SSEHandler)
    server_instance = server
    url = f"http://127.0.0.1:{port}"
    print("=" * 50, flush=True)
    print(f"  WebUI 已启动!", flush=True)
    print(f"  请在浏览器中访问: {url}", flush=True)
    print("=" * 50, flush=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    time.sleep(0.8)
    try:
        webbrowser.open(url)
    except Exception:
        pass

    # 启动后延迟3秒静默检查更新（有更新才通知前端）
    def delayed_check():
        time.sleep(3)
        start_check_update_thread(silent=True)
    threading.Thread(target=delayed_check, daemon=True).start()

    try:
        while not exit_flag:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    print("\n正在关闭服务器...", flush=True)
    # 终止下载进程
    _kill_proc_tree(download_proc)
    server.shutdown()
    print("已退出。", flush=True)
    os._exit(0)


if __name__ == "__main__":
    main()
