"""持久化蹲开播（WAIT）服务。

组成：
- ``WatchJob``：任务值对象；
- ``WatchJobStore``：SQLite 持久化，应用重启可恢复；
- ``LiveWatchService``：调度器 + Probe 调用 + 开播回调。

P1 只负责“检测到开播后触发一次录制”，不接管录制器内部生命周期。
"""

from __future__ import annotations

import random
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable

from .probe import LiveProbe, LiveStatus, ProbeService
from .urls import LiveTarget, TargetKind, classify_target, expand_short_url


class WatchStatus(str, Enum):
    PROBING = "probing"
    WAITING = "waiting"
    WAITING_NEAR = "waiting_near"
    STARTING = "starting"
    TRIGGERED = "triggered"
    ERROR = "error"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = {
    WatchStatus.TRIGGERED,
    WatchStatus.EXPIRED,
    WatchStatus.CANCELLED,
}


@dataclass
class WatchJob:
    id: str
    url: str
    platform: str
    target_kind: str
    stable_id: str
    record_mode: str
    status: WatchStatus
    created_at: float
    updated_at: float
    next_probe_at: float | None
    max_wait_at: float
    attempts: int = 0
    last_error: str = ""
    probe: dict = field(default_factory=dict)
    triggered_at: float | None = None
    session_id: str = ""

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "url": self.url,
            "platform": self.platform,
            "target_kind": self.target_kind,
            "stable_id": self.stable_id,
            "record_mode": self.record_mode,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "next_probe_at": self.next_probe_at,
            "max_wait_at": self.max_wait_at,
            "attempts": self.attempts,
            "last_error": self.last_error,
            "probe": dict(self.probe or {}),
            "triggered_at": self.triggered_at,
            "session_id": self.session_id,
        }


class WatchJobStore:
    """SQLite 任务库；每次操作独立连接，避免多线程共享连接。"""

    def __init__(self, db_path: str | Path):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=8.0)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connection(self):
        """提交并关闭连接；Windows 下必须关闭，否则临时目录无法清理。"""
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _init_schema(self) -> None:
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS watch_jobs (
                    id TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    target_kind TEXT NOT NULL,
                    stable_id TEXT NOT NULL,
                    record_mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    next_probe_at REAL,
                    max_wait_at REAL NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT NOT NULL DEFAULT '',
                    probe_json TEXT NOT NULL DEFAULT '{}',
                    triggered_at REAL,
                    session_id TEXT NOT NULL DEFAULT ''
                )
            """)
            connection.execute("CREATE INDEX IF NOT EXISTS idx_watch_status_next ON watch_jobs(status, next_probe_at)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_watch_url ON watch_jobs(url)")

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> WatchJob:
        import json

        try:
            probe = json.loads(row["probe_json"] or "{}")
        except (ValueError, TypeError):
            probe = {}
        return WatchJob(
            id=row["id"],
            url=row["url"],
            platform=row["platform"],
            target_kind=row["target_kind"],
            stable_id=row["stable_id"],
            record_mode=row["record_mode"],
            status=WatchStatus(row["status"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            next_probe_at=row["next_probe_at"],
            max_wait_at=row["max_wait_at"],
            attempts=row["attempts"],
            last_error=row["last_error"],
            probe=probe,
            triggered_at=row["triggered_at"],
            session_id=row["session_id"],
        )

    def add(self, job: WatchJob) -> None:
        import json

        with self._connection() as connection:
            connection.execute(
                """INSERT INTO watch_jobs
                   (id,url,platform,target_kind,stable_id,record_mode,status,created_at,updated_at,
                    next_probe_at,max_wait_at,attempts,last_error,probe_json,triggered_at,session_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (job.id, job.url, job.platform, job.target_kind, job.stable_id,
                 job.record_mode, job.status.value, job.created_at, job.updated_at,
                 job.next_probe_at, job.max_wait_at, job.attempts, job.last_error,
                 json.dumps(job.probe, ensure_ascii=False), job.triggered_at, job.session_id),
            )

    def update(self, job: WatchJob, *, expected_status: WatchStatus | None = None) -> bool:
        import json

        with self._connection() as connection:
            cursor = connection.execute(
                """UPDATE watch_jobs SET url=?,platform=?,target_kind=?,stable_id=?,record_mode=?,
                   status=?,updated_at=?,next_probe_at=?,max_wait_at=?,attempts=?,last_error=?,
                   probe_json=?,triggered_at=?,session_id=? WHERE id=?""" +
                   (" AND status=?" if expected_status else ""),
                (job.url, job.platform, job.target_kind, job.stable_id, job.record_mode,
                 job.status.value, job.updated_at, job.next_probe_at, job.max_wait_at,
                 job.attempts, job.last_error, json.dumps(job.probe, ensure_ascii=False),
                 job.triggered_at, job.session_id, job.id) +
                ((expected_status.value,) if expected_status else ()),
            )
            return cursor.rowcount == 1

    def claim(self, job_id: str, now: float) -> bool:
        """Atomically claim a due probe; cancellation and another scheduler win safely."""
        with self._connection() as connection:
            return connection.execute(
                "UPDATE watch_jobs SET status=?,next_probe_at=NULL,updated_at=? WHERE id=? "
                "AND status IN (?,?,?,?) AND next_probe_at<=?",
                (WatchStatus.PROBING.value, now, job_id, WatchStatus.PROBING.value,
                 WatchStatus.WAITING.value, WatchStatus.WAITING_NEAR.value, WatchStatus.ERROR.value, now),
            ).rowcount == 1

    def get(self, job_id: str) -> WatchJob | None:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM watch_jobs WHERE id=?", (job_id,)).fetchone()
        return self._row_to_job(row) if row else None

    def list_recent(self, limit: int = 100) -> list[WatchJob]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM watch_jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._row_to_job(row) for row in rows]

    def due(self, now: float) -> list[WatchJob]:
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT * FROM watch_jobs
                   WHERE status IN (?,?,?,?) AND next_probe_at IS NOT NULL AND next_probe_at <= ?
                   ORDER BY next_probe_at ASC LIMIT 20""",
                (WatchStatus.PROBING.value, WatchStatus.WAITING.value,
                 WatchStatus.WAITING_NEAR.value, WatchStatus.ERROR.value, now),
            ).fetchall()
        return [self._row_to_job(row) for row in rows]

    def find_active_url(self, url: str) -> WatchJob | None:
        active = (WatchStatus.PROBING.value, WatchStatus.WAITING.value,
                  WatchStatus.WAITING_NEAR.value, WatchStatus.STARTING.value)
        with self._connection() as connection:
            row = connection.execute(
                f"SELECT * FROM watch_jobs WHERE url=? AND status IN ({','.join('?' for _ in active)})"
                " ORDER BY created_at DESC LIMIT 1",
                (url, *active),
            ).fetchone()
        return self._row_to_job(row) if row else None

    def has_active(self) -> bool:
        active = (WatchStatus.PROBING.value, WatchStatus.WAITING.value,
                  WatchStatus.WAITING_NEAR.value, WatchStatus.STARTING.value)
        with self._connection() as connection:
            row = connection.execute(
                f"SELECT 1 FROM watch_jobs WHERE status IN ({','.join('?' for _ in active)}) LIMIT 1",
                active,
            ).fetchone()
        return row is not None

    def recover_interrupted(self) -> int:
        """Resume probes; an interrupted dispatch needs review to avoid duplicates."""
        now = time.time()
        with self._connection() as connection:
            cursor = connection.execute(
                "UPDATE watch_jobs SET status=?, next_probe_at=?, updated_at=? WHERE status=?",
                (WatchStatus.WAITING.value, now, now, WatchStatus.PROBING.value),
            )
            count = cursor.rowcount
            cursor = connection.execute(
                "UPDATE watch_jobs SET status=?,next_probe_at=NULL,updated_at=?,last_error=? WHERE status=?",
                (WatchStatus.ERROR.value, now, "启动期间退出，请先确认录制任务是否已创建，再重新蹲守",
                 WatchStatus.STARTING.value),
            )
            return count + cursor.rowcount


class LiveWatchService:
    """WAIT 调度器。

    线程只做调度，实际探测在小型线程池中执行，避免单个慢请求阻塞所有任务。
    """

    def __init__(
        self,
        *,
        store: WatchJobStore,
        probe_service: ProbeService,
        on_live: Callable[[WatchJob, LiveProbe], dict],
        publish: Callable[[dict], None] | None = None,
        clock: Callable[[], float] = time.time,
        jitter: Callable[[], float] | None = None,
        max_workers: int = 2,
        max_wait_hours: float = 72.0,
        start_thread: bool = True,
        url_resolver: Callable[[str], str] = expand_short_url,
    ):
        self._store = store
        self._probe_service = probe_service
        self._on_live = on_live
        self._publish = publish or (lambda event: None)
        self._clock = clock
        self._jitter = jitter or (lambda: random.uniform(0.8, 1.2))
        self._max_wait_hours = max_wait_hours
        self._url_resolver = url_resolver
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="live-probe")
        self._max_workers = max_workers
        self._lock = threading.RLock()
        self._in_progress: set[str] = set()
        self._stopping = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        if start_thread:
            self.start()

    # ---- 生命周期 ----
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._store.recover_interrupted()
        self._stopping.clear()
        self._thread = threading.Thread(target=self._loop, name="live-watch", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stopping.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=3)
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _loop(self) -> None:
        while not self._stopping.is_set():
            try:
                self.tick()
            except Exception:
                pass
            self._wake.wait(1.0)
            self._wake.clear()

    # ---- 对外 API ----
    def add(self, url: str, platform: str | None = None, record_mode: str = "auto",
            max_wait_hours: float | None = None) -> dict:
        raw_url = (url or "").strip()
        if not raw_url:
            return {"error": "请输入有效的直播链接"}
        resolved = self._url_resolver(raw_url) or raw_url
        target = classify_target(resolved, platform)
        if target.needs_expand or target.kind is TargetKind.UNKNOWN:
            return {"error": target.reason or "无法识别该链接的直播类型"}
        if not target.can_watch:
            return {"error": "蹲开播只支持固定直播间/频道或单场直播事件 URL；列表/回放不能蹲守"}
        platform_name = platform or target.platform
        if not platform_name:
            return {"error": "无法识别平台"}
        if platform_name == "Withny":
            return {"error": "Withny 请使用专用 withny-dl 配置监控，不支持通用 WAIT"}
        from .modes import capability_for
        if not capability_for(platform_name).wait:
            return {"error": f"{platform_name} 当前未开放蹲开播"}
        existing = self._store.find_active_url(target.url)
        if existing:
            return {"ok": True, "waiting": True, "duplicate": True, "job": existing.to_dict()}
        now = self._clock()
        hours = self._max_wait_hours if max_wait_hours is None else float(max_wait_hours)
        job = WatchJob(
            id=uuid.uuid4().hex,
            url=target.url,
            platform=platform_name,
            target_kind=target.kind.value,
            stable_id=target.stable_id,
            record_mode=record_mode,
            status=WatchStatus.PROBING,
            created_at=now,
            updated_at=now,
            next_probe_at=now,
            max_wait_at=now + hours * 3600,
            attempts=0,
        )
        self._store.add(job)
        self._notify()
        self._wake.set()
        return {"ok": True, "waiting": True, "job": job.to_dict()}

    def cancel(self, job_id: str) -> dict:
        job = self._store.get(job_id)
        if not job:
            return {"error": "等待任务不存在"}
        if job.is_terminal:
            return {"ok": True, "job": job.to_dict()}
        if job.status is WatchStatus.STARTING:
            return {"error": "直播任务正在启动，请在录制任务中停止"}
        previous = job.status
        job.status = WatchStatus.CANCELLED
        job.next_probe_at = None
        job.updated_at = self._clock()
        job.last_error = "用户取消"
        if not self._store.update(job, expected_status=previous):
            return {"error": "任务状态已变化，请刷新后重试"}
        self._notify()
        return {"ok": True, "job": job.to_dict()}

    def list_jobs(self, limit: int = 100) -> list[dict]:
        return [job.to_dict() for job in self._store.list_recent(limit)]

    def has_active_jobs(self) -> bool:
        return self._store.has_active()

    # ---- 调度 ----
    def tick(self, now: float | None = None, wait: bool = False) -> int:
        now = self._clock() if now is None else now
        jobs = self._store.due(now)
        futures = []
        with self._lock:
            available = [job for job in jobs if job.id not in self._in_progress]
            free = max(0, self._max_workers - len(self._in_progress))
        for job in available[:free]:
            with self._lock:
                if job.id in self._in_progress:
                    continue
                self._in_progress.add(job.id)
            if not self._store.claim(job.id, now):
                self._release(job.id)
                continue
            futures.append(self._executor.submit(self._probe_job, job.id))
        if wait:
            for future in futures:
                future.result()
        return len(futures)

    def _probe_job(self, job_id: str) -> None:
        job = self._store.get(job_id)
        if not job or job.status is not WatchStatus.PROBING:
            self._release(job_id)
            return
        try:
            target = classify_target(job.url, job.platform)
            probe = self._probe_service.probe(target, timeout=20.0, force=True)
            # 探测期间用户可能取消/任务可能被其他路径更新；重新读取后再写。
            current = self._store.get(job.id)
            if not current or current.status is not WatchStatus.PROBING:
                return
            self._apply_probe(current, probe)
        except Exception as exc:
            job = self._store.get(job_id)
            if not job or job.status is not WatchStatus.PROBING:
                return
            now = self._clock()
            job.status = WatchStatus.WAITING
            job.last_error = f"探测异常：{type(exc).__name__}"
            job.attempts += 1
            job.updated_at = now
            job.next_probe_at = now + self._retry_interval(job.attempts)
            self._store.update(job, expected_status=WatchStatus.PROBING)
            self._notify()
        finally:
            self._release(job_id)

    def _apply_probe(self, job: WatchJob, probe: LiveProbe) -> None:
        now = self._clock()
        job.probe = probe.to_dict()
        job.updated_at = now
        job.attempts += 1
        if now >= job.max_wait_at:
            job.status = WatchStatus.EXPIRED
            job.next_probe_at = None
            job.last_error = "超过最长等待时间"
            self._store.update(job, expected_status=WatchStatus.PROBING)
            self._notify()
            return

        if probe.status is LiveStatus.LIVE:
            job.status = WatchStatus.STARTING
            job.next_probe_at = None
            if not self._store.update(job, expected_status=WatchStatus.PROBING):
                return
            self._notify()
            try:
                result = self._on_live(job, probe) or {}
            except Exception as exc:
                result = {"error": f"{type(exc).__name__}: {exc}"}
            job = self._store.get(job.id) or job
            if result.get("error"):
                job.status = WatchStatus.ERROR
                job.last_error = str(result["error"])
                job.next_probe_at = None
            else:
                job.status = WatchStatus.TRIGGERED
                job.triggered_at = now
                job.last_error = ""
                job.session_id = str(result.get("session_id") or "")
            job.updated_at = self._clock()
            self._store.update(job, expected_status=WatchStatus.STARTING)
            self._notify()
            return

        if probe.status is LiveStatus.UPCOMING:
            job.status = WatchStatus.WAITING_NEAR
            job.last_error = ""
            job.next_probe_at = now + self._schedule_interval(probe, now)
            self._store.update(job, expected_status=WatchStatus.PROBING)
            self._notify()
            return

        if probe.status is LiveStatus.OFFLINE:
            job.status = WatchStatus.WAITING
            job.last_error = ""
            job.next_probe_at = now + self._schedule_interval(probe, now)
            self._store.update(job, expected_status=WatchStatus.PROBING)
            self._notify()
            return

        if probe.status in {LiveStatus.ENDED, LiveStatus.PRIVATE}:
            job.status = WatchStatus.EXPIRED
            job.next_probe_at = None
            job.last_error = probe.error or (
                "直播已结束" if probe.status is LiveStatus.ENDED else "需要登录或无权限"
            )
            self._store.update(job, expected_status=WatchStatus.PROBING)
            self._notify()
            return

        # UNKNOWN / ERROR：可重试则继续等待，否则终止。
        if probe.retryable:
            job.status = WatchStatus.WAITING
            job.last_error = probe.error or "探测失败"
            job.next_probe_at = now + self._retry_interval(job.attempts)
        else:
            job.status = WatchStatus.EXPIRED
            job.last_error = probe.error or "不可恢复的探测错误"
            job.next_probe_at = None
        self._store.update(job, expected_status=WatchStatus.PROBING)
        self._notify()

    def _release(self, job_id: str) -> None:
        with self._lock:
            self._in_progress.discard(job_id)

    # ---- 时间策略 ----
    def _retry_interval(self, attempts: int) -> float:
        base = min(600.0, 15.0 * (2 ** min(max(attempts - 1, 0), 5)))
        return max(5.0, base * self._jitter())

    def _schedule_interval(self, probe: LiveProbe, now: float) -> float:
        if probe.scheduled_start:
            diff = probe.scheduled_start - now
            if diff > 86400:
                base = 1800.0
            elif diff > 7200:
                base = 900.0
            elif diff > 3600:
                base = 300.0
            elif diff > 900:
                base = 90.0
            elif diff > 0:
                base = 20.0
            elif diff > -900:
                base = 12.0
            elif diff > -7200:
                base = 45.0
            elif diff > -43200:
                base = 180.0
            else:
                base = 900.0
        else:
            base = {
                "Bilibili": 45.0,
                "TwitCasting": 90.0,
                "Withny": 60.0,
            }.get(probe.platform, 60.0)
        return max(5.0, base * self._jitter())

    def _notify(self) -> None:
        self._publish({"type": "live_watch", "data": {"jobs": self.list_jobs()}})
