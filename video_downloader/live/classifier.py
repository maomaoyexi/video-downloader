"""直播 URL 识别。

实现从 ``core.platform`` 迁移而来。``core.platform.is_live_url`` 保留为兼容门面，
新代码应优先 ``from video_downloader.live import is_live_url``。
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

# 仅保留 URL 形状判断，不读网络、不依赖下载器。
_TWITCH_ONE_SEGMENT_BLOCKLIST = {"videos", "clips", "directory"}
_TWITCH_HOSTS = {"twitch.tv", "www.twitch.tv", "m.twitch.tv"}
_TWITCASTING_BLOCKLIST = {"movie", "twplayer", "show", "archive"}
_TWITTER_HOSTS = {"x.com", "twitter.com", "www.x.com", "www.twitter.com"}


def _detect_platform(url: str) -> str | None:
    # 延迟导入避免 core.platform <-> live 包循环依赖。
    from video_downloader.core.platform import detect_platform

    return detect_platform(url)


def is_live_url(url: str, platform: str | None = None) -> bool:
    """判断 URL 是否属于直播入口（只看形状，不代表当前真的在直播）。"""
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        path = parsed.path.lower().rstrip("/")
    except Exception:
        return False

    platform_name = platform or _detect_platform(url)
    if platform_name == "Rplay":
        from .urls import TargetKind, classify_target
        return classify_target(url, platform_name).kind is TargetKind.CHANNEL
    if platform_name == "YouTube":
        return (host == "youtube.com" or host.endswith(".youtube.com")) and (
            path == "/live" or path.startswith("/live/") or path.endswith("/live")
        )
    if platform_name == "Twitch":
        if host not in _TWITCH_HOSTS:
            return False
        segments = [segment for segment in path.split("/") if segment]
        return len(segments) == 1 and segments[0] not in _TWITCH_ONE_SEGMENT_BLOCKLIST
    if platform_name == "Niconico":
        return host in {"live.nicovideo.jp", "live2.nicovideo.jp"} or (
            host in {"nicovideo.jp", "www.nicovideo.jp", "m.nicovideo.jp"}
            and re.fullmatch(r"/watch/lv\d+", path) is not None
        )
    if platform_name == "NicoChannel":
        segments = [segment for segment in path.split("/") if segment]
        return (host == "nicochannel.jp" or host.endswith(".nicochannel.jp")) and (
            len(segments) == 3 and segments[1] == "live"
            and re.fullmatch(r"sm\w+", segments[2]) is not None)
    if platform_name == "Bilibili":
        return host == "live.bilibili.com" or host.endswith(".live.bilibili.com")
    if platform_name == "TwitCasting":
        if host != "twitcasting.tv" and not host.endswith(".twitcasting.tv"):
            return False
        segments = [segment for segment in path.split("/") if segment]
        return len(segments) == 1 and segments[0] not in _TWITCASTING_BLOCKLIST
    if platform_name == "Twitter":
        return host in _TWITTER_HOSTS and path.startswith("/i/spaces/")
    return False
