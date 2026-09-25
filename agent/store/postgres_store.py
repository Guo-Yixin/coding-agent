from __future__ import annotations

"""PostgreSQL implementation of the platform business Store.

The LangGraph checkpoint/store tables are owned by LangGraph.  This module only
owns the platform-facing tables that power the dashboard, worker lifecycle and
audit trail.  Keeping the two concerns separate makes migration and recovery
behaviour explicit instead of coupling the UI to LangGraph internals.
"""

import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, Iterator

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class PostgresBusinessStore:
    """Thread-safe pooled PostgreSQL Store with SQLite-compatible methods."""

    def __init__(
        self,
        dsn: str,
        *,
        tenant_id: str = "default",
        user_id: str = "system",
        min_size: int = 1,
        max_size: int = 8,
    ) -> None:
        if not dsn:
            raise ValueError("POSTGRES_DSN is required for PostgreSQL persistence")
        self.dsn = dsn
        self.tenant_id = tenant_id
        self.user_id = user_id
        self._pool = ConnectionPool(
            conninfo=dsn,
            min_size=min_size,
            max_size=max_size,
            kwargs={"autocommit": True, "row_factory": dict_row},
            open=False,
        )
        self._pool.open(wait=True)
        self._init_schema()

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        with self._pool.connection() as conn:
            yield conn

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _decode(value: Any, default: Any = None) -> Any:
        if value is None:
            return default
        if isinstance(value, (dict, list, int, float, bool)):
            return value
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return default if default is not None else value

    def _init_schema(self) -> None:
        statements = [
            """
            CREATE TABLE IF NOT EXISTS threads (
              thread_id TEXT PRIMARY KEY,
              tenant_id TEXT NOT NULL DEFAULT 'default',
              user_id TEXT NOT NULL DEFAULT 'system',
              title TEXT NOT NULL,
              user_prompt TEXT,
              repo_url TEXT,
              repo_owner TEXT,
              repo_name TEXT,
              branch_name TEXT,
              pr_url TEXT,
              latest_run_status TEXT NOT NULL,
              created_at TIMESTAMPTZ NOT NULL,
              updated_at TIMESTAMPTZ NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS runs (
              run_id TEXT PRIMARY KEY,
              thread_id TEXT NOT NULL,
              tenant_id TEXT NOT NULL DEFAULT 'default',
              user_id TEXT NOT NULL DEFAULT 'system',
              status TEXT NOT NULL,
              started_at TIMESTAMPTZ NOT NULL,
              finished_at TIMESTAMPTZ,
              error TEXT,
              worker_id TEXT,
              lease_expires_at TIMESTAMPTZ,
              heartbeat_at TIMESTAMPTZ,
              attempt INTEGER NOT NULL DEFAULT 0
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS run_events (
              id TEXT PRIMARY KEY,
              thread_id TEXT NOT NULL,
              run_id TEXT,
              tenant_id TEXT NOT NULL DEFAULT 'default',
              user_id TEXT NOT NULL DEFAULT 'system',
              kind TEXT NOT NULL,
              title TEXT NOT NULL,
              status TEXT NOT NULL,
              detail TEXT,
              created_at TIMESTAMPTZ NOT NULL,
              updated_at TIMESTAMPTZ NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS thread_messages (
              message_id TEXT PRIMARY KEY,
              thread_id TEXT NOT NULL,
              run_id TEXT,
              tenant_id TEXT NOT NULL DEFAULT 'default',
              user_id TEXT NOT NULL DEFAULT 'system',
              author TEXT NOT NULL,
              content TEXT NOT NULL,
              metadata JSONB,
              created_at TIMESTAMPTZ NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS thread_plans (
              plan_id TEXT PRIMARY KEY,
              thread_id TEXT NOT NULL,
              run_id TEXT,
              tenant_id TEXT NOT NULL DEFAULT 'default',
              user_id TEXT NOT NULL DEFAULT 'system',
              status TEXT NOT NULL,
              prompt TEXT NOT NULL,
              plan_text TEXT NOT NULL,
              plan_path TEXT NOT NULL,
              version INTEGER NOT NULL DEFAULT 1,
              supersedes_plan_id TEXT,
              decision_feedback TEXT,
              created_at TIMESTAMPTZ NOT NULL,
              approved_at TIMESTAMPTZ
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS thread_interventions (
              intervention_id TEXT PRIMARY KEY,
              thread_id TEXT NOT NULL,
              run_id TEXT NOT NULL,
              tenant_id TEXT NOT NULL DEFAULT 'default',
              user_id TEXT NOT NULL DEFAULT 'system',
              status TEXT NOT NULL,
              payload JSONB NOT NULL,
              response TEXT,
              created_at TIMESTAMPTZ NOT NULL,
              resolved_at TIMESTAMPTZ
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS review_findings (
              id TEXT PRIMARY KEY,
              thread_id TEXT NOT NULL,
              tenant_id TEXT NOT NULL DEFAULT 'default',
              user_id TEXT NOT NULL DEFAULT 'system',
              file TEXT NOT NULL,
              line INTEGER,
              severity TEXT NOT NULL,
              title TEXT NOT NULL,
              description TEXT NOT NULL,
              status TEXT NOT NULL,
              created_at TIMESTAMPTZ NOT NULL,
              updated_at TIMESTAMPTZ NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS settings (
              key TEXT PRIMARY KEY,
              value JSONB NOT NULL,
              updated_at TIMESTAMPTZ NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS audit_events (
              event_id TEXT PRIMARY KEY,
              tenant_id TEXT NOT NULL DEFAULT 'default',
              user_id TEXT NOT NULL DEFAULT 'system',
              thread_id TEXT,
              run_id TEXT,
              event_type TEXT NOT NULL,
              payload JSONB NOT NULL DEFAULT '{}'::jsonb,
              created_at TIMESTAMPTZ NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS worker_leases (
              lease_id TEXT PRIMARY KEY,
              worker_id TEXT NOT NULL,
              run_id TEXT NOT NULL,
              tenant_id TEXT NOT NULL DEFAULT 'default',
              acquired_at TIMESTAMPTZ NOT NULL,
              heartbeat_at TIMESTAMPTZ NOT NULL,
              expires_at TIMESTAMPTZ NOT NULL,
              UNIQUE(run_id)
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_threads_scope_updated ON threads (tenant_id, user_id, updated_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_runs_status_lease ON runs (status, lease_expires_at)",
            "CREATE INDEX IF NOT EXISTS idx_events_thread_created ON run_events (thread_id, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_events_run_created ON run_events (thread_id, run_id, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_audit_scope_created ON audit_events (tenant_id, created_at)",
        ]
        with self._connection() as conn:
            for statement in statements:
                conn.execute(statement)
            # Allows a previously created development database to gain the
            # fields introduced by the worker/audit implementation.
            for table, column, definition in (
                ("threads", "tenant_id", "TEXT NOT NULL DEFAULT 'default'"),
                ("threads", "user_id", "TEXT NOT NULL DEFAULT 'system'"),
                ("runs", "tenant_id", "TEXT NOT NULL DEFAULT 'default'"),
                ("runs", "user_id", "TEXT NOT NULL DEFAULT 'system'"),
                ("runs", "worker_id", "TEXT"),
                ("runs", "lease_expires_at", "TIMESTAMPTZ"),
                ("runs", "heartbeat_at", "TIMESTAMPTZ"),
                ("runs", "attempt", "INTEGER NOT NULL DEFAULT 0"),
                ("thread_plans", "version", "INTEGER NOT NULL DEFAULT 1"),
                ("thread_plans", "supersedes_plan_id", "TEXT"),
                ("thread_plans", "decision_feedback", "TEXT"),
            ):
                conn.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {definition}")

    def close(self) -> None:
        self._pool.close()

    def upsert_thread(
        self,
        *,
        thread_id: str,
        title: str,
        repo_url: str | None = None,
        repo_owner: str | None = None,
        repo_name: str | None = None,
        branch_name: str | None = None,
        pr_url: str | None = None,
        user_prompt: str | None = None,
        latest_run_status: str = "pending",
        tenant_id: str | None = None,
        user_id: str | None = None,
    ) -> None:
        now = datetime.now(UTC)
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO threads (
                  thread_id, tenant_id, user_id, title, user_prompt, repo_url,
                  repo_owner, repo_name, branch_name, pr_url, latest_run_status,
                  created_at, updated_at
                ) VALUES (%(thread_id)s, %(tenant_id)s, %(user_id)s, %(title)s,
                  %(user_prompt)s, %(repo_url)s, %(repo_owner)s, %(repo_name)s,
                  %(branch_name)s, %(pr_url)s, %(status)s, %(now)s, %(now)s)
                ON CONFLICT(thread_id) DO UPDATE SET
                  title=threads.title,
                  user_prompt=COALESCE(EXCLUDED.user_prompt, threads.user_prompt),
                  repo_url=COALESCE(EXCLUDED.repo_url, threads.repo_url),
                  repo_owner=COALESCE(EXCLUDED.repo_owner, threads.repo_owner),
                  repo_name=COALESCE(EXCLUDED.repo_name, threads.repo_name),
                  branch_name=COALESCE(EXCLUDED.branch_name, threads.branch_name),
                  pr_url=COALESCE(EXCLUDED.pr_url, threads.pr_url),
                  latest_run_status=EXCLUDED.latest_run_status,
                  updated_at=EXCLUDED.updated_at
                """,
                {
                    "thread_id": thread_id,
                    "tenant_id": tenant_id or self.tenant_id,
                    "user_id": user_id or self.user_id,
                    "title": title,
                    "user_prompt": user_prompt,
                    "repo_url": repo_url,
                    "repo_owner": repo_owner,
                    "repo_name": repo_name,
                    "branch_name": branch_name,
                    "pr_url": pr_url,
                    "status": latest_run_status,
                    "now": now,
                },
            )

    def get_thread(self, thread_id: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            return conn.execute("SELECT * FROM threads WHERE thread_id = %s", (thread_id,)).fetchone()

    def list_threads(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connection() as conn:
            return list(conn.execute("SELECT * FROM threads ORDER BY updated_at DESC LIMIT %s", (limit,)).fetchall())

    def update_thread_status(self, thread_id: str, status: str, *, pr_url: str | None = None, branch_name: str | None = None) -> None:
        with self._connection() as conn:
            conn.execute(
                """UPDATE threads SET latest_run_status=%s, pr_url=COALESCE(%s, pr_url),
                   branch_name=COALESCE(%s, branch_name), updated_at=%s WHERE thread_id=%s""",
                (status, pr_url, branch_name, datetime.now(UTC), thread_id),
            )

    def update_thread_title(self, thread_id: str, title: str) -> None:
        with self._connection() as conn:
            conn.execute("UPDATE threads SET title=%s, updated_at=%s WHERE thread_id=%s", (title, datetime.now(UTC), thread_id))

    def record_run(self, *, run_id: str, thread_id: str, status: str, error: str | None = None, finished: bool = False) -> None:
        now = datetime.now(UTC)
        with self._connection() as conn:
            conn.execute(
                """INSERT INTO runs (run_id, thread_id, tenant_id, user_id, status, started_at, finished_at, error)
                   VALUES (%(run_id)s, %(thread_id)s, %(tenant_id)s, %(user_id)s, %(status)s, %(now)s, %(finished_at)s, %(error)s)
                   ON CONFLICT(run_id) DO UPDATE SET status=EXCLUDED.status,
                   finished_at=COALESCE(EXCLUDED.finished_at, runs.finished_at), error=EXCLUDED.error""",
                {"run_id": run_id, "thread_id": thread_id, "tenant_id": self.tenant_id, "user_id": self.user_id,
                 "status": status, "now": now, "finished_at": now if finished else None, "error": error},
            )

    def add_run_event(self, *, event_id: str, thread_id: str, kind: str, title: str, status: str, detail: str | None = None, run_id: str | None = None) -> None:
        now = datetime.now(UTC)
        with self._connection() as conn:
            conn.execute(
                """INSERT INTO run_events (id, thread_id, run_id, tenant_id, user_id, kind, title, status, detail, created_at, updated_at)
                   VALUES (%(id)s, %(thread_id)s, %(run_id)s, %(tenant_id)s, %(user_id)s, %(kind)s, %(title)s, %(status)s, %(detail)s, %(now)s, %(now)s)
                   ON CONFLICT(id) DO UPDATE SET kind=EXCLUDED.kind, title=EXCLUDED.title,
                   status=EXCLUDED.status, detail=EXCLUDED.detail, updated_at=EXCLUDED.updated_at""",
                {"id": event_id, "thread_id": thread_id, "run_id": run_id, "tenant_id": self.tenant_id,
                 "user_id": self.user_id, "kind": kind, "title": title, "status": status, "detail": detail, "now": now},
            )

    def list_run_events(self, thread_id: str) -> list[dict[str, Any]]:
        with self._connection() as conn:
            return list(conn.execute("SELECT * FROM run_events WHERE thread_id=%s ORDER BY created_at ASC", (thread_id,)).fetchall())

    def list_run_events_for_run(self, thread_id: str, run_id: str) -> list[dict[str, Any]]:
        with self._connection() as conn:
            return list(conn.execute(
                "SELECT * FROM run_events WHERE thread_id=%s AND run_id=%s ORDER BY created_at ASC, id ASC",
                (thread_id, run_id),
            ).fetchall())

    def list_runs(self, thread_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        with self._connection() as conn:
            return list(conn.execute(
                "SELECT * FROM runs WHERE thread_id=%s ORDER BY started_at DESC LIMIT %s",
                (thread_id, max(1, min(limit, 100))),
            ).fetchall())

    def clear_run_events(self, thread_id: str) -> None:
        with self._connection() as conn:
            conn.execute("DELETE FROM run_events WHERE thread_id=%s", (thread_id,))

    def add_thread_message(self, *, message_id: str, thread_id: str, author: str, content: str, run_id: str | None = None, metadata: dict[str, Any] | None = None) -> None:
        normalized = content.strip()
        with self._connection() as conn:
            if author == "user":
                duplicate = conn.execute(
                    "SELECT 1 FROM thread_messages WHERE thread_id=%s AND author='user' AND content=%s LIMIT 1",
                    (thread_id, normalized),
                ).fetchone()
                if duplicate:
                    return
            conn.execute(
                """INSERT INTO thread_messages (message_id, thread_id, run_id, tenant_id, user_id, author, content, metadata, created_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
                   ON CONFLICT(message_id) DO UPDATE SET content=EXCLUDED.content, metadata=EXCLUDED.metadata""",
                (message_id, thread_id, run_id, self.tenant_id, self.user_id, author, normalized, self._json(metadata or {}), datetime.now(UTC)),
            )

    def list_thread_messages(self, thread_id: str) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = list(conn.execute("SELECT * FROM thread_messages WHERE thread_id=%s ORDER BY created_at ASC", (thread_id,)).fetchall())
        for row in rows:
            row["metadata"] = self._decode(row.get("metadata"), {})
        return rows

    def add_thread_plan(self, *, plan_id: str, thread_id: str, prompt: str, plan_text: str, plan_path: str, run_id: str | None = None, status: str = "pending", version: int = 1, supersedes_plan_id: str | None = None) -> None:
        with self._connection() as conn:
            conn.execute(
                """INSERT INTO thread_plans (plan_id, thread_id, run_id, tenant_id, user_id, status, prompt, plan_text, plan_path, version, supersedes_plan_id, created_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT(plan_id) DO UPDATE SET status=EXCLUDED.status, prompt=EXCLUDED.prompt,
                   plan_text=EXCLUDED.plan_text, plan_path=EXCLUDED.plan_path,
                   version=EXCLUDED.version, supersedes_plan_id=EXCLUDED.supersedes_plan_id""",
                (plan_id, thread_id, run_id, self.tenant_id, self.user_id, status, prompt.strip(), plan_text.strip(), plan_path, version, supersedes_plan_id, datetime.now(UTC)),
            )

    def get_latest_thread_plan(self, thread_id: str, *, status: str | None = None) -> dict[str, Any] | None:
        with self._connection() as conn:
            if status is None:
                return conn.execute("SELECT * FROM thread_plans WHERE thread_id=%s ORDER BY created_at DESC LIMIT 1", (thread_id,)).fetchone()
            return conn.execute("SELECT * FROM thread_plans WHERE thread_id=%s AND status=%s ORDER BY created_at DESC LIMIT 1", (thread_id, status)).fetchone()

    def list_thread_plans(self, thread_id: str) -> list[dict[str, Any]]:
        with self._connection() as conn:
            return list(conn.execute("SELECT * FROM thread_plans WHERE thread_id=%s ORDER BY created_at ASC", (thread_id,)).fetchall())

    def approve_thread_plan(self, plan_id: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            conn.execute("UPDATE thread_plans SET status='approved', approved_at=%s WHERE plan_id=%s AND status='pending'", (datetime.now(UTC), plan_id))
            return conn.execute("SELECT * FROM thread_plans WHERE plan_id=%s", (plan_id,)).fetchone()

    def get_thread_plan(self, plan_id: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            return conn.execute("SELECT * FROM thread_plans WHERE plan_id=%s", (plan_id,)).fetchone()

    def transition_thread_plan(
        self, plan_id: str, *, thread_id: str, expected_status: str,
        status: str, decision_feedback: str | None = None,
    ) -> dict[str, Any] | None:
        with self._connection() as conn:
            approved_at = datetime.now(UTC) if status == "approved" else None
            row = conn.execute(
                """UPDATE thread_plans
                   SET status=%s, decision_feedback=%s, approved_at=COALESCE(%s, approved_at)
                   WHERE plan_id=%s AND thread_id=%s AND status=%s
                   RETURNING *""",
                (status, decision_feedback, approved_at, plan_id, thread_id, expected_status),
            ).fetchone()
            return row

    def create_thread_intervention(self, *, intervention_id: str, thread_id: str, run_id: str, payload: dict[str, Any]) -> None:
        with self._connection() as conn:
            conn.execute(
                """INSERT INTO thread_interventions
                   (intervention_id, thread_id, run_id, tenant_id, user_id, status, payload, created_at)
                   VALUES (%s,%s,%s,%s,%s,'pending',%s::jsonb,%s)""",
                (intervention_id, thread_id, run_id, self.tenant_id, self.user_id, self._json(payload), datetime.now(UTC)),
            )

    def get_thread_intervention(self, intervention_id: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM thread_interventions WHERE intervention_id=%s", (intervention_id,)
            ).fetchone()
        if row:
            row["payload"] = self._decode(row.get("payload"), {})
        return row

    def get_latest_active_thread_intervention(self, thread_id: str) -> dict[str, Any] | None:
        """读取会话中最新待答复或正在恢复的人工介入。"""

        with self._connection() as conn:
            row = conn.execute(
                """SELECT * FROM thread_interventions
                   WHERE thread_id=%s AND status IN ('pending', 'resuming')
                   ORDER BY created_at DESC LIMIT 1""",
                (thread_id,),
            ).fetchone()
        if row:
            row["payload"] = self._decode(row.get("payload"), {})
        return row

    def resolve_thread_intervention(self, intervention_id: str, *, thread_id: str, response: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute(
                """UPDATE thread_interventions SET status='resuming', response=%s
                   WHERE intervention_id=%s AND thread_id=%s AND status='pending'
                   RETURNING *""",
                (response, intervention_id, thread_id),
            ).fetchone()
        if row:
            row["payload"] = self._decode(row.get("payload"), {})
        return row if row and row.get("status") == "resuming" else None

    def finish_thread_intervention(self, intervention_id: str, *, thread_id: str, status: str = "resolved") -> None:
        with self._connection() as conn:
            resolved_at = datetime.now(UTC) if status == "resolved" else None
            conn.execute(
                """UPDATE thread_interventions SET status=%s, resolved_at=%s
                   WHERE intervention_id=%s AND thread_id=%s AND status='resuming'""",
                (status, resolved_at, intervention_id, thread_id),
            )

    def finish_open_run_events(
        self, thread_id: str, *, status: str = "completed", run_id: str | None = None
    ) -> None:
        with self._connection() as conn:
            if run_id is None:
                conn.execute(
                    "UPDATE run_events SET status=%s, updated_at=%s WHERE thread_id=%s AND status IN ('pending','in_progress')",
                    (status, datetime.now(UTC), thread_id),
                )
            else:
                conn.execute(
                    "UPDATE run_events SET status=%s, updated_at=%s WHERE thread_id=%s AND run_id=%s AND status IN ('pending','in_progress')",
                    (status, datetime.now(UTC), thread_id, run_id),
                )

    def get_latest_run(self, thread_id: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            return conn.execute("SELECT * FROM runs WHERE thread_id=%s ORDER BY started_at DESC LIMIT 1", (thread_id,)).fetchone()

    def delete_thread(self, thread_id: str) -> bool:
        with self._connection() as conn:
            exists = conn.execute("SELECT 1 FROM threads WHERE thread_id=%s", (thread_id,)).fetchone()
            if not exists:
                return False
            for table in ("review_findings", "thread_plans", "thread_interventions", "thread_messages", "run_events", "runs"):
                conn.execute(f"DELETE FROM {table} WHERE thread_id=%s", (thread_id,))
            conn.execute("DELETE FROM audit_events WHERE thread_id=%s", (thread_id,))
            conn.execute("DELETE FROM threads WHERE thread_id=%s", (thread_id,))
            return True

    def add_finding(self, *, finding_id: str, thread_id: str, file: str, line: int | None, severity: str, title: str, description: str, status: str = "open") -> None:
        now = datetime.now(UTC)
        with self._connection() as conn:
            conn.execute(
                """INSERT INTO review_findings (id, thread_id, tenant_id, user_id, file, line, severity, title, description, status, created_at, updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT(id) DO UPDATE SET file=EXCLUDED.file, line=EXCLUDED.line,
                   severity=EXCLUDED.severity, title=EXCLUDED.title, description=EXCLUDED.description,
                   status=EXCLUDED.status, updated_at=EXCLUDED.updated_at""",
                (finding_id, thread_id, self.tenant_id, self.user_id, file, line, severity, title, description, status, now, now),
            )

    def list_findings(self, thread_id: str) -> list[dict[str, Any]]:
        with self._connection() as conn:
            return list(conn.execute("SELECT * FROM review_findings WHERE thread_id=%s ORDER BY created_at ASC", (thread_id,)).fetchall())

    def set_setting(self, key: str, value: Any) -> None:
        with self._connection() as conn:
            conn.execute(
                """INSERT INTO settings (key, value, updated_at) VALUES (%s,%s::jsonb,%s)
                   ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value, updated_at=EXCLUDED.updated_at""",
                (key, self._json(value), datetime.now(UTC)),
            )

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self._connection() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key=%s", (key,)).fetchone()
        return self._decode(row["value"], default) if row else default

    def append_audit_event(self, *, event_id: str, event_type: str, payload: dict[str, Any] | None = None, thread_id: str | None = None, run_id: str | None = None) -> None:
        with self._connection() as conn:
            conn.execute(
                """INSERT INTO audit_events (event_id, tenant_id, user_id, thread_id, run_id, event_type, payload, created_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s) ON CONFLICT(event_id) DO NOTHING""",
                (event_id, self.tenant_id, self.user_id, thread_id, run_id, event_type, self._json(payload or {}), datetime.now(UTC)),
            )

    def list_audit_events(self, *, thread_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with self._connection() as conn:
            if thread_id:
                rows = list(conn.execute("SELECT * FROM audit_events WHERE thread_id=%s ORDER BY created_at DESC LIMIT %s", (thread_id, limit)).fetchall())
            else:
                rows = list(conn.execute("SELECT * FROM audit_events ORDER BY created_at DESC LIMIT %s", (limit,)).fetchall())
        for row in rows:
            row["payload"] = self._decode(row.get("payload"), {})
        return rows

    def acquire_worker_lease(self, *, lease_id: str, worker_id: str, run_id: str, ttl_seconds: int = 60) -> bool:
        now = datetime.now(UTC)
        expires = now + timedelta(seconds=ttl_seconds)
        with self._connection() as conn:
            row = conn.execute(
                """INSERT INTO worker_leases (lease_id, worker_id, run_id, tenant_id, acquired_at, heartbeat_at, expires_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT(run_id) DO UPDATE SET worker_id=EXCLUDED.worker_id,
                   heartbeat_at=EXCLUDED.heartbeat_at, expires_at=EXCLUDED.expires_at
                   WHERE worker_leases.expires_at < EXCLUDED.heartbeat_at OR worker_leases.worker_id=EXCLUDED.worker_id
                RETURNING lease_id""",
                (lease_id, worker_id, run_id, self.tenant_id, now, now, expires),
            ).fetchone()
            if row is not None:
                conn.execute(
                    """UPDATE runs
                       SET worker_id=%s, lease_expires_at=%s, heartbeat_at=%s
                       WHERE run_id=%s""",
                    (worker_id, expires, now, run_id),
                )
            return row is not None

    def renew_worker_lease(self, *, run_id: str, worker_id: str, ttl_seconds: int = 60) -> bool:
        now = datetime.now(UTC)
        with self._connection() as conn:
            row = conn.execute(
                "UPDATE worker_leases SET heartbeat_at=%s, expires_at=%s WHERE run_id=%s AND worker_id=%s RETURNING lease_id",
                (now, now + timedelta(seconds=ttl_seconds), run_id, worker_id),
            ).fetchone()
            if row is not None:
                conn.execute(
                    "UPDATE runs SET lease_expires_at=%s, heartbeat_at=%s WHERE run_id=%s AND worker_id=%s",
                    (now + timedelta(seconds=ttl_seconds), now, run_id, worker_id),
                )
            return row is not None

    def release_worker_lease(self, *, run_id: str, worker_id: str) -> bool:
        with self._connection() as conn:
            result = conn.execute("DELETE FROM worker_leases WHERE run_id=%s AND worker_id=%s", (run_id, worker_id))
            conn.execute(
                "UPDATE runs SET worker_id=NULL, lease_expires_at=NULL, heartbeat_at=NULL WHERE run_id=%s AND worker_id=%s",
                (run_id, worker_id),
            )
            return result.rowcount > 0

    def recover_stale_runs(self) -> list[str]:
        with self._connection() as conn:
            rows = list(conn.execute(
                """UPDATE runs SET status='queued', worker_id=NULL, lease_expires_at=NULL,
                   heartbeat_at=NULL, attempt=attempt+1
                   WHERE status='running' AND lease_expires_at IS NOT NULL AND lease_expires_at < NOW()
                   RETURNING run_id"""
            ).fetchall())
            conn.execute("DELETE FROM worker_leases WHERE expires_at < NOW()")
            return [row["run_id"] for row in rows]
