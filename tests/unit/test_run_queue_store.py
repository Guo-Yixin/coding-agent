from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

from agent.core import run_queue
from agent.store.sqlite_store import LocalSqliteStore


def make_store(tmp_path):
    store = LocalSqliteStore(tmp_path / "queue.sqlite")
    store.upsert_thread(
        thread_id="thread-a", title="A", user_prompt="", repo_url="https://github.com/a/b",
        repo_owner="a", repo_name="b", latest_run_status="queued",
    )
    store.upsert_thread(
        thread_id="thread-b", title="B", user_prompt="", repo_url="https://github.com/a/b",
        repo_owner="a", repo_name="b", latest_run_status="queued",
    )
    return store


def test_enqueue_rejects_second_active_run_for_same_thread(tmp_path):
    store = make_store(tmp_path)
    try:
        store.enqueue_run(run_id="run-1", thread_id="thread-a", payload={"content": "first"})
        with pytest.raises(ValueError, match="already has an active run"):
            store.enqueue_run(run_id="run-2", thread_id="thread-a", payload={"content": "second"})
        store.enqueue_run(run_id="run-3", thread_id="thread-b", payload={"content": "parallel"})
    finally:
        store.close()


def test_competing_workers_claim_a_run_only_once(tmp_path):
    store = make_store(tmp_path)
    try:
        store.enqueue_run(run_id="run-1", thread_id="thread-a", payload={"content": "one"})
        with ThreadPoolExecutor(max_workers=12) as pool:
            claims = list(pool.map(lambda index: store.claim_next_run(worker_id=f"worker-{index}"), range(12)))
        claimed = [item for item in claims if item]
        assert len(claimed) == 1
        assert claimed[0]["run_id"] == "run-1"
        assert claimed[0]["payload"] == {"content": "one"}
        assert claimed[0]["attempt"] == 1
    finally:
        store.close()


def test_claim_respects_configured_global_active_limit(tmp_path):
    store = make_store(tmp_path)
    try:
        store.enqueue_run(run_id="run-1", thread_id="thread-a", payload={"content": "one"})
        store.enqueue_run(run_id="run-2", thread_id="thread-b", payload={"content": "two"})
        first = store.claim_next_run(worker_id="worker-a", max_active=1)
        second = store.claim_next_run(worker_id="worker-b", max_active=1)
        assert first["run_id"] == "run-1"
        assert second is None
        store.finish_queued_run(thread_id="thread-a", run_id="run-1", status="completed")
        assert store.claim_next_run(worker_id="worker-b", max_active=1)["run_id"] == "run-2"
    finally:
        store.close()


def test_event_cursor_cancel_heartbeat_and_stale_recovery(tmp_path):
    store = make_store(tmp_path)
    try:
        store.enqueue_run(run_id="run-1", thread_id="thread-a", payload={"content": "one"})
        assert store.append_run_stream_event(
            thread_id="thread-a", run_id="run-1", event="text_delta", payload={"content": "a"}
        ) == 1
        assert store.append_run_stream_event(
            thread_id="thread-a", run_id="run-1", event="text_delta", payload={"content": "b"}
        ) == 2
        assert [event["seq"] for event in store.list_run_stream_events(
            thread_id="thread-a", run_id="run-1", after_seq=1
        )] == [2]
        assert store.request_run_cancel(thread_id="thread-a", run_id="run-1") == "cancelled"
        assert store.get_run("thread-a", "run-1")["status"] == "cancelled"

        store.enqueue_run(run_id="run-2", thread_id="thread-a", payload={"content": "two"})
        claimed = store.claim_next_run(worker_id="worker-a", ttl_seconds=1)
        assert claimed["run_id"] == "run-2"
        assert store.renew_run_lease(run_id="run-2", worker_id="worker-a", ttl_seconds=30)
        with store._lock:
            store._conn.execute(
                "UPDATE runs SET lease_expires_at=? WHERE run_id=?",
                ((datetime.now(UTC) - timedelta(seconds=2)).isoformat(), "run-2"),
            )
            store._conn.commit()
        assert store.interrupt_stale_runs() == ["run-2"]
        assert store.get_run("thread-a", "run-2")["status"] == "interrupted"
        assert store.get_thread("thread-a")["latest_run_status"] == "interrupted"
    finally:
        store.close()


def test_stale_running_record_without_worker_lease_is_recovered_but_fresh_one_is_kept(tmp_path):
    store = make_store(tmp_path)
    try:
        store.upsert_thread(thread_id="stale-thread", title="stale", latest_run_status="running")
        store.upsert_thread(thread_id="fresh-thread", title="fresh", latest_run_status="running")
        store.record_run(run_id="stale-run", thread_id="stale-thread", status="running", finished=False)
        store.record_run(run_id="fresh-run", thread_id="fresh-thread", status="running", finished=False)
        with store._lock:
            store._conn.execute(
                "UPDATE runs SET started_at=? WHERE run_id=?",
                ((datetime.now(UTC) - timedelta(minutes=10)).isoformat(), "stale-run"),
            )
            store._conn.commit()

        assert store.interrupt_stale_runs() == ["stale-run"]
        assert store.get_run("stale-thread", "stale-run")["status"] == "interrupted"
        assert store.get_run("fresh-thread", "fresh-run")["status"] == "running"
    finally:
        store.close()


def test_delete_thread_removes_durable_run_stream_events(tmp_path):
    store = make_store(tmp_path)
    try:
        store.enqueue_run(run_id="run-1", thread_id="thread-a", payload={"content": "one"})
        store.append_run_stream_event(
            thread_id="thread-a", run_id="run-1", event="text_delta", payload={"content": "hello"}
        )
        assert store.delete_thread("thread-a")
        assert store.list_run_stream_events(thread_id="thread-a", run_id="run-1") == []
        assert store.get_run("thread-a", "run-1") is None
    finally:
        store.close()


def test_worker_pool_runs_independent_threads_concurrently_and_keeps_events_scoped(tmp_path, monkeypatch):
    store = make_store(tmp_path)
    store.enqueue_run(run_id="run-a", thread_id="thread-a", payload={"repo_url": "https://github.com/a/b", "content": "A"})
    store.enqueue_run(run_id="run-b", thread_id="thread-b", payload={"repo_url": "https://github.com/a/b", "content": "B"})
    both_started = __import__("threading").Barrier(2)

    def fake_run_agent_task(*, repo_url, prompt, thread_id, run_id, event_sink, worker_id, **_kwargs):
        del repo_url, worker_id
        both_started.wait(timeout=5)
        event_sink("text_delta", {"content": prompt, "message_id": f"assistant-{thread_id}"})
        store.update_thread_status(thread_id, "completed")
        store.record_run(run_id=run_id, thread_id=thread_id, status="completed", finished=True)
        return {"thread_id": thread_id, "run_id": run_id, "status": "completed"}

    monkeypatch.setattr(run_queue, "get_store", lambda: store)
    monkeypatch.setattr(run_queue, "run_agent_task", fake_run_agent_task)
    pool = run_queue.RunWorkerPool(concurrency=2, lease_seconds=30)
    pool.start()
    try:
        import time

        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            statuses = [store.get_run(thread_id, run_id)["status"] for thread_id, run_id in (
                ("thread-a", "run-a"), ("thread-b", "run-b")
            )]
            if statuses == ["completed", "completed"]:
                break
            time.sleep(0.05)
        assert statuses == ["completed", "completed"]
        for thread_id, run_id, expected in (
            ("thread-a", "run-a", "A"), ("thread-b", "run-b", "B")
        ):
            events = store.list_run_stream_events(thread_id=thread_id, run_id=run_id)
            assert any(row["event"] == "text_delta" and row["payload"]["content"] == expected for row in events)
            assert events[-1]["event"] == "done"
    finally:
        pool.stop()
        store.close()
