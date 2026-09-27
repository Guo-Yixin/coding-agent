from __future__ import annotations

from pathlib import Path

import pytest

from agent.core import persistence


def test_sqlite_checkpointer_factory_creates_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(persistence, "PERSISTENCE_BACKEND", "sqlite")
    saver = persistence.make_checkpointer(tmp_path / "checkpoints.sqlite")

    assert saver is not None
    assert (tmp_path / "checkpoints.sqlite").exists()


def test_sqlite_store_factory_creates_business_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(persistence, "PERSISTENCE_BACKEND", "sqlite")
    monkeypatch.setattr("agent.core.settings.STORE_DB_PATH", tmp_path / "store.sqlite")
    store = persistence.make_business_store()

    store.upsert_thread(thread_id="thread-1", title="demo", latest_run_status="pending")
    assert store.get_thread("thread-1")["title"] == "demo"
    store.close()


def test_postgres_requires_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(persistence, "PERSISTENCE_BACKEND", "postgres")
    monkeypatch.setattr(persistence, "POSTGRES_DSN", "")
    monkeypatch.delenv("POSTGRES_DSN", raising=False)

    with pytest.raises(RuntimeError, match="POSTGRES_DSN"):
        persistence.make_checkpointer()


@pytest.mark.integration
def test_postgres_connection_smoke() -> None:
    """Exercise every PostgreSQL persistence adapter against a disposable DSN."""
    dsn = persistence.POSTGRES_DSN
    if not dsn:
        pytest.skip("POSTGRES_DSN is not configured")
    from uuid import uuid4
    import json

    from agent.store.postgres_store import PostgresBusinessStore

    checkpointer = None
    graph_store = None
    business_store = None
    suffix = uuid4().hex
    thread_id = f"eval-{suffix}"
    namespace = ("eval", suffix)
    checkpoint_id = f"checkpoint-{suffix}"
    try:
        persistence.PERSISTENCE_BACKEND = "postgres"
        checkpointer = persistence.make_checkpointer()
        graph_store = persistence.make_langgraph_store()
        business_store = persistence.make_business_store()

        business_store.upsert_thread(thread_id=thread_id, title="integration", latest_run_status="pending")
        assert business_store.get_thread(thread_id)["title"] == "integration"
        business_store.add_thread_message(
            message_id=f"message-{suffix}", thread_id=thread_id, author="agent", content="persisted"
        )
        assert business_store.list_thread_messages(thread_id)[0]["content"] == "persisted"
        business_store.add_run_event(
            event_id=f"event-{suffix}", thread_id=thread_id, kind="eval", title="smoke", status="completed"
        )
        assert business_store.list_run_events(thread_id)[0]["kind"] == "eval"
        business_store.append_audit_event(
            event_id=f"audit-{suffix}", event_type="eval.persistence_smoke",
            payload={"component": "business_store"}, thread_id=thread_id,
        )
        assert business_store.list_audit_events(thread_id=thread_id)[0]["event_type"] == "eval.persistence_smoke"

        # Reapplying CREATE/ALTER IF NOT EXISTS schema setup must be safe.
        migration_probe = PostgresBusinessStore(dsn)
        migration_probe.close()

        rollback_event_id = f"rollback-{suffix}"
        try:
            with business_store._connection() as connection:  # noqa: SLF001 - exercise PostgreSQL rollback
                with connection.transaction():
                    connection.execute(
                        "INSERT INTO audit_events (event_id, thread_id, event_type, payload, created_at) "
                        "VALUES (%s, %s, %s, %s::jsonb, now())",
                        (rollback_event_id, thread_id, "eval.rollback_probe", json.dumps({"rollback": True})),
                    )
                    raise RuntimeError("rollback probe")
        except RuntimeError as exc:
            assert str(exc) == "rollback probe"
        assert all(event["event_id"] != rollback_event_id for event in business_store.list_audit_events(thread_id=thread_id))

        graph_store.put(namespace, "value", {"ok": True, "run": suffix})
        item = graph_store.get(namespace, "value")
        assert item is not None and item.value == {"ok": True, "run": suffix}

        config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
        checkpoint = {
            "v": 1,
            "id": checkpoint_id,
            "ts": "2026-09-26T00:00:00+00:00",
            "channel_values": {"eval_value": "persisted"},
            "channel_versions": {"eval_value": 1},
            "versions_seen": {},
            "pending_sends": [],
        }
        checkpoint_config = checkpointer.put(
            config,
            checkpoint,
            {"source": "input", "step": 0, "writes": {}, "parents": {}},
            {"eval_value": 1},
        )
        stored = checkpointer.get_tuple(checkpoint_config)
        assert stored is not None
        assert stored.checkpoint["channel_values"]["eval_value"] == "persisted"

        # Close every pool/connection and reconstruct them to verify persisted
        # data remains readable after an application-style reconnect.
        persistence.close_persistence()
        checkpointer = persistence.make_checkpointer()
        graph_store = persistence.make_langgraph_store()
        business_store = persistence.make_business_store()
        assert business_store.get_thread(thread_id)["title"] == "integration"
        assert graph_store.get(namespace, "value").value["run"] == suffix
        assert checkpointer.get_tuple(checkpoint_config).checkpoint["channel_values"]["eval_value"] == "persisted"

        assert business_store.delete_thread(thread_id) is True
        graph_store.delete(namespace, "value")
    finally:
        persistence.close_persistence()
