from __future__ import annotations

import asyncio

from agent.api import dashboard_routes
from agent.core import run_queue
from agent.store.sqlite_store import LocalSqliteStore


def test_post_run_stream_is_durable_and_can_resume_from_event_cursor(tmp_path, monkeypatch):
    store = LocalSqliteStore(tmp_path / "stream.sqlite")

    def initialize(*, repo_url, prompt, thread_id, **_kwargs):
        store.upsert_thread(
            thread_id=thread_id, title=prompt, user_prompt=prompt, repo_url=repo_url,
            repo_owner="owner", repo_name="repo", latest_run_status="running",
        )
        return thread_id

    monkeypatch.setattr(dashboard_routes, "get_store", lambda: store)
    monkeypatch.setattr(dashboard_routes, "initialize_task_record", initialize)
    monkeypatch.setattr(dashboard_routes, "get_task", lambda thread_id: store.get_thread(thread_id))
    monkeypatch.setattr(
        dashboard_routes, "_thread_meta_payload",
        lambda thread: {"id": thread["thread_id"], "title": thread["title"], "status": "queued"},
    )
    monkeypatch.setattr(run_queue, "get_store", lambda: store)

    def fake_run_agent_task(*, repo_url, prompt, thread_id, run_id, event_sink, **_kwargs):
        del repo_url
        event_sink("message_start", {"message_id": "assistant", "author": "agent"})
        event_sink("text_delta", {"message_id": "assistant", "content": prompt})
        store.record_run(run_id=run_id, thread_id=thread_id, status="completed", finished=True)
        store.update_thread_status(thread_id, "completed")
        return {"thread_id": thread_id, "run_id": run_id, "status": "completed"}

    monkeypatch.setattr(run_queue, "run_agent_task", fake_run_agent_task)
    pool = run_queue.RunWorkerPool(concurrency=1, lease_seconds=30)
    thread_id = "durable-stream-probe"
    pool.start()
    try:
        response = dashboard_routes._post_streaming_response(
            thread_id=thread_id, repo_url="https://github.com/owner/repo.git", content="persist me"
        )

        async def collect(response):
            chunks = []
            async for chunk in response.body_iterator:
                chunks.append(chunk.decode() if isinstance(chunk, bytes) else str(chunk))
            return "".join(chunks)

        body = asyncio.run(collect(response))
        # Completed runs are no longer active; derive the run id from its event rows.
        rows = store._conn.execute(
            "SELECT DISTINCT run_id FROM run_stream_events WHERE thread_id=?", (thread_id,)
        ).fetchall()
        run_id = rows[0]["run_id"]
        assert "event: text_delta" in body and "persist me" in body
        assert "id: " in body and body.rstrip().endswith("}")

        resumed = asyncio.run(dashboard_routes.dashboard_resume_run_stream(thread_id, run_id, after=7))
        resumed_body = asyncio.run(collect(resumed))
        assert "event: done" in resumed_body
        assert "persist me" not in resumed_body
        assert store.get_run(thread_id, run_id)["status"] == "completed"
    finally:
        pool.stop()
        store.close()


def test_repository_free_chat_uses_durable_queue_and_persists_reply(tmp_path, monkeypatch):
    store = LocalSqliteStore(tmp_path / "plain-chat-stream.sqlite")
    monkeypatch.setattr(dashboard_routes, "get_store", lambda: store)
    monkeypatch.setattr(run_queue, "get_store", lambda: store)
    monkeypatch.setattr(dashboard_routes, "_normalize_dashboard_model_id", lambda value: value or "deepseek-flash")
    monkeypatch.setattr(dashboard_routes, "_thread_payload", lambda thread: {
        "id": thread["thread_id"], "title": thread["title"], "chatOnly": True,
    })
    monkeypatch.setattr(dashboard_routes, "_thread_meta_payload", lambda thread: {
        "id": thread["thread_id"], "title": thread["title"], "status": "queued",
    })
    monkeypatch.setattr(dashboard_routes, "get_task", lambda thread_id: store.get_thread(thread_id))

    def fake_chat_task(*, thread_id, run_id, model_id, event_sink):
        assert model_id == "deepseek-v4-pro"
        event_sink("message_start", {"message_id": f"assistant-{run_id}", "author": "agent"})
        event_sink("text_delta", {"message_id": f"assistant-{run_id}", "content": "无仓库回答"})
        store.add_thread_message(
            message_id=f"assistant-{run_id}", thread_id=thread_id, run_id=run_id,
            author="agent", content="无仓库回答", metadata={"model_id": model_id},
        )
        store.update_thread_status(thread_id, "completed")
        return {"status": "completed"}

    monkeypatch.setattr(run_queue, "run_plain_chat_task", fake_chat_task)
    pool = run_queue.RunWorkerPool(concurrency=1, lease_seconds=30)
    pool.start()
    try:
        response = asyncio.run(dashboard_routes.dashboard_stream_new_message(
            dashboard_routes.DashboardThreadMessageRequest(
                content="请解释异步队列", model_id="deepseek-v4-pro",
            )
        ))

        async def collect():
            chunks = []
            async for chunk in response.body_iterator:
                chunks.append(chunk.decode() if isinstance(chunk, bytes) else str(chunk))
            return "".join(chunks)

        body = asyncio.run(collect())
        row = store._conn.execute("SELECT thread_id, run_id FROM runs LIMIT 1").fetchone()
        run = store.get_run(row["thread_id"], row["run_id"])
        assert run["status"] == "completed"
        assert run["payload"]["chat_only"] is True
        assert run["payload"]["repo_url"] is None
        assert "无仓库回答" in body
        assert store.get_thread(row["thread_id"])["project_id"] is None
        assert [item["content"] for item in store.list_thread_messages(row["thread_id"])] == [
            "请解释异步队列", "无仓库回答",
        ]
    finally:
        pool.stop()
        store.close()
