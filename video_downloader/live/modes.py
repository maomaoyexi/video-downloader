"""直播录制的领域模型与平台能力注册表。

该模块只包含纯数据和纯函数，不依赖 UI、下载执行器或 yt-dlp 子进程。
新增平台时优先扩充 ``CAPABILITIES``，不要在命令构造/执行器中写平台分支。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping


class LiveMode(str, Enum):
    """一次直播任务的录制语义。"""

    AUTO = "auto"
    CATCH_UP = "catch_up"
    LIVE_EDGE = "live_edge"
    # 预留给 P1 的持久化等待；当前不允许直接启动。
    WAIT = "wait"

    @classmethod
    def parse(cls, value: "LiveMode | str | None") -> "LiveMode":
        if isinstance(value, cls):
            return value
        if value is None or str(value).strip() == "":
            return cls.AUTO
        try:
            return cls(str(value).strip().lower())
        except ValueError as exc:
            allowed = ", ".join(mode.value for mode in cls)
            raise LiveModeError(f"未知直播模式: {value}（可选: {allowed}）") from exc


class Support(str, Enum):
    """平台能力的三态；CONDITIONAL 必须探测后才可启用。"""

    SUPPORTED = "supported"
    CONDITIONAL = "conditional"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class PlatformCapability:
    """一个平台的直播能力声明。"""

    catch_up: Support
    catch_up_reason: str = ""
    live_edge: bool = True
    wait: bool = True


# 平台名必须与 core.constants.PLATFORM_INFO 的 name 一致。
CAPABILITIES: Mapping[str, PlatformCapability] = MappingProxyType({
    "YouTube": PlatformCapability(
        catch_up=Support.CONDITIONAL,
        catch_up_reason="DVR/归档可用时才能从头；主播可关闭 DVR",
    ),
    "Twitch": PlatformCapability(
        catch_up=Support.CONDITIONAL,
        catch_up_reason="仅本场增长中 VOD 可见时才能从头",
    ),
    "Bilibili": PlatformCapability(
        catch_up=Support.UNSUPPORTED,
        catch_up_reason="普通观看侧没有 DVR/历史分片",
    ),
    "Niconico": PlatformCapability(
        catch_up=Support.CONDITIONAL,
        catch_up_reason="需要 chasePlay 权限；P4 探测后启用",
    ),
    "NicoChannel": PlatformCapability(
        catch_up=Support.CONDITIONAL,
        catch_up_reason="需要 allow_dvr_flg；P4 探测后启用",
    ),
    "TwitCasting": PlatformCapability(
        catch_up=Support.CONDITIONAL,
        catch_up_reason="仅会员追っかけ且主播开启；窗口极短",
    ),
    "Twitter": PlatformCapability(
        catch_up=Support.CONDITIONAL,
        catch_up_reason="依赖活动清单或 replay 开关；P4 探测后启用",
    ),
    "Withny": PlatformCapability(
        catch_up=Support.UNSUPPORTED,
        catch_up_reason="无公开 DVR 证据",
    ),
    "Rplay": PlatformCapability(
        catch_up=Support.UNSUPPORTED,
        catch_up_reason="尚无可验证的 DVR",
        live_edge=True,
        wait=True,
    ),
})

_UNKNOWN_CAPABILITY = PlatformCapability(
    catch_up=Support.UNSUPPORTED,
    catch_up_reason="未知平台，默认只允许从当前时刻录制",
)


class LiveModeError(ValueError):
    """直播模式不可用或参数非法。"""


@dataclass(frozen=True)
class LiveDecision:
    """模式解析结果；命令构造只消费这个对象。"""

    is_live: bool
    platform: str
    requested_mode: LiveMode
    mode: LiveMode | None
    reason: str = ""

    @property
    def effective_mode(self) -> LiveMode | None:
        return self.mode


def capability_for(platform: str | None) -> PlatformCapability:
    if not platform:
        return _UNKNOWN_CAPABILITY
    return CAPABILITIES.get(platform, _UNKNOWN_CAPABILITY)


def auto_mode_for(platform: str | None) -> LiveMode:
    """自动模式的默认策略：目前只有 YouTube/Twitch 尝试追开播。"""
    if platform in {"YouTube", "Twitch"}:
        return LiveMode.CATCH_UP
    return LiveMode.LIVE_EDGE


def resolve_mode(platform: str | None, requested_mode: "LiveMode | str | None") -> LiveMode:
    """把用户请求解析成实际模式；不可用时抛 LiveModeError。"""
    requested = LiveMode.parse(requested_mode)
    if requested is LiveMode.AUTO:
        requested = auto_mode_for(platform)

    capability = capability_for(platform)
    if requested is LiveMode.CATCH_UP:
        if capability.catch_up is Support.SUPPORTED or platform in {"YouTube", "Twitch"}:
            return requested
        if capability.catch_up is Support.CONDITIONAL:
            raise LiveModeError(
                f"{platform or '未知平台'} 的追开播是条件能力，需要先探测；"
                "当前请选择“从当前时刻”或“自动”"
            )
        raise LiveModeError(
            f"{platform or '未知平台'} 不支持追开播：{capability.catch_up_reason}"
        )
    if requested is LiveMode.LIVE_EDGE:
        if capability.live_edge:
            return requested
        raise LiveModeError(f"{platform or '未知平台'} 不支持从当前时刻录制")
    if requested is LiveMode.WAIT:
        raise LiveModeError("蹲开播（WAIT）尚未在 P0/P1 中启用")
    raise LiveModeError(f"无法解析直播模式: {requested.value}")


def decide_live(
    platform: str | None,
    requested_mode: "LiveMode | str | None",
    is_live: bool,
) -> LiveDecision:
    """生成一次直播决策；非直播 URL 不解析模式。"""
    requested = LiveMode.parse(requested_mode)
    if not is_live:
        return LiveDecision(
            is_live=False,
            platform=platform or "",
            requested_mode=requested,
            mode=None,
            reason="非直播 URL",
        )
    mode = resolve_mode(platform, requested)
    capability = capability_for(platform)
    reason = capability.catch_up_reason if mode is LiveMode.CATCH_UP else ""
    return LiveDecision(
        is_live=True,
        platform=platform or "",
        requested_mode=requested,
        mode=mode,
        reason=reason,
    )
