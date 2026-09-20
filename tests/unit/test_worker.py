from __future__ import annotations

import pytest

from agent.core.worker import WorkerLeaseManager, WorkerLeaseUnavailable


class FakeStore:
    def __init__(self, acquired: bool = True) -> None:
        self.acquired = acquired
        self.events: list[tuple[str, str]] = []
        self.released = False

    def acquire_worker_lease(self, **_: object) -> bool:
        return self.acquired

    def renew_worker_lease(self, **_: object) -> bool:
        return self.acquired

    def release_worker_lease(self, **_: object) -> bool:
        self.released = True
        return True

    def append_audit_event(self, *, event_type: str, run_id: str, **_: object) -> None:
        self.events.append((event_type, run_id))

    def recover_stale_runs(self) -> list[str]:
        return ["stale-run"]


def test_hold_acquires_and_releases_with_audit() -> None:
    store = FakeStore()
    manager = WorkerLeaseManager(store, worker_id="worker-a", ttl_seconds=10)
    with manager.hold("run-1") as lease:
        assert lease.active is True
        assert manager.renew(lease) is True
    assert store.released is True
    assert [event[0] for event in store.events] == [
        "worker.lease.acquired", "worker.lease.renewed", "worker.lease.released"
    ]


def test_hold_rejects_duplicate_claim() -> None:
    manager = WorkerLeaseManager(FakeStore(acquired=False), worker_id="worker-b")
    with pytest.raises(WorkerLeaseUnavailable):
        with manager.hold("run-2"):
            pass


def test_sqlite_compatible_store_uses_noop_lease() -> None:
    lease = WorkerLeaseManager(object()).acquire("run-3")
    assert lease.active is False


def test_recover_stale_runs_audits_recovered_ids() -> None:
    store = FakeStore()
    manager = WorkerLeaseManager(store, worker_id="recovery-worker")
    assert manager.recover_stale_runs() == ["stale-run"]
    assert store.events[-1] == ("worker.run.recovered", "stale-run")
