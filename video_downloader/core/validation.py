from .constants import (
    AUDIO_FORMAT_OPTIONS,
    AUDIO_MODE_OPTIONS,
    AUDIO_OPTIONS,
    BILI_POLICY_OPTIONS,
    BROWSER_OPTIONS,
    CODEC_OPTIONS,
    DEFAULT_CONFIG,
    FORMAT_OPTIONS,
    HWACCEL_OPTIONS,
    LIVE_STREAM_METHOD_OPTIONS,
    LIVE_MODE_OPTIONS,
    MP3_BITRATE_OPTIONS,
    PLATFORM_INFO,
    PROXY_TYPE_OPTIONS,
    RESOLUTION_OPTIONS,
    SUBTITLE_TYPE_OPTIONS,
    TASK_ORDER_OPTIONS,
)

# 校验错误的中文说明（key → 错误详情映射）
_ERROR_REASONS = {
    "FANBOX_OPTIONS": "FANBOX 设置必须是有效的版本化 JSON 配置",
    "FANBOX_COOKIE_FILE": "凭据路径格式无效或超过 4000 字符",
    "FANBOX_ENABLED": "平台开关仅支持 0 或 1",
    "FANBOX_ANONYMOUS": "匿名访问开关仅支持 0 或 1",
    "RPLAY_AUTH_SOURCE": "Rplay 登录来源仅支持 none/firefox",
    "RPLAY_FIREFOX_PROFILE": "Firefox 配置路径长度不能超过 200 字符",
    "PLATFORM": "平台选项无效",
    "RESOLUTION": "分辨率选项无效",
    "CODEC": "编码选项无效",
    "AUDIO_QUALITY": "音频质量选项无效",
    "OUTPUT_FORMAT": "输出格式选项无效",
    "PROXY_TYPE": "代理类型仅支持 http/socks5",
    "BROWSER_NAME": "浏览器选项无效",
    "HWACCEL": "硬件加速选项无效",
    "BILI_MULTIP_POLICY": "B站多P策略选项无效",
    "LIVE_STREAM_METHOD": "直播下载方式仅支持 auto/yt-dlp/bililive-recorder",
    "LIVE_MAX_RETRIES": "直播重试次数需在 0-5 之间",
    "LIVE_WATCHDOG_SECONDS": "直播看门狗告警时间需在 10-600 秒之间",
    "LIVE_MIN_FREE_MB": "直播磁盘安全余量需在 64-102400 MiB 之间",
    "LIVE_ESTIMATED_BITRATE_KBPS": "直播预估码率需在 128-100000 Kbps 之间",
    "LIVE_MODE": "直播模式仅支持 auto/catch_up/live_edge/wait",
    "LIVE_DANMAKU_ENABLED": "直播弹幕开关仅支持 0 或 1",
    "LIVE_DANMAKU_ANONYMIZE": "弹幕匿名化开关仅支持 0 或 1",
    "LIVE_DANMAKU_FORMATS": "直播弹幕格式仅支持 srt、ass 或 srt,ass",
    "LIVE_DANMAKU_PLATFORMS": "平台弹幕默认值需为已支持平台的 inherit/on/off JSON 对象",
    "LIVE_DANMAKU_OFFSET_MS": "弹幕时间微调需在 -600000 到 600000 毫秒之间",
    "LIVE_PLATFORM_MODES": "平台直播设置为 JSON，长度不能超过 2000 字符",
    "TASK_ORDER": "任务排序仅支持 none/live_first/download_first",
    "TASK_MAX_PARALLEL": "并行任务数需在 1-5 之间",
    "TASK_LIVE_PARALLEL": "任务内直播并行数需在 2-5 之间",
    "TASK_DOWNLOAD_PARALLEL": "任务内下载并行数需在 1-5 之间",
    "TASK_MIXED_PARALLEL": "任务内并行开关仅支持 0 或 1",
    "TASK_DOWNLOAD_SPEED_LIMIT": "普通下载限速需在 0-100000 MiB/s 之间",
    "AUDIO_MODE": "音频模式选项无效",
    "AUDIO_FORMAT": "音频格式选项无效",
    "THREADS": "线程数需在 1-32 之间",
    "SPEED_LIMIT": "限速值需在 0-100000 MB/s 之间",
    "COOKIE_MODE": "Cookie模式仅支持 1(文件) 或 2(浏览器)",
    "MP3_BITRATE": f"MP3比特率仅支持 {', '.join(str(v) for v in MP3_BITRATE_OPTIONS)}",
    "PROXY_PORT": "代理端口需在 1-65535 之间",
    "PROXY_ADDR": "代理地址格式无效（不允许包含协议头、斜杠、@ 或空白字符）",
    "MERGE_MODE": "合并模式仅支持 0 或 1",
    "PROXY_ENABLED": "代理开关仅支持 0 或 1",
    "USE_COOKIES": "Cookie开关仅支持 0 或 1",
    "EMBED_META": "嵌入元数据仅支持 0 或 1",
    "DOWNLOAD_THUMB": "下载封面仅支持 0 或 1",
    "DOWNLOAD_SUBTITLES": "字幕下载开关仅支持 0 或 1",
    "SUBTITLE_TYPE": "字幕类型选项无效",
    "SUBTITLE_LANGS": "字幕语言设置长度不能超过 200 字符",
    "WIN_FILENAMES": "Win文件名兼容仅支持 0 或 1",
    "STRICT_FILENAME": "严格文件名仅支持 0 或 1",
    "NICO_COMMENTS": "Niconico弹幕仅支持 0 或 1",
    "NICO_RECODE": "Niconico重编码仅支持 0 或 1",
    "TC_PASSWORD": "TwitCasting密码长度不能超过 200 字符",
    "TC_REMEMBER_PASSWORD": "TwitCasting 记住密码仅支持 0 或 1",
    "TC_SAVE_PASSWORD_XLSX": "TwitCasting 保存密码到 XLSX 仅支持 0 或 1",
    "ENABLE_LOG": "日志开关仅支持 0 或 1",
    "DEL_WAV_AFTER_CONVERT": "删除WAV仅支持 0 或 1",
    "YOUTUBE_PO_TOKEN_ENABLED": "YouTube PO Token 开关仅支持 0 或 1",
    "YTDLP_DEFAULT_ARGS": "默认 yt-dlp 参数长度不能超过 4000 字符",
    "HWACCEL_WEBM": "WebM输出格式不支持硬件加速，已自动回退为CPU编码",
}


def _err(key):
    """构建校验错误信息：`字段名：原因`。"""
    reason = _ERROR_REASONS.get(key, "未知校验错误")
    return f"{key}：{reason}"


def validate_config(values, base=None):
    result = dict(DEFAULT_CONFIG if base is None else base)
    errors = []
    # Import the upstream name once; the live domain remains the only executor.
    values = dict(values)
    if "LIVE_RECORD_MODE" in values and "LIVE_MODE" not in values:
        legacy = {"from_start": "catch_up", "current": "live_edge", "wait": "wait"}
        mode = str(values["LIVE_RECORD_MODE"]).strip().lower()
        if mode in legacy:
            values["LIVE_MODE"] = legacy[mode]
        else:
            errors.append("LIVE_RECORD_MODE：直播录制策略无效")
    proxy_enabled = values.get("PROXY_ENABLED", result["PROXY_ENABLED"])
    try:
        proxy_enabled = int(proxy_enabled) == 1
    except (TypeError, ValueError, OverflowError):
        proxy_enabled = bool(result["PROXY_ENABLED"])
    enums = {
        "RPLAY_AUTH_SOURCE": ["none", "firefox"],
        "PLATFORM": [item["name"] for item in PLATFORM_INFO],
        "RESOLUTION": RESOLUTION_OPTIONS,
        "CODEC": CODEC_OPTIONS,
        "AUDIO_QUALITY": AUDIO_OPTIONS,
        "OUTPUT_FORMAT": FORMAT_OPTIONS,
        "PROXY_TYPE": PROXY_TYPE_OPTIONS,
        "BROWSER_NAME": BROWSER_OPTIONS,
        "HWACCEL": HWACCEL_OPTIONS,
        "BILI_MULTIP_POLICY": BILI_POLICY_OPTIONS,
        "AUDIO_MODE": AUDIO_MODE_OPTIONS,
        "AUDIO_FORMAT": AUDIO_FORMAT_OPTIONS,
        "AUDIO_OUTPUT_FORMAT": ["mp3", "aac", "wav", "flac", "ogg", "opus", "wma", "ac3", "alac"],
        "LIVE_STREAM_METHOD": LIVE_STREAM_METHOD_OPTIONS,
        "LIVE_MODE": LIVE_MODE_OPTIONS,
        "LIVE_DANMAKU_FORMATS": ["srt", "ass", "srt,ass"],
        "TASK_ORDER": TASK_ORDER_OPTIONS,
        "SUBTITLE_TYPE": SUBTITLE_TYPE_OPTIONS,
    }
    integer_ranges = {
        "THREADS": (1, 32),
        "SPEED_LIMIT": (0, 100000),
        "COOKIE_MODE": (1, 2),
        "MP3_BITRATE": (min(MP3_BITRATE_OPTIONS), max(MP3_BITRATE_OPTIONS)),
        "LIVE_DOWNLOAD_TIMEOUT": (0, 1440),
        "LIVE_DANMAKU_OFFSET_MS": (-600000, 600000),
        "LIVE_MAX_RETRIES": (0, 5),
        "LIVE_WATCHDOG_SECONDS": (10, 600),
        "LIVE_MIN_FREE_MB": (64, 102400),
        "LIVE_ESTIMATED_BITRATE_KBPS": (128, 100000),
        "TASK_MODE": (0, 1),
        "TASK_MAX_PARALLEL": (1, 5),
        "TASK_LIVE_PARALLEL": (2, 5),
        "TASK_DOWNLOAD_PARALLEL": (1, 5),
    }
    booleans = {
        "MERGE_MODE", "PROXY_ENABLED", "USE_COOKIES", "EMBED_META",
        "DOWNLOAD_THUMB", "DOWNLOAD_SUBTITLES", "WIN_FILENAMES", "STRICT_FILENAME",
        "NICO_COMMENTS", "NICO_RECODE", "ENABLE_LOG", "DEL_WAV_AFTER_CONVERT",
        "YOUTUBE_PO_TOKEN_ENABLED", "TC_REMEMBER_PASSWORD", "TC_SAVE_PASSWORD_XLSX",
        "TASK_MIXED_PARALLEL", "AUDIO_RECURSIVE",
        "LIVE_DANMAKU_ENABLED", "LIVE_DANMAKU_ANONYMIZE",
        "FANBOX_ENABLED",
        "FANBOX_ANONYMOUS",
    }
    for key, value in values.items():
        if key not in DEFAULT_CONFIG:
            continue
        try:
            if key in enums:
                value = str(value)
                if value not in enums[key]:
                    raise ValueError
            elif key == "TASK_DOWNLOAD_SPEED_LIMIT":
                import math
                value = float(value)
                if not math.isfinite(value) or not 0 <= value <= 100000:
                    raise ValueError
            elif key in integer_ranges:
                value = int(value)
                low, high = integer_ranges[key]
                if value < low or value > high:
                    raise ValueError
            elif key in booleans:
                value = int(value)
                if value not in (0, 1):
                    raise ValueError
            elif key == "PROXY_PORT":
                value = str(value).strip()
                if proxy_enabled:
                    port = int(value)
                    if port < 1 or port > 65535:
                        raise ValueError
            elif key == "PROXY_ADDR":
                value = str(value).strip()
                if proxy_enabled and (
                    not value
                    or "://" in value
                    or "/" in value
                    or "@" in value
                    or any(character.isspace() for character in value)
                ):
                    raise ValueError
            elif key == "FANBOX_OPTIONS":
                from video_downloader.platforms.fanbox.options import options_json
                from video_downloader.platforms.fanbox.errors import FanboxError
                try:
                    value = options_json(value)
                    if value == options_json():
                        value = "{}"
                except FanboxError:
                    raise ValueError from None
            elif key == 'FANBOX_COOKIE_FILE':
                value=str(value).strip()
                if len(value)>4000 or any(char in value for char in '\r\n\0'):
                    raise ValueError
            elif key == "YTDLP_DEFAULT_ARGS":
                value = str(value).strip()
                if len(value) > 4000:
                    raise ValueError
            elif key == 'RPLAY_FIREFOX_PROFILE':
                value = str(value).strip()
                if len(value) > 200 or any(char in value for char in '\r\n\0'):
                    raise ValueError
            elif key == "LIVE_DANMAKU_PLATFORMS":
                import json
                from video_downloader.live.danmaku.preferences import platform_defaults
                value = json.dumps(platform_defaults(value), ensure_ascii=False, sort_keys=True)
            elif key == "LIVE_PLATFORM_MODES":
                import json
                value = str(value).strip() or "{}"
                if len(value) > 2000:
                    raise ValueError
                parsed = json.loads(value)
                if not isinstance(parsed, dict):
                    raise ValueError
            else:
                value = str(value).strip()
                if len(value) > 200:
                    raise ValueError
            result[key] = value
        except (TypeError, ValueError, OverflowError):
            errors.append(_err(key))
    if result["HWACCEL"] != "cpu" and result["OUTPUT_FORMAT"] == "webm":
        result["HWACCEL"] = "cpu"
        hw_err = _err("HWACCEL_WEBM")
        if hw_err not in errors:
            errors.append(hw_err)
    return result, errors
