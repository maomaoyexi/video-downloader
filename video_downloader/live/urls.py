"""直播 URL 分类（纯函数，无网络）。

分类结果用于 WAIT 任务选择探测策略：
- CHANNEL：固定房间/频道，适合长期蹲守；
- EVENT：单场直播/预约事件；
- LIST：直播列表页，不能直接当单场任务；
- ARCHIVE：已结束回放/点播，不能蹲守；
- UNKNOWN：未识别。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from urllib.parse import parse_qs, urlparse


class TargetKind(str, Enum):
    CHANNEL = "channel"
    EVENT = "event"
    LIST = "list"
    ARCHIVE = "archive"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class LiveTarget:
    url: str
    platform: str | None
    kind: TargetKind
    stable_id: str = ""
    needs_expand: bool = False
    reason: str = ""

    @property
    def can_watch(self) -> bool:
        return self.kind in {TargetKind.CHANNEL, TargetKind.EVENT}


def _detect_platform(url: str) -> str | None:
    # 延迟导入，避免 core.platform 与 live 包循环依赖。
    from video_downloader.core.platform import detect_platform

    return detect_platform(url)


def _segments(path: str) -> list[str]:
    return [segment for segment in path.split("/") if segment]


def classify_target(url: str, platform: str | None = None) -> LiveTarget:
    """按 URL 形状分类；不做网络请求、不判断当前是否在直播。"""
    raw_url = (url or "").strip()
    try:
        parsed = urlparse(raw_url)
    except Exception:
        return LiveTarget(raw_url, platform, TargetKind.UNKNOWN, reason="URL 解析失败")

    host = (parsed.hostname or "").lower()
    path = parsed.path.rstrip("/")
    lowered = path.lower()
    query = parse_qs(parsed.query)
    platform_name = platform or _detect_platform(raw_url)
    if host in {"withny.com", "www.withny.com", "withny.fun", "www.withny.fun"}:
        platform_name = "Withny"

    if not host:
        return LiveTarget(raw_url, platform_name, TargetKind.UNKNOWN, reason="缺少 host")

    if platform_name == "Rplay":
        if (parsed.scheme != "https" or host not in {"rplay.live", "www.rplay.live"}
                or parsed.username or parsed.password):
            return LiveTarget(raw_url, platform_name, TargetKind.UNKNOWN, reason="需要 Rplay HTTPS 主站链接")
        try:
            if parsed.port not in (None, 443):
                return LiveTarget(raw_url, platform_name, TargetKind.UNKNOWN, reason="Rplay 端口无效")
        except ValueError:
            return LiveTarget(raw_url, platform_name, TargetKind.UNKNOWN, reason="Rplay 端口无效")
        segments = _segments(path)
        if re.fullmatch(r"/(?:play|live|creatorhome)/[0-9a-fA-F]{24}/?", parsed.path):
            stable = segments[1].lower()
            if segments[0] == "play":
                return LiveTarget(raw_url, platform_name, TargetKind.ARCHIVE, stable)
            if segments[0] == "live":
                return LiveTarget(raw_url, platform_name, TargetKind.CHANNEL, stable)
            if segments[0] == "creatorhome":
                kind = TargetKind.LIST if query.get("page", [""])[0] in {"contents", "replays", "playlists"} else TargetKind.CHANNEL
                return LiveTarget(raw_url, platform_name, kind, stable)
        return LiveTarget(raw_url, platform_name, TargetKind.UNKNOWN, reason="Rplay 暂不支持此路径")

    if platform_name == "YouTube":
        if host in {"youtu.be", "www.youtu.be"}:
            video_id = _segments(lowered)[0] if _segments(lowered) else ""
            return LiveTarget(raw_url, platform_name, TargetKind.EVENT, video_id)
        if host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
            segments = _segments(lowered)
            if len(segments) >= 2 and segments[0] == "live":
                return LiveTarget(raw_url, platform_name, TargetKind.EVENT, segments[1])
            if segments and segments[0] == "watch":
                video_id = (query.get("v") or [""])[0]
                if video_id:
                    return LiveTarget(raw_url, platform_name, TargetKind.EVENT, video_id)
            if segments and (segments[-1] in {"streams", "videos"}):
                return LiveTarget(raw_url, platform_name, TargetKind.LIST)
            if len(segments) >= 2 and segments[0] in {"channel", "user"}:
                stable = segments[1]
                return LiveTarget(raw_url, platform_name, TargetKind.CHANNEL, stable)
            if segments and segments[0].startswith("@"):
                return LiveTarget(raw_url, platform_name, TargetKind.CHANNEL, segments[0])
            if segments and segments[-1] == "live":
                return LiveTarget(raw_url, platform_name, TargetKind.CHANNEL, segments[0])
            return LiveTarget(raw_url, platform_name, TargetKind.UNKNOWN, reason="未识别的 YouTube 路径")

    if platform_name == "Twitch":
        if host not in {"twitch.tv", "www.twitch.tv", "m.twitch.tv"}:
            return LiveTarget(raw_url, platform_name, TargetKind.UNKNOWN, reason="非 Twitch 主站")
        segments = _segments(lowered)
        if len(segments) == 1 and segments[0] not in {"videos", "clips", "directory"}:
            return LiveTarget(raw_url, platform_name, TargetKind.CHANNEL, segments[0])
        if len(segments) >= 2 and segments[0] == "videos":
            return LiveTarget(raw_url, platform_name, TargetKind.ARCHIVE, segments[1])
        if len(segments) >= 1 and segments[0] in {"videos", "directory"}:
            return LiveTarget(raw_url, platform_name, TargetKind.LIST)
        return LiveTarget(raw_url, platform_name, TargetKind.UNKNOWN, reason="未识别的 Twitch 路径")

    if platform_name == "Bilibili":
        if host == "b23.tv" or host.endswith(".b23.tv"):
            return LiveTarget(raw_url, platform_name, TargetKind.UNKNOWN, needs_expand=True,
                              reason="短链需要展开")
        if host == "live.bilibili.com" or host.endswith(".live.bilibili.com"):
            segments = _segments(lowered)
            stable = segments[0] if segments else ""
            return LiveTarget(raw_url, platform_name, TargetKind.CHANNEL, stable)
        return LiveTarget(raw_url, platform_name, TargetKind.ARCHIVE, reason="Bilibili 非直播 URL")

    if platform_name == "Niconico":
        segments = _segments(lowered)
        if host in {"live.nicovideo.jp", "live2.nicovideo.jp"}:
            if len(segments) >= 2 and segments[0] == "watch" and segments[1].startswith("lv"):
                return LiveTarget(raw_url, platform_name, TargetKind.EVENT, segments[1])
            return LiveTarget(raw_url, platform_name, TargetKind.UNKNOWN, reason="未识别的 Niconico 直播路径")
        if (host in {"www.nicovideo.jp", "nicovideo.jp", "m.nicovideo.jp"}
                and len(segments) == 2 and segments[0] == "watch"
                and re.fullmatch(r"lv\d+", segments[1])):
            return LiveTarget(raw_url, platform_name, TargetKind.EVENT, segments[1])
        if host in {"www.nicovideo.jp", "nicovideo.jp", "m.nicovideo.jp"} and segments[:1] == ["watch"]:
            return LiveTarget(raw_url, platform_name, TargetKind.ARCHIVE, segments[1] if len(segments) > 1 else "")
        return LiveTarget(raw_url, platform_name, TargetKind.UNKNOWN, reason="未识别的 Niconico 路径")

    if platform_name == "NicoChannel":
        segments = _segments(lowered)
        if len(segments) == 3 and segments[1] == "live" and re.fullmatch(r"sm\w+", segments[2]):
            return LiveTarget(raw_url, platform_name, TargetKind.EVENT, segments[2])
        if len(segments) >= 2 and segments[1] == "lives":
            return LiveTarget(raw_url, platform_name, TargetKind.LIST, segments[0])
        if len(segments) >= 3 and segments[1] == "video" and segments[2].startswith("sm"):
            return LiveTarget(raw_url, platform_name, TargetKind.ARCHIVE, segments[2])
        if len(segments) >= 2 and segments[1] == "videos":
            return LiveTarget(raw_url, platform_name, TargetKind.LIST, segments[0])
        return LiveTarget(raw_url, platform_name, TargetKind.UNKNOWN, reason="未识别的 NicoChannel 路径")

    if platform_name == "TwitCasting":
        segments = _segments(lowered)
        if not segments:
            return LiveTarget(raw_url, platform_name, TargetKind.UNKNOWN, reason="TwitCasting 缺少主播名")
        if len(segments) >= 3 and segments[1] in {"movie", "twplayer"}:
            return LiveTarget(raw_url, platform_name, TargetKind.EVENT, segments[2])
        if len(segments) >= 2 and segments[1] in {"show", "archive"}:
            return LiveTarget(raw_url, platform_name, TargetKind.LIST, segments[0])
        if len(segments) == 1:
            return LiveTarget(raw_url, platform_name, TargetKind.CHANNEL, segments[0])
        return LiveTarget(raw_url, platform_name, TargetKind.UNKNOWN, reason="未识别的 TwitCasting 路径")

    if platform_name == "Twitter":
        segments = _segments(lowered)
        if len(segments) >= 3 and segments[:2] == ["i", "spaces"]:
            return LiveTarget(raw_url, platform_name, TargetKind.EVENT, segments[2])
        if len(segments) >= 2 and segments[0] == "i" and segments[1] == "broadcasts":
            return LiveTarget(raw_url, platform_name, TargetKind.UNKNOWN, reason="X Broadcast 暂不支持")
        if len(segments) >= 3 and segments[1] == "status":
            return LiveTarget(raw_url, platform_name, TargetKind.ARCHIVE)
        return LiveTarget(raw_url, platform_name, TargetKind.UNKNOWN, reason="未识别的 X 路径")

    if platform_name == "Withny":
        segments = _segments(lowered)
        if len(segments) >= 2 and segments[1].startswith("@"):
            return LiveTarget(raw_url, platform_name, TargetKind.CHANNEL, segments[1])
        if len(segments) == 1 and segments[0].startswith("@"):
            return LiveTarget(raw_url, platform_name, TargetKind.CHANNEL, segments[0])
        return LiveTarget(raw_url, platform_name, TargetKind.UNKNOWN, reason="未识别的 Withny 路径")

    return LiveTarget(raw_url, platform_name, TargetKind.UNKNOWN, reason="未知平台")


def expand_short_url(url: str, resolver=None, timeout: float = 8.0) -> str:
    """展开 b23.tv 短链；失败时返回原 URL（探测会按 UNKNOWN 处理）。"""
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return url
    if host not in {"b23.tv", "www.b23.tv"}:
        return url
    if resolver is not None:
        return resolver(url) or url
    try:
        from urllib.request import Request, urlopen

        request = Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(request, timeout=timeout) as response:
            return response.geturl() or url
    except Exception:
        return url
