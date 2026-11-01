"""Normalized content model. A missing summary body is never a restricted post."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Asset:
    id: str
    kind: str
    name: str
    extension: str
    url: str = field(repr=False)
    variant: str = "original"
    index: int = 0
    size: int | None = None
    width: int | None = None
    height: int | None = None
    thumbnail_url: str | None = field(default=None, repr=False)
    selected: bool = True
    skip_reason: str | None = None


@dataclass
class Link:
    url: str = field(repr=False)
    kind: str = "web"
    occurrences: list[dict] = field(default_factory=list, repr=False)


@dataclass
class Post:
    id: str
    creator_id: str
    user_id: str
    title: str
    type: str
    published_at: str
    updated_at: str
    fee: int
    tags: list[str]
    access: str
    blocks: list[dict] = field(default_factory=list, repr=False)
    assets: list[Asset] = field(default_factory=list, repr=False)
    links: list[Link] = field(default_factory=list, repr=False)
    comments: list[dict] = field(default_factory=list, repr=False)
    comments_complete: bool = True
    warnings: list[str] = field(default_factory=list)
    selected: bool = True
    skip_reason: str | None = None
    source: dict | None = field(default=None, repr=False)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        fields = dict(value)
        fields["assets"] = [Asset(**a) for a in fields["assets"]]
        fields["links"] = [Link(**link) for link in fields["links"]]
        return cls(**fields)
