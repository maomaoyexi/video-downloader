"""保留旧导入路径的直播能力门面。应用内部直接使用对应的领域函数。"""

from __future__ import annotations

from .arguments import LiveArgumentStrategy, build_live_arguments
from .classifier import is_live_url
from .modes import (
    CAPABILITIES,
    LiveDecision,
    LiveMode,
    LiveModeError,
    PlatformCapability,
    capability_for,
    decide_live,
    resolve_mode,
)


class LiveService:
    """面向应用层的直播能力入口。"""

    def is_live_url(self, url: str, platform: str | None = None) -> bool:
        return is_live_url(url, platform)

    def decide(
        self,
        platform: str | None,
        requested_mode: "LiveMode | str | None",
        is_live: bool,
    ) -> LiveDecision:
        return decide_live(platform, requested_mode, is_live)

    def resolve_mode(self, platform: str | None, requested_mode: "LiveMode | str | None") -> LiveMode:
        return resolve_mode(platform, requested_mode)

    def arguments(
        self,
        platform: str | None,
        requested_mode: "LiveMode | str | None",
        is_live: bool,
        strategy: LiveArgumentStrategy | None = None,
    ) -> tuple[str, ...]:
        if strategy is None:
            return build_live_arguments(platform, requested_mode, is_live)
        return build_live_arguments(platform, requested_mode, is_live, strategy=strategy)

    def capability(self, platform: str | None) -> PlatformCapability:
        return capability_for(platform)


LIVE_SERVICE = LiveService()

__all__ = [
    "CAPABILITIES",
    "LIVE_SERVICE",
    "LiveDecision",
    "LiveMode",
    "LiveModeError",
    "LiveService",
    "PlatformCapability",
    "capability_for",
    "decide_live",
    "is_live_url",
    "resolve_mode",
]
