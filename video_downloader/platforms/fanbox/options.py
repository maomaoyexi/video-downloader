"""Versioned options, strict validation and explicit extension-setting migration."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
import math

from .errors import FanboxError

DEFAULT_OPTIONS = {
    "schema_version": 1,
    "workflow": {"auto_download": True,"scope":"source"},
    "content": {"body": True, "body_formats": ["html"], "raw_snapshot": True,
                "cover": True, "links": True, "comments": False, "comment_max_pages": 20,
                "image_quality": "original", "image_fallback": "ask"},
    "fan_cards": {"enabled": False, "only": False, "scope": "current", "show_username": True},
    "filters": {"include_free": True, "include_paid": True, "max_posts": None,
        "resource_types": dict.fromkeys(("image", "audio", "video", "archive", "source", "other"), True),
        "fee": {"enabled": False, "op": ">=", "value": 500, "minimum": None, "maximum": None},
        "post_id": {"enabled": False, "op": ">", "value": "0"},
        "published": {"enabled": False, "start": None, "end": None},
        "title": {"include_enabled": False, "include": [], "exclude_enabled": False, "exclude": []},
        "attachment_name": {"include_enabled": False, "include": [], "exclude_enabled": False, "exclude": []}},
    "naming": {"post_dir": "{creator_id}/{date} [{post_id}] {title}", "images": "images/{index}-{name}",
               "timezone": "Asia/Shanghai",
               "attachments": "attachments/{name}", "date_format": "YYYY-MM-DD", "zero_pad": True,
               "pad_width": 3, "conflict": "uniquify", "favorites": [], "layout": "post_directory"},
    "network": {"engine": "curl", "api_interval_seconds": 1., "file_concurrency": 2,
                "file_start_interval_seconds": 1., "proxy_policy": "inherit"},
    "quota": {"enabled": True, "limit_gib": 10., "timezone": "Asia/Shanghai", "on_limit": "wait_manual"},
    "archive": {"incremental": True, "refresh_recent_days": 30},
    "external": {"mode": "collect", "recurse_fanbox": False},
    "notifications": {"on_complete": False},
    "ui": {"language": "auto", "theme": "auto", "advanced": False, "bold_keywords": True,
           "folder_tip": True, "show_help": True},
    "compat": {"original_ui": {}},
}

_ENUMS = {
    "workflow.scope": {"source","supporting","following"},
    "content.image_quality": {"original", "thumbnail"}, "content.image_fallback": {"ask", "never", "allow"},
    "fan_cards.scope": {"current", "all_supporting"},
    "filters.fee.op": {">=", "=", "<="}, "filters.post_id.op": {">", "<"},
    "naming.conflict": {"uniquify", "overwrite", "prompt", "skip"},
    "naming.layout": {"post_directory", "legacy_full"}, "network.engine": {"curl", "httpx"},
    "network.proxy_policy": {"inherit", "direct"}, "quota.on_limit": {"wait_manual", "next_day"},
    "external.mode": {"collect"}, "ui.theme": {"auto", "white", "dark"},
    "ui.language": {"auto", "zh-cn", "zh-tw", "ja", "en", "ko", "ru"},
}
_RANGES = {"content.comment_max_pages": (1, 100), "filters.fee.value": (0, 100000000),
    "naming.pad_width": (1, 12), "network.api_interval_seconds": (0, 3600),
    "network.file_start_interval_seconds": (0, 3600), "network.file_concurrency": (1, 3),
    "quota.limit_gib": (0, 102400), "archive.refresh_recent_days": (0, 36500)}


def _invalid(path):
    raise FanboxError("invalid_config", f"FANBOX 配置无效：{path}")


def boolean(value, path):
    if value in (True, False) and isinstance(value, (bool, int)):
        return bool(value)
    if isinstance(value, str) and value.lower() in ("true", "false", "1", "0"):
        return value.lower() in ("true", "1")
    _invalid(path)


def timestamp(value):
    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return datetime.fromtimestamp(value / 1000, timezone.utc)
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError
        return parsed
    except (ValueError, TypeError, AttributeError, OverflowError, OSError):
        _invalid("filters.published")


def normalize_options(value=None) -> dict:
    if isinstance(value, str):
        if len(value.encode("utf-8")) > 65536:
            _invalid("size")
        try:
            value = json.loads(value)
        except (ValueError, RecursionError):
            _invalid("json")
    if value is None:
        value = {}
    if not isinstance(value, dict):
        _invalid("root")

    def merge(default, incoming, prefix=""):
        if not isinstance(incoming, dict):
            _invalid(prefix)
        if set(incoming) - set(default):
            _invalid(prefix or "unknown_field")
        result = copy.deepcopy(default)
        for key, raw in incoming.items():
            path = f"{prefix}.{key}" if prefix else key
            original = default[key]
            if path == "compat.original_ui":
                if not isinstance(raw, dict) or len(json.dumps(raw, ensure_ascii=False)) > 8192:
                    _invalid(path)
                result[key] = copy.deepcopy(raw)
            elif isinstance(original, dict):
                result[key] = merge(original, raw, path)
            elif isinstance(original, bool):
                result[key] = boolean(raw, path)
            elif isinstance(original, list):
                if not isinstance(raw, list) or len(raw) > 1000 or any(not isinstance(x, str) or len(x) > 2000 for x in raw):
                    _invalid(path)
                if path == "content.body_formats" and (not raw or set(raw) - {"txt", "html", "md"}):
                    _invalid(path)
                result[key] = list(dict.fromkeys(raw))
            elif original is None:
                if path in {"filters.fee.minimum","filters.fee.maximum"}:
                    if raw is not None and (type(raw) is not int or not 0 <= raw <= 100000000):
                        _invalid(path)
                    result[key]=raw
                elif path == "filters.max_posts":
                    if raw is not None and (type(raw) is not int or not 1 <= raw <= 1000000):
                        _invalid(path)
                    result[key] = raw
                else:
                    result[key] = timestamp(raw).isoformat() if raw is not None else None
            elif isinstance(original, (float, int)):
                if (isinstance(raw, bool) or not isinstance(raw, (int, float))
                        or (isinstance(raw, float) and not math.isfinite(raw))):
                    _invalid(path)
                if isinstance(original, int) and int(raw) != raw:
                    _invalid(path)
                low, high = _RANGES.get(path, (original, original))
                if not low <= raw <= high:
                    _invalid(path)
                result[key] = int(raw) if isinstance(original, int) else float(raw)
            else:
                if not isinstance(raw, str) or len(raw) > 4000 or any(c in raw for c in "\x00\r\n"):
                    _invalid(path)
                if path in _ENUMS and raw not in _ENUMS[path]:
                    _invalid(path)
                if path == "filters.post_id.value" and (not raw.isascii() or not raw.isdigit()):
                    _invalid(path)
                if path in {"quota.timezone","naming.timezone"}:
                    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
                    try:
                        ZoneInfo(raw)
                    except ZoneInfoNotFoundError:
                        # Windows has no system IANA database. Load the pinned
                        # portable dependency before retrying stdlib resolution.
                        from .runtime import library
                        library("tzdata")
                        try:
                            ZoneInfo(raw)
                        except (ZoneInfoNotFoundError, ValueError):
                            _invalid(path)
                    except ValueError:
                        _invalid(path)
                result[key] = raw
        return result

    result = merge(DEFAULT_OPTIONS, value)
    fee=result['filters']['fee']
    if fee['minimum'] is not None and fee['maximum'] is not None and fee['minimum']>fee['maximum']:
        _invalid('filters.fee')
    if result['fan_cards']['only']:
        result['fan_cards']['enabled']=True
    from .naming import render
    variables=dict.fromkeys(('creator_id','create_id','user_id','uid','user','post_id','postid','title',
        'name','ext','index','date','task_date','fee','tags','PVA'),'value')
    for field in ('post_dir','images','attachments'):
        render(result['naming'][field] or DEFAULT_OPTIONS['naming'][field],variables)
    dates = result["filters"]["published"]
    if dates["enabled"] and (not dates["start"] or not dates["end"] or timestamp(dates["start"]) > timestamp(dates["end"])):
        _invalid("filters.published")
    if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > 65536:
        _invalid("size")
    return result


def options_json(value=None):
    return json.dumps(normalize_options(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


_LEGACY_MAP = {
    **{key: f"filters.resource_types.{target}" for key, target in
       {"image":"image", "music":"audio", "video":"video", "compressed":"archive", "ps":"source", "other":"other"}.items()},
    "free":"filters.include_free", "pay":"filters.include_paid", "feeSwitch":"filters.fee.enabled",
    "feeRange":"filters.fee.op", "fee":"filters.fee.value", "idRangeSwitch":"filters.post_id.enabled",
    "idRangeInput":"filters.post_id.value", "idRange":"filters.post_id.op", "postDate":"filters.published.enabled",
    "postDateStart":"filters.published.start", "postDateEnd":"filters.published.end",
    "saveLink":"content.links", "saveText":"content.body", "textFormat":"content.body_formats",
    "saveComment":"content.comments", "savePostCover":"content.cover", "imageSize":"content.image_quality",
    "userSetName":"naming.images", "nameruleForNonImages":"naming.attachments", "dateFormat":"naming.date_format",
    "zeroPadding":"naming.zero_pad", "zeroPaddingLength":"naming.pad_width", "namingRuleList":"naming.favorites",
    "conflictAction":"naming.conflict", "autoStartDownload":"workflow.auto_download",
    "downloadThread":"network.file_concurrency", "downloadInterval":"network.file_start_interval_seconds",
    "crawlInterval":"network.api_interval_seconds", "deduplication":"archive.incremental",
    "totalDownloadLimitSwitch":"quota.enabled", "totalDownloadLimit":"quota.limit_gib",
    "showNotificationAfterDownloadComplete":"notifications.on_complete", "userSetLang":"ui.language",
    "theme":"ui.theme", "showAdvancedSettings":"ui.advanced", "boldKeywords":"ui.bold_keywords",
    "tipCreateFolder":"ui.folder_tip", "showHowToUse":"ui.show_help",
    "titleMustTextSwitch":"filters.title.include_enabled", "titleMustText":"filters.title.include",
    "titleCannotTextSwitch":"filters.title.exclude_enabled", "titleCannotText":"filters.title.exclude",
    "fileNameIncludeSwitch":"filters.attachment_name.include_enabled", "fileNameInclude":"filters.attachment_name.include",
    "fileNameExcludeSwitch":"filters.attachment_name.exclude_enabled", "fileNameExclude":"filters.attachment_name.exclude",
}
_LEGACY_UI = {"whatIsNewFlag", "unifiedURL", "bgDisplay", "bgOpacity", "bgPositionY"}
LEGACY_KEYS = frozenset(_LEGACY_MAP) | _LEGACY_UI | {"totalDownloadLimitByte"}


def import_plugin_settings(value: dict) -> tuple[dict, list[dict]]:
    if not isinstance(value, dict) or not (set(value) & LEGACY_KEYS):
        _invalid("plugin_settings")
    result, report = {}, []
    for key, raw in value.items():
        status = "mapped"
        if key in _LEGACY_MAP:
            path = _LEGACY_MAP[key].split(".")
            if key == "textFormat": raw = [raw]
            if key == "idRangeInput": raw = str(raw)
            target = result
            for part in path[:-1]: target = target.setdefault(part, {})
            target[path[-1]] = raw
            if key in {'userSetLang','theme','showAdvancedSettings'}:status='follows_application'
            if key in {'tipCreateFolder','showHowToUse'}:status='preserved_not_applied'
        elif key in _LEGACY_UI:
            result.setdefault("compat", {}).setdefault("original_ui", {})[key] = raw
            status = "preserved_not_applied"
        elif key == "totalDownloadLimitByte":
            status = "derived"
        else:
            status = "unknown"
        report.append({"key": key, "status": status})
    if "userSetName" in value or "nameruleForNonImages" in value:
        result.setdefault("naming", {})["layout"] = "legacy_full"
    if "saveText" in value and not boolean(value["saveText"], "saveText"):
        # The extension has no raw-snapshot option; do not silently persist its
        # disabled prose through the new integration's additional source copy.
        result.setdefault("content", {})["raw_snapshot"] = False
    return normalize_options(result), report
