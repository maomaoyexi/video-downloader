"""Stable, credential-free errors for CLI, jobs and future WebUI adapters."""
from __future__ import annotations


class FanboxError(Exception):
    def __init__(self, code: str, message: str, *, retry_after: float | None = None):
        super().__init__(message)
        self.code = code
        self.retry_after = retry_after

    def to_dict(self) -> dict:
        return {"code": self.code, "message": str(self), "retry_after": self.retry_after}
