from __future__ import annotations

from typing import Any, TypedDict


class AgentTaskState(TypedDict, total=False):
    thread_id: str
    repo_url: str
    repo_owner: str
    repo_name: str
    branch_name: str
    pr_url: str
    latest_run_status: str
    messages: list[dict[str, Any]]
