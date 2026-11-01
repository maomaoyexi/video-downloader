"""直播状态探测。

设计：
- ``LiveProbe`` 是稳定的值对象；
- 每个平台一个 Provider（策略对象），通过注册表分派；
- HTTP/子进程可注入，便于离线单测；
- ``ProbeService`` 只负责缓存、异常归一化和 fallback 到 yt-dlp。
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from .urls import LiveTarget, TargetKind
from .catchup import CatchUpPlanner, context_arguments
from .process import hidden_options


class LiveStatus(str, Enum):
    UNKNOWN = "unknown"
    OFFLINE = "offline"
    UPCOMING = "upcoming"
    LIVE = "live"
    ENDED = "ended"
    PRIVATE = "private"
    ERROR = "error"


@dataclass(frozen=True)
class LiveProbe:
    platform: str
    target_kind: TargetKind
    stable_id: str
    status: LiveStatus
    scheduled_start: float | None = None
    started_at: float | None = None
    ended_at: float | None = None
    title: str = ""
    uploader: str = ""
    stream_instance_key: str = ""
    live_status_raw: str = ""
    source: str = ""
    observed_at: float = 0.0
    error: str = ""
    retryable: bool = True
    catch_up_available: bool = False
    catch_up_reason: str = "尚未验证该场直播的追播能力"

    def to_dict(self) -> dict:
        return {
            "platform": self.platform,
            "target_kind": self.target_kind.value,
            "stable_id": self.stable_id,
            "status": self.status.value,
            "scheduled_start": self.scheduled_start,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "title": self.title,
            "uploader": self.uploader,
            "stream_instance_key": self.stream_instance_key,
            "live_status_raw": self.live_status_raw,
            "source": self.source,
            "observed_at": self.observed_at,
            "error": self.error,
            "retryable": self.retryable,
            "catch_up_available": self.catch_up_available,
            "catch_up_reason": self.catch_up_reason,
        }


class ProbeError(Exception):
    def __init__(self, message: str, *, status: LiveStatus = LiveStatus.ERROR,
                 retryable: bool = True):
        super().__init__(message)
        self.status = status
        self.retryable = retryable


def _http_json(url: str, headers: Mapping[str, str] | None = None, timeout: float = 8.0, data=None) -> dict:
    request = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json, text/plain, */*",
        **(headers or {}),
    }, data=data)
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read()
    except HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        retryable = exc.code in (408, 425, 429, 500, 502, 503, 504)
        status = LiveStatus.PRIVATE if exc.code in (401, 403) else LiveStatus.ERROR
        raise ProbeError(f"HTTP {exc.code}: {detail}", status=status, retryable=retryable) from None
    except (URLError, TimeoutError, OSError) as exc:
        raise ProbeError(f"网络错误: {exc}", retryable=True) from None
    try:
        return json.loads(body.decode("utf-8", "replace"))
    except (ValueError, UnicodeError) as exc:
        raise ProbeError(f"响应不是 JSON: {exc}", retryable=True) from None


def _epoch(value) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    text = value.strip()
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        return parsed.timestamp()
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).timestamp()
        except ValueError:
            continue
    return None


class BilibiliProbe:
    platform = "Bilibili"

    def __init__(self, http_json: Callable[..., dict] = _http_json):
        self._http_json = http_json

    def probe(self, target: LiveTarget, timeout: float = 8.0) -> LiveProbe:
        room_id = target.stable_id
        if not room_id:
            raise ProbeError("缺少 Bilibili 房间号", retryable=False)
        url = "https://api.live.bilibili.com/room/v1/Room/get_info?" + urlencode({"id": room_id})
        data = self._http_json(url, headers={"Referer": "https://live.bilibili.com/"}, timeout=timeout)
        if data.get("code") != 0:
            message = data.get("message") or f"Bilibili API code={data.get('code')}"
            retryable = data.get("code") in (-352, -412, 429)
            raise ProbeError(message, retryable=retryable)
        info = data.get("data") or {}
        raw = info.get("live_status")
        started = _epoch(info.get("live_time"))
        if raw == 1:
            status = LiveStatus.LIVE
        elif raw == 0:
            status = LiveStatus.OFFLINE
        elif raw == 2:
            # 轮播不是主播实时直播，不应触发录制。
            status = LiveStatus.OFFLINE
        else:
            status = LiveStatus.UNKNOWN
        stream_key = f"bilibili:{info.get('room_id') or room_id}:{started or ''}"
        return LiveProbe(
            platform=self.platform,
            target_kind=target.kind,
            stable_id=str(info.get("room_id") or room_id),
            status=status,
            started_at=started if status is LiveStatus.LIVE else None,
            title=str(info.get("title") or ""),
            uploader=str(info.get("uname") or ""),
            stream_instance_key=stream_key if status is LiveStatus.LIVE else "",
            live_status_raw=str(raw),
            source="bilibili_room_api",
            observed_at=time.time(),
        )


class TwitCastingProbe:
    platform = "TwitCasting"

    def __init__(self, http_json: Callable[..., dict] = _http_json):
        self._http_json = http_json

    def probe(self, target: LiveTarget, timeout: float = 8.0) -> LiveProbe:
        segments = [segment for segment in urlparse(target.url).path.split("/") if segment]
        user = segments[0] if segments else target.stable_id
        if not user:
            raise ProbeError("缺少 TwitCasting 主播名", retryable=False)
        data = self._http_json(
            f"https://frontendapi.twitcasting.tv/watch/user/{user}",
            timeout=timeout, data=b"",
        )
        is_live = data.get("is_live")
        movie = data.get("movie") if isinstance(data.get("movie"), dict) else {}
        movie_id = str(movie.get("id") or data.get("movie_id") or "")
        if is_live is True:
            status = LiveStatus.LIVE
        elif is_live is False:
            status = LiveStatus.OFFLINE
        else:
            status = LiveStatus.UNKNOWN
        return LiveProbe(
            platform=self.platform,
            target_kind=target.kind,
            stable_id=movie_id or user,
            status=status,
            title=str(movie.get("title") or data.get("title") or ""),
            uploader=str(movie.get("user", {}).get("name") if isinstance(movie.get("user"), dict) else user),
            stream_instance_key=f"twitcasting:{user}:{movie_id}" if status is LiveStatus.LIVE else "",
            live_status_raw=str(is_live),
            source="twitcasting_frontendapi",
            observed_at=time.time(),
        )


class YtDlpProbe:
    platform = "*"

    def __init__(self, ytdlp_path: str, runner: Callable[..., object] | None = None,
                 plugin_dirs: list[str] | None = None, command_context=None):
        self._ytdlp_path = ytdlp_path
        self._plugin_dirs = list(plugin_dirs or [])
        self._runner = runner or self._default_runner
        self._command_context = command_context

    @staticmethod
    def _default_runner(command, timeout):
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            **hidden_options(),
        )

    def _command(self, target: LiveTarget) -> list[str]:
        command = [
            self._ytdlp_path,
            "--ignore-config",
            "--simulate",
            "--dump-single-json",
            "--no-warnings",
            "--no-color",
            "--socket-timeout", "15",
        ]
        for plugin_dir in self._plugin_dirs:
            command.extend(["--plugin-dirs", plugin_dir])
        if self._command_context:
            command += context_arguments(self._command_context(target))
        if target.platform == "Rplay":
            command += ["--encoding", "utf-8", "--extractor-args", "RplayLive:inspect=1", "--ignore-no-formats-error"]
        command += ["--no-live-from-start", "--no-playlist"]
        command.append(target.url)
        return command

    def probe(self, target: LiveTarget, timeout: float = 25.0) -> LiveProbe:
        if not self._ytdlp_path:
            raise ProbeError("未找到 yt-dlp", retryable=False)
        try:
            result = self._runner(self._command(target), timeout)
        except subprocess.TimeoutExpired:
            raise ProbeError("yt-dlp 探测超时", retryable=True) from None
        except OSError as exc:
            raise ProbeError(f"yt-dlp 启动失败: {exc}", retryable=False) from None

        stdout = getattr(result, "stdout", "") or ""
        stderr = getattr(result, "stderr", "") or ""
        returncode = getattr(result, "returncode", 1)
        if returncode != 0:
            message = stderr or stdout
            if target.platform == 'Rplay':
                from video_downloader.platforms.rplay import sanitize_output
                message = sanitize_output(message)
            raise _probe_error_from_stderr(message)

        try:
            info = json.loads(stdout)
        except (ValueError, UnicodeError):
            raise ProbeError("yt-dlp 输出无法解析", retryable=True) from None
        if not isinstance(info, dict):
            raise ProbeError("yt-dlp 输出不是对象", retryable=True)

        if info.get("_type") in {"playlist", "multi_video"}:
            entries = [entry for entry in (info.get("entries") or []) if isinstance(entry, dict)]
            live_entries = [entry for entry in entries if _ytdlp_status(entry) is LiveStatus.LIVE]
            upcoming = [entry for entry in entries if _ytdlp_status(entry) is LiveStatus.UPCOMING]
            if live_entries:
                info = live_entries[0]
            elif upcoming:
                info = upcoming[0]
            else:
                return LiveProbe(
                    platform=target.platform or "",
                    target_kind=target.kind,
                    stable_id=target.stable_id,
                    status=LiveStatus.OFFLINE,
                    source="yt_dlp",
                    observed_at=time.time(),
                )

        status = _ytdlp_status(info)
        timestamp = _epoch(info.get("timestamp"))
        release = _epoch(info.get("release_timestamp"))
        if status is LiveStatus.LIVE:
            started = timestamp
            scheduled = None
        elif status is LiveStatus.UPCOMING:
            started = None
            scheduled = release or timestamp
        else:
            started = None
            scheduled = None
        stable = str(info.get("id") or target.stable_id)
        stream_key = f"{target.platform or ''}:{stable}:{timestamp or ''}" if status is LiveStatus.LIVE else ""
        evidence = None
        if status is LiveStatus.LIVE and target.platform in {"YouTube", "Twitch"}:
            evidence = CatchUpPlanner(self._runner).probe(self._command(target), target.url, target.platform,
                                                        edge_info=info)
        return LiveProbe(
            platform=target.platform or "",
            target_kind=target.kind,
            stable_id=stable,
            status=status,
            scheduled_start=scheduled,
            started_at=started,
            ended_at=timestamp if status is LiveStatus.ENDED else None,
            title=str(info.get("title") or ""),
            uploader=str(info.get("uploader") or info.get("channel") or ""),
            stream_instance_key=stream_key,
            live_status_raw=str(info.get("live_status") or info.get("is_live") or ""),
            source="yt_dlp",
            observed_at=time.time(),
            catch_up_available=bool(evidence and evidence.available),
            catch_up_reason=evidence.reason if evidence else "该平台尚未验证追播，使用从当前时刻录制",
        )


def _ytdlp_status(info: dict) -> LiveStatus:
    live_status = str(info.get("live_status") or "").lower()
    if live_status == "is_live":
        return LiveStatus.LIVE
    if live_status == "is_upcoming":
        return LiveStatus.UPCOMING
    if live_status in {"post_live", "was_live"}:
        return LiveStatus.ENDED
    if live_status == "not_live":
        return LiveStatus.OFFLINE
    if info.get("is_live") is True:
        return LiveStatus.LIVE
    return LiveStatus.UNKNOWN


def _probe_error_from_stderr(text: str) -> ProbeError:
    lowered = text.lower()
    if 'rplay' in lowered and any(value in text for value in (
            '尚未接入', '暂不支持', '身份与请求不一致', '场次时间', '转播来源无效')):
        return ProbeError('Rplay 返回未支持或无法确认身份的直播信息', retryable=False)
    if any(part in lowered for part in ("not currently live", "is not live", "user is not live",
                                        "channel is not live", "not live", "offline")):
        return ProbeError(text.strip()[:500] or "未开播", status=LiveStatus.OFFLINE, retryable=True)
    if any(part in lowered for part in ("login required", "private", "members-only", "members only",
                                        "requires authentication", "age-restricted")):
        return ProbeError(text.strip()[:500] or "需要登录或无权限", status=LiveStatus.PRIVATE, retryable=False)
    if any(part in lowered for part in ("429", "too many requests", "rate limit")):
        return ProbeError(text.strip()[:500] or "触发限流", status=LiveStatus.ERROR, retryable=True)
    return ProbeError(text.strip()[:500] or "yt-dlp 探测失败", retryable=True)


class ProbeService:
    """按平台分派探测；HTTP/子进程均可注入。"""

    def __init__(
        self,
        ytdlp_path: str | None = None,
        *,
        providers: Mapping[str, object] | None = None,
        http_json: Callable[..., dict] = _http_json,
        runner: Callable[..., object] | None = None,
        plugin_dirs: list[str] | None = None,
        cache_ttl: float = 15.0,
        clock: Callable[[], float] = time.time,
        command_context=None,
    ):
        self._providers = dict(providers or {
            "Bilibili": BilibiliProbe(http_json=http_json),
            "TwitCasting": TwitCastingProbe(http_json=http_json),
        })
        self._fallback = YtDlpProbe(ytdlp_path or "", runner=runner, plugin_dirs=plugin_dirs,
                                    command_context=command_context)
        self._cache: dict[tuple[str, str], tuple[float, LiveProbe]] = {}
        self._cache_ttl = cache_ttl
        self._clock = clock

    def probe(self, target: LiveTarget, *, timeout: float = 20.0, force: bool = False) -> LiveProbe:
        key = (target.platform or "", target.url)
        now = self._clock()
        if not force:
            cached = self._cache.get(key)
            if cached and now - cached[0] <= self._cache_ttl and cached[1].status is not LiveStatus.ERROR:
                return cached[1]
        provider = self._providers.get(target.platform or "") or self._fallback
        try:
            probe = provider.probe(target, timeout=timeout)
        except ProbeError as exc:
            probe = LiveProbe(
                platform=target.platform or "",
                target_kind=target.kind,
                stable_id=target.stable_id,
                status=exc.status,
                error=str(exc),
                retryable=exc.retryable,
                source="probe",
                observed_at=now,
            )
        except Exception as exc:  # 防御未知 provider 异常，避免调度线程退出
            probe = LiveProbe(
                platform=target.platform or "",
                target_kind=target.kind,
                stable_id=target.stable_id,
                status=LiveStatus.ERROR,
                error=f"{type(exc).__name__}: {exc}",
                retryable=True,
                source="probe",
                observed_at=now,
            )
        self._cache[key] = (now, probe)
        return probe
