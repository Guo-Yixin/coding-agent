from datetime import UTC, datetime, timedelta
import sqlite3

import pytest
from fastapi import HTTPException

import agent.api.dashboard_routes as dashboard_routes
from agent.store.sqlite_store import LocalSqliteStore


def test_sqlite_run_events_are_kept_and_scoped_to_each_run(tmp_path):
    store = LocalSqliteStore(tmp_path / "store.sqlite")
    try:
        store.record_run(run_id="run-1", thread_id="thread-1", status="running")
        store.add_run_event(
            event_id="thread-1:run-1:todo", thread_id="thread-1", run_id="run-1",
            kind="todo", title="任务清单", status="in_progress", detail='{"todos": []}',
        )
        store.finish_open_run_events("thread-1", run_id="run-1")
        store.record_run(run_id="run-1", thread_id="thread-1", status="completed", finished=True)

        store.record_run(run_id="run-2", thread_id="thread-1", status="running")
        store.add_run_event(
            event_id="thread-1:run-2:todo", thread_id="thread-1", run_id="run-2",
            kind="todo", title="任务清单", status="in_progress", detail='{"todos": []}',
        )

        assert [run["run_id"] for run in store.list_runs("thread-1")] == ["run-2", "run-1"]
        assert [event["run_id"] for event in store.list_run_events_for_run("thread-1", "run-1")] == ["run-1"]
        assert store.list_run_events_for_run("thread-1", "run-1")[0]["status"] == "completed"
        assert len(store.list_run_events("thread-1")) == 2
    finally:
        store.close()


def test_sqlite_adds_run_id_to_legacy_event_table(tmp_path):
    db_path = tmp_path / "legacy.sqlite"
    connection = sqlite3.connect(db_path)
    connection.execute(
        "CREATE TABLE run_events (id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, kind TEXT NOT NULL, "
        "title TEXT NOT NULL, status TEXT NOT NULL, detail TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    connection.commit()
    connection.close()

    store = LocalSqliteStore(db_path)
    try:
        columns = {row["name"] for row in store._conn.execute("PRAGMA table_info(run_events)").fetchall()}
        assert "run_id" in columns
    finally:
        store.close()


def test_message_payload_restores_run_activity_between_user_and_answer(monkeypatch):
    started = datetime(2026, 9, 25, 8, 0, tzinfo=UTC)

    class FakeStore:
        def list_thread_messages(self, _thread_id):
            return [
                {"message_id": "user-1", "author": "user", "content": "做个功能", "created_at": started},
                {
                    "message_id": "answer-1", "author": "agent", "content": "完成了",
                    "created_at": started + timedelta(seconds=65), "run_id": "run-1",
                },
            ]

        def list_runs(self, _thread_id, *, limit):
            assert limit == 50
            return [{
                "run_id": "run-1", "status": "completed", "started_at": started,
                "finished_at": started + timedelta(seconds=65), "error": None,
            }]

    monkeypatch.setattr(dashboard_routes, "get_store", lambda: FakeStore())
    monkeypatch.setattr(dashboard_routes, "visible_checkpoint_messages", lambda _thread_id: [])

    messages = dashboard_routes._message_payload({"thread_id": "thread-1", "created_at": started})

    assert [message["id"] for message in messages] == [
        "user-1", "thread-1-run-activity-run-1", "answer-1",
    ]
    activity = messages[1]["chunks"][0]
    assert activity["kind"] == "run_activity"
    assert activity["activity"]["run_id"] == "run-1"
    assert activity["activity"]["status"] == "completed"


def test_run_activity_endpoint_returns_safe_run_scoped_events(monkeypatch):
    class FakeStore:
        def list_runs(self, thread_id, *, limit):
            assert thread_id == "thread-1"
            assert limit == 100
            return [{"run_id": "run-1"}]

        def list_run_events_for_run(self, thread_id, run_id):
            assert (thread_id, run_id) == ("thread-1", "run-1")
            return [
                {
                    "id": "todo", "kind": "todo", "title": "任务清单", "status": "completed",
                    "created_at": datetime(2026, 9, 25, 8, 0, tzinfo=UTC),
                    "detail": '{"todos":[{"content":"写测试","status":"completed"}]}',
                },
                {
                    "id": "progress", "kind": "other", "title": "正在生成内容", "status": "completed",
                    "created_at": datetime(2026, 9, 25, 8, 0, 1, tzinfo=UTC),
                    "detail": '{"text":"完成了"}',
                },
                {
                    "id": "failure-detail", "kind": "execute", "title": "运行测试", "status": "error",
                    "created_at": datetime(2026, 9, 25, 8, 0, 2, tzinfo=UTC),
                    "detail": "secret output should not be exposed",
                },
            ]

        def list_thread_messages(self, _thread_id):
            return [{"run_id": "run-1", "author": "agent", "content": "完成了"}]

    monkeypatch.setattr(dashboard_routes, "get_task", lambda _thread_id: {"thread_id": "thread-1"})
    monkeypatch.setattr(dashboard_routes, "get_store", lambda: FakeStore())

    result = dashboard_routes.dashboard_run_activity_events("thread-1", "run-1")

    assert result["run_id"] == "run-1"
    assert result["events"][0]["detail"]["todos"][0]["content"] == "写测试"
    assert result["events"][1]["detail"] == {}
    assert result["events"][2]["detail"] == {}


def test_run_activity_endpoint_rejects_run_from_another_thread(monkeypatch):
    class FakeStore:
        def list_runs(self, _thread_id, *, limit):
            return [{"run_id": "different-run"}]

    monkeypatch.setattr(dashboard_routes, "get_task", lambda _thread_id: {"thread_id": "thread-1"})
    monkeypatch.setattr(dashboard_routes, "get_store", lambda: FakeStore())

    with pytest.raises(HTTPException) as exc_info:
        dashboard_routes.dashboard_run_activity_events("thread-1", "foreign-run")

    assert exc_info.value.status_code == 404
