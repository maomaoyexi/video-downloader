"""任务前的直播检查（Inspection）。

把 URL 分类、Probe、平台能力合成给 UI 的一次性结果：
- 是否直播目标；
- 当前状态、已开播时长；
- 是否支持蹲开播；
- 可用录制模式、推荐模式、是否需要降级及原因。
"""

from __future__ import annotations

import time
from typing import Callable

from .modes import LiveMode, Support, auto_mode_for, capability_for
from .probe import LiveStatus, ProbeService
from .urls import TargetKind, classify_target, expand_short_url


class LiveInspector:
    def __init__(
        self,
        probe_service: ProbeService,
        *,
        clock: Callable[[], float] = time.time,
        url_resolver: Callable[[str], str] = expand_short_url,
    ):
        self._probe_service = probe_service
        self._clock = clock
        self._url_resolver = url_resolver

    def inspect(self, url: str, requested_mode: LiveMode | str | None = "auto") -> dict:
        resolved_url = self._url_resolver((url or "").strip()) or (url or "").strip()
        target = classify_target(resolved_url)
        platform = target.platform or ""
        base = {
            "is_live_target": target.kind in {TargetKind.CHANNEL, TargetKind.EVENT},
            "url": target.url,
            "platform": platform,
            "kind": target.kind.value,
            "stable_id": target.stable_id,
            "reason": target.reason,
        }
        if not base["is_live_target"]:
            return base
        if platform == "Withny":
            base.update({
                "status": LiveStatus.UNKNOWN.value,
                "can_wait": False,
                "wait_reason": "Withny 使用 withny-dl 专用监控",
                "modes": [],
                "error": "Withny 请使用专用 withny-dl 配置监控，不支持通用直播检查",
            })
            return base

        capability = capability_for(platform)
        probe = self._probe_service.probe(target, timeout=20.0)
        now = self._clock()
        requested = _safe_mode(requested_mode)
        catch_up_available = probe.catch_up_available and capability.catch_up is not Support.UNSUPPORTED
        catch_up_reason = (capability.catch_up_reason if capability.catch_up is Support.UNSUPPORTED
                           else probe.catch_up_reason or capability.catch_up_reason)
        modes = [
            {
                "value": LiveMode.CATCH_UP.value,
                "label": "追开播",
                "available": catch_up_available,
                "reason": catch_up_reason,
            },
            {
                "value": LiveMode.LIVE_EDGE.value,
                "label": "从当前时刻",
                "available": capability.live_edge,
                "reason": "" if capability.live_edge else "平台不支持当前时刻录制",
            },
        ]
        can_wait = (
            target.can_watch
            and capability.wait
            and platform != "Withny"
        )
        base.update({
            "status": probe.status.value,
            "title": probe.title,
            "uploader": probe.uploader,
            "started_at": probe.started_at,
            "scheduled_start": probe.scheduled_start,
            "live_duration_seconds": (
                max(0, int(now - probe.started_at))
                if probe.started_at and probe.status is LiveStatus.LIVE else None
            ),
            "can_wait": can_wait,
            "wait_reason": "" if can_wait else _wait_reason(platform, capability.wait),
            "modes": modes,
            "probe_error": probe.error,
            "source": probe.source,
            "catch_up_reason": catch_up_reason,
        })

        if probe.status is LiveStatus.LIVE:
            if not capability.live_edge and not catch_up_available:
                base.update({"recommended_mode": "", "effective_mode": "", "warning": "",
                             "downgraded": False, "error": f"{platform} 当前未开放直播录制"})
                return base
            effective = _choose_live_mode(platform, requested, catch_up_available)
            warning = ""
            if (requested is LiveMode.CATCH_UP or (requested is LiveMode.AUTO and
                    auto_mode_for(platform) is LiveMode.CATCH_UP)) and not catch_up_available:
                label = "不支持追开播" if capability.catch_up is Support.UNSUPPORTED else "追开播不可用"
                warning = f"{platform} {label}：{catch_up_reason}；已降级为从当前时刻录制"
            base.update({
                "recommended_mode": effective.value,
                "effective_mode": effective.value,
                "warning": warning,
                "downgraded": bool(warning),
            })
            return base

        if probe.status in {LiveStatus.OFFLINE, LiveStatus.UPCOMING}:
            if can_wait:
                base.update({
                    "recommended_mode": LiveMode.WAIT.value,
                    "effective_mode": LiveMode.WAIT.value,
                    "warning": "",
                    "downgraded": False,
                })
            else:
                base.update({
                    "recommended_mode": "",
                    "effective_mode": "",
                    "warning": "",
                    "downgraded": False,
                    "error": f"直播尚未开始，且 {platform or '该平台'} 不支持蹲开播"
                             + (f"：{base['wait_reason']}" if base["wait_reason"] else ""),
                })
            return base

        message = probe.error or {
            LiveStatus.ENDED: "直播已结束",
            LiveStatus.PRIVATE: "需要登录或没有观看权限",
            LiveStatus.ERROR: "直播状态探测失败",
            LiveStatus.UNKNOWN: "无法确认直播状态",
        }.get(probe.status, "无法确认直播状态")
        base.update({
            "recommended_mode": "",
            "effective_mode": "",
            "warning": "",
            "downgraded": False,
            "error": message,
        })
        return base


def _safe_mode(value) -> LiveMode:
    try:
        return LiveMode.parse(value)
    except Exception:
        return LiveMode.AUTO


def _choose_live_mode(platform: str, requested: LiveMode, catch_up_available: bool) -> LiveMode:
    if requested is LiveMode.CATCH_UP:
        return LiveMode.CATCH_UP if catch_up_available else LiveMode.LIVE_EDGE
    if requested is LiveMode.LIVE_EDGE:
        return LiveMode.LIVE_EDGE
    # auto / wait：直播已经开始时 wait 无意义，按平台默认执行。
    effective = auto_mode_for(platform)
    if effective is LiveMode.CATCH_UP and not catch_up_available:
        return LiveMode.LIVE_EDGE
    return effective


def _wait_reason(platform: str, wait_supported: bool) -> str:
    if platform == "Withny":
        return "Withny 使用 withny-dl 专用监控"
    if not wait_supported:
        return "平台能力未声明支持"
    return "该 URL 不是可蹲守的频道/事件入口"
