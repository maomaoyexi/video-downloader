"""Process-independent scheduling; waits never hold SQL locks and are cancellable."""
from __future__ import annotations

from contextlib import contextmanager
import threading

from .errors import FanboxError


class AccountGate:
    def __init__(self, repository, cancel, interval=1, *, heartbeat_tokens=()):
        self.repository,self.cancel,self.interval=repository,cancel,interval
        self.token=None
        self._tokens=set(heartbeat_tokens)
        self._heartbeat_lock=threading.RLock()
        self._last_heartbeat=repository.clock()

    def check(self):
        if self.cancel.is_set():
            raise FanboxError('cancelled','任务已暂停')
        with self._heartbeat_lock:
            now=self.repository.clock()
            if now-self._last_heartbeat>=20:
                for token in self._tokens:self.repository.heartbeat(token)
                self._last_heartbeat=now

    def wait(self, seconds):
        self.check()
        while seconds>0:
            interval=min(seconds,.5)
            self.cancel.wait(interval)
            self.check()
            seconds-=interval

    def __enter__(self):
        self.token=self.acquire('api',interval=self.interval)
        return self

    def acquire(self, kind, *, limit=1, interval=0):
        while True:
            self.check()
            if kind in {'api','file'}:
                cooldown=self.repository.cooldown_remaining()
                if cooldown:
                    raise FanboxError('rate_limited','账号正在冷却',retry_after=cooldown)
            token,wait=self.repository.acquire(kind,limit=limit,interval=interval)
            if token:
                with self._heartbeat_lock:self._tokens.add(token)
                return token
            self.wait(min(wait,.5))

    def __exit__(self,*_):
        self.release(self.token,interval=self.interval)

    def release(self,token,*,interval=0):
        with self._heartbeat_lock:
            self._tokens.discard(token)
            self.repository.release(token,interval=interval)

    def defer(self, seconds):
        self.repository.defer(seconds)

    @contextmanager
    def file(self, options):
        token=self.acquire('file',limit=options['network']['file_concurrency'],
                           interval=options['network']['file_start_interval_seconds'])
        try:
            yield token
        finally:
            self.release(token)
