"""FANBOX URL boundaries. Never accept a caller-supplied arbitrary API host."""
from __future__ import annotations

from dataclasses import dataclass
import re
from urllib.parse import urlsplit, urlunsplit,quote,unquote

from .errors import FanboxError

API_HOST = "api.fanbox.cc"
API_ENDPOINTS = frozenset({"creator.get", "post.paginateCreator", "post.listCreator",
                           "post.info", "post.getComments", "plan.listSupporting", "legacy/support/creator",
                           "creator.listFollowing", "post.listSupporting", "post.listTagged"})
_SLUG = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_-]{0,99}\Z")
_RESERVED = {"www", "api", "downloads", "static", "help", "fanbox"}


@dataclass(frozen=True)
class Source:
    url: str
    creator_id: str
    scope: str = "creator"
    post_id: str | None = None
    tag: str | None = None


def split_http_url(value: str):
    if not isinstance(value, str) or len(value) > 16384 or any(ord(c) < 32 for c in value):
        raise FanboxError("invalid_url", "链接格式无效")
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.port not in (None, 80, 443) or "\\" in value):
            raise ValueError
        return parsed
    except ValueError:
        raise FanboxError("invalid_url", "链接格式无效") from None


def parse_source(value: str) -> Source:
    parsed = split_http_url(value.strip())
    host = parsed.hostname.lower()
    path = parsed.path.rstrip("/")
    parts = path.strip("/").split("/") if path else []
    if host in ("fanbox.cc", "www.fanbox.cc"):
        if path in {'/home/supporting','/creators/supporting'}:
            return Source('https://www.fanbox.cc/creators/supporting','','supporting')
        if path=='/creators/following':
            return Source('https://www.fanbox.cc/creators/following','','following')
        if not parts or not parts[0].startswith("@"):
            raise FanboxError("scope_required", "请提供创作者主页或单篇投稿链接")
        creator, rest = parts[0][1:], parts[1:]
    elif host.endswith(".fanbox.cc") and host.count(".") == 2:
        creator, rest = host.split(".", 1)[0], parts
        if creator in _RESERVED:
            raise FanboxError("invalid_url", "请提供创作者主页链接")
    else:
        raise FanboxError("invalid_url", "不是 FANBOX 创作者链接")
    if not _SLUG.fullmatch(creator):
        raise FanboxError("invalid_url", "创作者标识无效")
    creator = creator.lower()
    canonical = f"https://www.fanbox.cc/@{creator}"
    if rest in ([], ["posts"]):
        return Source(canonical, creator)
    if len(rest) == 2 and rest[0] == "posts" and re.fullmatch(r"[1-9][0-9]*", rest[1]):
        return Source(f"{canonical}/posts/{rest[1]}", creator, "post", rest[1])
    if len(rest)==2 and rest[0]=='tags':
        try:
            if re.search(r'%(?![0-9a-fA-F]{2})',rest[1]):raise ValueError
            tag=unquote(rest[1],errors='strict')
            if not tag or len(tag)>2000 or any(ord(c)<32 for c in tag):raise ValueError
        except (ValueError,UnicodeError):raise FanboxError('invalid_url','标签链接编码无效') from None
        return Source(canonical+'/tags/'+quote(tag,safe=''),creator,'tag',tag=tag)
    raise FanboxError("unsupported_scope", "不支持该 FANBOX 页面范围")


def source_for_options(url,options):
    mode=options['workflow'].get('scope','source')
    if mode=='source':return parse_source(url)
    parsed=split_http_url(url.strip())
    if not (parsed.hostname.lower() in {'fanbox.cc','www.fanbox.cc'} and parsed.path in {'','/','/home'}):
        parse_source(url)
    return parse_source('https://www.fanbox.cc/creators/'+mode)


def validate_api_url(value: str, *, endpoints=API_ENDPOINTS) -> str:
    parsed = split_http_url(value)
    if (parsed.scheme != "https" or parsed.hostname.lower() != API_HOST
            or parsed.port not in (None, 443) or parsed.fragment
            or parsed.path not in {'/'+endpoint for endpoint in endpoints}):
        raise FanboxError("unsafe_api_url", "分页链接超出允许的 FANBOX 接口范围")
    return urlunsplit(("https", API_HOST, parsed.path, parsed.query, ""))


def validate_resource_url(value: str) -> str:
    parsed = split_http_url(value)
    host = parsed.hostname.lower()
    if (parsed.scheme != "https" or parsed.port not in (None, 443)
            or not (host in {"downloads.fanbox.cc", "fanbox.pixiv.net"}
                    or host == "pximg.net" or host.endswith(".pximg.net"))):
        raise FanboxError("unsafe_resource_url", "资源地址不在 FANBOX 已知资源域范围")
    return value
