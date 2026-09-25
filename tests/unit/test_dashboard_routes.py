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


def test_message_payload_restores_versioned_proposal_and_current_decision(monkeypatch) -> None:
    class FakeStore:
        def list_thread_messages(self, _thread_id):
            return [{
                "message_id": "plan-message",
                "author": "agent",
                "content": "完整方案文本",
                "metadata": {"proposal": {
                    "plan_id": "plan-1", "version": 2, "status": "pending",
                    "source_prompt": "实施功能", "plan_text": "完整方案文本",
                }},
                "created_at": datetime(2026, 9, 24, 12, 0, tzinfo=UTC),
            }]

        def get_thread_plan(self, plan_id):
            assert plan_id == "plan-1"
            return {"status": "superseded", "version": 2}

    monkeypatch.setattr(dashboard_routes, "get_store", lambda: FakeStore())
    result = dashboard_routes._message_payload({"thread_id": "thread-1"})

    assert result[0]["chunks"] == [{
        "kind": "proposal", "plan_id": "plan-1", "version": 2,
        "status": "superseded", "source_prompt": "实施功能", "plan_text": "完整方案文本",
    }]


def test_awaiting_approval_status_is_not_rendered_as_finished():
    assert dashboard_routes._status_for_frontend("awaiting_approval") == "awaiting_approval"


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


def test_expired_plan_action_is_rejected_before_stream_starts(monkeypatch) -> None:
    class FakeStore:
        def get_thread_plan(self, _plan_id):
            return {"plan_id": "plan-1", "thread_id": "thread-1", "status": "approved"}

    monkeypatch.setattr(
        dashboard_routes,
        "get_task",
        lambda _thread_id: {"repo_url": "https://github.com/owner/repo.git"},
    )
    monkeypatch.setattr(dashboard_routes, "get_store", lambda: FakeStore())
    monkeypatch.setattr(
        dashboard_routes,
        "_post_streaming_response",
        lambda **_kwargs: pytest.fail("expired plan must be rejected before opening SSE"),
    )
    body = dashboard_routes.DashboardThreadMessageRequest(
        content="确认并实施", repo="owner/repo", provider="github",
        interaction_action="approve_plan", plan_id="plan-1",
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(dashboard_routes.dashboard_stream_existing_message("thread-1", body))

    assert exc_info.value.status_code == 409


def test_pending_intervention_is_restored_as_thread_card(monkeypatch) -> None:
    class FakeStore:
        def get_latest_thread_plan(self, _thread_id):
            return None

        def get_latest_active_thread_intervention(self, thread_id):
            assert thread_id == "thread-1"
            return {
                "intervention_id": "intervention-1",
                "status": "pending",
                "payload": {"question": "可以继续吗？", "reason": "需要确认", "options": ["可以"]},
                "created_at": datetime(2026, 9, 25, 12, 0, tzinfo=UTC),
            }

        def list_thread_messages(self, _thread_id):
            return []

    monkeypatch.setattr(dashboard_routes, "get_store", lambda: FakeStore())
    monkeypatch.setattr(dashboard_routes, "visible_checkpoint_messages", lambda _thread_id: [])
    payload = dashboard_routes._thread_payload({
        "thread_id": "thread-1", "repo_url": "https://github.com/owner/repo.git",
        "created_at": datetime(2026, 9, 25, 12, 0, tzinfo=UTC),
    })

    assert payload["pendingIntervention"]["intervention_id"] == "intervention-1"
    assert payload["messages"][-1]["chunks"] == [{
        "kind": "intervention", "intervention_id": "intervention-1", "status": "pending",
        "question": "可以继续吗？", "reason": "需要确认", "options": ["可以"],
    }]


def test_pending_intervention_rejects_ordinary_message_before_stream(monkeypatch) -> None:
    class FakeStore:
        def get_latest_active_thread_intervention(self, _thread_id):
            return {"intervention_id": "intervention-1", "status": "pending"}

    monkeypatch.setattr(
        dashboard_routes, "get_task",
        lambda _thread_id: {"repo_url": "https://github.com/owner/repo.git"},
    )
    monkeypatch.setattr(dashboard_routes, "get_store", lambda: FakeStore())
    monkeypatch.setattr(
        dashboard_routes, "_post_streaming_response",
        lambda **_kwargs: pytest.fail("ordinary input must not start a new run while HITL is pending"),
    )
    body = dashboard_routes.DashboardThreadMessageRequest(
        content="1", repo="owner/repo", provider="github",
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(dashboard_routes.dashboard_stream_existing_message("thread-1", body))

    assert exc_info.value.status_code == 409
    assert "人工介入答复" in exc_info.value.detail


def test_pending_intervention_reply_resumes_matching_interruption(monkeypatch) -> None:
    expected_response = object()

    class FakeStore:
        def get_latest_active_thread_intervention(self, _thread_id):
            return {"intervention_id": "intervention-1", "status": "pending"}

        def get_thread_intervention(self, intervention_id):
            assert intervention_id == "intervention-1"
            return {
                "intervention_id": intervention_id,
                "thread_id": "thread-1",
                "status": "pending",
            }

    monkeypatch.setattr(
        dashboard_routes, "get_task",
        lambda _thread_id: {"repo_url": "https://github.com/owner/repo.git"},
    )
    monkeypatch.setattr(dashboard_routes, "get_store", lambda: FakeStore())
    monkeypatch.setattr(
        dashboard_routes, "_post_streaming_response",
        lambda **kwargs: expected_response if (
            kwargs["thread_id"] == "thread-1"
            and kwargs["interaction_action"] == "resume_intervention"
            and kwargs["intervention_id"] == "intervention-1"
            and kwargs["content"] == "允许继续"
        ) else pytest.fail(f"unexpected resume request: {kwargs}"),
    )
    body = dashboard_routes.DashboardThreadMessageRequest(
        content="允许继续", repo="owner/repo", provider="github",
        interaction_action="resume_intervention", intervention_id="intervention-1",
    )

    result = asyncio.run(dashboard_routes.dashboard_stream_existing_message("thread-1", body))

    assert result is expected_response
