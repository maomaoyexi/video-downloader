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
    MP3_BITRATE_OPTIONS,
    PLATFORM_INFO,
    PROXY_TYPE_OPTIONS,
    RESOLUTION_OPTIONS,
)

# 校验错误的中文说明（key → 错误详情映射）
_ERROR_REASONS = {
    "PLATFORM": "平台选项无效",
    "RESOLUTION": "分辨率选项无效",
    "CODEC": "编码选项无效",
    "AUDIO_QUALITY": "音频质量选项无效",
    "OUTPUT_FORMAT": "输出格式选项无效",
    "PROXY_TYPE": "代理类型仅支持 http/socks5",
    "BROWSER_NAME": "浏览器选项无效",
    "HWACCEL": "硬件加速选项无效",
    "BILI_MULTIP_POLICY": "B站多P策略选项无效",
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
    "WIN_FILENAMES": "Win文件名兼容仅支持 0 或 1",
    "STRICT_FILENAME": "严格文件名仅支持 0 或 1",
    "NICO_COMMENTS": "Niconico弹幕仅支持 0 或 1",
    "NICO_RECODE": "Niconico重编码仅支持 0 或 1",
    "ENABLE_LOG": "日志开关仅支持 0 或 1",
    "DEL_WAV_AFTER_CONVERT": "删除WAV仅支持 0 或 1",
    "HWACCEL_WEBM": "WebM输出格式不支持硬件加速，已自动回退为CPU编码",
}


def _err(key):
    """构建校验错误信息：`字段名：原因`。"""
    reason = _ERROR_REASONS.get(key, "未知校验错误")
    return f"{key}：{reason}"


def validate_config(values, base=None):
    result = dict(DEFAULT_CONFIG if base is None else base)
    errors = []
    proxy_enabled = values.get("PROXY_ENABLED", result["PROXY_ENABLED"])
    try:
        proxy_enabled = int(proxy_enabled) == 1
    except (TypeError, ValueError):
        proxy_enabled = bool(result["PROXY_ENABLED"])
    enums = {
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
    }
    integer_ranges = {
        "THREADS": (1, 32),
        "SPEED_LIMIT": (0, 100000),
        "COOKIE_MODE": (1, 2),
        "MP3_BITRATE": (min(MP3_BITRATE_OPTIONS), max(MP3_BITRATE_OPTIONS)),
    }
    booleans = {
        "MERGE_MODE", "PROXY_ENABLED", "USE_COOKIES", "EMBED_META",
        "DOWNLOAD_THUMB", "WIN_FILENAMES", "STRICT_FILENAME",
        "NICO_COMMENTS", "NICO_RECODE", "ENABLE_LOG", "DEL_WAV_AFTER_CONVERT",
    }
    for key, value in values.items():
        if key not in DEFAULT_CONFIG:
            continue
        try:
            if key in enums:
                value = str(value)
                if value not in enums[key]:
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
            else:
                value = str(value).strip()
                if len(value) > 200:
                    raise ValueError
            result[key] = value
        except (TypeError, ValueError):
            errors.append(_err(key))
    if result["HWACCEL"] != "cpu" and result["OUTPUT_FORMAT"] == "webm":
        result["HWACCEL"] = "cpu"
        hw_err = _err("HWACCEL_WEBM")
        if hw_err not in errors:
            errors.append(hw_err)
    return result, errors
