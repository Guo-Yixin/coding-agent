"""Durable, bounded Agent run workers backed by the business store."""
from __future__ import annotations

import logging
import os
import threading
import uuid
from typing import Any

from agent.core.graph import get_store
from agent.core.runtime import run_agent_task, run_plain_chat_task

logger = logging.getLogger(__name__)


class RunCancelled(Exception):
    """Raised at an Agent event boundary after a cooperative cancellation request."""


class RunLeaseLost(Exception):
    """Raised when a worker can no longer prove ownership of its run."""


class RunWorkerPool:
    def __init__(self, *, concurrency: int | None = None, lease_seconds: int = 90) -> None:
        self.concurrency = max(1, concurrency or int(os.getenv("AGENT_MAX_CONCURRENT_RUNS", "2")))
        self.lease_seconds = lease_seconds
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        if self._threads:
            return
        self._stop.clear()
        store = get_store()
        try:
            store.interrupt_stale_runs()
        except Exception:
            logger.exception("Could not reconcile stale Agent runs at startup")
        for index in range(self.concurrency):
            thread = threading.Thread(
                target=self._worker_loop,
                name=f"agent-run-worker-{index + 1}",
                daemon=True,
            )
            self._threads.append(thread)
            thread.start()
        reaper = threading.Thread(target=self._reconcile_loop, name="agent-run-reaper", daemon=True)
        self._threads.append(reaper)
        reaper.start()
        logger.info("Agent run worker pool started: concurrency=%s", self.concurrency)

    def stop(self) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=2)
        self._threads.clear()

    def _worker_loop(self) -> None:
        store = get_store()
        worker_id = f"{os.getenv('CODING_WORKER_ID', 'api')}-{uuid.uuid4().hex[:8]}"
        poll_seconds = max(0.1, float(os.getenv("AGENT_QUEUE_POLL_SECONDS", "0.5")))
        while not self._stop.is_set():
            try:
                item = store.claim_next_run(
                    worker_id=worker_id,
                    ttl_seconds=self.lease_seconds,
                    max_active=self.concurrency,
                )
                if item is None:
                    self._stop.wait(poll_seconds)
                    continue
                self._execute(item, worker_id)
            except Exception:
                logger.exception("Agent run queue worker failed while polling")
                self._stop.wait(min(5, poll_seconds * 4))

    def _reconcile_loop(self) -> None:
        store = get_store()
        interval = max(2, int(os.getenv("AGENT_RUN_REAPER_SECONDS", "10")))
        while not self._stop.wait(interval):
            try:
                store.interrupt_stale_runs()
            except Exception:
                logger.exception("Could not reconcile expired Agent run leases")

    def _execute(self, item: dict[str, Any], worker_id: str) -> None:
        store = get_store()
        run_id = str(item["run_id"])
        thread_id = str(item["thread_id"])
        payload = item.get("payload") or {}
        heartbeat_stop = threading.Event()
        ownership_lost = threading.Event()

        def heartbeat() -> None:
            while not heartbeat_stop.wait(max(5, self.lease_seconds // 3)):
                try:
                    if not store.renew_run_lease(
                        run_id=run_id, worker_id=worker_id, ttl_seconds=self.lease_seconds
                    ):
                        logger.warning("Run lease lost: run_id=%s", run_id)
                        ownership_lost.set()
                        return
                except Exception:
                    logger.exception("Run lease heartbeat failed: run_id=%s", run_id)
                    ownership_lost.set()
                    return

        def emit(event: str, data: dict[str, Any]) -> None:
            if event not in {"thread_done", "done"} and store.is_run_cancel_requested(run_id):
                raise RunCancelled("Run cancelled by user")
            if event not in {"thread_done", "done"} and ownership_lost.is_set():
                raise RunLeaseLost("Run worker lease was lost; task stopped to prevent duplicate execution")
            event_payload = dict(data)
            event_payload.setdefault("thread_id", thread_id)
            event_payload.setdefault("run_id", run_id)
            store.append_run_stream_event(
                thread_id=thread_id, run_id=run_id, event=event, payload=event_payload
            )

        heartbeat_thread = threading.Thread(target=heartbeat, name=f"run-heartbeat-{run_id[:8]}", daemon=True)
        heartbeat_thread.start()
        try:
            emit("run_status", {"status": "running"})
            if payload.get("chat_only"):
                run_plain_chat_task(
                    thread_id=thread_id, run_id=run_id,
                    model_id=payload.get("model_id"), event_sink=emit,
                )
            else:
                run_agent_task(
                    repo_url=payload["repo_url"],
                    prompt=payload["content"],
                    thread_id=thread_id,
                    run_id=run_id,
                    event_sink=emit,
                    interaction_action=payload.get("interaction_action"),
                    plan_id=payload.get("plan_id"),
                    intervention_id=payload.get("intervention_id"),
                    model_id=payload.get("model_id"),
                    worker_id=worker_id,
                )
            if store.is_run_cancel_requested(run_id):
                raise RunCancelled("Run cancelled by user")
            if ownership_lost.is_set():
                raise RunLeaseLost("Run worker lease was lost; task stopped to prevent duplicate execution")
            terminal = store.get_run(thread_id, run_id) or {}
            status = terminal.get("status") or "completed"
            if status in {"queued", "running", "cancelling"}:
                status = "completed"
            store.finish_queued_run(thread_id=thread_id, run_id=run_id, status=status)
            emit("thread_done", {"id": thread_id, "thread_id": thread_id, "status": status})
            emit("done", {"status": status})
        except RunCancelled as exc:
            store.finish_queued_run(thread_id=thread_id, run_id=run_id, status="cancelled", error=str(exc))
            store.update_thread_status(thread_id, "cancelled")
            emit_terminal(store, thread_id, run_id, "cancelled", str(exc))
        except RunLeaseLost as exc:
            store.finish_queued_run(thread_id=thread_id, run_id=run_id, status="interrupted", error=str(exc))
            store.update_thread_status(thread_id, "interrupted")
            emit_terminal(store, thread_id, run_id, "interrupted", str(exc))
        except Exception as exc:
            logger.exception("Agent run failed: thread_id=%s run_id=%s", thread_id, run_id)
            store.finish_queued_run(thread_id=thread_id, run_id=run_id, status="failed", error=str(exc))
            store.update_thread_status(thread_id, "failed")
            emit_terminal(store, thread_id, run_id, "failed", str(exc))
        finally:
            heartbeat_stop.set()
            heartbeat_thread.join(timeout=1)


def emit_terminal(store: Any, thread_id: str, run_id: str, status: str, message: str) -> None:
    for event, payload in (
        ("error", {"message": message, "thread_id": thread_id, "run_id": run_id}),
        ("thread_done", {"id": thread_id, "thread_id": thread_id, "status": status}),
        ("done", {"status": status}),
    ):
        try:
            store.append_run_stream_event(thread_id=thread_id, run_id=run_id, event=event, payload=payload)
        except Exception:
            logger.exception("Could not persist terminal run event: run_id=%s event=%s", run_id, event)


_pool: RunWorkerPool | None = None
_pool_lock = threading.Lock()


def get_run_worker_pool() -> RunWorkerPool:
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = RunWorkerPool()
        return _pool


__all__ = ["RunCancelled", "RunLeaseLost", "RunWorkerPool", "get_run_worker_pool"]
