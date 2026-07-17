# -*- coding: utf-8 -*-
"""
四平台极致音画下载工具 v1.9.5 WebUI版
支持 YouTube / Twitch / Niconico / Fantia
使用内置HTTP服务器 + 浏览器界面，无需额外GUI库
自动更新通过 GitHub Releases 检查和分发
"""
import os
import sys
import threading
import time
import webbrowser
import secrets
from pathlib import Path
from datetime import datetime
from video_downloader.app_state import AppState
from video_downloader.config_validation import validate_config
from video_downloader.download_executor import DownloadExecutor
from video_downloader.download_manager import DownloadManager
from video_downloader.storage import StorageService
from video_downloader.tool_service import ToolService
from video_downloader.updater import UpdaterService
from video_downloader.web_page import render_html_page
from video_downloader.http_service import HttpHandlerDependencies, HttpService, create_handler
from video_downloader.constants import (
    AUDIO_OPTIONS,
    AUDIO_SEP_LABELS,
    AUDIO_SEP_OPTIONS,
    BROWSER_OPTIONS,
    CODEC_LABELS,
    CODEC_OPTIONS,
    DEFAULT_CONFIG,
    FORMAT_OPTIONS,
    HWACCEL_LABELS,
    HWACCEL_OPTIONS,
    IDLE_TIMEOUT,
    MP3_BITRATE_OPTIONS,
    PLATFORM_INFO,
    PROXY_TYPE_OPTIONS,
    RESOLUTION_LABELS,
    RESOLUTION_OPTIONS,
    VERSION,
)
from video_downloader.ytdlp_command import build_ytdlp_cmd as _build_ytdlp_cmd

SESSION_TOKEN = secrets.token_urlsafe(32)

# 路径兼容 PyInstaller
if getattr(sys, 'frozen', False):
    TOOL_DIR = Path(sys.executable).parent
else:
    TOOL_DIR = Path(__file__).parent

EXE_SUFFIX = ".exe" if os.name == "nt" else ""
LOG_DIR = TOOL_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

# 全局状态
app_state = AppState()
download_manager = DownloadManager()
config = app_state.config
server_instance = None
exit_event = threading.Event()
idle_timer = None  # 空闲自动退出计时器
sse_clients = app_state.sse_clients
log_history = app_state.log_history
download_thread_context = app_state.download_thread_context

def cancel_idle_timer():
    """取消空闲自动退出计时器"""
    global idle_timer
    if idle_timer is not None:
        idle_timer.cancel()
        idle_timer = None


def start_idle_timer():
    """启动空闲自动退出计时器（无浏览器连接且无下载时）"""
    global idle_timer
    cancel_idle_timer()
    if download_manager.snapshot()["running"] or app_state.has_sse_clients():
        return
    def do_idle_exit():
        if not download_manager.snapshot()["running"] and not app_state.has_sse_clients():
            add_log(f"[系统] 浏览器已关闭，{IDLE_TIMEOUT}秒无活动，自动退出", "warn")
            request_exit()
    idle_timer = threading.Timer(IDLE_TIMEOUT, do_idle_exit)
    idle_timer.daemon = True
    idle_timer.start()
progress_data = app_state.progress_data
batch_stats = app_state.batch_stats


def add_log(msg, level="info"):
    ts = datetime.now().strftime("%H:%M:%S")
    entry = {"time": ts, "msg": msg, "level": level}
    log_history.append(entry)
    if len(log_history) > 500:
        log_history.pop(0)
    app_state.publish({"type": "log", "data": entry})


def emit_event(event_type, data=None):
    event = {"type": event_type}
    if data is not None:
        event["data"] = data
    app_state.publish(event)


storage = StorageService(
    tool_dir=TOOL_DIR,
    app_state=app_state,
    validate_config=validate_config,
    log=add_log,
    emit_event=emit_event,
)
load_config = storage.load_config
save_config = storage.save_config
load_presets = storage.load_presets
save_preset = storage.save_preset
load_preset = storage.load_preset
delete_preset = storage.delete_preset
load_history = storage.load_history
add_history = storage.add_history
clear_history = storage.clear_history


def update_progress(percent, status=None, speed="", eta=""):
    global progress_data
    context_task_id = getattr(download_thread_context, "task_id", None)
    if context_task_id is not None and context_task_id != download_manager.snapshot()["generation"]:
        return
    progress_data["percent"] = percent
    if status:
        progress_data["status"] = status
    progress_data["speed"] = speed
    progress_data["eta"] = eta
    snapshot = dict(progress_data)
    app_state.publish({"type": "progress", "data": snapshot})


def broadcast_download_state():
    snapshot = download_manager.snapshot()
    data = {
        "running": snapshot["running"],
        "phase": snapshot["phase"],
        "generation": snapshot["generation"],
        "kind": snapshot["kind"],
    }
    app_state.publish({"type": "download_state", "data": data})


def build_ytdlp_cmd(url, is_live=False, platform_override=None, config_override=None):
    cookie_file = TOOL_DIR / "cookies.txt"
    return _build_ytdlp_cmd(
        url,
        config_override if config_override is not None else app_state.config_snapshot(),
        TOOL_DIR,
        EXE_SUFFIX,
        is_live=is_live,
        platform_override=platform_override,
        cookie_file=cookie_file if cookie_file.exists() else None,
    )


download_executor = DownloadExecutor(
    tool_dir=TOOL_DIR,
    exe_suffix=EXE_SUFFIX,
    app_state=app_state,
    download_manager=download_manager,
    build_command=build_ytdlp_cmd,
    log=add_log,
    update_progress=update_progress,
    broadcast_download_state=broadcast_download_state,
    add_history=add_history,
    cancel_idle_timer=cancel_idle_timer,
    start_idle_timer=start_idle_timer,
)


def start_download(url):
    return download_executor.start_download(url)


def _kill_proc_tree(p):
    return download_executor.kill_process_tree(p)


updater = UpdaterService(
    download_manager=download_manager,
    emit_event=emit_event,
    log=add_log,
    broadcast_download_state=broadcast_download_state,
    kill_process_tree=_kill_proc_tree,
)


def stop_download():
    return download_executor.stop_download()


tool_service = ToolService(
    tool_dir=TOOL_DIR,
    exe_suffix=EXE_SUFFIX,
    app_state=app_state,
    save_config=save_config,
    log=add_log,
)
check_deps = tool_service.check_deps
update_ytdlp = tool_service.update_ytdlp
clean_temp = tool_service.clean_temp
gen_url_template = tool_service.gen_url_template
wav_to_mp3 = tool_service.wav_to_mp3
browse_folder = tool_service.browse_folder
open_folder = tool_service.open_folder
gen_cookie_template = tool_service.gen_cookie_template
read_urls_file = tool_service.read_urls_file
handle_tool_action = tool_service.handle_tool_action


def batch_txt_download():
    """从urls.txt批量下载（混合平台）"""
    urls, err = read_urls_file()
    if err:
        return {"error": err}
    save_config()
    return download_executor.batch_download(urls)


def request_exit():
    ticket = download_manager.request_stop()
    _kill_proc_tree(ticket.process)
    app_state.publish({"type": "exit"})
    exit_event.set()


def create_http_service():
    dependencies = HttpHandlerDependencies(
        session_token=SESSION_TOKEN,
        version=VERSION,
        default_config=DEFAULT_CONFIG,
        app_state=app_state,
        download_manager=download_manager,
        updater=updater,
        render_html_page=render_html_page,
        check_deps=check_deps,
        load_presets=load_presets,
        load_history=load_history,
        cancel_idle_timer=cancel_idle_timer,
        start_idle_timer=start_idle_timer,
        start_download=start_download,
        batch_txt_download=batch_txt_download,
        stop_download=stop_download,
        save_preset=save_preset,
        load_preset=load_preset,
        delete_preset=delete_preset,
        clear_history=clear_history,
        validate_config=validate_config,
        save_config=save_config,
        handle_tool_action=handle_tool_action,
        browse_folder=browse_folder,
        update_ytdlp=update_ytdlp,
        clean_temp=clean_temp,
        gen_url_template=gen_url_template,
        wav_to_mp3=wav_to_mp3,
        request_exit=request_exit,
    )
    return HttpService(lambda: create_handler(dependencies), port=0)


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

    global server_instance
    server_instance = create_http_service()
    url = server_instance.start()
    start_idle_timer()
    print("=" * 50, flush=True)
    print(f"  WebUI 已启动!", flush=True)
    print(f"  请在浏览器中访问: {url}", flush=True)
    print("=" * 50, flush=True)
    time.sleep(0.8)
    try:
        webbrowser.open(url)
    except Exception:
        pass

    # 启动后延迟3秒静默检查更新（有更新才通知前端）
    def delayed_check():
        time.sleep(3)
        updater.start_check_thread(silent=True)
    threading.Thread(target=delayed_check, daemon=True).start()

    try:
        exit_event.wait()
    except KeyboardInterrupt:
        request_exit()
    print("\n正在关闭服务器...", flush=True)
    server_instance.stop()
    print("已退出。", flush=True)


if __name__ == "__main__":
    main()
