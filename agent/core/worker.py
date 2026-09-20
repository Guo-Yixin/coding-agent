"""多 Worker 运行租约与重启恢复。"""

from __future__ import annotations

import os
import socket
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

from agent.core.settings import DEFAULT_TENANT_ID


class WorkerLeaseUnavailable(RuntimeError):
    """当前运行已被其他 worker 持有。"""


@dataclass(frozen=True)
class WorkerLease:
    lease_id: str
    run_id: str
    worker_id: str
    active: bool = True


class WorkerLeaseManager:
    """为业务 Store 提供统一的 acquire/renew/release/recover 外观。"""

    def __init__(self, store: Any, *, worker_id: str | None = None, ttl_seconds: int = 60) -> None:
        self.store = store
        self.worker_id = worker_id or os.environ.get("CODING_WORKER_ID") or f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
        self.ttl_seconds = ttl_seconds

    @property
    def distributed(self) -> bool:
        return all(callable(getattr(self.store, name, None)) for name in (
            "acquire_worker_lease", "renew_worker_lease", "release_worker_lease"
        ))

    def acquire(self, run_id: str) -> WorkerLease:
        lease_id = str(uuid.uuid4())
        if not self.distributed:
            return WorkerLease(lease_id=lease_id, run_id=run_id, worker_id=self.worker_id, active=False)
        acquired = self.store.acquire_worker_lease(
            lease_id=lease_id, worker_id=self.worker_id, run_id=run_id, ttl_seconds=self.ttl_seconds
        )
        if not acquired:
            raise WorkerLeaseUnavailable(f"run {run_id} 已被其他 worker 持有")
        self._audit("worker.lease.acquired", run_id, {"worker_id": self.worker_id, "lease_id": lease_id})
        return WorkerLease(lease_id=lease_id, run_id=run_id, worker_id=self.worker_id)

    def renew(self, lease: WorkerLease) -> bool:
        if not lease.active or not self.distributed:
            return True
        renewed = bool(self.store.renew_worker_lease(
            run_id=lease.run_id, worker_id=lease.worker_id, ttl_seconds=self.ttl_seconds
        ))
        if renewed:
            self._audit("worker.lease.renewed", lease.run_id, {"worker_id": lease.worker_id})
        return renewed

    def release(self, lease: WorkerLease) -> bool:
        if not lease.active or not self.distributed:
            return True
        released = bool(self.store.release_worker_lease(run_id=lease.run_id, worker_id=lease.worker_id))
        self._audit("worker.lease.released", lease.run_id, {"worker_id": lease.worker_id, "released": released})
        return released

    def recover_stale_runs(self) -> list[str]:
        recover = getattr(self.store, "recover_stale_runs", None)
        if not callable(recover):
            return []
        run_ids = list(recover())
        for run_id in run_ids:
            self._audit("worker.run.recovered", run_id, {"worker_id": self.worker_id})
        return run_ids

    @contextmanager
    def hold(self, run_id: str) -> Iterator[WorkerLease]:
        lease = self.acquire(run_id)
        try:
            yield lease
        finally:
            self.release(lease)

    def _audit(self, event_type: str, run_id: str, payload: dict[str, Any]) -> None:
        append = getattr(self.store, "append_audit_event", None)
        if not callable(append):
            return
        append(event_id=str(uuid.uuid4()), event_type=event_type,
               payload={"tenant_id": DEFAULT_TENANT_ID, **payload}, run_id=run_id)


__all__ = ["WorkerLease", "WorkerLeaseManager", "WorkerLeaseUnavailable"]
