"""One policy shared by queued, batch and specialist recording entry points."""
from __future__ import annotations

import json


SOURCES = {
    "Bilibili": "录播姬 XML",
    "YouTube": "yt-dlp live_chat",
    "Twitch": "IRC WebSocket",
    "TwitCasting": "官方网页评论 WebSocket",
    "NicoChannel": "评论历史 API 轮询",
    "Niconico": "NDGR 消息流",
    "Withny": "withny-dl 聊天 JSON",
    "Rplay": "AWS IVS 评论",
}


def platform_defaults(value):
    values = json.loads(value) if isinstance(value, str) else value
    if not isinstance(values, dict) or len(values) > len(SOURCES):
        raise ValueError("Invalid platform comment defaults")
    if any(k not in SOURCES or v not in {"inherit", "on", "off"} for k, v in values.items()):
        raise ValueError("Unknown comment platform or preference")
    return {k: v for k, v in values.items() if v != "inherit"}


def enabled(config, platform):
    if platform not in SOURCES:
        return False
    try:
        choice = platform_defaults(config.get("LIVE_DANMAKU_PLATFORMS", "{}")).get(platform, "inherit")
    except (ValueError, TypeError):
        choice = "inherit"
    return choice == "on" or (choice == "inherit" and bool(config.get("LIVE_DANMAKU_ENABLED", 0)))
