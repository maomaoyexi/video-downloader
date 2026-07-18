import json
import queue
import secrets
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from urllib.parse import parse_qs, urlparse


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
    batch_txt_download: object
    stop_download: object
    fetch_bili_playlist: object
    save_preset: object
    load_preset: object
    delete_preset: object
    clear_history: object
    validate_config: object
    save_config: object
    handle_tool_action: object
    browse_folder: object
    update_ytdlp: object
    clean_temp: object
    gen_url_template: object
    wav_to_mp3: object
    request_exit: object


def create_handler(dependencies):
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
            return secrets.compare_digest(token, dependencies.session_token)

        def _forbidden(self):
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
            elif path == "/api/deps":
                self._json(dependencies.check_deps())
            elif path == "/api/presets":
                self._json({"presets": list(dependencies.load_presets().keys())})
            elif path == "/api/history":
                self._json({"history": dependencies.load_history()[:100]})
            elif path == "/api/events":
                self._serve_events()
            elif path == "/api/check-update":
                if not dependencies.updater.is_checking():
                    dependencies.updater.start_check_thread(silent=True)
                self._json({"checking": True})
            elif path == "/api/update-status":
                self._json(dependencies.updater.snapshot())
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
                # 静态资源缓存1小时（版本号变更时URL可加?v=参数强制刷新）
                self.send_header("Cache-Control", "public, max-age=3600")
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
                    "progress": dict(dependencies.app_state.progress_data),
                    "stats": dict(dependencies.app_state.batch_stats),
                    "update": dependencies.updater.snapshot(),
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

        def do_POST(self):
            parsed = urlparse(self.path)
            path = parsed.path
            if not self._is_authorized(parsed):
                self._forbidden()
                return
            if self.headers.get_content_type() != "application/json":
                self._json({"error": "Content-Type 必须为 application/json"}, status=415)
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
            try:
                body = self.rfile.read(length).decode("utf-8") if length else "{}"
                data = json.loads(body) if body else {}
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._json({"error": "请求体不是有效的 JSON"}, status=400)
                return
            if not isinstance(data, dict):
                self._json({"error": "JSON 请求体必须是对象"}, status=400)
                return
            if path == "/api/start":
                url = self._field(data, "url", str, "")
                if url is None:
                    return
                bili_parts = data.get("bili_parts") or None
                self._json(dependencies.start_download(url, bili_parts=bili_parts))
            elif path == "/api/batch-txt":
                bili_parts_map = data.get("bili_parts_map") or None
                self._json(dependencies.batch_txt_download(bili_parts_map=bili_parts_map))
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
            elif path == "/api/do-update":
                self._json(dependencies.updater.do_update())
            elif path == "/api/exit":
                self._json({"ok": True})
                threading.Thread(target=self._request_exit, daemon=True).start()
            else:
                self.send_error(404)

        def _field(self, data, name, expected_type, default):
            value = data.get(name, default)
            if (expected_type is int and isinstance(value, bool)) or not isinstance(value, expected_type):
                self._json({"error": f"字段 {name} 类型错误"}, status=400)
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
