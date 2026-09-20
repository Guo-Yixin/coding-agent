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
    """Run explicitly with -m integration after the local DSN is valid."""
    dsn = persistence.POSTGRES_DSN
    if not dsn:
        pytest.skip("POSTGRES_DSN is not configured")
    store = persistence.PostgresBusinessStore(dsn)
    try:
        store.upsert_thread(thread_id="test-thread", title="integration", latest_run_status="pending")
        assert store.get_thread("test-thread")["title"] == "integration"
        assert store.delete_thread("test-thread") is True
    finally:
        store.close()
