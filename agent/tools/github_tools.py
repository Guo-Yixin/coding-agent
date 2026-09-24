"""GitHub 仓库协作工具。"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import tool

from agent.core.events import record_event
from agent.core.graph import get_store
from agent.tools.github_api import (
    cancel_workflow,
    create_issue,
    create_pull_request,
    get_pull_request_context,
    get_issue_context,
    list_workflow_runs,
    post_issue_comment,
    post_pr_comment,
    rerun_workflow,
)
from agent.tools.runtime_context import get_runtime_thread_id, runtime_is_read_only_task

logger = logging.getLogger("agent.run.github")


def _write_blocked() -> dict[str, Any] | None:
    if runtime_is_read_only_task():
        return {"ok": False, "error": "当前任务是只读任务，不能执行 GitHub 写操作。请先确认实施。"}
    return None


@tool
def open_github_pull_request(
    owner: str,
    repo: str,
    head: str,
    base: str = "",
    title: str = "CODING generated changes",
    body: str = "由 CODING 自动生成。",
) -> dict[str, Any]:
    """为已推送到 GitHub 的分支创建或复用普通 Pull Request，不创建 Draft。"""

    blocked = _write_blocked()
    if blocked:
        return blocked
    data = create_pull_request(owner=owner, repo=repo, head=head, base=base or None, title=title, body=body)
    url = data.get("html_url") or data.get("url") or ""
    thread_id = get_runtime_thread_id()
    if thread_id:
        get_store().update_thread_status(thread_id, "pr_created", pr_url=url, branch_name=head)
        record_event(thread_id, "github:pr", "创建或复用 GitHub Pull Request", kind="fetch", status="completed", detail=url)
    return {"ok": True, "pr_url": url, "raw": data}


@tool
def publish_github_pr_comment(owner: str, repo: str, number: int, body: str) -> dict[str, Any]:
    """向 GitHub Pull Request 发布普通评论。"""

    blocked = _write_blocked()
    if blocked:
        return blocked
    return {"ok": True, "raw": post_pr_comment(owner=owner, repo=repo, number=number, body=body)}


@tool
def get_github_pull_request_context(owner: str, repo: str, number: int) -> dict[str, Any]:
    """读取 GitHub PR、commits、文件、普通评论、Review Comment、Review 和 CI 状态。"""

    return get_pull_request_context(owner=owner, repo=repo, number=number)


@tool
def create_github_issue(owner: str, repo: str, title: str, body: str = "", labels: list[str] | None = None) -> dict[str, Any]:
    """创建 GitHub Issue。"""

    blocked = _write_blocked()
    if blocked:
        return blocked
    data = create_issue(owner=owner, repo=repo, title=title, body=body, labels=labels)
    return {"ok": True, "issue_url": data.get("html_url") or data.get("url") or "", "raw": data}


@tool
def publish_github_issue_comment(owner: str, repo: str, number: int, body: str) -> dict[str, Any]:
    """向 GitHub Issue 或 PR 发布普通评论。"""

    blocked = _write_blocked()
    if blocked:
        return blocked
    return {"ok": True, "raw": post_issue_comment(owner=owner, repo=repo, number=number, body=body)}


@tool
def get_github_issue_context(owner: str, repo: str, number: int) -> dict[str, Any]:
    """读取 GitHub Issue 和评论上下文。"""

    return get_issue_context(owner=owner, repo=repo, number=number)


@tool
def get_github_actions_status(owner: str, repo: str, head_sha: str = "") -> dict[str, Any]:
    """读取 GitHub Actions workflow runs，供 CI 状态回流使用。"""

    runs = list_workflow_runs(owner=owner, repo=repo, head_sha=head_sha or None)
    return {"ok": True, "workflow_runs": runs, "count": len(runs)}


@tool
def rerun_github_actions(owner: str, repo: str, run_id: int, failed_jobs_only: bool = False) -> dict[str, Any]:
    """重新运行 GitHub Actions workflow。"""

    blocked = _write_blocked()
    if blocked:
        return blocked
    return {"ok": True, "raw": rerun_workflow(owner=owner, repo=repo, run_id=run_id, failed_jobs_only=failed_jobs_only)}


@tool
def cancel_github_actions(owner: str, repo: str, run_id: int) -> dict[str, Any]:
    """取消正在运行的 GitHub Actions workflow。"""

    blocked = _write_blocked()
    if blocked:
        return blocked
    return {"ok": True, "raw": cancel_workflow(owner=owner, repo=repo, run_id=run_id)}
