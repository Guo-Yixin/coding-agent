from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import psycopg
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.store.postgres import PostgresStore
from langgraph.store.sqlite import SqliteStore
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from agent.store.postgres_store import PostgresBusinessStore


@dataclass
class MigrationReport:
    source: str
    target_database: str
    tables: dict[str, int] = field(default_factory=dict)
    checkpoints: int = 0
    checkpoint_writes: int = 0
    store_items: int = 0
    skipped: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sqlite_rows(path: Path, table: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in conn.execute(f"SELECT * FROM {table}").fetchall()]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def migrate_business_store(source: Path, target: PostgresBusinessStore, report: MigrationReport) -> None:
    """Idempotently copy platform-owned SQLite tables."""
    with target._connection() as conn:  # noqa: SLF001 - migration is a storage boundary
        for row in _sqlite_rows(source, "threads"):
            conn.execute(
                """INSERT INTO threads (thread_id, tenant_id, user_id, title, user_prompt, repo_url, repo_owner,
                   repo_name, branch_name, pr_url, latest_run_status, created_at, updated_at)
                   VALUES (%(thread_id)s, %(tenant_id)s, %(user_id)s, %(title)s, %(user_prompt)s, %(repo_url)s,
                   %(repo_owner)s, %(repo_name)s, %(branch_name)s, %(pr_url)s, %(status)s, %(created_at)s, %(updated_at)s)
                   ON CONFLICT(thread_id) DO UPDATE SET title=EXCLUDED.title, user_prompt=EXCLUDED.user_prompt,
                   repo_url=EXCLUDED.repo_url, repo_owner=EXCLUDED.repo_owner, repo_name=EXCLUDED.repo_name,
                   branch_name=EXCLUDED.branch_name, pr_url=EXCLUDED.pr_url, latest_run_status=EXCLUDED.latest_run_status,
                   updated_at=EXCLUDED.updated_at""",
                {**row, "tenant_id": row.get("tenant_id", target.tenant_id), "user_id": row.get("user_id", target.user_id), "status": row.get("latest_run_status", "pending")},
            )
        report.tables["threads"] = len(_sqlite_rows(source, "threads"))

        for row in _sqlite_rows(source, "runs"):
            conn.execute(
                """INSERT INTO runs (run_id, thread_id, tenant_id, user_id, status, started_at, finished_at, error)
                   VALUES (%(run_id)s, %(thread_id)s, %(tenant_id)s, %(user_id)s, %(status)s, %(started_at)s, %(finished_at)s, %(error)s)
                   ON CONFLICT(run_id) DO UPDATE SET status=EXCLUDED.status, finished_at=EXCLUDED.finished_at, error=EXCLUDED.error""",
                {**row, "tenant_id": row.get("tenant_id", target.tenant_id), "user_id": row.get("user_id", target.user_id)},
            )
        report.tables["runs"] = len(_sqlite_rows(source, "runs"))

        for row in _sqlite_rows(source, "run_events"):
            conn.execute(
                """INSERT INTO run_events (id, thread_id, tenant_id, user_id, kind, title, status, detail, created_at, updated_at)
                   VALUES (%(id)s, %(thread_id)s, %(tenant_id)s, %(user_id)s, %(kind)s, %(title)s, %(status)s, %(detail)s, %(created_at)s, %(updated_at)s)
                   ON CONFLICT(id) DO UPDATE SET status=EXCLUDED.status, detail=EXCLUDED.detail, updated_at=EXCLUDED.updated_at""",
                {**row, "tenant_id": row.get("tenant_id", target.tenant_id), "user_id": row.get("user_id", target.user_id)},
            )
        report.tables["run_events"] = len(_sqlite_rows(source, "run_events"))

        for row in _sqlite_rows(source, "thread_messages"):
            metadata = row.get("metadata") or "{}"
            conn.execute(
                """INSERT INTO thread_messages (message_id, thread_id, run_id, tenant_id, user_id, author, content, metadata, created_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
                   ON CONFLICT(message_id) DO UPDATE SET content=EXCLUDED.content, metadata=EXCLUDED.metadata""",
                (row["message_id"], row["thread_id"], row.get("run_id"), row.get("tenant_id", target.tenant_id), row.get("user_id", target.user_id), row["author"], row["content"], metadata, row["created_at"]),
            )
        report.tables["thread_messages"] = len(_sqlite_rows(source, "thread_messages"))

        for row in _sqlite_rows(source, "thread_plans"):
            conn.execute(
                """INSERT INTO thread_plans (plan_id, thread_id, run_id, tenant_id, user_id, status, prompt, plan_text, plan_path, created_at, approved_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT(plan_id) DO UPDATE SET status=EXCLUDED.status, plan_text=EXCLUDED.plan_text, approved_at=EXCLUDED.approved_at""",
                (row["plan_id"], row["thread_id"], row.get("run_id"), row.get("tenant_id", target.tenant_id), row.get("user_id", target.user_id), row["status"], row["prompt"], row["plan_text"], row["plan_path"], row["created_at"], row.get("approved_at")),
            )
        report.tables["thread_plans"] = len(_sqlite_rows(source, "thread_plans"))

        for row in _sqlite_rows(source, "review_findings"):
            conn.execute(
                """INSERT INTO review_findings (id, thread_id, tenant_id, user_id, file, line, severity, title, description, status, created_at, updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT(id) DO UPDATE SET status=EXCLUDED.status, description=EXCLUDED.description, updated_at=EXCLUDED.updated_at""",
                (row["id"], row["thread_id"], row.get("tenant_id", target.tenant_id), row.get("user_id", target.user_id), row["file"], row.get("line"), row["severity"], row["title"], row["description"], row["status"], row["created_at"], row["updated_at"]),
            )
        report.tables["review_findings"] = len(_sqlite_rows(source, "review_findings"))

        for row in _sqlite_rows(source, "settings"):
            value = row.get("value") or "null"
            conn.execute(
                """INSERT INTO settings (key, value, updated_at) VALUES (%s,%s::jsonb,%s)
                   ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value, updated_at=EXCLUDED.updated_at""",
                (row["key"], value, row["updated_at"]),
            )
        report.tables["settings"] = len(_sqlite_rows(source, "settings"))


def migrate_checkpoints(source: Path, dsn: str, report: MigrationReport) -> None:
    if not source.exists():
        report.skipped.append(f"checkpoint source not found: {source}")
        return
    sqlite_conn = sqlite3.connect(source, check_same_thread=False)
    try:
        sqlite_saver = SqliteSaver(sqlite_conn)
        with psycopg.connect(dsn, autocommit=True, prepare_threshold=0, row_factory=dict_row) as conn:
            postgres_saver = PostgresSaver(conn)
            postgres_saver.setup()
            for item in sqlite_saver.list(None):
                postgres_saver.put(item.config, item.checkpoint, item.metadata, item.checkpoint.get("channel_versions", {}))
                report.checkpoints += 1
                for pending in item.pending_writes or []:
                    if len(pending) >= 3:
                        task_id, channel, value = pending[:3]
                        postgres_saver.put_writes(item.config, [(channel, value)], task_id)
                        report.checkpoint_writes += 1
    finally:
        sqlite_conn.close()


def migrate_store(source: Path, dsn: str, report: MigrationReport) -> None:
    if not source.exists():
        report.skipped.append(f"store source not found: {source}")
        return
    sqlite_conn = sqlite3.connect(source, check_same_thread=False)
    try:
        sqlite_store = SqliteStore(sqlite_conn)
        pool = ConnectionPool(conninfo=dsn, min_size=1, max_size=4, kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row}, open=False)
        pool.open(wait=True)
        try:
            postgres_store = PostgresStore(conn=pool)
            postgres_store.setup()
            namespaces = sqlite_store.list_namespaces(limit=100000)
            for namespace in namespaces:
                for item in sqlite_store.search(namespace, limit=100000):
                    postgres_store.put(item.namespace, item.key, item.value, index=False)
                    report.store_items += 1
        finally:
            pool.close()
    finally:
        sqlite_conn.close()


def migrate_all(*, business_db: Path, checkpoint_db: Path, store_db: Path, dsn: str) -> MigrationReport:
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        database = conn.execute("SELECT current_database()").fetchone()["current_database"]
    report = MigrationReport(source=str(business_db.parent), target_database=database)
    business = PostgresBusinessStore(dsn)
    try:
        migrate_business_store(business_db, business, report)
    finally:
        business.close()
    migrate_checkpoints(checkpoint_db, dsn, report)
    migrate_store(store_db, dsn, report)
    return report
