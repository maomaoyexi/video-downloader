"""Loopback streaming relay: signed CDN URLs stay inside the extractor process."""

import atexit
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import uuid


class MediaRelay:
    def __init__(self, open_remote):
        # yt-dlp passes its upstream proxy to FFmpeg through the environment.
        # The local relay must stay reachable directly; its remote opener still
        # uses yt-dlp's original proxy/TLS configuration.
        for name in ('no_proxy', 'NO_PROXY'):
            entries = [value.strip() for value in os.environ.get(name, '').split(',') if value.strip()]
            os.environ[name] = ','.join(dict.fromkeys([*entries, '127.0.0.1', 'localhost', '::1']))
        self._open = open_remote
        self._routes = {}
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                remote = owner._routes.get(self.path)
                if remote is None:
                    self.send_error(404)
                    return
                try:
                    response = owner._open(remote)
                except Exception as exc:
                    status = getattr(exc, 'status', None)
                    self.send_error(status if isinstance(status, int) and 400 <= status <= 599 else 502)
                    return
                try:
                    self.send_response(200)
                    self.send_header('Content-Type', 'video/x-flv')
                    self.send_header('Cache-Control', 'no-store')
                    self.end_headers()
                    while True:
                        chunk = response.read(32768)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        self.wfile.flush()
                except Exception:
                    pass
                finally:
                    response.close()
        self._server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, name='rplay-media-relay', daemon=True)
        self._thread.start()
        atexit.register(self.close)

    def add(self, url):
        path = '/' + uuid.uuid4().hex + '.flv'
        self._routes[path] = url
        return f'http://127.0.0.1:{self._server.server_port}{path}'

    def close(self):
        atexit.unregister(self.close)
        if self._thread.is_alive():
            self._server.shutdown()
            self._server.server_close()
            self._thread.join(timeout=2)
        self._server.server_close()
        self._routes.clear()
