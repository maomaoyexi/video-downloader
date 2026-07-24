import threading
from dataclasses import dataclass

@dataclass(frozen=True)
class TaskHandle:
    generation: int
    kind: str
    cancel_event: threading.Event


@dataclass(frozen=True)
class StopTicket:
    process: object
    active: bool
    generation: int


class DownloadManager:
    def __init__(self):
        self._lock = threading.RLock()
        self._generation = 0
        self._handle = None
        self._process = None
        self._phase = "idle"
        self._accepting = True

    def begin(self, kind):
        with self._lock:
            if not self._accepting or self._handle is not None:
                return None
            # 单调递增的代际标识用于隔离已结束任务的迟到回调。
            self._generation += 1
            handle = TaskHandle(self._generation, kind, threading.Event())
            self._handle = handle
            self._process = None
            self._phase = "starting"
            return handle

    def suspend(self):
        with self._lock:
            if self._handle is not None:
                return False
            self._accepting = False
            self._phase = "suspended"
            return True

    def resume(self):
        with self._lock:
            self._accepting = True
            if self._handle is None:
                self._phase = "idle"

    def is_current(self, handle):
        with self._lock:
            return self._handle is not None and self._handle.generation == handle.generation

    def is_cancelled(self, handle):
        with self._lock:
            return not self.is_current(handle) or handle.cancel_event.is_set()

    def publish_process(self, handle, process):
        with self._lock:
            # 覆盖"进程刚创建、停止请求已到达"的竞态，拒绝接管后由调用方立即清理。
            if self.is_cancelled(handle) or self._phase == "stopping":
                return False
            self._process = process
            self._phase = "running"
            return True

    def clear_process(self, handle, process):
        with self._lock:
            # 同时核对代际和对象身份，防止旧任务清掉新任务的进程引用。
            if self.is_current(handle) and self._process is process:
                self._process = None
                return True
            return False

    def request_stop(self):
        with self._lock:
            if self._handle is None:
                return StopTicket(None, False, self._generation)
            self._handle.cancel_event.set()
            self._phase = "stopping"
            return StopTicket(self._process, True, self._handle.generation)

    def finish(self, handle):
        with self._lock:
            # 迟到的旧任务只能自行收尾，不得重置当前任务状态。
            if not self.is_current(handle):
                return False
            self._handle = None
            self._process = None
            self._phase = "idle" if self._accepting else "suspended"
            return True

    def snapshot(self):
        with self._lock:
            return {
                "running": self._handle is not None,
                "phase": self._phase,
                "generation": self._generation,
                "kind": self._handle.kind if self._handle is not None else None,
                "accepting": self._accepting,
                "process": self._process,
            }
