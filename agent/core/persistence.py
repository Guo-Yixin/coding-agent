from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.store.sqlite import SqliteStore
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from agent.core.settings import (
    DEFAULT_TENANT_ID,
    DEFAULT_USER_ID,
    PERSISTENCE_BACKEND,
    POSTGRES_DSN,
    POSTGRES_POOL_MAX_SIZE,
    POSTGRES_POOL_MIN_SIZE,
)
from agent.store.postgres_store import PostgresBusinessStore

_postgres_checkpointer_connection: Connection[Any] | None = None
_postgres_store_pool: ConnectionPool[Any] | None = None
_postgres_business_store: PostgresBusinessStore | None = None


def _require_postgres_dsn() -> str:
    dsn = POSTGRES_DSN or os.environ.get("POSTGRES_DSN", "").strip()
    if not dsn:
        raise RuntimeError("PERSISTENCE_BACKEND=postgres requires POSTGRES_DSN")
    return dsn


def make_checkpointer(db_path: Path | None = None):
    """创建 LangGraph checkpointer，按配置选择 SQLite 或 PostgreSQL。"""
    if PERSISTENCE_BACKEND == "postgres":
        global _postgres_checkpointer_connection
        if _postgres_checkpointer_connection is None:
            os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")
            _postgres_checkpointer_connection = Connection.connect(
                _require_postgres_dsn(), autocommit=True, prepare_threshold=0, row_factory=dict_row
            )
            from langgraph.checkpoint.postgres import PostgresSaver
            saver = PostgresSaver(_postgres_checkpointer_connection)
            saver.setup()
            return saver
        from langgraph.checkpoint.postgres import PostgresSaver
        return PostgresSaver(_postgres_checkpointer_connection)

    if db_path is None:
        raise ValueError("SQLite checkpointer requires db_path")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    return saver


def make_langgraph_store(db_path: Path | None = None):
    """创建 DeepAgents StoreBackend 使用的 LangGraph Store。"""
    if PERSISTENCE_BACKEND == "postgres":
        global _postgres_store_pool
        from langgraph.store.postgres import PostgresStore
        if _postgres_store_pool is None:
            _postgres_store_pool = ConnectionPool(
                conninfo=_require_postgres_dsn(),
                min_size=POSTGRES_POOL_MIN_SIZE,
                max_size=POSTGRES_POOL_MAX_SIZE,
                kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
                open=False,
            )
            _postgres_store_pool.open(wait=True)
            store = PostgresStore(conn=_postgres_store_pool)
            store.setup()
            return store
        return PostgresStore(conn=_postgres_store_pool)

    if db_path is None:
        raise ValueError("SQLite LangGraph Store requires db_path")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False, isolation_level=None)
    store = SqliteStore(conn)
    store.setup()
    return store


def make_business_store():
    """创建平台业务 Store，与 LangGraph checkpoint/store 分开管理。"""
    global _postgres_business_store
    if PERSISTENCE_BACKEND == "postgres":
        if _postgres_business_store is None:
            _postgres_business_store = PostgresBusinessStore(
                _require_postgres_dsn(), tenant_id=DEFAULT_TENANT_ID, user_id=DEFAULT_USER_ID,
                min_size=POSTGRES_POOL_MIN_SIZE, max_size=POSTGRES_POOL_MAX_SIZE,
            )
        return _postgres_business_store
    from agent.core.settings import STORE_DB_PATH
    from agent.store.sqlite_store import LocalSqliteStore
    return LocalSqliteStore(STORE_DB_PATH)


def close_persistence() -> None:
    """关闭长生命周期的 PostgreSQL 连接，供测试和优雅停机调用。"""
    global _postgres_checkpointer_connection, _postgres_store_pool, _postgres_business_store
    if _postgres_business_store is not None:
        _postgres_business_store.close()
        _postgres_business_store = None
    if _postgres_store_pool is not None:
        _postgres_store_pool.close()
        _postgres_store_pool = None
    if _postgres_checkpointer_connection is not None:
        _postgres_checkpointer_connection.close()
        _postgres_checkpointer_connection = None
