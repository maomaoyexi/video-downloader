"""Six post formats into ordered blocks/assets/links; no network or filesystem IO."""
from __future__ import annotations

import copy
import hashlib
import re
from urllib.parse import unquote, urlsplit

from .errors import FanboxError
from .filters import asset_reason, category
from .links import HtmlContent, LinkCollector, embed_url
from .models import Asset, Post
from .options import normalize_options, timestamp
from .urls import validate_resource_url


def require_post(value: dict, *, detail=True):
    if not isinstance(value, dict):
        raise FanboxError("schema_changed", "投稿响应不是对象")
    for key in ("id", "creatorId", "title", "feeRequired", "publishedDatetime"):
        if key not in value:
            raise FanboxError("schema_changed", f"投稿缺少字段：{key}")
    if (not isinstance(value["id"], str) or not re.fullmatch(r"[1-9][0-9]*", value["id"])
            or not isinstance(value["creatorId"], str) or not isinstance(value["title"], str)
            or type(value["feeRequired"]) is not int or value["feeRequired"] < 0):
        raise FanboxError("schema_changed", "投稿基本字段类型变化")
    try:
        timestamp(value["publishedDatetime"])
    except FanboxError:
        raise FanboxError("schema_changed", "投稿发布时间结构变化") from None
    if (not isinstance(value.get("user", {}), dict) or not isinstance(value.get("tags", []), list)
            or any(not isinstance(tag, str) for tag in value.get("tags", []))):
        raise FanboxError("schema_changed", "投稿用户或标签结构变化")
    if detail and ("body" not in value or not isinstance(value.get("type"), str)):
        raise FanboxError("schema_changed", "投稿详情缺少正文或类型；不能将摘要作为详情解析")
    return value


def parse_post(value: dict, options: dict | None = None) -> Post:
    value = require_post(value)
    options = normalize_options(options)
    post = Post(id=value["id"], creator_id=value["creatorId"],
        user_id=str(value.get("user", {}).get("userId", "")), title=value["title"], type=value["type"],
        published_at=value["publishedDatetime"], updated_at=value.get("updatedDatetime", value["publishedDatetime"]),
        fee=value["feeRequired"], tags=list(value.get("tags") or []),
        access="restricted" if value["body"] is None or value.get("isRestricted") else "accessible",
        source=copy.deepcopy(value) if options["content"]["raw_snapshot"] else None)
    links = LinkCollector(f"https://www.fanbox.cc/@{post.creator_id}/posts/{post.id}")
    seen_assets = set()

    def add_asset(data, *, kind=None, index=0):
        if not isinstance(data, dict):
            post.warnings.append("missing_asset")
            return None
        image = kind == "image"
        url = data.get("originalUrl" if image else "url")
        if not isinstance(url, str):
            post.warnings.append("missing_asset_url")
            return None
        try:
            validate_resource_url(url)
        except FanboxError:
            post.warnings.append("unsafe_asset_url")
            return None
        name = unquote(urlsplit(url).path.rsplit("/", 1)[-1])
        extension = str(data.get("extension") or name.rsplit(".", 1)[-1]).lower()
        asset_id = str(data.get("id") or hashlib.sha256(url.encode()).hexdigest()[:24])
        variant = options["content"]["image_quality"] if image else "original"
        if image and variant == "thumbnail":
            candidate = data.get("thumbnailUrl")
            try:
                validate_resource_url(candidate)
                url = candidate
            except (FanboxError, TypeError):
                post.warnings.append("missing_thumbnail")
                return None
        key = (asset_id, kind or category(extension), variant)
        if key in seen_assets: return asset_id
        seen_assets.add(key)
        size = data.get("size")
        resource_index = 0 if kind == "cover" else 1 + sum(a.kind != "cover" for a in post.assets)
        asset = Asset(asset_id, kind or category(extension), str(data.get("name") or name.rsplit(".", 1)[0]),
                      extension, url, variant, resource_index, size if type(size) is int and size >= 0 else None,
                      data.get("width"), data.get("height"), data.get("thumbnailUrl"))
        asset.skip_reason = asset_reason(asset, options)
        asset.selected = asset.skip_reason is None
        post.assets.append(asset)
        return asset_id

    cover_data = value.get("cover") or {}
    if not isinstance(cover_data, dict):
        raise FanboxError("schema_changed", "投稿封面结构变化")
    cover = value.get("coverImageUrl") or cover_data.get("url")
    if cover is not None and not isinstance(cover, str):
        raise FanboxError("schema_changed", "投稿封面地址结构变化")
    if cover:
        cover = re.sub(r"/c/[0-9a-z_]+/", "/", cover)
        add_asset({"id": "cover", "url": cover}, kind="cover")
    body = value["body"]
    if post.access == "restricted":
        return post
    if not isinstance(body, dict):
        raise FanboxError("schema_changed", "投稿正文结构变化")

    def add_text(text, index, block_type="p", raw=None):
        if not isinstance(text, str):
            raise FanboxError("schema_changed", "投稿文本结构变化")
        post.blocks.append({"type": block_type, "text": text,
                            "styles": copy.deepcopy((raw or {}).get("styles", [])),
                            "links": copy.deepcopy((raw or {}).get("links", []))})
        links.text(text, source="body", index=index)
        for link in (raw or {}).get("links", []):
            if not isinstance(link, dict):
                raise FanboxError("schema_changed", "段落链接结构变化")
            links.add(link.get("url"), source="block_link", index=index, context=text)

    def add_embed(data, index, *, url_embed=False):
        if not isinstance(data, dict):
            post.warnings.append("missing_embed")
            return
        if not url_embed:
            urls = [embed_url(data)]
        elif data.get("type") == "default": urls = [data.get("url")]
        elif data.get("type") in {"html", "html.card"}: urls = HtmlContent(data.get("html", "")).references
        elif data.get("type") == "fanbox.post":
            info = data.get("postInfo", {})
            urls = [f"https://www.fanbox.cc/@{info['creatorId']}/posts/{info['id']}"] if "creatorId" in info and "id" in info else []
        else: urls = []
        found = [links.add(url, source="embed", index=index, context="") for url in urls if url]
        post.blocks.append({"type": "embed", "urls": [url for url in found if url]})
        if not any(found):
            post.warnings.append("unknown_embed")
            post.blocks[-1]["raw"] = copy.deepcopy(data)

    if post.type == "article":
        if not isinstance(body.get("blocks"), list):
            raise FanboxError("schema_changed", "article 缺少 blocks")
        for name in ("imageMap", "fileMap", "embedMap", "urlEmbedMap"):
            if name in body and not isinstance(body[name], dict):
                raise FanboxError("schema_changed", f"article 的 {name} 结构变化")
        for index, block in enumerate(body["blocks"], 1):
            if not isinstance(block, dict):
                raise FanboxError("schema_changed", "投稿 block 结构变化")
            kind = block.get("type")
            if kind in {"p", "header"}: add_text(block.get("text", ""), index, kind, block)
            elif kind in {"image", "file"}:
                resource = (body.get(kind + "Map") or {}).get(block.get(kind + "Id"))
                ref = add_asset(resource, kind="image" if kind == "image" else None, index=index)
                post.blocks.append({"type": kind, "asset_id": ref})
            elif kind in {"embed", "url_embed"}:
                map_key, id_key = ("embedMap", "embedId") if kind == "embed" else ("urlEmbedMap", "urlEmbedId")
                add_embed((body.get(map_key) or {}).get(block.get(id_key)), index, url_embed=kind == "url_embed")
            else:
                post.blocks.append({"type": "unknown", "raw": copy.deepcopy(block)})
                post.warnings.append("unknown_block")
    elif post.type in {"image", "file", "text", "video"}:
        add_text(body.get("text", ""), 0)
        key = {"image": "images", "file": "files"}.get(post.type)
        if key:
            if not isinstance(body.get(key), list):
                raise FanboxError("schema_changed", f"投稿缺少 {key}")
            for index, resource in enumerate(body[key], 1):
                ref = add_asset(resource, kind="image" if key == "images" else None, index=index)
                post.blocks.append({"type": "image" if key == "images" else "file", "asset_id": ref})
        if post.type == "video": add_embed(body.get("video"), 1)
    elif post.type == "entry":
        html = HtmlContent(body.get("html", ""))
        add_text(html.text, 0)
        for url in html.references: links.add(url, source="entry_html", context=html.text)
        for index, image in enumerate(html.images, 1):
            url = image["original"] or image["src"]
            # A surrounding ordinary web link is not an original image URL.
            try: validate_resource_url(url)
            except (FanboxError, TypeError): url = image["src"]
            ref = add_asset({"originalUrl": url, "thumbnailUrl": image["src"]}, kind="image", index=index)
            post.blocks.append({"type": "image", "asset_id": ref})
    else:
        post.blocks.append({"type": "unknown", "raw": copy.deepcopy(body)})
        post.warnings.append("unknown_post_type")
    post.links = links.links if options["content"]["links"] else []
    if not options["content"]["body"]:
        # Derived prose and explicit raw snapshots have independent switches.
        for block in post.blocks:
            if "text" in block: block["text"] = ""
    return post
