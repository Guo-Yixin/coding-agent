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
            CREATE TABLE IF NOT EXISTS projects (
              project_id TEXT PRIMARY KEY,
              tenant_id TEXT NOT NULL DEFAULT 'default',
              user_id TEXT NOT NULL DEFAULT 'system',
              name TEXT NOT NULL,
              provider TEXT,
              repo_url TEXT,
              repo_owner TEXT,
              repo_name TEXT,
              is_legacy BOOLEAN NOT NULL DEFAULT FALSE,
              created_at TIMESTAMPTZ NOT NULL,
              updated_at TIMESTAMPTZ NOT NULL
            )
            """,
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
              project_id TEXT,
              branch_name TEXT,
              pr_url TEXT,
              latest_run_status TEXT NOT NULL,
              created_at TIMESTAMPTZ NOT NULL,
              updated_at TIMESTAMPTZ NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS thread_drafts (
              thread_id TEXT PRIMARY KEY,
              tenant_id TEXT NOT NULL DEFAULT 'default',
              user_id TEXT NOT NULL DEFAULT 'system',
              content TEXT NOT NULL DEFAULT '',
              revision BIGINT NOT NULL DEFAULT 1,
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
              attempt INTEGER NOT NULL DEFAULT 0,
              payload JSONB,
              queued_at TIMESTAMPTZ,
              cancel_requested BOOLEAN NOT NULL DEFAULT FALSE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS run_stream_events (
              seq BIGSERIAL PRIMARY KEY,
              thread_id TEXT NOT NULL,
              run_id TEXT NOT NULL,
              event TEXT NOT NULL,
              payload JSONB NOT NULL,
              created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_run_stream_events_run_seq ON run_stream_events (thread_id, run_id, seq)",
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
            "CREATE INDEX IF NOT EXISTS idx_projects_scope_updated ON projects (tenant_id, user_id, updated_at DESC)",
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
                ("threads", "project_id", "TEXT"),
                ("runs", "tenant_id", "TEXT NOT NULL DEFAULT 'default'"),
                ("runs", "user_id", "TEXT NOT NULL DEFAULT 'system'"),
                ("runs", "worker_id", "TEXT"),
                ("runs", "lease_expires_at", "TIMESTAMPTZ"),
                ("runs", "heartbeat_at", "TIMESTAMPTZ"),
                ("runs", "attempt", "INTEGER NOT NULL DEFAULT 0"),
                ("runs", "payload", "JSONB"),
                ("runs", "queued_at", "TIMESTAMPTZ"),
                ("runs", "cancel_requested", "BOOLEAN NOT NULL DEFAULT FALSE"),
                ("thread_plans", "version", "INTEGER NOT NULL DEFAULT 1"),
                ("thread_plans", "supersedes_plan_id", "TEXT"),
                ("thread_plans", "decision_feedback", "TEXT"),
            ):
                conn.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {definition}")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_threads_project_updated ON threads (project_id, updated_at DESC)")
            self._backfill_legacy_projects(conn)
            conn.execute(
                """CREATE INDEX IF NOT EXISTS idx_runs_queue_claim
                   ON runs (queued_at, run_id)
                   WHERE status='queued' AND payload IS NOT NULL AND cancel_requested=FALSE"""
            )

    def _backfill_legacy_projects(self, conn: Any | None = None) -> None:
        """Group historical threads by repository without changing their history."""

        if conn is None:
            with self._connection() as connection:
                self._backfill_legacy_projects(connection)
            return
        legacy_rows = conn.execute(
            """
            SELECT thread_id, tenant_id, user_id, title, repo_url, repo_owner, repo_name,
                   created_at, updated_at,
                   CASE WHEN NULLIF(BTRIM(repo_url), '') IS NULL
                     THEN 'legacy-' || md5(tenant_id || ':' || user_id || ':' || thread_id)
                     ELSE 'legacy-' || md5(tenant_id || ':' || user_id || ':' ||
                       lower(regexp_replace(rtrim(repo_url, '/'), '\\.git$', '', 'i')))
                   END AS legacy_project_id
            FROM threads WHERE project_id IS NULL
            ORDER BY created_at, thread_id
            """
        ).fetchall()
        projects: dict[str, dict[str, Any]] = {}
        for row in legacy_rows:
            project_id = row["legacy_project_id"]
            if project_id in projects:
                continue
            repo_url = row.get("repo_url")
            provider = None
            if repo_url:
                lowered = str(repo_url).lower()
                provider = "github" if "github.com/" in lowered else "gitee" if "gitee.com/" in lowered else None
            repo_label = "/".join(part for part in (row.get("repo_owner"), row.get("repo_name")) if part)
            projects[project_id] = {
                "project_id": project_id,
                "tenant_id": row["tenant_id"],
                "user_id": row["user_id"],
                "name": repo_label or ("历史会话 · " + str(row.get("title") or "未命名")[:48]),
                "provider": provider,
                "repo_url": repo_url,
                "repo_owner": row.get("repo_owner"),
                "repo_name": row.get("repo_name"),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        for project in projects.values():
            conn.execute(
                """INSERT INTO projects (project_id, tenant_id, user_id, name, provider, repo_url,
                       repo_owner, repo_name, is_legacy, created_at, updated_at)
                   VALUES (%(project_id)s, %(tenant_id)s, %(user_id)s, %(name)s, %(provider)s,
                       %(repo_url)s, %(repo_owner)s, %(repo_name)s, TRUE, %(created_at)s, %(updated_at)s)
                   ON CONFLICT(project_id) DO NOTHING""",
                project,
            )
        for row in legacy_rows:
            conn.execute(
                "UPDATE threads SET project_id=%s WHERE thread_id=%s AND project_id IS NULL",
                (row["legacy_project_id"], row["thread_id"]),
            )

    def close(self) -> None:
        self._pool.close()

    def create_project(
        self, *, project_id: str, name: str, provider: str, repo_url: str,
        repo_owner: str, repo_name: str,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        with self._connection() as conn:
            return conn.execute(
                """INSERT INTO projects
                   (project_id, tenant_id, user_id, name, provider, repo_url, repo_owner,
                    repo_name, is_legacy, created_at, updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,FALSE,%s,%s)
                   RETURNING *""",
                (project_id, self.tenant_id, self.user_id, name, provider, repo_url,
                 repo_owner, repo_name, now, now),
            ).fetchone()

    def create_chat_thread(self, *, thread_id: str) -> dict[str, Any]:
        """Create a general chat thread without attaching it to a repository project."""
        self.upsert_thread(thread_id=thread_id, title="新聊天", latest_run_status="pending")
        return self.get_thread(thread_id)

    def list_project_thread_ids(self, project_id: str) -> list[str]:
        with self._connection() as conn:
            rows = conn.execute(
                """SELECT thread_id FROM threads
                   WHERE project_id=%s AND tenant_id=%s AND user_id=%s
                   ORDER BY updated_at DESC""",
                (project_id, self.tenant_id, self.user_id),
            ).fetchall()
            return [str(row["thread_id"]) for row in rows]

    def delete_project(self, project_id: str) -> bool:
        with self._connection() as conn:
            deleted = conn.execute(
                """DELETE FROM projects AS p
                   WHERE p.project_id=%s AND p.tenant_id=%s AND p.user_id=%s
                     AND NOT EXISTS (
                       SELECT 1 FROM threads AS t WHERE t.project_id=p.project_id
                     )
                   RETURNING project_id""",
                (project_id, self.tenant_id, self.user_id),
            ).fetchone()
            return deleted is not None

    def list_projects(self) -> list[dict[str, Any]]:
        with self._connection() as conn:
            return list(conn.execute(
                """SELECT * FROM projects WHERE tenant_id=%s AND user_id=%s
                   ORDER BY updated_at DESC, name""",
                (self.tenant_id, self.user_id),
            ).fetchall())

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            return conn.execute(
                "SELECT * FROM projects WHERE project_id=%s AND tenant_id=%s AND user_id=%s",
                (project_id, self.tenant_id, self.user_id),
            ).fetchone()

    def update_project_name(self, project_id: str, name: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            return conn.execute(
                """UPDATE projects SET name=%s, updated_at=%s
                   WHERE project_id=%s AND tenant_id=%s AND user_id=%s RETURNING *""",
                (name, datetime.now(UTC), project_id, self.tenant_id, self.user_id),
            ).fetchone()

    def create_thread_for_project(self, *, thread_id: str, project_id: str) -> dict[str, Any] | None:
        now = datetime.now(UTC)
        with self._connection() as conn:
            with conn.transaction():
                project = conn.execute(
                    """SELECT * FROM projects WHERE project_id=%s AND tenant_id=%s AND user_id=%s
                       FOR UPDATE""",
                    (project_id, self.tenant_id, self.user_id),
                ).fetchone()
                if not project or not project.get("repo_url"):
                    return None
                thread = conn.execute(
                    """INSERT INTO threads
                       (thread_id, tenant_id, user_id, title, repo_url, repo_owner, repo_name,
                        project_id, latest_run_status, created_at, updated_at)
                       VALUES (%s,%s,%s,'新会话',%s,%s,%s,%s,'pending',%s,%s)
                       RETURNING *""",
                    (thread_id, self.tenant_id, self.user_id, project["repo_url"], project["repo_owner"],
                     project["repo_name"], project_id, now, now),
                ).fetchone()
                conn.execute(
                    """INSERT INTO thread_drafts (thread_id, tenant_id, user_id, content, revision, updated_at)
                       VALUES (%s,%s,%s,'',1,%s)""",
                    (thread_id, self.tenant_id, self.user_id, now),
                )
                return thread

    def get_thread_draft(self, thread_id: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            thread = conn.execute(
                "SELECT 1 FROM threads WHERE thread_id=%s AND tenant_id=%s AND user_id=%s",
                (thread_id, self.tenant_id, self.user_id),
            ).fetchone()
            if not thread:
                return None
            return conn.execute(
                "SELECT content, revision, updated_at FROM thread_drafts WHERE thread_id=%s",
                (thread_id,),
            ).fetchone() or {"content": "", "revision": 0, "updated_at": None}

    def save_thread_draft(self, *, thread_id: str, content: str) -> dict[str, Any] | None:
        now = datetime.now(UTC)
        with self._connection() as conn:
            return conn.execute(
                """INSERT INTO thread_drafts (thread_id, tenant_id, user_id, content, revision, updated_at)
                   SELECT thread_id, tenant_id, user_id, %s, 1, %s FROM threads
                   WHERE thread_id=%s AND tenant_id=%s AND user_id=%s
                   ON CONFLICT(thread_id) DO UPDATE SET content=EXCLUDED.content,
                     revision=thread_drafts.revision+1, updated_at=EXCLUDED.updated_at
                   RETURNING content, revision, updated_at""",
                (content, now, thread_id, self.tenant_id, self.user_id),
            ).fetchone()

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

    def enqueue_run(self, *, run_id: str, thread_id: str, payload: dict[str, Any]) -> None:
        now = datetime.now(UTC)
        with self._connection() as conn:
            with conn.transaction():
                conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (thread_id,))
                active = conn.execute(
                    "SELECT 1 FROM runs WHERE thread_id=%s AND status IN ('queued','running','cancelling') LIMIT 1",
                    (thread_id,),
                ).fetchone()
                if active:
                    raise ValueError("this thread already has an active run")
                conn.execute(
                    """INSERT INTO runs (run_id, thread_id, tenant_id, user_id, status, started_at, queued_at, payload)
                       VALUES (%s,%s,%s,%s,'queued',%s,%s,%s::jsonb)""",
                    (run_id, thread_id, self.tenant_id, self.user_id, now, now, self._json(payload)),
                )

    def get_run(self, thread_id: str, run_id: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM runs WHERE thread_id=%s AND run_id=%s", (thread_id, run_id)
            ).fetchone()
        if row and row.get("payload") is not None:
            row["payload"] = self._decode(row["payload"], {})
        return row

    def list_active_runs(self, *, limit: int = 50) -> list[dict[str, Any]]:
        with self._connection() as conn:
            return list(conn.execute(
                """SELECT run_id, thread_id, status, queued_at, started_at FROM runs
                   WHERE status IN ('queued','running','cancelling')
                   ORDER BY COALESCE(queued_at, started_at), run_id LIMIT %s""",
                (max(1, min(limit, 200)),),
            ).fetchall())

    def claim_next_run(
        self, *, worker_id: str, ttl_seconds: int = 300, max_active: int | None = None
    ) -> dict[str, Any] | None:
        now = datetime.now(UTC)
        with self._connection() as conn:
            with conn.transaction():
                if max_active is not None:
                    # Serialize admission checks across API replicas so the
                    # configured concurrency limit is global, not per process.
                    conn.execute("SELECT pg_advisory_xact_lock(75486593)")
                    active = conn.execute(
                        "SELECT COUNT(*) AS count FROM runs WHERE status IN ('running','cancelling') AND worker_id IS NOT NULL"
                    ).fetchone()
                    if int(active["count"]) >= max_active:
                        return None
                row = conn.execute(
                    """WITH candidate AS (
                         SELECT run_id FROM runs
                         WHERE status='queued' AND payload IS NOT NULL AND cancel_requested=FALSE
                         ORDER BY queued_at, run_id
                         FOR UPDATE SKIP LOCKED LIMIT 1
                       )
                       UPDATE runs AS r SET status='running', worker_id=%s,
                         lease_expires_at=%s, heartbeat_at=%s, started_at=%s, attempt=r.attempt+1
                       FROM candidate WHERE r.run_id=candidate.run_id
                       RETURNING r.*""",
                    (worker_id, now + timedelta(seconds=ttl_seconds), now, now),
                ).fetchone()
        if row and row.get("payload") is not None:
            row["payload"] = self._decode(row["payload"], {})
        return row

    def request_run_cancel(self, *, thread_id: str, run_id: str) -> str | None:
        with self._connection() as conn:
            with conn.transaction():
                row = conn.execute(
                    """UPDATE runs SET
                         status=CASE WHEN status='queued' THEN 'cancelled' ELSE 'cancelling' END,
                         cancel_requested=TRUE,
                         finished_at=CASE WHEN status='queued' THEN NOW() ELSE finished_at END
                       WHERE thread_id=%s AND run_id=%s AND status IN ('queued','running','cancelling')
                       RETURNING status""",
                    (thread_id, run_id),
                ).fetchone()
        return row["status"] if row else None

    def is_run_cancel_requested(self, run_id: str) -> bool:
        with self._connection() as conn:
            row = conn.execute("SELECT cancel_requested FROM runs WHERE run_id=%s", (run_id,)).fetchone()
        return bool(row and row["cancel_requested"])

    def renew_run_lease(self, *, run_id: str, worker_id: str, ttl_seconds: int = 300) -> bool:
        now = datetime.now(UTC)
        with self._connection() as conn:
            row = conn.execute(
                """UPDATE runs SET heartbeat_at=%s, lease_expires_at=%s
                   WHERE run_id=%s AND worker_id=%s AND status IN ('running','cancelling')
                   RETURNING run_id""",
                (now, now + timedelta(seconds=ttl_seconds), run_id, worker_id),
            ).fetchone()
        return row is not None

    def finish_queued_run(self, *, thread_id: str, run_id: str, status: str, error: str | None = None) -> bool:
        if status not in {"completed", "failed", "cancelled", "interrupted"}:
            raise ValueError(f"invalid terminal run status: {status}")
        with self._connection() as conn:
            row = conn.execute(
                """UPDATE runs SET status=%s, error=%s, finished_at=NOW(), worker_id=NULL,
                   lease_expires_at=NULL, heartbeat_at=NULL WHERE thread_id=%s AND run_id=%s RETURNING run_id""",
                (status, error, thread_id, run_id),
            ).fetchone()
        return row is not None

    def append_run_stream_event(
        self, *, thread_id: str, run_id: str, event: str, payload: dict[str, Any]
    ) -> int:
        with self._connection() as conn:
            row = conn.execute(
                """INSERT INTO run_stream_events (thread_id, run_id, event, payload)
                   VALUES (%s,%s,%s,%s::jsonb) RETURNING seq""",
                (thread_id, run_id, event, self._json(payload)),
            ).fetchone()
        return int(row["seq"])

    def list_run_stream_events(
        self, *, thread_id: str, run_id: str, after_seq: int = 0, limit: int = 200
    ) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = list(conn.execute(
                """SELECT seq, event, payload, created_at FROM run_stream_events
                   WHERE thread_id=%s AND run_id=%s AND seq>%s ORDER BY seq LIMIT %s""",
                (thread_id, run_id, max(0, after_seq), max(1, min(limit, 1000))),
            ).fetchall())
        for row in rows:
            row["payload"] = self._decode(row.get("payload"), {})
        return rows

    def interrupt_stale_runs(self) -> list[str]:
        with self._connection() as conn:
            with conn.transaction():
                rows = list(conn.execute(
                    """UPDATE runs SET status='interrupted', error='Worker lease expired; retry explicitly',
                         finished_at=NOW(), worker_id=NULL, lease_expires_at=NULL, heartbeat_at=NULL
                       WHERE status IN ('running','cancelling') AND (
                         (lease_expires_at IS NOT NULL AND lease_expires_at < NOW()) OR
                         (lease_expires_at IS NULL AND started_at < NOW() - INTERVAL '5 minutes')
                       ) RETURNING run_id, thread_id"""
                ).fetchall())
                for row in rows:
                    conn.execute(
                        "UPDATE threads SET latest_run_status='interrupted', updated_at=NOW() WHERE thread_id=%s",
                        (row["thread_id"],),
                    )
        for row in rows:
            self.append_run_stream_event(
                thread_id=row["thread_id"], run_id=row["run_id"], event="error",
                payload={"message": "Worker lease expired; this run was interrupted. Retry it explicitly."},
            )
            self.append_run_stream_event(
                thread_id=row["thread_id"], run_id=row["run_id"], event="done",
                payload={"status": "interrupted"},
            )
        return [row["run_id"] for row in rows]

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
        """Return the newest pending or resuming intervention for a thread."""

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
            for table in ("review_findings", "thread_plans", "thread_interventions", "thread_messages", "thread_drafts", "run_events", "run_stream_events", "runs"):
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
