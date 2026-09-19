from __future__ import annotations

import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.store.sqlite import SqliteStore


def make_checkpointer(db_path: Path) -> SqliteSaver:
    """创建保存 LangGraph thread state 的 SQLite checkpointer。"""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    return saver


def make_langgraph_store(db_path: Path) -> SqliteStore:
    """创建 DeepAgents StoreBackend 使用的 LangGraph SQLite Store。

    该数据库只负责 `/memories/...` 这类长期记忆文件的底层持久化。
    表结构、文件内容格式和读写协议都由 LangGraph Store 管理，项目代码只负责
    提供数据库路径和复用同一个 store 实例。
    """

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False, isolation_level=None)
    store = SqliteStore(conn)
    store.setup()
    return store
