from datetime import UTC, datetime

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
