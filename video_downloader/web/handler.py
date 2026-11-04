import json
import queue
import secrets
import sys
import threading
import time
from contextlib import nullcontext
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from urllib.parse import parse_qs, urlparse

from video_downloader.core.constants import DEFAULT_SUBTITLE_LANGS
from video_downloader.web.rendering import read_error_manual


DEPENDENCY_GUARDED_PATHS = frozenset({
    "/api/start", "/api/start-urls", "/api/start-withny-archive", "/api/start-withny-live",
    "/api/batch-txt", "/api/download-subtitles", "/api/download-covers",
    "/api/live/inspect", "/api/bili-playlist",
    "/api/update-ytdlp", "/api/do-update", "/api/clean-temp",
    "/api/wav2mp3", "/api/audio-convert", "/api/audio-loudnorm", "/api/audio-volume",
    "/api/exit", "/api/dependencies/check", "/api/dependencies/update", "/api/dependencies/cancel",
})


@dataclass(frozen=True)
class HttpHandlerDependencies:
    session_token: str
    version: str
    default_config: dict
    app_state: object
    download_manager: object
    updater: object
    render_html_page: object
    serve_static_file: object
    check_deps: object
    load_presets: object
    load_history: object
    cancel_idle_timer: object
    start_idle_timer: object
    start_download: object
    list_live_watch_jobs: object
    cancel_live_watch: object
    inspect_live_url: object
    live_capabilities: object
    list_tasks: object
    cancel_task: object
    clear_tasks: object
    start_withny_archive: object
    start_withny_live: object
    batch_txt_download: object
    start_urls_download: object
    download_subtitles: object
    download_covers: object
    stop_download: object
    get_current_command: object
    submit_password: object
    submit_task_password: object
    submit_archive_choice: object
    submit_task_archive_choice: object
    fetch_bili_playlist: object
    save_preset: object
    load_preset: object
    delete_preset: object
    clear_history: object
    find_cover: object
    validate_config: object
    save_config: object
    handle_tool_action: object
    browse_folder: object
    update_ytdlp: object
    clean_temp: object
    gen_url_template: object
    wav_to_mp3: object
    audio_loudnorm: object
    audio_volume: object
    request_exit: object
    network_diagnostics: object = None
    list_live_recordings: object = None
    get_live_report: object = None
    export_live_comments: object = None
    audio_convert: object = None
    stop_audio_tool: object = None
    fanbox: object = None
    dependency_manager: object = None
    maintenance_lock: object = None


def create_handler(dependencies):
    maintenance_lock = dependencies.maintenance_lock or threading.RLock()

    class RequestHandler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def _is_local_request(self):
            host = self.headers.get("Host", "").split(":", 1)[0].lower()
            if host not in ("127.0.0.1", "localhost"):
                return False
            origin = self.headers.get("Origin")
            return not origin or origin == f"http://{self.headers.get('Host', '')}"

        def _is_authorized(self, parsed=None):
            if not self._is_local_request():
                return False
            token = self.headers.get("X-Session-Token", "")
            if not token and parsed is not None:
                token = parse_qs(parsed.query).get("token", [""])[0]
            return token.isascii() and secrets.compare_digest(token, dependencies.session_token)

        def _forbidden(self):
            # As with the recording webhook, unread POST bytes can turn a 403
            # into a TCP reset on Windows. Drain only a bounded small body.
            if self.command == "POST":
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if 0 < length <= 65536:
                        self.connection.settimeout(0.5)
                        self.rfile.read(length)
                except (ValueError, OSError):
                    pass
            self.send_error(403, "Forbidden")

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/" or path == "/index.html":
                if not self._is_local_request():
                    self._forbidden()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(dependencies.render_html_page(dependencies.session_token))
            elif path.startswith("/api/") and not self._is_authorized(parsed):
                self._forbidden()
            elif path == "/api/config":
                self._json({"version": dependencies.version, "config": dependencies.app_state.config_snapshot()})
            elif path == "/api/help/error-manual":
                if set(parse_qs(parsed.query, keep_blank_values=True)) - {"token"}:
                    self._json({"error": "完整错误手册接口不接受文件路径或其他查询参数"}, status=400)
                    return
                manual = read_error_manual()
                self._json(manual if manual is not None else {
                    "error": "完整错误手册暂不可用，请确认程序文件完整或查看程序目录中的 docs/错误码.txt"
                }, status=200 if manual is not None else 404)
            elif path == "/api/deps":
                self._json(dependencies.check_deps())
            elif path == "/api/dependencies":
                query = parse_qs(parsed.query, keep_blank_values=True)
                summary = query.get("summary", ["0"])
                if set(query) - {"token", "summary"} or summary not in (["0"], ["1"]):
                    self._json({"error": "依赖状态接口不接受文件路径或其他查询参数"}, status=400)
                    return
                module = dependencies.dependency_manager
                if module is None:
                    state = {"available": False, "error": "依赖管理暂不可用"}
                elif summary == ["1"]:
                    state = module.snapshot(include_groups=False)
                else:
                    state = module.snapshot()
                self._json(state, status=200 if module is not None else 503)
            elif path == "/api/presets":
                self._json({"presets": list(dependencies.load_presets().keys())})
            elif path == "/api/history":
                self._json({"history": dependencies.load_history()[:100]})
            elif path == "/api/cover":
                filepath = parse_qs(parsed.query).get("path", [""])[0]
                content, content_type = dependencies.find_cover(filepath)
                if content is None:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(content)
            elif path == "/api/events":
                self._serve_events()
            elif path == "/api/check-update":
                if not dependencies.updater.is_checking():
                    dependencies.updater.start_check_thread(silent=True)
                self._json({"checking": True})
            elif path == "/api/update-status":
                self._json(dependencies.updater.snapshot())
            elif path == "/api/current-command":
                self._json(dependencies.get_current_command())
            elif path == "/api/live/watch-jobs":
                self._json({"jobs": dependencies.list_live_watch_jobs()})
            elif path == "/api/live/capabilities":
                self._json({"platforms": dependencies.live_capabilities()})
            elif path == "/api/live/recordings":
                self._json({"recordings": dependencies.list_live_recordings() if dependencies.list_live_recordings else []})
            elif path == "/api/live/report":
                job_id = parse_qs(parsed.query).get("job_id", [""])[0]
                report = dependencies.get_live_report(job_id) if dependencies.get_live_report else None
                self._json(report if report is not None else {"error": "报告不存在或仍在生成"}, status=200 if report is not None else 404)
            elif path == "/api/tasks":
                self._json({"tasks": dependencies.list_tasks()})
            elif path.startswith('/api/fanbox/'):
                self._fanbox_get(path,parse_qs(parsed.query))
            elif path == "/api/network-test":
                self._json(dependencies.network_diagnostics.snapshot() if dependencies.network_diagnostics
                           else {"running": False, "phase": "unavailable", "message": "网络检测不可用", "result": None})
            elif path.startswith("/static/"):
                if not self._is_local_request():
                    self._forbidden()
                    return
                content, content_type = dependencies.serve_static_file(path)
                if content is None:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                # Local assets can change between launches without a versioned URL.
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(content)
            else:
                self.send_error(404)

        def _serve_events(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            def ready_event():
                download_snapshot = dependencies.download_manager.snapshot()
                return {"type": "ready", "data": {
                    "logs": dependencies.app_state.log_history[-50:],
                    "running": download_snapshot["running"],
                    "phase": download_snapshot["phase"],
                    "generation": download_snapshot["generation"],
                    "kind": download_snapshot.get("kind"),
                    "progress": dict(dependencies.app_state.progress_data),
                    "stats": dict(dependencies.app_state.batch_stats),
                    "archive_prompt": dependencies.app_state.archive_prompt,
                    "update": dependencies.updater.snapshot(),
                    "live_watch": dependencies.list_live_watch_jobs(),
                    "tasks": dependencies.list_tasks(),
                    "network_test": dependencies.network_diagnostics.snapshot() if dependencies.network_diagnostics else None,
                    "fanbox_jobs": dependencies.fanbox.snapshot() if dependencies.fanbox else [],
                }}
            # 每个 SSE 连接使用有界队列；慢连接的丢旧保新策略由 AppState 统一执行。
            client_queue = queue.Queue(maxsize=256)
            dependencies.app_state.add_sse_client(client_queue, ready_event)
            dependencies.cancel_idle_timer()
            last_keepalive = time.monotonic()
            try:
                while not self.server.stop_event.is_set():
                    try:
                        event = client_queue.get(timeout=1)
                        data = json.dumps(event, ensure_ascii=False)
                        self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
                        self.wfile.flush()
                        if event.get("type") == "exit":
                            break
                    except queue.Empty:
                        if time.monotonic() - last_keepalive >= 15:
                            self.wfile.write(b": keepalive\n\n")
                            self.wfile.flush()
                            last_keepalive = time.monotonic()
            except Exception:
                pass
            finally:
                no_clients = dependencies.app_state.remove_sse_client(client_queue)
                if no_clients and not dependencies.download_manager.snapshot()["running"] and not self.server.stop_event.is_set():
                    dependencies.start_idle_timer()

        def _fanbox_error(self,error):
            from video_downloader.platforms.fanbox.errors import FanboxError
            if isinstance(error,FanboxError):
                status=409 if error.code in {'stale_version','request_conflict','job_busy'} else 404 if error.code.endswith('not_found') else 400
                self._json({'error':str(error),'code':error.code},status=status)
            else:
                self._json({'error':'FANBOX 操作失败','code':'fanbox_error'},status=400)

        def _fanbox_get(self,path,query):
            service=dependencies.fanbox
            if service is None:
                self._json({'error':'FANBOX 不可用'},status=503);return
            try:
                if path=='/api/fanbox/jobs':result={'jobs':service.list(),'error':service.access_error}
                elif path=='/api/fanbox/options':result=service.options()
                elif path=='/api/fanbox/auth':result=service.auth_status()
                elif path=='/api/fanbox/history':result=service.history(query.get('source',[''])[0])
                elif path=='/api/fanbox/logs':result=service.logs(query.get('id',[''])[0])
                elif path=='/api/fanbox/manifest':result=service.manifest(query.get('id',[''])[0])
                elif path=='/api/fanbox/records':result=service.records(export=query.get('export',['0'])[0]=='1')
                elif path=='/api/fanbox/usage':result=service.usage()
                elif path=='/api/fanbox/job':
                    result=service.detail(query.get('id',[''])[0],offset=int(query.get('offset',['0'])[0]),
                        limit=int(query.get('limit',['25'])[0]),post_id=query.get('post_id',[None])[0],query=query.get('q',[''])[0])
                else:self.send_error(404);return
                self._json(result)
            except Exception as error:self._fanbox_error(error)

        def _fanbox_post(self,path,data):
            service=dependencies.fanbox
            if service is None:
                self._json({'error':'FANBOX 不可用'},status=503);return
            try:
                if path=='/api/fanbox/create':result=service.create(data)
                elif path=='/api/fanbox/action':result=service.action(data)
                elif path=='/api/fanbox/naming-preview':result=service.naming_preview(data)
                elif path=='/api/fanbox/records':result=service.record_command(data)
                elif path=='/api/fanbox/import-settings':
                    from video_downloader.platforms.fanbox.options import import_plugin_settings
                    options,report=import_plugin_settings(data.get('settings'))
                    result={'options':options,'report':report}
                else:self.send_error(404);return
                self._json(result)
            except Exception as error:self._fanbox_error(error)

        def do_POST(self):
            parsed = urlparse(self.path)
            path = parsed.path
            if not self._is_authorized(parsed):
                self._forbidden()
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
            except ValueError:
                self._json({"error": "无效的 Content-Length"}, status=400)
                return
            if length < 0:
                self._json({"error": "无效的 Content-Length"}, status=400)
                return
            if length > 65536:
                self.send_error(413, "Request body too large")
                return
            if self.headers.get_content_type() != "application/json":
                # Drain a bounded authenticated request before closing. Leaving
                # unread bytes can cause a Windows TCP reset to hide the 415.
                if length:
                    self.rfile.read(length)
                self._json({"error": "Content-Type 必须为 application/json"}, status=415)
                return
            try:
                body = self.rfile.read(length).decode("utf-8") if length else "{}"
                data = json.loads(body) if body else {}
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._json({"error": "请求体不是有效的 JSON"}, status=400)
                return
            if not isinstance(data, dict):
                self._json({"error": "JSON 请求体必须是对象"}, status=400)
                return
            module = dependencies.dependency_manager
            fanbox_write = path.startswith('/api/fanbox/') and not (
                path == '/api/fanbox/action' and data.get('action') in ('pause', 'cancel'))
            tool_write = path == '/api/tool' and data.get('action') in ('update-ytdlp', 'clean-temp')
            guarded = module is not None and (path in DEPENDENCY_GUARDED_PATHS or fanbox_write or tool_write)
            with maintenance_lock if guarded else nullcontext():
                if guarded and not path.startswith('/api/dependencies/'):
                    state = module.snapshot()
                    installing = state.get('running') and state.get('action') == 'install'
                    if installing or (state.get('recovery_required') and path != '/api/exit'):
                        self._json({"error": "依赖正在安装或等待恢复，请先取消、等待完成或修复依赖后再启动其他操作",
                                    "code": "dependency_maintenance"}, status=409)
                        return
                self._dispatch_post(path, data)

        def _dependency_post(self, path, data):
            module = dependencies.dependency_manager
            if module is None:
                self._json({"error": "依赖更新暂不可用"}, status=503)
                return
            command = path.rsplit('/', 1)[-1]
            if command not in {"check", "update", "cancel"}:
                self.send_error(404)
                return
            if data:
                self._json({"error": "依赖操作包含不支持的参数"}, status=400)
                return
            if command == 'cancel':
                self._json(module.cancel())
                return
            result = module.check() if command == 'check' else module.update()
            self._json(result)

        def _dispatch_post(self, path, data):
            if path.startswith('/api/dependencies/'):
                self._dependency_post(path, data)
                return
            if path.startswith('/api/fanbox/'):
                self._fanbox_post(path,data)
            elif path.startswith("/api/network-test/"):
                service = dependencies.network_diagnostics
                if service is None:
                    self._json({"error": "网络检测不可用"})
                elif path == "/api/network-test/start":
                    self._json(service.start())
                elif path == "/api/network-test/cancel":
                    self._json(service.cancel())
                elif path == "/api/network-test/apply":
                    mode = self._field(data, "mode", str, "")
                    result_id = self._field(data, "result_id", str, "")
                    if mode is not None and result_id is not None:
                        self._json(service.apply(mode, result_id))
                else:
                    self.send_error(404)
            elif path == "/api/start":
                url = self._field(data, "url", str, "")
                if url is None:
                    return
                bili_parts = data.get("bili_parts") or None
                tc_password = data.get("tc_password")
                if tc_password is not None and not isinstance(tc_password, str):
                    self._json({"error": "字段 tc_password 类型错误"}, status=400)
                    return
                tc_password = tc_password or None
                custom_args = self._custom_args(data)
                if custom_args is None:
                    return
                live_mode = data.get("live_mode")
                if live_mode is not None and not isinstance(live_mode, str):
                    self._json({"error": "字段 live_mode 类型错误"}, status=400)
                    return
                self._json(dependencies.start_download(
                    url,
                    bili_parts=bili_parts,
                    tc_password=tc_password,
                    custom_args=custom_args or None,
                    live_mode=live_mode or None,
                ))
            elif path == "/api/start-withny-archive":
                self._json(dependencies.start_withny_archive())
            elif path == "/api/start-withny-live":
                self._json(dependencies.start_withny_live())
            elif path == "/api/live/watch-cancel":
                job_id = self._field(data, "id", str, "")
                if job_id is None:
                    return
                if not job_id:
                    self._json({"error": "缺少等待任务 id"}, status=400)
                    return
                self._json(dependencies.cancel_live_watch(job_id))
            elif path == "/api/live/comments-export":
                job_id = self._field(data, "job_id", str, "")
                values = self._field(data, "settings", dict, {})
                if job_id is None or values is None:
                    return
                if not dependencies.export_live_comments:
                    self._json({"error": "弹幕导出不可用"}, status=503)
                    return
                result = dependencies.export_live_comments(job_id, values)
                self._json(result, status=400 if "error" in result else 200)
            elif path == "/api/tasks/cancel":
                task_id = self._field(data, "id", str, "")
                if task_id is None:
                    return
                if not task_id:
                    self._json({"error": "缺少任务 id"}, status=400)
                    return
                self._json(dependencies.cancel_task(task_id))
            elif path == "/api/tasks/clear":
                self._json(dependencies.clear_tasks())
            elif path == "/api/live/inspect":
                url = self._field(data, "url", str, "")
                if url is None:
                    return
                if not url:
                    self._json({"error": "缺少 url"}, status=400)
                    return
                live_mode = data.get("live_mode")
                if live_mode is not None and not isinstance(live_mode, str):
                    self._json({"error": "字段 live_mode 类型错误"}, status=400)
                    return
                self._json(dependencies.inspect_live_url(url, live_mode or None))
            elif path == "/api/archive-choice":
                request_id = self._field(data, "request_id", str, "")
                if request_id is None:
                    return
                redownload = data.get("redownload")
                if not request_id or not isinstance(redownload, bool):
                    self._json({"error": "归档确认需要 request_id 和布尔值 redownload"}, status=400)
                    return
                task_id = data.get("task_id")
                if task_id is not None and not isinstance(task_id, str):
                    self._json({"error": "字段 task_id 类型错误"}, status=400)
                    return
                if task_id:
                    self._json(dependencies.submit_task_archive_choice(task_id, request_id, redownload))
                else:
                    self._json(dependencies.submit_archive_choice(request_id, redownload))
            elif path == "/api/submit-password":
                url = self._field(data, "url", str, "")
                if url is None:
                    return
                password = self._field(data, "password", str, "")
                if password is None:
                    return
                skip = data.get("skip", False)
                if not isinstance(skip, bool):
                    self._json({"error": "字段 skip 类型错误"}, status=400)
                    return
                if not password.strip() and not (skip and data.get("task_id")):
                    self._json({"error": "密码不能为空"}, status=400)
                    return
                task_id = data.get("task_id")
                if task_id is not None and not isinstance(task_id, str):
                    self._json({"error": "字段 task_id 类型错误"}, status=400)
                    return
                if task_id:
                    item_id = data.get("item_id")
                    request_id = data.get("request_id")
                    if any(v is not None and not isinstance(v, str) for v in (item_id, request_id)):
                        self._json({"error": "字段 item_id/request_id 类型错误"}, status=400)
                        return
                    if item_id or request_id:
                        self._json(dependencies.submit_task_password(
                            task_id, url, "" if skip else password, item_id=item_id, request_id=request_id))
                    else:
                        self._json(dependencies.submit_task_password(task_id, url, "" if skip else password))
                else:
                    self._json(dependencies.submit_password(url, password))
            elif path == "/api/start-urls":
                urls = self._field(data, "urls", list, [])
                if urls is None:
                    return
                if not all(isinstance(u, str) for u in urls):
                    self._json({"error": "字段 urls 必须是字符串数组"}, status=400)
                    return
                custom_args = self._custom_args(data)
                if custom_args is None:
                    return
                self._json(dependencies.start_urls_download(urls, custom_args=custom_args or None))
            elif path == "/api/download-subtitles":
                urls = self._field(data, "urls", list, [])
                if urls is None:
                    return
                if not all(isinstance(url, str) for url in urls):
                    self._json({"error": "字段 urls 必须是字符串数组"}, status=400)
                    return
                subtitle_type = self._field(data, "subtitle_type", str, "all")
                if subtitle_type is None:
                    return
                subtitle_langs = self._field(data, "subtitle_langs", str, DEFAULT_SUBTITLE_LANGS)
                if subtitle_langs is None:
                    return
                self._json(dependencies.download_subtitles(urls, subtitle_type, subtitle_langs))
            elif path == "/api/download-covers":
                urls = self._field(data, "urls", list, [])
                if urls is None:
                    return
                if not all(isinstance(url, str) for url in urls):
                    self._json({"error": "字段 urls 必须是字符串数组"}, status=400)
                    return
                self._json(dependencies.download_covers(urls))
            elif path == "/api/batch-txt":
                bili_parts_map = data.get("bili_parts_map") or None
                custom_args = self._custom_args(data)
                if custom_args is None:
                    return
                self._json(dependencies.batch_txt_download(
                    bili_parts_map=bili_parts_map,
                    custom_args=custom_args or None,
                ))
            elif path == "/api/bili-playlist":
                url = self._field(data, "url", str, "")
                if url is None:
                    return
                self._json(dependencies.fetch_bili_playlist(url))
            elif path == "/api/stop":
                self._json(dependencies.stop_download())
            elif path == "/api/save-preset":
                name = self._field(data, "name", str, "")
                if name is not None:
                    self._json(dependencies.save_preset(name))
            elif path == "/api/load-preset":
                name = self._field(data, "name", str, "")
                if name is not None:
                    self._json(dependencies.load_preset(name))
            elif path == "/api/delete-preset":
                name = self._field(data, "name", str, "")
                if name is not None:
                    self._json(dependencies.delete_preset(name))
            elif path == "/api/clear-history":
                self._json(dependencies.clear_history())
            elif path == "/api/save-config":
                with dependencies.app_state.config_lock:
                    previous = dependencies.app_state.config_snapshot()
                    validated, errors = dependencies.validate_config(data, previous)
                    if errors:
                        self._json({"error": f"无效设置: {', '.join(errors)}"}, status=400)
                        return
                    dependencies.app_state.replace_config(validated)
                    try:
                        dependencies.save_config()
                    except Exception as exc:
                        dependencies.app_state.replace_config(previous)
                        self._json({"error": f"保存设置失败: {exc}"}, status=500)
                        return
                self._json({"ok": True})
            elif path == "/api/reset-config":
                with dependencies.app_state.config_lock:
                    previous = dependencies.app_state.config_snapshot()
                    dependencies.app_state.replace_config(dependencies.default_config)
                    try:
                        dependencies.save_config()
                    except Exception as exc:
                        dependencies.app_state.replace_config(previous)
                        self._json({"error": f"重置设置失败: {exc}"}, status=500)
                        return
                self._json({"ok": True})
            elif path == "/api/tool":
                action = self._field(data, "action", str, "")
                if action is not None:
                    self._json(dependencies.handle_tool_action(action))
            elif path == "/api/browse-folder":
                self._json(dependencies.browse_folder())
            elif path == "/api/update-ytdlp":
                self._json(dependencies.update_ytdlp())
            elif path == "/api/clean-temp":
                self._json(dependencies.clean_temp())
            elif path == "/api/gen-template":
                self._json(dependencies.gen_url_template())
            elif path == "/api/audio-stop":
                self._json(dependencies.stop_audio_tool() if dependencies.stop_audio_tool
                           else {"error": "音频工具未配置"})
            elif path == "/api/audio-convert":
                fields = {
                    'dir': (str, ''), 'recursive': (bool, False),
                    'output_format': (str, 'mp3'), 'del_src': (bool, False),
                    'bitrate': ((str, int), '320k'),
                    'compression_level': (int, 5), 'quality': ((int, float), 7),
                }
                values = {}
                for key, (kind, default) in fields.items():
                    values[key] = self._field(data, key, kind, default)
                    if values[key] is None:
                        return
                directory = values.pop('dir')
                self._json(dependencies.audio_convert(directory, **values) if dependencies.audio_convert
                           else {"error": "音频转换工具未配置"})
            elif path == "/api/wav2mp3":
                directory = self._field(data, "dir", str, "")
                if directory is None:
                    return
                recursive = self._field(data, "recursive", bool, False)
                if recursive is None:
                    return
                bitrate = self._field(data, "bitrate", int, 320)
                if bitrate is None:
                    return
                del_src = self._field(data, "del_src", bool, False)
                if del_src is None:
                    return
                self._json(dependencies.wav_to_mp3(directory, recursive, bitrate, del_src))
            elif path == "/api/audio-loudnorm":
                directory = self._field(data, "dir", str, "")
                if directory is None:
                    return
                recursive = self._field(data, "recursive", bool, False)
                if recursive is None:
                    return
                mode = self._field(data, "mode", str, "single")
                if mode is None:
                    return
                i_target = self._field(data, "i_target", (int, float), -24)
                if i_target is None:
                    return
                lra_target = self._field(data, "lra_target", (int, float), 7)
                if lra_target is None:
                    return
                tp_target = self._field(data, "tp_target", (int, float), -2)
                if tp_target is None:
                    return
                output_dir = self._field(data, "output_dir", str, "")
                if output_dir is None:
                    return
                output_format = self._field(data, "output_format", str, "")
                if output_format is None:
                    return
                self._json(dependencies.audio_loudnorm(
                    directory, recursive, mode, i_target, lra_target, tp_target,
                    output_dir, output_format))
            elif path == "/api/audio-volume":
                directory = self._field(data, "dir", str, "")
                if directory is None:
                    return
                recursive = self._field(data, "recursive", bool, False)
                if recursive is None:
                    return
                gain_db = self._field(data, "gain_db", (int, float), 0)
                if gain_db is None:
                    return
                limiter_enabled = self._field(data, "limiter_enabled", bool, True)
                if limiter_enabled is None:
                    return
                output_dir = self._field(data, "output_dir", str, "")
                if output_dir is None:
                    return
                output_format = self._field(data, "output_format", str, "")
                if output_format is None:
                    return
                self._json(dependencies.audio_volume(
                    directory, recursive, gain_db, limiter_enabled,
                    output_dir, output_format))
            elif path == "/api/do-update":
                self._json(dependencies.updater.do_update())
            elif path == "/api/exit":
                self._json({"ok": True})
                threading.Thread(target=self._request_exit, daemon=True).start()
            else:
                self.send_error(404)

        def _field(self, data, name, expected_type, default):
            value = data.get(name, default)
            # bool is a subclass of int — reject it for numeric types
            if isinstance(value, bool):
                is_int = expected_type is int
                is_num_tuple = isinstance(expected_type, tuple) and (int in expected_type or float in expected_type)
                if is_int or is_num_tuple or expected_type is float:
                    self._json({"error": f"字段 {name} 类型错误"}, status=400)
                    return None
            if not isinstance(value, expected_type):
                self._json({"error": f"字段 {name} 类型错误"}, status=400)
                return None
            return value

        def _custom_args(self, data):
            value = self._field(data, "custom_args", str, "")
            if value is None:
                return None
            value = value.strip()
            if len(value) > 4000:
                self._json({"error": "字段 custom_args 不能超过 4000 字符"}, status=400)
                return None
            return value

        def _request_exit(self):
            time.sleep(0.5)
            dependencies.request_exit()

        def _json(self, obj, status=200):
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    return RequestHandler


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    block_on_close = False
    allow_reuse_address = True

    def __init__(self, *args, **kwargs):
        self.stop_event = threading.Event()
        super().__init__(*args, **kwargs)

    def handle_error(self, request, client_address):
        """忽略浏览器刷新/关闭 SSE 时产生的正常本地连接中断。"""
        error = sys.exc_info()[1]
        ignored_socket_errors = (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)
        if isinstance(error, ignored_socket_errors):
            return
        if isinstance(error, OSError) and getattr(error, "winerror", None) in {10053, 10054}:
            return
        super().handle_error(request, client_address)


class HttpService:
    def __init__(self, handler_factory, host="127.0.0.1", port=0):
        self._handler_factory = handler_factory
        self._host = host
        self._requested_port = port
        self._server = None
        self._thread = None

    @property
    def port(self):
        if self._server is None:
            return None
        return self._server.server_address[1]

    @property
    def url(self):
        if self.port is None:
            return None
        return f"http://{self._host}:{self.port}"

    def start(self):
        if self._server is not None:
            return self.url
        self._server = ThreadedHTTPServer(
            (self._host, self._requested_port),
            self._handler_factory(),
        )
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self.url

    def stop(self):
        if self._server is None:
            return
        server = self._server
        thread = self._thread
        self._server = None
        self._thread = None
        # 先通知 SSE 循环退出，再关闭监听并等待服务线程，避免长连接拖住停机。
        server.stop_event.set()
        server.shutdown()
        server.server_close()
        if thread is not None:
            thread.join()
