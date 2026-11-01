"""Link occurrences, text context and HTML attributes without executing HTML."""
from __future__ import annotations

from html import unescape
from html.parser import HTMLParser
import re
from urllib.parse import quote, urljoin, urlsplit

from .errors import FanboxError
from .models import Link
from .urls import split_http_url


def clean_link(value: str, base: str) -> str | None:
    if not isinstance(value, str):
        return None
    value = unescape(value.strip())
    if value.startswith(("javascript:", "data:", "file:", "mailto:")):
        return None
    value = urljoin(base, value)
    try:
        split_http_url(value)
    except FanboxError:
        return None
    return value


def text_links(text: str):
    for match in re.finditer(r'https?://[^\s<>"\x00]+', unescape(text)):
        value = match.group().rstrip("，。；：！？、.,;:'\u300d\u300f\u300b")
        for close, opening in ((")", "("), ("]", "["), ("}", "{")):
            while value.endswith(close) and value.count(close) > value.count(opening):
                value = value[:-1]
        yield value


def link_kind(url):
    host = urlsplit(url).hostname.lower()
    if host in {"drive.google.com", "docs.google.com", "mega.nz", "mega.io", "www.dropbox.com", "dropbox.com"}:
        return "share"
    if host == "fanbox.cc" or host.endswith(".fanbox.cc"):
        return "fanbox"
    if any(host == h or host.endswith("." + h) for h in ("youtube.com", "youtu.be", "vimeo.com", "soundcloud.com", "twitter.com", "x.com")):
        return "media"
    return "web"


class LinkCollector:
    def __init__(self, base):
        self.base = base
        self._links: dict[str, Link] = {}

    @property
    def links(self):
        return list(self._links.values())

    def add(self, value, *, source, index=None, context="", comment_id=None):
        url = clean_link(value, self.base)
        if not url:
            return None
        link = self._links.setdefault(url, Link(url, link_kind(url)))
        occurrence = {"source": source, "block_index": index, "context": context}
        if comment_id is not None:
            occurrence["comment_id"] = comment_id
        if occurrence not in link.occurrences:
            link.occurrences.append(occurrence)
        return url

    def text(self, value, **context):
        for link in text_links(value):
            self.add(link, context=value, **context)


def embed_url(value: dict):
    provider = value.get("serviceProvider")
    content = value.get("contentId", value.get("videoId"))
    if not isinstance(content, str) or not content:
        return None
    if provider == "youtube": return "https://www.youtube.com/watch?v=" + quote(content, safe="")
    if provider == "vimeo": return "https://vimeo.com/" + quote(content, safe="")
    if provider == "soundcloud": return "https://soundcloud.com/" + content.lstrip("/")
    if provider == "twitter": return "https://twitter.com/i/web/status/" + quote(content, safe="")
    if provider == "google_forms": return "https://docs.google.com/forms/d/e/" + quote(content, safe="") + "/viewform"
    if provider == "gist": return "https://gist.github.com/" + content.lstrip("/")
    if provider == "fanbox": return "https://www.fanbox.cc/" + content.lstrip("/")
    return None


class HtmlContent(HTMLParser):
    def __init__(self, html: str):
        super().__init__(convert_charrefs=True)
        self.text_parts, self.references, self.images = [], [], []
        self._anchor, self._ignored = [], 0
        self.feed(html)
        self.close()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {"script", "style"}: self._ignored += 1
        if self._ignored: return
        if tag == "a": self._anchor.append(attrs.get("href"))
        for key in ("href", "src"):
            if tag in {"a", "iframe"} and attrs.get(key):
                self.references.append(attrs[key])
        if tag == "img":
            self.images.append({"original": attrs.get("data-src-original") or (self._anchor[-1] if self._anchor else None),
                                "src": attrs.get("src"), "width": attrs.get("width"), "height": attrs.get("height")})
        if tag in {"p", "br", "div", "h1", "h2", "h3", "li"}: self.text_parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self._ignored = max(0, self._ignored - 1)
        if tag == "a" and self._anchor: self._anchor.pop()
        if tag in {"p", "div", "li"} and not self._ignored: self.text_parts.append("\n")

    def handle_data(self, data):
        if not self._ignored: self.text_parts.append(data)

    @property
    def text(self):
        return "".join(self.text_parts).strip()
