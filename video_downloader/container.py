"""
video_downloader.container - 依赖注入容器，或者说是聚合根
将手动布线封装为 AppContainer.wire()。按依赖顺序显式构造所有对象
"""

from __future__ import annotations

import secrets
import threading
import time
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .core.validation import validate_config
from .core.constants import DEFAULT_CONFIG, IDLE_TIMEOUT, VERSION
from .core.command import build_ytdlp_cmd as _build_ytdlp_cmd
from .state.app_state import AppState
from .services.download_executor import DownloadExecutor
from .services.download_manager import DownloadManager
from .services.storage import StorageService
from .services.tools import ToolService
from .services.updater import UpdaterService
from .web.handler import HttpHandlerDependencies, HttpService, create_handler
from .web.rendering import render_html_page, serve_static_file


@dataclass
class WiredApp:
    """AppContainer.wire() 返回的完全配置好的应用程序句柄。"""
    http_service: HttpService
    load_config: Callable[[], dict]
    check_deps: Callable[[], dict]
    request_exit: Callable[[], None]
    app_state: AppState
    updater: UpdaterService
    log: Callable[[str, str], None]
    cancel_idle_timer: Callable[[], None]
    start_idle_timer: Callable[[], None]
    main: Callable[[], None]


class AppContainer:
    """组合根。创建并连接所有应用程序组件。"""

    def __init__(self, tool_dir: Path, exe_suffix: str = ".exe"):
        self._tool_dir = tool_dir
        self._exe_suffix = exe_suffix
        self._log_dir = tool_dir / "logs"
        self._log_dir.mkdir(exist_ok=True)

    def wire(self) -> WiredApp:
        """构造完整的对象图并返回 WiredApp 句柄。"""
        tool_dir = self._tool_dir
        exe_suffix = self._exe_suffix
        session_token = secrets.token_urlsafe(32)

        # ---- 叶子对象 ----
        app_state = AppState()
        download_manager = DownloadManager()
        exit_event = threading.Event()

        # ---- 日志与事件 ----
        def add_log(msg: str, level: str = "info") -> None:
            ts = datetime.now().strftime("%H:%M:%S")
            entry = {"time": ts, "msg": msg, "level": level}
            app_state.log_history.append(entry)
            if len(app_state.log_history) > 500:
                app_state.log_history.pop(0)
            app_state.publish({"type": "log", "data": entry})

        def emit_event(event_type: str, data: Any = None) -> None:
            event: dict = {"type": event_type}
            if data is not None:
                event["data"] = data
            app_state.publish(event)

        # ---- 空闲计时器 ----
        idle_timer: threading.Timer | None = None

        def cancel_idle_timer() -> None:
            nonlocal idle_timer
            if idle_timer is not None:
                idle_timer.cancel()
                idle_timer = None

        def start_idle_timer() -> None:
            nonlocal idle_timer
            cancel_idle_timer()
            if download_manager.snapshot()["running"] or app_state.has_sse_clients():
                return

            def do_idle_exit() -> None:
                if not download_manager.snapshot()["running"] and not app_state.has_sse_clients():
                    add_log(f"[系统] 浏览器已关闭，{IDLE_TIMEOUT}秒无活动，自动退出", "warn")
                    request_exit()

            idle_timer = threading.Timer(IDLE_TIMEOUT, do_idle_exit)
            idle_timer.daemon = True
            idle_timer.start()

        # ---- 存储服务 ----
        storage = StorageService(
            tool_dir=tool_dir,
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
        find_cover = storage.find_cover

        # ---- 进度回调 ----
        def update_progress(percent: float, status: str | None = None,
                            speed: str = "", eta: str = "") -> None:
            dc = app_state.download_thread_context
            context_task_id = getattr(dc, "task_id", None)
            if context_task_id is not None and context_task_id != download_manager.snapshot()["generation"]:
                return
            app_state.progress_data["percent"] = percent
            if status:
                app_state.progress_data["status"] = status
            app_state.progress_data["speed"] = speed
            app_state.progress_data["eta"] = eta
            app_state.publish({"type": "progress", "data": dict(app_state.progress_data)})

        def broadcast_download_state() -> None:
            snapshot = download_manager.snapshot()
            app_state.publish({"type": "download_state", "data": {
                "running": snapshot["running"],
                "phase": snapshot["phase"],
                "generation": snapshot["generation"],
                "kind": snapshot["kind"],
            }})

        # ---- yt-dlp 命令构建 ----
        def build_command(url: str, *, is_live: bool = False,
                          platform_override: str | None = None,
                          config_override: dict | None = None,
                          bili_parts: str | None = None) -> list[str]:
            cookie_file = tool_dir / "cookies.txt"
            return _build_ytdlp_cmd(
                url,
                config_override if config_override is not None else app_state.config_snapshot(),
                tool_dir,
                exe_suffix,
                is_live=is_live,
                platform_override=platform_override,
                cookie_file=cookie_file if cookie_file.exists() else None,
                bili_parts=bili_parts,
            )

        # ---- 下载执行器 ----
        download_executor = DownloadExecutor(
            tool_dir=tool_dir,
            exe_suffix=exe_suffix,
            app_state=app_state,
            download_manager=download_manager,
            build_command=build_command,
            log=add_log,
            update_progress=update_progress,
            broadcast_download_state=broadcast_download_state,
            add_history=add_history,
            cancel_idle_timer=cancel_idle_timer,
            start_idle_timer=start_idle_timer,
            emit_event=emit_event,
        )

        def start_download(url: str, bili_parts: str | None = None, tc_password: str | None = None) -> dict:
            return download_executor.start_download(url, bili_parts=bili_parts, tc_password=tc_password)

        def submit_password(url: str, password: str) -> dict:
            return download_executor.submit_password(url, password)

        def stop_download() -> dict:
            return download_executor.stop_download()

        def fetch_bili_playlist(url: str) -> dict:
            return download_executor.fetch_bili_playlist(url)

        def _kill_proc_tree(p: Any) -> None:
            download_executor.kill_process_tree(p)

        # ---- 更新器 ----
        updater = UpdaterService(
            download_manager=download_manager,
            emit_event=emit_event,
            log=add_log,
            broadcast_download_state=broadcast_download_state,
            kill_process_tree=_kill_proc_tree,
        )

        # ---- 工具服务 ----
        tool_service = ToolService(
            tool_dir=tool_dir,
            exe_suffix=exe_suffix,
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
        handle_tool_action = tool_service.handle_tool_action
        read_urls_file = tool_service.read_urls_file

        def batch_txt_download(bili_parts_map: dict | None = None) -> dict:
            """从 urls.txt 批量下载（混合平台）。"""
            urls, err = read_urls_file()
            if err:
                return {"error": err}
            save_config()
            return download_executor.batch_download(urls, bili_parts_map=bili_parts_map)

        def start_urls_download(urls: list) -> dict:
            """从输入框的多行文本批量下载（每行一个链接）。"""
            save_config()
            return download_executor.batch_download(urls)

        def request_exit() -> None:
            ticket = download_manager.request_stop()
            _kill_proc_tree(ticket.process)
            app_state.publish({"type": "exit"})
            exit_event.set()

        # ---- HTTP 服务 ----
        def create_http_service() -> HttpService:
            deps = HttpHandlerDependencies(
                session_token=session_token,
                version=VERSION,
                default_config=DEFAULT_CONFIG,
                app_state=app_state,
                download_manager=download_manager,
                updater=updater,
                render_html_page=render_html_page,
                serve_static_file=serve_static_file,
                check_deps=check_deps,
                load_presets=load_presets,
                load_history=load_history,
                cancel_idle_timer=cancel_idle_timer,
                start_idle_timer=start_idle_timer,
                start_download=start_download,
                batch_txt_download=batch_txt_download,
                start_urls_download=start_urls_download,
                stop_download=stop_download,
                submit_password=submit_password,
                fetch_bili_playlist=fetch_bili_playlist,
                save_preset=save_preset,
                load_preset=load_preset,
                delete_preset=delete_preset,
                clear_history=clear_history,
                find_cover=find_cover,
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
            return HttpService(lambda: create_handler(deps), port=0)

        http_service = create_http_service()

        # ---- main 函数 ----
        def main() -> None:
            print("正在启动 WebUI 服务器...", flush=True)
            load_config()
            deps = check_deps()
            for dep, ok in deps.items():
                if dep in ["yt-dlp", "ffmpeg", "ffprobe"] and not ok:
                    add_log(f"[警告] 缺少依赖: {dep}{exe_suffix}", "warn")
            add_log(f"[就绪] {VERSION} 已启动", "success")
            if not all(deps.get(d, False) for d in ["yt-dlp", "ffmpeg", "ffprobe"]):
                add_log("[提示] yt-dlp: github.com/yt-dlp/yt-dlp/releases", "warn")
                add_log("[提示] ffmpeg: www.gyan.dev/ffmpeg/builds/ (full_build)", "warn")

            url = http_service.start()
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

            def delayed_check() -> None:
                time.sleep(3)
                updater.start_check_thread(silent=True)
            threading.Thread(target=delayed_check, daemon=True).start()

            try:
                exit_event.wait()
            except KeyboardInterrupt:
                request_exit()
            print("\n正在关闭服务器...", flush=True)
            http_service.stop()
            print("已退出。", flush=True)

        return WiredApp(
            http_service=http_service,
            load_config=load_config,
            check_deps=check_deps,
            request_exit=request_exit,
            app_state=app_state,
            updater=updater,
            log=add_log,
            cancel_idle_timer=cancel_idle_timer,
            start_idle_timer=start_idle_timer,
            main=main,
        )
