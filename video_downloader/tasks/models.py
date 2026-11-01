"""多任务模型。

一个 Task 对应 UI 上一次“开始”点击；urls 可以是 1 条或多条。
任务状态、进度、日志与每个任务自己的下载执行器绑定，互不覆盖。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    WAITING = "waiting"
    STOPPED = "stopped"
    TIMED_OUT = "timed_out"
    PARTIAL = "partial"


TERMINAL_TASK_STATUSES = {
    TaskStatus.COMPLETED,
    TaskStatus.FAILED,
    TaskStatus.CANCELLED,
    TaskStatus.STOPPED,
    TaskStatus.TIMED_OUT,
    TaskStatus.PARTIAL,
}


@dataclass
class Task:
    urls: list[str]
    kind: str = "download"          # download | live
    live_mode: str | None = None
    bili_parts: str | None = None
    bili_parts_map: dict | None = None
    tc_password: str | None = None
    custom_args: str | None = None
    priority: int = 0
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: TaskStatus = TaskStatus.QUEUED
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    progress: float = 0.0
    indeterminate: bool = False
    speed: str = ""
    eta: str = ""
    stage: str = "video"
    message: str = "等待开始"
    title: str = ""
    result: str = ""
    error: str = ""
    history: list[dict] = field(default_factory=list)
    logs: list[dict] = field(default_factory=list)
    cancel_requested: bool = False
    order_index: int = 0
    config: dict = field(default_factory=dict, repr=False)
    mixed_parallel: bool = True
    live_parallel: int = 2
    download_parallel: int = 1
    items: list[Task] = field(default_factory=list)
    stats: dict = field(default_factory=lambda: {"ok": 0, "fail": 0, "skipped": 0, "total": 0})
    prompts: dict = field(default_factory=dict, repr=False)
    operation: str = "download"
    selection: dict = field(default_factory=dict, repr=False)
    content_kind: str = ""
    content_stats: dict = field(default_factory=dict)
    archive_status: str = ""
    content_job_id: str = ""

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_TASK_STATUSES

    @property
    def label(self) -> str:
        if self.title:
            return self.title
        if len(self.urls) == 1:
            return self.urls[0]
        return f"{self.urls[0]} 等 {len(self.urls)} 个链接"

    def to_dict(self, *, include_logs: bool = True) -> dict:
        return {
            "id": self.id,
            "urls": list(self.urls),
            "kind": self.kind,
            "live_mode": self.live_mode,
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "progress": round(self.progress, 2),
            "indeterminate": self.indeterminate,
            "speed": self.speed,
            "eta": self.eta,
            "stage": self.stage,
            "message": self.message,
            "title": self.title,
            "label": self.label,
            "result": self.result,
            "error": self.error,
            "history": list(self.history[-20:]),
            "logs": list(self.logs[-60:]) if include_logs else [],
            "created_ago": max(0, int(time.time() - self.created_at)),
            "url_count": len(self.urls),
            "mixed_parallel": self.mixed_parallel,
            "live_parallel": self.live_parallel,
            "download_parallel": self.download_parallel,
            "stats": dict(self.stats),
            "items": [item.to_dict(include_logs=False) for item in self.items],
            "prompts": [dict(prompt) for prompt in self.prompts.values()],
            "content_kind": self.content_kind,
            "content_stats": dict(self.content_stats),
            "archive_status": self.archive_status,
            "content_job_id": self.content_job_id,
        }
