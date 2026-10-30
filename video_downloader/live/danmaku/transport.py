"""Bounded TLS transports sharing the recording's cookie/proxy context."""
from __future__ import annotations

import contextlib
import http.cookiejar
from urllib.parse import urlsplit, unquote

from .dependencies import library


def option(command, name, default=None):
    result = default
    for i, value in enumerate(command):
        if value == name and i + 1 < len(command):
            result = command[i + 1]
        elif value.startswith(name + "="):
            result = value.split("=", 1)[1]
    return result


def remote_url(url, domains, *, websocket=False):
    parts = urlsplit(url)
    host = parts.hostname or ""
    if (parts.scheme != ("wss" if websocket else "https") or parts.username or parts.password
            or parts.port not in (None, 443) or not any(host == d or host.endswith("." + d) for d in domains)):
        raise ValueError("unexpected_comment_endpoint")
    return url


class Transport:
    def __init__(self, command):
        self.command = command
        self.proxy = option(command, "--proxy", "")
        self.headers = {"User-Agent": option(command, "--user-agent", "Mozilla/5.0"), "Accept": "*/*"}
        self.jar = http.cookiejar.MozillaCookieJar()
        path = option(command, "--cookies")
        if path:
            self.jar.load(path, ignore_discard=True, ignore_expires=False)
        browser = option(command, "--cookies-from-browser")
        if browser:
            # Extract in memory; never export the browser's entire cookie jar.
            from yt_dlp.cookies import extract_cookies_from_browser
            from yt_dlp import parse_options
            parsed = parse_options(["--cookies-from-browser", browser]).ydl_opts["cookiesfrombrowser"]
            self.jar = extract_cookies_from_browser(parsed[0], profile=parsed[1], keyring=parsed[2], container=parsed[3])
        self.client = library("httpx").Client(proxy=self.proxy or None, cookies=self.jar,
                                               headers=self.headers, trust_env=False, http2=True,
                                               timeout=10, follow_redirects=True, max_redirects=3)

    def response(self, url, *, method="GET", **kwargs):
        with self.client.stream(method, url, **kwargs) as response:
            response.raise_for_status()
            chunks, size = [], 0
            for chunk in response.iter_bytes(chunk_size=65536):
                size += len(chunk)
                if size > 8 * 1024 * 1024:
                    raise ValueError("oversized_comment_response")
                chunks.append(chunk)
            return b"".join(chunks)

    def json(self, url, *, method="GET", **kwargs):
        import json
        return json.loads(self.response(url, method=method, **kwargs))

    def text(self, url):
        return self.response(url).decode("utf-8-sig", "replace")

    @contextlib.contextmanager
    def stream(self, url):
        with self.client.stream("GET", url, timeout=library("httpx").Timeout(10, read=40)) as response:
            response.raise_for_status()
            # Small protobuf entries must be delivered immediately. A fixed
            # chunk size buffers low-volume live streams until the buffer fills.
            yield response.iter_bytes()

    def socket(self, url, *, origin=None, subprotocols=None):
        params = {"timeout": 1, "header": ["User-Agent: " + self.headers["User-Agent"]],
                  "http_no_proxy": [] if self.proxy else ["*"]}
        if origin:
            params["origin"] = origin
        if subprotocols:
            params['subprotocols'] = subprotocols
        # httpx scopes cookies to the target host/path before WebSocket upgrade.
        request = self.client.build_request("GET", url.replace("wss://", "https://", 1))
        if request.headers.get("cookie"):
            params["cookie"] = request.headers["cookie"]
        if self.proxy:
            proxy = urlsplit(self.proxy)
            if proxy.scheme not in {"http", "socks5", "socks5h", "socks4", "socks4a"}:
                raise ValueError("unsupported_websocket_proxy_scheme")
            params.update(http_proxy_host=proxy.hostname, http_proxy_port=proxy.port or (80 if proxy.scheme == "http" else 1080),
                          proxy_type="socks5h" if proxy.scheme == "socks5" else proxy.scheme)
            if proxy.username:
                params["http_proxy_auth"] = (unquote(proxy.username), unquote(proxy.password or ""))
        return library("websocket").create_connection(url, **params)

    def close(self):
        self.client.close()
