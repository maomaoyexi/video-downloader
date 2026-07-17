import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AppState:
    config: dict = field(default_factory=dict)
    config_lock: Any = field(default_factory=threading.RLock)
    sse_lock: Any = field(default_factory=threading.RLock)
    sse_clients: list = field(default_factory=list)
    log_history: list = field(default_factory=list)
    download_thread_context: Any = field(default_factory=threading.local)
    progress_data: dict = field(default_factory=lambda: {"percent": 0, "status": "就绪", "speed": "", "eta": ""})
    batch_stats: dict = field(default_factory=lambda: {"ok": 0, "fail": 0, "total": 0, "current": 0})

    def replace_config(self, values):
        with self.config_lock:
            self.config.update(values)

    def update_config(self, values):
        with self.config_lock:
            self.config.update(values)

    def config_snapshot(self):
        with self.config_lock:
            return dict(self.config)

    def add_sse_client(self, client, ready_factory):
        with self.sse_lock:
            # 初始快照与注册同锁完成，保证客户端先收到 ready，再收到并发增量事件。
            client.put_nowait(ready_factory())
            self.sse_clients.append(client)

    def remove_sse_client(self, client):
        with self.sse_lock:
            if client in self.sse_clients:
                self.sse_clients.remove(client)
            return not self.sse_clients

    def has_sse_clients(self):
        with self.sse_lock:
            return bool(self.sse_clients)

    def publish(self, event):
        with self.sse_lock:
            for client in self.sse_clients[:]:
                try:
                    client.put_nowait(event)
                except Exception:
                    # 慢客户端队列满时淘汰最旧事件，避免其反向阻塞所有生产线程。
                    try:
                        client.get_nowait()
                        client.put_nowait(event)
                    except Exception:
                        pass
