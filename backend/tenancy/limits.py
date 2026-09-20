"""WP10 — tenant budget / rate / concurrency limits.

Dev-local in-process enforcement matching the central-DB contract:
the same guard interface is intended to move to a shared store without
callers changing. Limits are per-tenant; exceeding them raises
`QuotaExceeded` which the API maps to 429 / jobs to WAITING_QUOTA.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass


class QuotaExceeded(Exception):
    def __init__(self, kind: str, detail: str):
        super().__init__(detail)
        self.kind = kind          # rate | concurrency | budget
        self.detail = detail


@dataclass
class TenantLimits:
    requests_per_minute: int = 60
    max_concurrent_jobs: int = 2
    monthly_byte_budget: int = 500 * 1024 * 1024  # 500MB


class TenantLimiter:
    """Per-tenant rate window + job concurrency + byte budget."""

    def __init__(self, limits: TenantLimits | None = None):
        self.limits = limits or TenantLimits()
        self._lock = threading.RLock()
        self._requests: dict[str, deque] = defaultdict(deque)
        self._running: dict[str, int] = defaultdict(int)
        self._bytes: dict[str, int] = defaultdict(int)

    def check_rate(self, tenant_id: str) -> None:
        with self._lock:
            now = time.time()
            q = self._requests[tenant_id]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= self.limits.requests_per_minute:
                raise QuotaExceeded(
                    "rate",
                    f"tenant {tenant_id}: {self.limits.requests_per_minute} req/min exceeded",
                )
            q.append(now)

    def acquire_job(self, tenant_id: str) -> None:
        """Reserve a job slot; call release_job when the job finishes."""
        with self._lock:
            if self._running[tenant_id] >= self.limits.max_concurrent_jobs:
                raise QuotaExceeded(
                    "concurrency",
                    f"tenant {tenant_id}: {self.limits.max_concurrent_jobs} concurrent jobs exceeded",
                )
            self._running[tenant_id] += 1

    def release_job(self, tenant_id: str) -> None:
        with self._lock:
            if self._running[tenant_id] > 0:
                self._running[tenant_id] -= 1

    def charge_bytes(self, tenant_id: str, n: int) -> None:
        with self._lock:
            if self._bytes[tenant_id] + n > self.limits.monthly_byte_budget:
                raise QuotaExceeded(
                    "budget",
                    f"tenant {tenant_id}: monthly byte budget exceeded",
                )
            self._bytes[tenant_id] += n

    def running_jobs(self, tenant_id: str) -> int:
        return self._running[tenant_id]
