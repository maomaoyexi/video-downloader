from .constants import (
    AUDIO_OPTIONS,
    AUDIO_SEP_OPTIONS,
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
    }
    integer_ranges = {
        "AUDIO_SEP_MODE": (0, len(AUDIO_SEP_OPTIONS)),
        "THREADS": (1, 32),
        "SPEED_LIMIT": (0, 100000),
        "COOKIE_MODE": (1, 2),
        "MP3_BITRATE": (min(MP3_BITRATE_OPTIONS), max(MP3_BITRATE_OPTIONS)),
    }
    booleans = {
        "MERGE_MODE", "PROXY_ENABLED", "USE_COOKIES", "EMBED_META",
        "DOWNLOAD_THUMB", "WIN_FILENAMES", "STRICT_FILENAME", "NICO_COMMENTS",
        "NICO_RECODE", "ENABLE_LOG", "DEL_WAV_AFTER_CONVERT",
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
            errors.append(key)
    if result["MERGE_MODE"] == 0 and result["AUDIO_SEP_MODE"] > 0:
        result["AUDIO_SEP_MODE"] = 0
    if result["HWACCEL"] != "cpu" and result["OUTPUT_FORMAT"] == "webm":
        result["HWACCEL"] = "cpu"
        if "HWACCEL" not in errors:
            errors.append("HWACCEL")
    return result, errors
