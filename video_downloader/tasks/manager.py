"""Bounded parent queue with an independent executor for every URL."""
from __future__ import annotations

import copy
import threading
import time
from dataclasses import dataclass
from typing import Callable

from video_downloader.core.platform import clean_url, detect_platform
from video_downloader.live import is_live_url
from video_downloader.services.download_manager import DownloadManager
from .context import TaskAppState
from .models import Task, TaskStatus


@dataclass
class TaskCallbacks:
    log: Callable
    update_progress: Callable
    add_history: Callable
    broadcast_download_state: Callable
    emit_event: Callable
    cancel_idle_timer: Callable
    start_idle_timer: Callable


class TaskManager:
    def __init__(self, *, base_app_state, executor_factory, max_parallel_getter,
                 order_getter, publish=None, cancel_idle_timer=None,
                 start_idle_timer=None, add_history=None, accepting_getter=None, clock=time.time):
        self._base_app_state = base_app_state
        self._executor_factory = executor_factory
        self._max_parallel_getter = max_parallel_getter
        self._order_getter = order_getter
        self._publish = publish or (lambda event: None)
        self._cancel_idle = cancel_idle_timer or (lambda: None)
        self._start_idle = start_idle_timer or (lambda: None)
        self._add_history = add_history or (lambda *args: None)
        self._accepting = accepting_getter or (lambda: True)
        self._clock = clock
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._stopping = threading.Event()
        self._tasks: dict[str, Task] = {}
        self._runtimes: dict[str, dict] = {}
        self._snapshot = []
        self._dirty = False
        self._order_seq = 0
        self._thread = threading.Thread(target=self._loop, name="task-scheduler", daemon=True)
        self._thread.start()

    def stop(self):
        self._stopping.set()
        self._wake.set()
        self.cancel_all()
        self._thread.join(timeout=3)
        with self._lock:
            threads = [rt["thread"] for rt in self._runtimes.values()]
        deadline = time.monotonic() + 45
        for thread in threads:
            if thread is not threading.current_thread():
                thread.join(timeout=max(0, deadline - time.monotonic()))
        self._flush()

    def _loop(self):
        while not self._stopping.is_set():
            try:
                self._dispatch()
                self._flush()
            except Exception as exc:
                self._publish({"type": "log", "data": {
                    "time": time.strftime("%H:%M:%S"), "level": "error",
                    "msg": f"[任务调度] {exc}"}})
            self._wake.wait(0.1)
            self._wake.clear()

    @staticmethod
    def _limit(value, default=1, minimum=1):
        try:
            return max(minimum, min(5, int(value)))
        except (TypeError, ValueError, OverflowError):
            return default

    def submit(self, urls, *, kind=None, live_mode=None, bili_parts=None,
               bili_parts_map=None, tc_password=None, custom_args=None,
               operation="download", selection=None):
        cleaned = list(dict.fromkeys(url for raw in (urls or []) if (url := clean_url(raw))))
        if not cleaned:
            return {"error": "没有有效的链接"}
        if str(live_mode or "").lower() == "wait":
            return {"error": "蹲开播任务请使用等待开播面板，不能加入任务队列"}
        config = self._base_app_state.config_snapshot()
        items = [Task(urls=[url], kind="live" if is_live_url(url, detect_platform(url)) else "download")
                 for url in cleaned]
        if operation != "download" or (kind == "live" and len(items) == 1):
            for item in items:
                item.kind = kind or "download"
        with self._lock:
            if self._stopping.is_set() or not self._accepting():
                return {"error": "程序正在关闭或更新，暂不能添加任务"}
            if any(set(cleaned).intersection(t.urls) for t in self._tasks.values() if not t.is_terminal):
                return {"error": "此链接已有运行或排队任务，请先完成或取消，避免同时写入同一文件"}
            self._order_seq += 1
            task = Task(
                urls=cleaned, kind=kind or ("live" if any(i.kind == "live" for i in items) else "download"),
                live_mode=live_mode, bili_parts=bili_parts, bili_parts_map=copy.deepcopy(bili_parts_map),
                tc_password=tc_password, custom_args=custom_args, order_index=self._order_seq,
                config=config, mixed_parallel=bool(int(config.get("TASK_MIXED_PARALLEL", 1))),
                live_parallel=self._limit(config.get("TASK_LIVE_PARALLEL", 2), default=2, minimum=2),
                download_parallel=self._limit(config.get("TASK_DOWNLOAD_PARALLEL", 1)),
                items=items, message="排队中", operation=operation, selection=dict(selection or {}),
                stats={"ok": 0, "fail": 0, "skipped": 0, "total": len(items)})
            self._tasks[task.id] = task
            self._broadcast(refresh=True)
            result = {"ok": True, "task": task.to_dict()}
        self._cancel_idle()
        self._wake.set()
        return result

    def list_tasks(self):
        # SSE ready_factory holds sse_lock: do not acquire the task lock here.
        return copy.deepcopy(self._snapshot)

    def has_active(self):
        with self._lock:
            return bool(self._runtimes) or any(not t.is_terminal for t in self._tasks.values())

    def active_count(self):
        with self._lock:
            return sum(not t.is_terminal for t in self._tasks.values())

    def start_exclusive(self, callback, *args, **kwargs):
        """Serialize legacy handle creation against queue submission/dispatch."""
        with self._lock:
            if self.has_active():
                return {"error": "请先完成或取消任务列表中的任务，再使用单任务或工具功能"}
            return callback(*args, **kwargs)

    def get_current_command(self):
        with self._lock:
            executors = [child["executor"] for runtime in self._runtimes.values()
                         for child in runtime["children"].values()]
        for executor in executors:
            result = executor.get_current_ytdlp_command()
            if result.get("command"):
                return result
        return {"error": "当前任务还没有生成 yt-dlp 命令"}

    def clear_finished(self):
        with self._lock:
            ids = [tid for tid, t in self._tasks.items() if t.is_terminal and tid not in self._runtimes]
            for tid in ids:
                del self._tasks[tid]
            self._broadcast(refresh=True)
        self._wake.set()
        return {"ok": True, "removed": len(ids)}

    def _prune_finished(self):
        finished = sorted((t for t in self._tasks.values() if t.is_terminal),
                          key=lambda t: (t.finished_at or 0, t.order_index))
        for old in finished[:-100]:
            self._tasks.pop(old.id, None)

    def _prompt_executor(self, task_id, prompt_type, *, url=None, request_id=None, item_id=None):
        with self._lock:
            task = self._tasks.get(task_id)
            runtime = self._runtimes.get(task_id)
            if not task or task.cancel_requested or not runtime:
                return None
            for prompt in task.prompts.values():
                if (prompt["type"] == prompt_type
                        and (item_id is None or prompt["item_id"] == item_id)
                        and (url is None or prompt.get("url") == url)
                        and (request_id is None or prompt.get("request_id") == request_id)):
                    child = runtime["children"].get(prompt["item_id"])
                    return child["executor"] if child else None
        return None

    def submit_password(self, task_id, url, password, item_id=None, request_id=None):
        executor = self._prompt_executor(task_id, "password_required", url=url, item_id=item_id, request_id=request_id)
        if executor is None:
            return {"error": "此密码确认已结束，请以当前任务状态为准"}
        return executor.submit_password(url, password, request_id=request_id)

    def submit_archive_choice(self, task_id, request_id, redownload):
        executor = self._prompt_executor(task_id, "archive_choice_required", request_id=request_id)
        if executor is None:
            return {"error": "此归档确认已结束，请以当前任务状态为准"}
        return executor.submit_archive_choice(request_id, redownload)

    def cancel(self, task_id):
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return {"error": "任务不存在"}
            if task.is_terminal:
                return {"ok": True, "task": task.to_dict()}
            task.cancel_requested = True
            task.message = "正在停止"
            task.prompts.clear()
            for item in task.items:
                if item.status is TaskStatus.QUEUED:
                    item.status = TaskStatus.CANCELLED
                    item.message = "已取消"
            runtime = self._runtimes.get(task_id)
            if runtime is None:
                task.status, task.message = TaskStatus.CANCELLED, "已取消"
                task.finished_at = self._clock()
                self._prune_finished()
            children = list(runtime["children"].values()) if runtime else []
            self._broadcast(refresh=True)
            result = {"ok": True, "task": task.to_dict()}
        for child in children:
            # If start_download has not created its handle, suspend prevents a
            # late begin(). Otherwise stop_download cancels the current handle.
            child["manager"].suspend()
            child["executor"].stop_download()
        self._wake.set()
        self._start_idle()
        return result

    def cancel_all(self):
        with self._lock:
            ids = [tid for tid, t in self._tasks.items() if not t.is_terminal]
            # Block dispatch of the entire queue before stopping the first process.
            for tid in ids:
                self._tasks[tid].cancel_requested = True
        for tid in ids:
            self.cancel(tid)
        return {"ok": True, "cancelled": len(ids)}

    def _dispatch(self):
        with self._lock:
            if self._stopping.is_set() or not self._accepting():
                return
            free = self._limit(self._max_parallel_getter(), default=2) - len(self._runtimes)
            queued = [t for t in self._tasks.values() if t.status is TaskStatus.QUEUED and not t.cancel_requested]
            order = self._order_getter()
            queued.sort(key=lambda t: (
                (t.kind != "live") if order == "live_first" else
                (t.kind == "live") if order == "download_first" else 0, t.order_index))
            for task in queued[:max(0, free)]:
                task.status = TaskStatus.RUNNING
                task.started_at = self._clock()
                task.message = "开始下载"
                thread = threading.Thread(target=self._run_task, args=(task,),
                                          name=f"task-{task.id[:8]}", daemon=True)
                self._runtimes[task.id] = {"thread": thread, "children": {}}
                try:
                    thread.start()
                except Exception as exc:
                    task.error = f"任务线程启动失败: {exc}"
                    self._complete(task)
            if queued:
                self._broadcast()

    def _run_task(self, task):
        workers = {}
        pending = list(task.items)
        try:
            while pending or workers:
                workers = {w: item for w, item in workers.items() if w.is_alive()}
                if task.cancel_requested:
                    pending.clear()
                while pending and not task.cancel_requested:
                    live_running = sum(item.kind == "live" for item in workers.values())
                    downloads_running = len(workers) - live_running
                    if not task.mixed_parallel:
                        index = 0 if not workers else None
                    else:
                        # Separate lanes: a long recording cannot occupy a video
                        # slot, and queued videos cannot consume live capacity.
                        index = next((i for i, item in enumerate(pending)
                                      if (live_running < task.live_parallel if item.kind == "live"
                                          else downloads_running < task.download_parallel)), None)
                    if index is None:
                        break
                    item = pending.pop(index)
                    worker = threading.Thread(target=self._run_item, args=(task, item), daemon=True)
                    worker.start()
                    workers[worker] = item
                for worker in workers:
                    worker.join(timeout=0.05)
        except Exception as exc:
            task.error = f"任务执行失败: {exc}"
        finally:
            for worker in workers:
                worker.join()
            self._complete(task)

    def _run_item(self, task, item):
        config = dict(task.config)
        video_limit = float(config.get("TASK_DOWNLOAD_SPEED_LIMIT", 0))
        if item.kind != "live" and video_limit > 0:
            configured = float(config.get("SPEED_LIMIT", 0))
            config["SPEED_LIMIT"] = min(configured, video_limit) if configured > 0 else video_limit
        state = TaskAppState(self._base_app_state, task.id, config,
                             publish=lambda event: self._on_state(task, item, event))
        done, dm = threading.Event(), DownloadManager()
        callbacks = TaskCallbacks(
            log=lambda msg, level="info": self._on_log(task, item, msg, level),
            update_progress=lambda percent, status=None, speed="", eta="", stage="video":
                self._on_progress(task, item, percent, status, speed, eta, stage),
            add_history=lambda *args, **kwargs: self._on_history(task, item, *args, **kwargs),
            broadcast_download_state=lambda: None,
            emit_event=lambda event_type, data=None: self._on_event(task, item, event_type, data),
            cancel_idle_timer=self._cancel_idle, start_idle_timer=lambda: None)
        try:
            executor = self._executor_factory(task, state, dm, callbacks, lambda _handle: done.set())
            with self._lock:
                if task.cancel_requested:
                    item.status = TaskStatus.CANCELLED
                    return
                item.status, item.started_at = TaskStatus.RUNNING, self._clock()
                self._runtimes[task.id]["children"][item.id] = {"executor": executor, "manager": dm}
            # Validation (including large HAR files) must not hold the task lock.
            if task.operation == "download":
                result = executor.start_download(
                    item.urls[0], bili_parts=(task.bili_parts_map or {}).get(item.urls[0], task.bili_parts),
                    tc_password=task.tc_password, custom_args=task.custom_args, live_mode=task.live_mode,
                    is_live_override=item.kind == "live")
            else:
                result = getattr(executor, "start_" + task.operation)()
            if isinstance(result, dict) and result.get("error"):
                raise RuntimeError(result["error"])
            done.wait()
            with self._lock:
                recording_status = item.history[-1].get("status") if item.history else None
                if item.content_kind and item.archive_status in {"partial","paused","failed"}:
                    item.status = TaskStatus.FAILED if item.archive_status=='failed' else TaskStatus.PARTIAL
                elif item.kind == "live" and recording_status in {"stopped", "timeout", "gaps", "earliest"}:
                    item.status = {"stopped": TaskStatus.STOPPED, "timeout": TaskStatus.TIMED_OUT,
                                   "gaps": TaskStatus.PARTIAL, "earliest": TaskStatus.PARTIAL}[recording_status]
                elif item.kind == "live" and recording_status == "fail":
                    item.status = TaskStatus.FAILED
                elif task.cancel_requested:
                    item.status = TaskStatus.CANCELLED
                elif item.stats["fail"] or (not item.history and item.error):
                    item.status = TaskStatus.FAILED
                else:
                    item.status, item.progress, item.error = TaskStatus.COMPLETED, 100, ""
        except Exception as exc:
            with self._lock:
                item.status = TaskStatus.CANCELLED if task.cancel_requested else TaskStatus.FAILED
                item.error = "" if task.cancel_requested else str(exc)
        finally:
            with self._lock:
                item.finished_at, item.indeterminate = self._clock(), False
                item.speed = item.eta = ""
                item.message = {TaskStatus.CANCELLED: "已取消", TaskStatus.FAILED: "失败",
                                TaskStatus.STOPPED: "已停止（已收尾）", TaskStatus.TIMED_OUT: "已到录制时限（已收尾）",
                                TaskStatus.PARTIAL: "归档已保留，可继续" if item.content_kind else "已保留录制，请查看完整性报告",
                                TaskStatus.COMPLETED: "已跳过" if item.stats["skipped"] else "已完成"}.get(item.status, item.message)
                task.prompts.pop(item.id, None)
                self._runtimes[task.id]["children"].pop(item.id, None)
                self._aggregate(task)
                self._broadcast()

    def _complete(self, task):
        with self._lock:
            for item in task.items:
                if item.status is TaskStatus.QUEUED:
                    item.status = TaskStatus.CANCELLED if task.cancel_requested else TaskStatus.FAILED
                    item.message = "已取消" if task.cancel_requested else "任务异常，未执行"
            self._aggregate(task)
            failures = sum(i.status is TaskStatus.FAILED for i in task.items)
            live_outcomes = [i.status for i in task.items if i.status in {
                TaskStatus.STOPPED, TaskStatus.TIMED_OUT, TaskStatus.PARTIAL}]
            if failures and any(i.kind == "live" and i.status is TaskStatus.FAILED for i in task.items):
                task.status, task.message = TaskStatus.FAILED, "直播录制或验证失败，请查看报告"
            elif live_outcomes:
                task.status = TaskStatus.PARTIAL if failures or TaskStatus.PARTIAL in live_outcomes else live_outcomes[0]
                task.message = {TaskStatus.STOPPED: "已停止（已收尾）", TaskStatus.TIMED_OUT: "已到录制时限（已收尾）",
                                TaskStatus.PARTIAL: "部分归档已保留" if any(i.content_kind for i in task.items) else "部分录制，请查看完整性报告"}[task.status]
            elif task.cancel_requested:
                task.status, task.message = TaskStatus.CANCELLED, "已取消"
            elif failures or task.error:
                task.status = TaskStatus.FAILED
                task.message = f"完成，{failures} 个链接失败" if failures else "失败"
                task.error = task.error or next((i.error for i in task.items if i.error), "下载失败")
            else:
                task.status, task.message, task.progress, task.error = TaskStatus.COMPLETED, "已完成", 100, ""
            task.finished_at, task.indeterminate = self._clock(), False
            task.speed = task.eta = ""
            task.prompts.clear()
            self._runtimes.pop(task.id, None)
            self._prune_finished()
            self._broadcast()
        self._wake.set()
        self._start_idle()

    def _aggregate(self, task):
        task.progress = sum(i.progress for i in task.items) / len(task.items)
        task.indeterminate = any(i.indeterminate and not i.is_terminal for i in task.items)
        task.stats = {
            "ok": sum(i.status is TaskStatus.COMPLETED and not i.stats["skipped"] for i in task.items),
            "fail": sum(i.status is TaskStatus.FAILED for i in task.items),
            "skipped": sum(i.status is TaskStatus.COMPLETED and bool(i.stats["skipped"]) for i in task.items),
            "total": len(task.items)}
        content=[i for i in task.items if i.content_kind]
        if content:
            task.content_kind='fanbox' if len(content)==len(task.items) else 'mixed'
            keys={key for item in content for key in item.content_stats}
            task.content_stats={key:sum(item.content_stats.get(key,0) for item in content) for key in keys}
            if len(content)==1:
                task.content_job_id=content[0].content_job_id
                task.archive_status=content[0].archive_status

    def _on_progress(self, task, item, percent, status, speed, eta, stage):
        with self._lock:
            if item.is_terminal or task.cancel_requested:
                return
            if percent is not None:
                item.indeterminate = percent < 0
                if percent >= 0:
                    item.progress = max(0, min(100, float(percent) * 100))
            if status:
                item.message = task.message = status
            item.speed = task.speed = speed or ""
            item.eta = task.eta = eta or ""
            item.stage = task.stage = stage or "video"
            self._aggregate(task)
            self._broadcast()

    def _on_log(self, task, item, message, level):
        with self._lock:
            task.logs.append({"time": time.strftime("%H:%M:%S"), "msg": str(message),
                              "level": level, "item_id": item.id})
            task.logs = task.logs[-120:]
            if level == "error":
                item.error = str(message)
            self._broadcast()

    def _on_history(self, task, item, url, title, platform, status, output_path="", **kwargs):
        output_path = kwargs.get("filepath", output_path)
        with self._lock:
            record = {"url": url, "title": title, "platform": platform, "status": status, "output": output_path}
            item.history.append(record)
            counter = {"success": "ok", "skipped": "skipped", "fail": "fail", "gaps": "fail"}.get(status)
            if counter:
                item.stats[counter] += 1
            task.history.append(record)
            task.history = task.history[-50:]
            if title:
                item.title = title
                if len(task.items) == 1:
                    task.title = title
            self._broadcast()
        self._add_history(url, title, platform, status, output_path)

    def _on_state(self, task, item, event):
        if event.get("type") == "stats":
            with self._lock:
                item.stats.update(event.get("data") or {})
                self._broadcast()

    def _on_event(self, task, item, event_type, data=None):
        data = dict(data or {}, task_id=task.id, item_id=item.id)
        with self._lock:
            if event_type in {'content_progress','content_result'} and not item.is_terminal:
                item.content_kind=data.get('content_kind','')
                item.content_stats=dict(data.get('content_stats') or {})
                item.content_job_id=data.get('job_id','')
                item.archive_status=data.get('archive_status',data.get('status',''))
                self._aggregate(task)
            if event_type in {"password_required", "archive_choice_required"}:
                if task.cancel_requested:
                    return
                task.prompts[item.id] = dict(data, type=event_type)
            elif event_type in {"password_closed", "archive_choice_closed"}:
                task.prompts.pop(item.id, None)
            self._broadcast()
        self._publish({"type": event_type, "task_id": task.id, "data": data})

    def _broadcast(self, refresh=False):
        # Expensive snapshot construction is coalesced with publication.
        if refresh:
            self._snapshot = [t.to_dict() for t in self._tasks.values()]
        self._dirty = True

    def _flush(self):
        with self._lock:
            if not self._dirty:
                return
            self._snapshot = [t.to_dict() for t in self._tasks.values()]
            event = {"type": "task_snapshot", "data": {"tasks": self._snapshot}}
            self._dirty = False
        self._publish(event)
