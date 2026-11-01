"""Pure post/asset decisions, preserving the extension's OR and strict-ID semantics."""
from __future__ import annotations

from .options import timestamp

EXTENSIONS = {"image": {"jpg", "jpeg", "png", "gif", "bmp", "webp"},
              "audio": {"wav", "mp3", "flac"}, "video": {"mp4", "mov", "avi"},
              "archive": {"zip"}, "source": {"psd", "clip"}}


def category(extension):
    return next((key for key, values in EXTENSIONS.items() if extension.lower() in values), "other")


def text_reason(value, rules):
    folded = value.casefold()
    if rules["exclude_enabled"] and any(x.casefold() in folded for x in rules["exclude"]):
        return "keyword_excluded"
    if rules["include_enabled"] and rules["include"] and not any(x.casefold() in folded for x in rules["include"]):
        return "keyword_required"
    return None


def post_reason(post: dict, options: dict):
    filters = options["filters"]
    fee = post["feeRequired"]
    if not filters["include_paid" if fee > 0 else "include_free"]:
        return "fee_type"
    rule = filters["fee"]
    if rule["enabled"]:
        if rule.get('minimum') is not None or rule.get('maximum') is not None:
            if ((rule.get('minimum') is not None and fee<rule['minimum'])
                    or (rule.get('maximum') is not None and fee>rule['maximum'])):
                return 'fee_range'
        elif not {">=": fee >= rule["value"], "<=": fee <= rule["value"], "=": fee == rule["value"]}[rule["op"]]:
            return "fee_range"
    rule = filters["post_id"]
    if rule["enabled"]:
        current, limit = int(post["id"]), int(rule["value"])
        if not (current > limit if rule["op"] == ">" else current < limit):
            return "post_id"
    rule = filters["published"]
    if rule["enabled"] and not timestamp(rule["start"]) <= timestamp(post["publishedDatetime"]) <= timestamp(rule["end"]):
        return "published_at"
    return text_reason(post["title"], filters["title"])


def asset_reason(asset, options):
    if asset.kind == "cover":
        return None if options["content"]["cover"] else "cover_disabled"
    if not options["filters"]["resource_types"][asset.kind]:
        return "resource_type"
    if asset.kind != "image":
        return text_reason(asset.name, options["filters"]["attachment_name"])
    return None
