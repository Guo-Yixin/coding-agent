import asyncio
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

import agent.api.dashboard_routes as dashboard_routes
from agent.api.dashboard_routes import _timestamp_ms


def test_timestamp_ms_accepts_postgres_datetime() -> None:
    value = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)

    assert _timestamp_ms(value) == int(value.timestamp() * 1000)


def test_message_payload_reads_postgres_projection(monkeypatch) -> None:
    class FakeStore:
        def list_thread_messages(self, thread_id: str) -> list[dict[str, object]]:
            assert thread_id == "thread-1"
            return [
                {
                    "message_id": "message-1",
                    "author": "user",
                    "content": "请读取历史消息",
                    "created_at": datetime(2026, 9, 24, 12, 0, tzinfo=UTC),
                }
            ]

    monkeypatch.setattr(dashboard_routes, "PERSISTENCE_BACKEND", "postgres")
    monkeypatch.setattr(dashboard_routes, "get_store", lambda: FakeStore())

    payload = dashboard_routes._message_payload({"thread_id": "thread-1"})

    assert payload == [
        {
            "id": "message-1",
            "author": "user",
            "timestamp": "2026-09-24T12:00:00+00:00",
            "chunks": [{"kind": "text", "text": "请读取历史消息"}],
        }
    ]


def test_existing_thread_rejects_repository_switch(monkeypatch) -> None:
    monkeypatch.setattr(
        dashboard_routes,
        "get_task",
        lambda _thread_id: {"repo_url": "https://gitee.com/owner/repo.git"},
    )
    monkeypatch.setattr(
        dashboard_routes,
        "_post_streaming_response",
        lambda **_kwargs: pytest.fail("must reject before starting the task"),
    )
    body = dashboard_routes.DashboardThreadMessageRequest(
        content="继续",
        repo="owner/repo",
        provider="github",
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(dashboard_routes.dashboard_stream_existing_message("thread-1", body))

    assert exc_info.value.status_code == 409
    assert "新建会话" in exc_info.value.detail


def test_existing_thread_accepts_same_repo_shorthand(monkeypatch) -> None:
    expected = object()
    monkeypatch.setattr(
        dashboard_routes,
        "get_task",
        lambda _thread_id: {"repo_url": "https://github.com/Owner/Repo.git"},
    )
    monkeypatch.setattr(
        dashboard_routes,
        "_post_streaming_response",
        lambda **kwargs: expected if kwargs["repo_url"] == "https://github.com/Owner/Repo.git" else None,
    )
    body = dashboard_routes.DashboardThreadMessageRequest(
        content="继续",
        repo="owner/repo",
        provider="github",
    )

    result = asyncio.run(dashboard_routes.dashboard_stream_existing_message("thread-1", body))

    assert result is expected
