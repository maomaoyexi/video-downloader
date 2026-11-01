"""Load only in-scope, unexpired Netscape cookies without exposing values."""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from http.cookiejar import CookieJar, DefaultCookiePolicy, LoadError, MozillaCookieJar
from pathlib import Path

from .errors import FanboxError


def cookie_policy():
    return DefaultCookiePolicy(strict_ns_domain=DefaultCookiePolicy.DomainStrictNonDomain)


@dataclass(frozen=True)
class Credentials:
    jar: CookieJar = field(repr=False)

    @property
    def has_session(self) -> bool:
        return any(c.name == "FANBOXSESSID" and c.value and not c.is_expired() for c in self.jar)


def load_credentials(path: str | Path | None = None) -> Credentials:
    jar = CookieJar(policy=cookie_policy())
    if path is None:
        return Credentials(jar)
    try:
        file = Path(path)
        if file.stat().st_size > 2 * 1024 * 1024:
            raise FanboxError("cookie_file", "Cookie 文件超过大小限制")
        source = MozillaCookieJar(str(file))
        source.load(ignore_discard=True, ignore_expires=True)
        for cookie in source:
            # Common cookies.txt exporters encode session cookies with expiry 0.
            if cookie.expires == 0:
                cookie.expires, cookie.discard = None, True
            if cookie.is_expired():
                continue
            domain = cookie.domain.lstrip(".").lower()
            if domain == "fanbox.cc" or domain.endswith(".fanbox.cc"):
                jar.set_cookie(copy.copy(cookie))
    except (OSError, LoadError, UnicodeError, ValueError):
        raise FanboxError("cookie_file", "无法读取有效的 Netscape Cookie 文件") from None
    return Credentials(jar)
