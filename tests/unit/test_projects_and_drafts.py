from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException

from agent.store.sqlite_store import LocalSqliteStore


def test_projects_bind_threads_to_fixed_repositories_and_isolate_drafts(tmp_path: Path) -> None:
    store = LocalSqliteStore(tmp_path / "business.sqlite")
    try:
        first = store.create_project(
            project_id="project-a", name="A", provider="github",
            repo_url="https://github.com/owner/repo-a.git", repo_owner="owner", repo_name="repo-a",
        )
        second = store.create_project(
            project_id="project-b", name="B", provider="gitee",
            repo_url="https://gitee.com/owner/repo-b.git", repo_owner="owner", repo_name="repo-b",
        )
        thread_a1 = store.create_thread_for_project(thread_id="a1", project_id=first["project_id"])
        thread_a2 = store.create_thread_for_project(thread_id="a2", project_id=first["project_id"])
        thread_b = store.create_thread_for_project(thread_id="b1", project_id=second["project_id"])

        assert thread_a1["repo_url"] == thread_a2["repo_url"] == first["repo_url"]
        assert thread_a1["project_id"] == thread_a2["project_id"] == first["project_id"]
        assert thread_b["repo_url"] == second["repo_url"]
        assert store.save_thread_draft(thread_id="a1", content="draft A") is not None
        assert store.save_thread_draft(thread_id="b1", content="draft B") is not None
        assert store.get_thread_draft("a1")["content"] == "draft A"
        assert store.get_thread_draft("a2")["content"] == ""
        assert store.get_thread_draft("b1")["content"] == "draft B"
        assert store.save_thread_draft(thread_id="missing", content="ignored") is None
    finally:
        store.close()


def test_standalone_chat_is_not_bound_to_a_project_or_repository_and_project_delete_requires_empty_project(tmp_path: Path) -> None:
    store = LocalSqliteStore(tmp_path / "projects.sqlite")
    try:
        chat = store.create_chat_thread(thread_id="chat-only")
        assert chat["repo_url"] is None
        assert chat["project_id"] is None
        assert chat["title"] == "新聊天"

        project = store.create_project(
            project_id="project-delete", name="Delete me", provider="github",
            repo_url="https://github.com/owner/repo.git", repo_owner="owner", repo_name="repo",
        )
        thread = store.create_thread_for_project(thread_id="project-thread", project_id=project["project_id"])
        assert store.list_project_thread_ids(project["project_id"]) == ["project-thread"]
        assert store.delete_project(project["project_id"]) is False
        assert store.delete_thread(thread["thread_id"]) is True
        assert store.delete_project(project["project_id"]) is True
        assert store.get_project(project["project_id"]) is None
    finally:
        store.close()


def test_legacy_threads_are_grouped_by_repository_and_keep_history(tmp_path: Path) -> None:
    store = LocalSqliteStore(tmp_path / "legacy.sqlite")
    try:
        store.upsert_thread(
            thread_id="legacy-one", title="First", repo_url="https://github.com/owner/repo.git",
            repo_owner="owner", repo_name="repo", latest_run_status="completed",
        )
        store.upsert_thread(
            thread_id="legacy-two", title="Second", repo_url="https://github.com/owner/repo.git",
            repo_owner="owner", repo_name="repo", latest_run_status="failed",
        )
        store._backfill_legacy_projects()
        rows = [store.get_thread("legacy-one"), store.get_thread("legacy-two")]
        assert rows[0]["project_id"] == rows[1]["project_id"]
        assert rows[0]["title"] == "First"
        assert rows[1]["latest_run_status"] == "failed"
    finally:
        store.close()


def test_project_api_normalizes_provider_and_rejects_mismatch(monkeypatch) -> None:
    from agent.api import dashboard_routes

    class FakeStore:
        def __init__(self): self.created = None
        def create_project(self, **values):
            self.created = values
            return {**values, "is_legacy": False}

    fake = FakeStore()
    monkeypatch.setattr(dashboard_routes, "get_store", lambda: fake)
    result = dashboard_routes.dashboard_create_project(
        dashboard_routes.DashboardProjectRequest(name=" Demo ", provider="gitee", repo="owner/repo")
    )
    assert result["repo"] == "https://gitee.com/owner/repo.git"
    assert fake.created["provider"] == "gitee"

    with pytest.raises(HTTPException) as error:
        dashboard_routes.dashboard_create_project(
            dashboard_routes.DashboardProjectRequest(name="Demo", provider="gitee", repo="https://github.com/owner/repo")
        )
    assert error.value.status_code == 422


def test_draft_api_enforces_size_and_thread_existence(monkeypatch) -> None:
    from agent.api import dashboard_routes

    class FakeStore:
        def save_thread_draft(self, **_values): return None

    monkeypatch.setattr(dashboard_routes, "get_store", lambda: FakeStore())
    with pytest.raises(HTTPException) as missing:
        dashboard_routes.dashboard_save_thread_draft("missing", dashboard_routes.DashboardThreadDraftRequest(content="x"))
    assert missing.value.status_code == 404

    with pytest.raises(HTTPException) as too_large:
        dashboard_routes.dashboard_save_thread_draft(
            "thread", dashboard_routes.DashboardThreadDraftRequest(content="x" * 100_001)
        )
    assert too_large.value.status_code == 413


def test_project_delete_endpoint_blocks_active_runs_then_deletes_all_conversations(monkeypatch) -> None:
    from agent.api import dashboard_routes

    class FakeStore:
        project = {"project_id": "project", "name": "Project"}
        active = [{"thread_id": "thread-1"}]
        deleted = False

        def get_project(self, project_id): return self.project if project_id == "project" else None
        def list_project_thread_ids(self, _project_id): return ["thread-1", "thread-2"]
        def list_active_runs(self): return self.active
        def delete_project(self, _project_id): self.deleted = True; return True

    fake = FakeStore()
    deleted_threads = []
    monkeypatch.setattr(dashboard_routes, "get_store", lambda: fake)
    monkeypatch.setattr(dashboard_routes, "delete_task", lambda thread_id: deleted_threads.append(thread_id) or True)

    with pytest.raises(HTTPException) as active_error:
        dashboard_routes.dashboard_delete_project("project")
    assert active_error.value.status_code == 409
    assert deleted_threads == []

    fake.active = []
    assert dashboard_routes.dashboard_delete_project("project") is None
    assert deleted_threads == ["thread-1", "thread-2"]
    assert fake.deleted is True


def test_project_delete_endpoint_rejects_missing_project(monkeypatch) -> None:
    from agent.api import dashboard_routes

    class FakeStore:
        def get_project(self, _project_id): return None

    monkeypatch.setattr(dashboard_routes, "get_store", lambda: FakeStore())
    with pytest.raises(HTTPException) as error:
        dashboard_routes.dashboard_delete_project("missing")
    assert error.value.status_code == 404
