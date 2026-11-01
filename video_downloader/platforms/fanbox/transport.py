"""Bounded HTTPX transport. No response bodies or credentials enter errors."""
from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import importlib
import json
import math
from contextlib import contextmanager
from pathlib import Path
import sys
import threading
import time

from .auth import Credentials, load_credentials
from .errors import FanboxError
from .urls import validate_api_url, validate_resource_url

DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")


def httpx_library():
    if not getattr(sys, "frozen", False):
        vendor = Path(__file__).resolve().parents[3] / "dependency" / "live-python"
        try:
            if vendor.is_dir() and str(vendor) not in sys.path:
                sys.path.insert(0, str(vendor))
        except OSError:
            pass
    try:
        return importlib.import_module("httpx")
    except ImportError:
        raise FanboxError("dependency_missing", "缺少 HTTPX 运行依赖，请安装项目锁定依赖") from None


def retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        result = float(value)
        return max(0., result) if math.isfinite(result) else None
    except ValueError:
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            return max(0., (date - datetime.now(timezone.utc)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return None


class RequestGate:
    """Share one gate per account; lock covers the request and completion gap."""
    def __init__(self, interval: float = 1., cancel: threading.Event | None = None):
        if not math.isfinite(interval) or interval < 0:
            raise ValueError("invalid request interval")
        self.interval = interval
        self.cancel = cancel or threading.Event()
        self._lock = threading.Lock()
        self._next = 0.

    def __enter__(self):
        while not self._lock.acquire(timeout=.1):
            self.check()
        try:
            self.check()
            if self.cancel.wait(max(0., self._next - time.monotonic())):
                self.check()
            return self
        except BaseException:
            self._lock.release()
            raise

    def check(self):
        if self.cancel.is_set():
            raise FanboxError("cancelled", "抓取已取消")

    def defer(self, seconds: float):
        self._next = max(self._next, time.monotonic() + seconds)

    def __exit__(self, *_):
        self.defer(self.interval)
        self._lock.release()


class HttpTransport:
    def __init__(self, credentials: Credentials | None = None, *, proxy: str | None = None,
                 gate: RequestGate | None = None, user_agent: str = DEFAULT_UA,
                 client=None, max_json_bytes: int = 16 * 1024 * 1024):
        lib = httpx_library()
        self.gate = gate or RequestGate()
        self._limit = max_json_bytes
        self._owned = client is None
        self._network_errors = (lib.HTTPError,)
        if any(c in user_agent for c in "\r\n") or not user_agent:
            raise FanboxError("invalid_config", "User-Agent 无效")
        try:
            self._client = client or lib.Client(
                cookies=(credentials or load_credentials()).jar, proxy=proxy,
                trust_env=False, follow_redirects=False,
                timeout=lib.Timeout(30., connect=10.),
                headers={"Origin": "https://www.fanbox.cc", "Referer": "https://www.fanbox.cc/",
                         "User-Agent": user_agent, "Accept": "application/json, text/plain, */*"})
        except (ImportError, ValueError):
            raise FanboxError("dependency_missing", "HTTP 代理配置或 SOCKS 依赖不可用") from None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        if self._owned:
            self._client.close()

    def _read(self, url: str, limit: int, *, prefix=False) -> tuple[bytes, dict]:
        headers = {"Accept-Encoding": "identity"}
        if prefix:
            headers["Range"] = f"bytes=0-{limit-1}"
        with self.gate:
            try:
                with self._client.stream("GET", url, headers=headers) as response:
                    status = response.status_code
                    if status == 429:
                        delay = retry_after(response.headers.get("Retry-After"))
                        self.gate.defer(delay if delay is not None else 360.)
                        raise FanboxError("rate_limited", "FANBOX 请求频率受限", retry_after=delay if delay is not None else 360.)
                    if status in (401, 403):
                        if (status == 403 and ("html" in response.headers.get("Content-Type", "").lower()
                                              or response.headers.get("cf-mitigated") == "challenge")):
                            raise FanboxError("challenge_required", "FANBOX 需要浏览器验证，已停止当前请求")
                        raise FanboxError("access_denied", "当前请求未获授权，需检查登录状态或浏览器验证")
                    if status == 404:
                        raise FanboxError("not_found", "投稿或创作者不存在，或当前账号不可访问")
                    if 300 <= status < 400:
                        raise FanboxError("unexpected_redirect", "接口返回未预期的重定向")
                    if status >= 500:
                        raise FanboxError("server_error", "FANBOX 服务暂时不可用")
                    if status not in ((200, 206) if prefix else (200,)):
                        raise FanboxError("http_error", f"FANBOX 返回 HTTP {status}")
                    result = bytearray()
                    for chunk in response.iter_bytes(chunk_size=min(limit, 65536)):
                        self.gate.check()
                        if len(result) + len(chunk) > limit:
                            if prefix:
                                result.extend(chunk[:limit-len(result)])
                                break
                            raise FanboxError("response_too_large", "接口响应超过大小限制")
                        result.extend(chunk)
                        if prefix and len(result) >= limit:
                            break
                    return bytes(result), {"status": status,
                        "content_type": response.headers.get("Content-Type", "").split(";")[0],
                        "content_range": response.headers.get("Content-Range")}
            except self._network_errors:
                raise FanboxError("network_error", "FANBOX 网络请求失败") from None

    def get_json(self, url: str) -> dict:
        body, headers = self._read(validate_api_url(url), self._limit)
        if "json" not in headers["content_type"].lower():
            raise FanboxError("challenge_required", "接口未返回 JSON，可能需要浏览器验证")
        try:
            value = json.loads(body)
        except (ValueError, UnicodeError, RecursionError):
            raise FanboxError("schema_changed", "接口未返回有效 JSON") from None
        if not isinstance(value, dict) or "body" not in value:
            raise FanboxError("schema_changed", "FANBOX 接口响应结构变化")
        return value

    def probe_resource(self, url: str, *, limit: int = 65536) -> dict:
        """P0 only: read a bounded prefix in memory, never save an attachment."""
        if not 1 <= limit <= 65536:
            raise ValueError("invalid probe size")
        body, headers = self._read(validate_resource_url(url), limit, prefix=True)
        return dict(headers, bytes_read=len(body),
                    signature=body[:12].hex(), looks_like_html=body.lstrip().lower().startswith((b"<!doctype", b"<html")))


class _CurlResponse:
    def __init__(self, response):
        self.status_code, self.headers, self._response = response.status_code, response.headers, response

    def iter_bytes(self, chunk_size):
        return self._response.iter_content(chunk_size=chunk_size)


class _CurlClient:
    def __init__(self, session):
        self.session = session

    @contextmanager
    def stream(self, method, url, headers):
        with self.session.stream(method, url, headers=headers, allow_redirects=False) as response:
            yield _CurlResponse(response)

    def close(self):
        self.session.close()


class CurlTransport(HttpTransport):
    """Browser-compatible TLS transport, verified against authorized live data.

    No challenge solvers, proxy rotation or automatic transport escalation.
    """
    def __init__(self, credentials: Credentials | None = None, *, proxy: str | None = None,
                 gate: RequestGate | None = None, user_agent: str | None = None,
                 max_json_bytes: int = 16 * 1024 * 1024):
        from .runtime import library
        lib = library("curl_cffi.requests")
        curl_options = library("curl_cffi").CurlOpt
        ca_bundle = library("certifi").where()
        self.gate = gate or RequestGate()
        self._limit, self._owned = max_json_bytes, True
        self._network_errors = (lib.exceptions.RequestException,)
        headers = {"Origin": "https://www.fanbox.cc", "Referer": "https://www.fanbox.cc/",
                   "Accept": "application/json, text/plain, */*"}
        if user_agent:
            if any(c in user_agent for c in "\r\n"):
                raise FanboxError("invalid_config", "User-Agent 无效")
            headers["User-Agent"] = user_agent
        self._client = _CurlClient(lib.Session(cookies=(credentials or load_credentials()).jar,
            headers=headers, impersonate="chrome", trust_env=False,
            proxies={"all": proxy or ""}, verify=ca_bundle,
            # 0.13.0 stores trust_env but does not apply it to libcurl's proxy
            # environment. Explicit empty PROXY and NOPROXY prevent inheritance.
            curl_options={curl_options.NOPROXY: ""}, timeout=(10, 30)))
