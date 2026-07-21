"""
core.models - 共享值对象、结构化 Protocol 和数据类。
所有模块依赖此文件，它只依赖标准库。
Protocol 使用 typing.Protocol 实现结构化子类型，这样现有类无需修改即可满足。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, runtime_checkable


# ============================================================
# Dataclasses — 值对象
# ============================================================

@dataclass(frozen=True)
class TaskHandle:
    """下载任务句柄，每个任务有唯一代际号防止旧回调污染新任务状态。"""
    generation: int
    kind: str                   # "single" | "batch"
    cancel_event: threading.Event


@dataclass(frozen=True)
class StopTicket:
    """停止请求凭证，携带当前进程引用和代际号。"""
    process: object             # subprocess.Popen | None
    active: bool
    generation: int


@dataclass
class ProgressData:
    """下载进度数据，通过 SSE 推送到前端。"""
    percent: float = 0.0        # -1 表示直播模式
    status: str = "就绪"
    speed: str = ""
    eta: str = ""


@dataclass
class BatchStats:
    """批量下载统计。"""
    ok: int = 0
    fail: int = 0
    total: int = 0
    current: int = 0


@dataclass
class LogEntry:
    """单条日志记录。"""
    time: str
    msg: str
    level: str                  # "info" | "success" | "warn" | "error"


@dataclass(frozen=True)
class ExecutorCallbacks:
    """DownloadExecutor 的回调包 -- 将 6 个独立回调合并为 1 个参数。"""
    log: Callable[[str, str], None]
    update_progress: Callable[..., None]   # (percent, status="", speed="", eta="")
    broadcast_state: Callable[[], None]
    add_history: Callable[..., None]  # (url, title, platform, status, filepath=None)
    cancel_idle_timer: Callable[[], None]
    start_idle_timer: Callable[[], None]


@dataclass(frozen=True)
class UpdaterCallbacks:
    """UpdaterService 的回调包 -- 将 3 个独立回调合并为 1 个参数。"""
    emit_event: Callable[[str, Any], None]
    log: Callable[[str, str], None]
    broadcast_state: Callable[[], None]


@dataclass(frozen=True)
class StorageCallbacks:
    """StorageService 的回调包。"""
    log: Callable[[str, str], None]
    emit_event: Callable[[str, Any], None]


# ============================================================
# Protocols — 结构化接口（零运行时开销）
# ============================================================

@runtime_checkable
class AppStateProvider(Protocol):
    """AppState 的结构化接口。"""
    config: dict
    config_lock: threading.RLock
    sse_clients: list
    log_history: list
    download_thread_context: threading.local
    progress_data: ProgressData
    batch_stats: BatchStats

    def config_snapshot(self) -> dict: ...
    def replace_config(self, values: dict) -> None: ...
    def update_config(self, values: dict) -> None: ...
    def add_sse_client(self, client: Any, ready_factory: Callable[[], dict]) -> None: ...
    def remove_sse_client(self, client: Any) -> bool: ...
    def has_sse_clients(self) -> bool: ...
    def publish(self, event: dict) -> None: ...


@runtime_checkable
class TaskManager(Protocol):
    """DownloadManager 的结构化接口。"""
    def begin(self, kind: str) -> TaskHandle | None: ...
    def finish(self, handle: TaskHandle) -> bool: ...
    def is_current(self, handle: TaskHandle) -> bool: ...
    def publish_process(self, handle: TaskHandle, process: object) -> bool: ...
    def clear_process(self, handle: TaskHandle, process: object) -> None: ...
    def request_stop(self) -> StopTicket: ...
    def suspend(self) -> None: ...
    def resume(self) -> None: ...
    def snapshot(self) -> dict: ...
