"""Process-independent scheduling; waits never hold SQL locks and are cancellable."""
from __future__ import annotations

from contextlib import contextmanager

from .errors import FanboxError


class AccountGate:
    def __init__(self, repository, cancel, interval=1):
        self.repository,self.cancel,self.interval=repository,cancel,interval
        self.token=None

    def check(self):
        if self.cancel.is_set():
            raise FanboxError('cancelled','任务已暂停')

    def wait(self, seconds):
        if self.cancel.wait(min(seconds,60)):
            self.check()

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
                return token
            self.wait(min(wait,.5))

    def __exit__(self,*_):
        self.repository.release(self.token,interval=self.interval)

    def defer(self, seconds):
        self.repository.defer(seconds)

    @contextmanager
    def file(self, options):
        token=self.acquire('file',limit=options['network']['file_concurrency'],
                           interval=options['network']['file_start_interval_seconds'])
        try:
            yield token
        finally:
            self.repository.release(token)
