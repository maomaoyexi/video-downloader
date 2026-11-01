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
from .core.paths import AppPaths
from .core.platform import detect_platform, is_live_url
from .live.inspect import LiveInspector
from .live.modes import CAPABILITIES
from .live.preferences import resolve_platform_mode
from .live.probe import ProbeService
from .live.wait import LiveWatchService, WatchJobStore
from .live.session import RecordingStore, recover_interrupted
from .live.danmaku.preferences import SOURCES as COMMENT_SOURCES
from .state.app_state import AppState
from .services.download_executor import DownloadExecutor
from .services.download_archive import TaskArchiveSession
from .services.nicochannel_auth import NicochannelAuthService
from .platforms.rplay import AuthWorkspace as RplayAuthWorkspace
from .services.download_manager import DownloadManager
from .services.routed_executor import RoutedDownloadExecutor
from .platforms.fanbox.archive import ArchiveApplication
from .platforms.fanbox.executor import FanboxExecutor
from .platforms.fanbox.controller import FanboxController
from .tasks.context import TaskAppState
from types import SimpleNamespace
from .services.network_diagnostics import NetworkDiagnostics
from .services.po_token_provider import PoTokenProviderService
from .services.storage import StorageService
from .services.tools import ToolService
from .services.updater import UpdaterService
from .tasks import TaskManager
from .tasks.manager import TaskCallbacks
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
        self._paths = AppPaths(tool_dir)
        self._paths.ensure_runtime_dirs()
        recover_interrupted(self._paths.download_dir / ".live-jobs")
        self._recordings = RecordingStore(self._paths.download_dir / ".live-jobs")
        self._log_dir = self._paths.log_dir

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
        live_watch_service: LiveWatchService | None = None
        task_manager: TaskManager | None = None

        def cancel_idle_timer() -> None:
            nonlocal idle_timer
            if idle_timer is not None:
                idle_timer.cancel()
                idle_timer = None

        def start_idle_timer() -> None:
            nonlocal idle_timer
            cancel_idle_timer()
            if (download_manager.snapshot()["running"] or not download_manager.snapshot()["accepting"]
                    or app_state.has_sse_clients()):
                return
            if live_watch_service is not None and live_watch_service.has_active_jobs():
                return
            if task_manager is not None and task_manager.has_active():
                return

            def do_idle_exit() -> None:
                if (not download_manager.snapshot()["running"] and not app_state.has_sse_clients()
                        and download_manager.snapshot()["accepting"]
                        and not live_watch_service.has_active_jobs()
                        and not task_manager.has_active()):
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
                            speed: str = "", eta: str = "",
                            stage: str | None = None) -> None:
            dc = app_state.download_thread_context
            context_task_id = getattr(dc, "task_id", None)
            if context_task_id is not None and context_task_id != download_manager.snapshot()["generation"]:
                return
            app_state.progress_data["percent"] = percent
            if status:
                app_state.progress_data["status"] = status
            app_state.progress_data["speed"] = speed
            app_state.progress_data["eta"] = eta
            if stage in {"video", "audio", "content"}:
                app_state.progress_data["stage"] = stage
            app_state.publish({"type": "progress", "data": dict(app_state.progress_data)})

        def broadcast_download_state() -> None:
            snapshot = download_manager.snapshot()
            app_state.publish({"type": "download_state", "data": {
                "running": snapshot["running"],
                "phase": snapshot["phase"],
                "generation": snapshot["generation"],
                "kind": snapshot["kind"],
            }})

        # ---- NicoChannel Auth ----
        nicochannel_auth = NicochannelAuthService(log=add_log)
        rplay_auth = RplayAuthWorkspace(self._paths)

        # ---- 命令构建 ----
        def build_command(url: str, *, is_live: bool = False,
                          live_mode: str | None = None,
                          platform_override: str | None = None,
                          config_override: dict | None = None,
                          bili_parts: str | None = None,
                          use_ffmpeg_for_hls: bool = False,
                          include_subtitles: bool = True,
                          subtitle_only: bool = False,
                          thumbnail_only: bool = False,
                          custom_args: str | None = None,
                          po_token_base_url: str | None = None) -> list[str]:
            cfg = config_override if config_override is not None else app_state.config_snapshot()
            cookie_file = tool_dir / "cookies.txt"
            effective_platform = platform_override if platform_override else cfg["PLATFORM"]

            # NicoChannel: extract JWT from Firefox localStorage
            nicochannel_token = None
            if effective_platform == "NicoChannel":
                nicochannel_token = nicochannel_auth.get_auth_token(
                    profile=None,  # None = Firefox 自动探测，BROWSER_PROFILE 是 Chrome 命名
                )

            return _build_ytdlp_cmd(
                url, cfg, tool_dir, exe_suffix,
                is_live=is_live,
                live_mode=live_mode,
                platform_override=platform_override,
                cookie_file=cookie_file if cookie_file.exists() else None,
                bili_parts=bili_parts,
                nicochannel_auth_token=nicochannel_token,
                use_ffmpeg_for_hls=use_ffmpeg_for_hls,
                include_subtitles=include_subtitles,
                subtitle_only=subtitle_only,
                thumbnail_only=thumbnail_only,
                custom_args=custom_args,
                po_token_base_url=po_token_base_url,
                rplay_auth_dir=rplay_auth.directory(cfg) if effective_platform == 'Rplay' else None,
            )

        def build_subtitle_command(url: str, *, subtitle_type: str, subtitle_langs: str) -> list[str]:
            cfg = app_state.config_snapshot()
            detected = detect_platform(url)
            effective_platform = detected if detected else cfg["PLATFORM"]
            subtitle_config = dict(
                cfg,
                DOWNLOAD_SUBTITLES=1,
                SUBTITLE_TYPE=subtitle_type,
                SUBTITLE_LANGS=subtitle_langs,
            )
            return build_command(
                url,
                platform_override=effective_platform,
                config_override=subtitle_config,
                subtitle_only=True,
            )

        def build_cover_command(url: str, *, platform_override: str | None = None) -> list[str]:
            cfg = app_state.config_snapshot()
            detected = platform_override or detect_platform(url)
            effective_platform = detected if detected else cfg["PLATFORM"]
            # 直播留档的封面要和视频一样落到「直播」目录，因此沿用同一个直播判定。
            return build_command(
                url,
                is_live=is_live_url(url, detected),
                platform_override=effective_platform,
                config_override=cfg,
                include_subtitles=False,
                thumbnail_only=True,
            )

        # ---- 工具服务 ----
        tool_service = ToolService(
            tool_dir=tool_dir,
            exe_suffix=exe_suffix,
            app_state=app_state,
            save_config=save_config,
            log=add_log,
            build_subtitle_command=build_subtitle_command,
            build_cover_command=build_cover_command,
            download_manager=download_manager,
            broadcast_download_state=broadcast_download_state,
            cancel_idle_timer=cancel_idle_timer,
            start_idle_timer=start_idle_timer,
            has_active_downloads=lambda: task_manager is not None and task_manager.has_active(),
        )

        # ---- 下载执行器 ----
        fanbox_application=ArchiveApplication(self._paths.download_dir/'Fanbox',publish=app_state.publish)
        po_token_provider = PoTokenProviderService(tool_dir=tool_dir, log=add_log)
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
            pick_withny_archive=tool_service.pick_withny_archive,
            pick_withny_live_config=tool_service.pick_withny_live_config,
            ensure_po_token_provider=po_token_provider.ensure_running,
            get_twitcasting_password=storage.get_twitcasting_password,
            save_twitcasting_password=storage.save_twitcasting_password,
            forget_twitcasting_password=storage.forget_twitcasting_password,
        )

        # ---- 多任务队列 ----
        def make_task_executor(task, task_state, manager, callbacks, on_finished):
            archives = TaskArchiveSession(tool_dir)

            def task_command(*args, **kwargs):
                return archives.prepare(build_command(*args, **kwargs))

            def finished(handle):
                try:
                    archives.finish()
                except Exception as exc:
                    callbacks.log(f"[归档] 合并任务归档失败: {exc}", "error")
                    task_state.publish({"type": "stats", "data": {"fail": 1}})
                finally:
                    on_finished(handle)

            video_executor = DownloadExecutor(
                tool_dir=tool_dir,
                exe_suffix=exe_suffix,
                app_state=task_state,
                download_manager=manager,
                build_command=task_command,
                log=callbacks.log,
                update_progress=callbacks.update_progress,
                broadcast_download_state=callbacks.broadcast_download_state,
                add_history=callbacks.add_history,
                cancel_idle_timer=callbacks.cancel_idle_timer,
                start_idle_timer=callbacks.start_idle_timer,
                emit_event=callbacks.emit_event,
                pick_withny_archive=lambda: dict(task.selection),
                pick_withny_live_config=lambda: dict(task.selection),
                ensure_po_token_provider=po_token_provider.ensure_running,
                on_finished=finished,
                get_twitcasting_password=storage.get_twitcasting_password,
                save_twitcasting_password=storage.save_twitcasting_password,
                forget_twitcasting_password=storage.forget_twitcasting_password,
            )
            return RoutedDownloadExecutor(video_executor,FanboxExecutor(fanbox_application,
                tool_dir=tool_dir,app_state=task_state,download_manager=manager,callbacks=callbacks,
                on_finished=on_finished,job_id=task.selection.get('fanbox_job_id'),
                preview=task.selection.get('fanbox_preview',False),selection=task.selection.get('fanbox_selection')))

        download_executor=RoutedDownloadExecutor(download_executor,FanboxExecutor(fanbox_application,
            tool_dir=tool_dir,app_state=app_state,download_manager=download_manager,
            callbacks=TaskCallbacks(log=add_log,update_progress=update_progress,add_history=add_history,
                broadcast_download_state=broadcast_download_state,emit_event=emit_event,
                cancel_idle_timer=cancel_idle_timer,start_idle_timer=start_idle_timer)),
            manager=download_manager,
            callbacks=TaskCallbacks(log=add_log,update_progress=update_progress,add_history=add_history,
                broadcast_download_state=broadcast_download_state,emit_event=emit_event,
                cancel_idle_timer=cancel_idle_timer,start_idle_timer=start_idle_timer),
            batch_factory=lambda manager,callbacks,finished,config:make_task_executor(SimpleNamespace(selection={}),
                TaskAppState(app_state,None,config),manager,callbacks,finished))

        task_manager = TaskManager(
            base_app_state=app_state,
            executor_factory=make_task_executor,
            max_parallel_getter=lambda: app_state.config_snapshot().get("TASK_MAX_PARALLEL", 2),
            order_getter=lambda: app_state.config_snapshot().get("TASK_ORDER", "none"),
            publish=app_state.publish,
            cancel_idle_timer=cancel_idle_timer,
            start_idle_timer=start_idle_timer,
            add_history=add_history,
            accepting_getter=lambda: (download_manager.snapshot()["accepting"]
                                     and not download_manager.snapshot()["running"]),
        )

        def task_mode_enabled() -> bool:
            try:
                return int(app_state.config_snapshot().get("TASK_MODE", 1)) == 1
            except (TypeError, ValueError):
                return True

        def start_fanbox_job(job_id,url,preview,selection):
            if task_mode_enabled():
                return task_manager.submit([url],selection={'fanbox_job_id':job_id,'fanbox_preview':preview,
                                                           'fanbox_selection':selection})
            def exclusive():
                executor=FanboxExecutor(fanbox_application,tool_dir=tool_dir,app_state=app_state,
                    download_manager=download_manager,callbacks=download_executor.callbacks,
                    job_id=job_id,preview=preview,selection=selection)
                result=executor.start_download(url)
                if result.get('ok'):download_executor.active=executor
                return result
            return task_manager.start_exclusive(exclusive)

        def pause_fanbox_job(job_id,target):
            if target!='exclusive':return task_manager.cancel(target)
            if getattr(download_executor.active,'job_id',None)==job_id:
                return download_executor.stop_download()
            return {'ok':True}

        fanbox_controller=FanboxController(fanbox_application,tool_dir=tool_dir,
            config_getter=app_state.config_snapshot,start=start_fanbox_job,cancel=pause_fanbox_job,
            publish=app_state.publish)

        # ---- 直播 WAIT 服务 ----
        probe_service = ProbeService(
            str(self._paths.executable("yt-dlp", exe_suffix)),
            plugin_dirs=[str(path) for path in self._paths.plugin_dirs()],
            command_context=lambda target: build_command(target.url, is_live=True, live_mode="live_edge",
                                                         platform_override=target.platform, include_subtitles=False),
        )
        watch_store = WatchJobStore(
            self._paths.download_dir / ".live-jobs" / "jobs.sqlite",
        )
        live_inspector = LiveInspector(probe_service)

        def on_live_watch(job, probe) -> dict:
            add_log(
                f"[蹲开播] 检测到开播: {probe.platform} {job.url}，开始录制",
                "success",
            )
            if task_mode_enabled():
                return task_manager.submit([job.url], kind="live", live_mode=job.record_mode)
            return task_manager.start_exclusive(download_executor.start_download, job.url, live_mode=job.record_mode)

        live_watch_service = LiveWatchService(
            store=watch_store,
            probe_service=probe_service,
            on_live=on_live_watch,
            publish=app_state.publish,
            max_wait_hours=72.0,
            start_thread=False,
        )

        def start_download(url: str, bili_parts: str | None = None,
                           tc_password: str | None = None,
                           custom_args: str | None = None,
                           live_mode: str | None = None) -> dict:
            config = app_state.config_snapshot()
            platform = detect_platform(url) or config.get("PLATFORM", "")
            requested = live_mode if live_mode is not None else resolve_platform_mode(
                platform, config.get("LIVE_MODE", "auto"), config.get("LIVE_PLATFORM_MODES", "{}"),
            )
            requested_value = str(getattr(requested, "value", requested)).lower()
            if requested_value == "wait":
                record_mode = resolve_platform_mode(
                    platform, "auto", config.get("LIVE_PLATFORM_MODES", "{}"),
                )
                if record_mode == "wait":
                    record_mode = "auto"
                return live_watch_service.add(url, record_mode=record_mode)
            if task_mode_enabled():
                kind = "live" if is_live_url(url, detect_platform(url)) else "download"
                result = task_manager.submit(
                    [url],
                    kind=kind,
                    live_mode=requested,
                    bili_parts=bili_parts,
                    tc_password=tc_password,
                    custom_args=custom_args,
                )
                if result.get("ok"):
                    add_log(f"[任务] 已加入队列: {url}", "info")
                return result
            return task_manager.start_exclusive(download_executor.start_download,
                url,
                bili_parts=bili_parts,
                tc_password=tc_password,
                custom_args=custom_args,
                live_mode=requested,
            )

        def inspect_live_url(url: str, live_mode: str | None = None) -> dict:
            config = app_state.config_snapshot()
            platform = detect_platform(url) or config.get("PLATFORM", "")
            requested = live_mode if live_mode is not None else resolve_platform_mode(
                platform, config.get("LIVE_MODE", "auto"), config.get("LIVE_PLATFORM_MODES", "{}"),
            )
            return live_inspector.inspect(url, requested_mode=requested)

        def live_capabilities() -> dict:
            return {
                name: {
                    "catch_up": capability.catch_up.value,
                    "catch_up_reason": capability.catch_up_reason,
                    "live_edge": capability.live_edge,
                    "wait": capability.wait,
                    "comments": {"supported":name in COMMENT_SOURCES, "source":COMMENT_SOURCES.get(name, "")},
                }
                for name, capability in CAPABILITIES.items()
            }

        def submit_password(url: str, password: str) -> dict:
            return task_manager.start_exclusive(download_executor.submit_password, url, password)

        def start_withny_archive() -> dict:
            if task_mode_enabled():
                selection = tool_service.pick_withny_archive()
                if selection.get("error") or selection.get("cancelled"):
                    return selection
                return task_manager.submit([selection["output_path"]], operation="withny_archive", selection=selection)
            return task_manager.start_exclusive(download_executor.start_withny_archive)

        def start_withny_live() -> dict:
            if task_mode_enabled():
                selection = tool_service.pick_withny_live_config()
                if selection.get("error") or selection.get("cancelled"):
                    return selection
                return task_manager.submit([selection["config_path"]], kind="live", operation="withny_live", selection=selection)
            return task_manager.start_exclusive(download_executor.start_withny_live)

        def stop_download() -> dict:
            tasks_result = task_manager.cancel_all()
            result = download_executor.stop_download()
            if tasks_result["cancelled"]:
                result["cancelled"] = tasks_result["cancelled"]
            return result

        def list_tasks() -> list[dict]:
            return task_manager.list_tasks()

        def cancel_task(task_id: str) -> dict:
            return task_manager.cancel(task_id)

        def clear_tasks() -> dict:
            return task_manager.clear_finished()

        def submit_task_password(task_id: str, url: str, password: str, item_id=None, request_id=None) -> dict:
            return task_manager.submit_password(task_id, url, password, item_id=item_id, request_id=request_id)

        def submit_task_archive_choice(task_id: str, request_id: str, redownload: bool) -> dict:
            return task_manager.submit_archive_choice(task_id, request_id, redownload)

        def get_current_command() -> dict:
            if task_manager.has_active():
                return task_manager.get_current_command()
            return download_executor.get_current_ytdlp_command()

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
            has_active_downloads=task_manager.has_active,
        )

        check_deps = tool_service.check_deps
        update_ytdlp = tool_service.update_ytdlp
        clean_temp = tool_service.clean_temp
        gen_url_template = tool_service.gen_url_template
        wav_to_mp3 = tool_service.wav_to_mp3
        audio_loudnorm = tool_service.audio_loudnorm
        audio_volume = tool_service.audio_volume
        browse_folder = tool_service.browse_folder
        handle_tool_action = tool_service.handle_tool_action
        read_urls_file = tool_service.read_urls_file
        download_subtitles = tool_service.download_subtitles
        download_covers = tool_service.download_covers

        def batch_txt_download(bili_parts_map: dict | None = None,
                               custom_args: str | None = None) -> dict:
            """从 urls.txt 批量下载（混合平台）。"""
            if str(app_state.config_snapshot().get("LIVE_MODE", "auto")).lower() == "wait":
                return {"error": "蹲开播仅支持单条链接，请逐条添加"}
            urls, err = read_urls_file()
            if err:
                return {"error": err}
            save_config()
            if task_mode_enabled():
                result = task_manager.submit(
                    urls, bili_parts_map=bili_parts_map, custom_args=custom_args,
                )
                if result.get("ok"):
                    add_log(f"[任务] 已加入队列: {len(urls)} 个链接", "info")
                return result
            return task_manager.start_exclusive(download_executor.batch_download,
                urls,
                bili_parts_map=bili_parts_map,
                custom_args=custom_args,
            )

        def start_urls_download(urls: list, custom_args: str | None = None) -> dict:
            """从输入框的多行文本批量下载（每行一个链接）。"""
            if str(app_state.config_snapshot().get("LIVE_MODE", "auto")).lower() == "wait":
                return {"error": "蹲开播仅支持单条链接，请逐条添加"}
            save_config()
            if task_mode_enabled():
                result = task_manager.submit(urls, custom_args=custom_args)
                if result.get("ok"):
                    add_log(f"[任务] 已加入队列: {len(urls)} 个链接", "info")
                return result
            return task_manager.start_exclusive(download_executor.batch_download, urls, custom_args=custom_args)

        def list_live_watch_jobs() -> list[dict]:
            return live_watch_service.list_jobs()

        def cancel_live_watch(job_id: str) -> dict:
            return live_watch_service.cancel(job_id)

        def request_exit() -> None:
            fanbox_controller.stop()
            download_executor.stop_download()
            network_diagnostics.stop()
            live_watch_service.stop()
            task_manager.stop()
            download_executor.wait_for_live_finalization()
            po_token_provider.stop()
            rplay_auth.close()
            app_state.publish({"type": "exit"})
            exit_event.set()

        # ---- HTTP 服务 ----
        network_diagnostics = NetworkDiagnostics(
            app_state=app_state, save_config=save_config,
            begin_guard=tool_service._begin_maintenance,
            end_guard=tool_service._end_maintenance, publish=app_state.publish,
        )

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
                list_live_watch_jobs=list_live_watch_jobs,
                cancel_live_watch=cancel_live_watch,
                inspect_live_url=inspect_live_url,
                live_capabilities=live_capabilities,
                list_tasks=list_tasks,
                cancel_task=cancel_task,
                clear_tasks=clear_tasks,
                start_withny_archive=start_withny_archive,
                start_withny_live=start_withny_live,
                batch_txt_download=batch_txt_download,
                start_urls_download=start_urls_download,
                download_subtitles=download_subtitles,
                download_covers=download_covers,
                stop_download=stop_download,
                get_current_command=get_current_command,
                submit_password=submit_password,
                submit_task_password=submit_task_password,
                submit_archive_choice=download_executor.submit_archive_choice,
                submit_task_archive_choice=submit_task_archive_choice,
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
                audio_convert=tool_service.audio_convert,
                stop_audio_tool=tool_service.stop_audio_tool,
                fanbox=fanbox_controller,
                audio_loudnorm=audio_loudnorm,
                audio_volume=audio_volume,
                request_exit=request_exit,
                network_diagnostics=network_diagnostics,
                list_live_recordings=self._recordings.recent,
                get_live_report=self._recordings.report,
                export_live_comments=self._recordings.export_comments,
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
            config = app_state.config_snapshot()
            live_watch_service.start()

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
            live_watch_service.stop()
            task_manager.stop()
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
