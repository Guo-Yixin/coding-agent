from __future__ import annotations

"""Dashboard 前端接口层。

这个文件只负责把 FastAPI HTTP/SSE 接口适配给 Vue Dashboard 前端，
不直接实现 Agent 推理逻辑，也不直接操作 Gitee 仓库。核心分工如下：

1. 普通 HTTP 接口：
   - `/me`、`/options` 提供页面初始化所需的用户和模型信息。
   - `/threads`、`/threads/{thread_id}` 提供左侧会话列表和历史详情。
   - `DELETE /threads/{thread_id}` 删除会话，并由 runtime 同步清理 Store 与 checkpoint。

2. POST SSE 接口：
   - `/threads/stream-message` 创建新会话并实时运行 Agent。
   - `/threads/{thread_id}/stream-message` 在已有会话中追加一轮用户输入并实时运行 Agent。

3. 数据源边界：
   - 聊天正文历史只从 LangGraph checkpoint 读取。
   - Store 只负责 thread/run/run_events/findings 等业务数据。
   - 实时页面增量来自本文件返回的 StreamingResponse，不再通过前端轮询 Store 拼接正文。
"""

import asyncio
import json
import re
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent.core.checkpoint_history import visible_checkpoint_messages
from agent.core.graph import get_store
from agent.core.runtime import delete_task, get_task, initialize_task_record, list_tasks
from agent.core.settings import PERSISTENCE_BACKEND
from agent.env_utils import get_env
from agent.repository import parse_repo_url

dashboard_router = APIRouter(prefix="/dashboard/api")

# 页面首次打开或用户没有填写仓库时使用的默认测试仓库。
DEFAULT_REPO_PROVIDER = get_env("DEFAULT_REPO_PROVIDER", "github").strip().lower()
DEFAULT_REPO_URL = get_env(
    "DEFAULT_REPO_URL",
    "https://github.com/Guo-Yixin/test-coding-repo.git"
    if DEFAULT_REPO_PROVIDER == "github"
    else "https://gitee.com/clumsypsc/test_coding_repo.git",
)


def _normalize_dashboard_repo_url(
    repo: str | None,
    *,
    provider: str | None = None,
    fallback: str | None = None,
) -> str:
    """把前端传入的仓库字段统一整理成标准 GitHub/Gitee URL。

    前端为了方便展示和输入，通常使用 `owner/repo` 这种简写；但是运行时、
    仓库映射、仓库记忆和 Gitee API 封装都统一依赖完整 URL。这里在 Dashboard
    API 边界做一次规范化，避免把 `msb-goldbin/efg-test` 直接传给
    `parse_gitee_repo_url` 后触发 500。

    支持格式：
    - `https://gitee.com/owner/repo`
    - `https://gitee.com/owner/repo.git`
    - `owner/repo`
    """

    text = (repo or fallback or DEFAULT_REPO_URL).strip()
    if not text:
        return DEFAULT_REPO_URL
    try:
        return parse_repo_url(text, provider=provider).clone_url
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="仓库地址格式不正确，请输入 GitHub/Gitee 完整 HTTPS URL 或 owner/repo。",
        ) from exc


def _normalize_dashboard_model_id(model_id: str | None) -> str:
    """只允许使用服务端当前暴露给前端的模型，避免接受任意模型名。"""

    from agent.core.model import available_agent_models

    configured_model = get_env("MAIN_MODEL", "deepseek-v4-pro").strip()
    selected_model = (model_id or configured_model).strip()
    available = available_agent_models()
    if selected_model not in available:
        raise HTTPException(
            status_code=422,
            detail=f"所选模型未启用：{selected_model}。当前可用模型为 {', '.join(available)}。",
        )
    return selected_model


class DashboardThreadMessageRequest(BaseModel):
    """前端发送一轮用户输入时的请求体。

    `content` 是用户真实输入，必须原样作为 user_message 推给前端。
    `repo` 可以是完整 URL，也可以是 owner/repo 简写。
    其它字段保留给页面模型选择、图片输入和推理强度扩展，当前本地部署版只使用部分字段。
    """

    content: str
    images: list[dict[str, Any]] | None = None
    repo: str | None = None
    provider: str | None = None
    model_id: str | None = None
    effort: str | None = None
    interaction_action: str | None = None
    plan_id: str | None = None
    intervention_id: str | None = None


class DashboardThreadTitleRequest(BaseModel):
    """前端编辑 Dashboard 会话标题时的请求体。"""

    title: str


class DashboardProjectRequest(BaseModel):
    name: str
    provider: str
    repo: str


class DashboardProjectRenameRequest(BaseModel):
    name: str


class DashboardThreadDraftRequest(BaseModel):
    content: str


def _sse_part(event: str, data: dict[str, Any], *, event_id: int | None = None) -> str:
    """输出标准命名 SSE 事件。

    新的 POST SSE 主链路采用 `event: xxx` + `data: json`，与
    `finqa_deepagent_observability` 项目保持一致。前端解析器已经兼容命名事件，
    不再需要把 event 包在 data JSON 里面。
    """

    id_line = f"id: {event_id}\n" if event_id is not None else ""
    return f"{id_line}event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def _timestamp_ms(value: str | datetime | None) -> int:
    """把 SQLite/PostgreSQL 的时间值转换成前端使用的毫秒时间戳。"""

    if not value:
        return int(datetime.now().timestamp() * 1000)
    if isinstance(value, datetime):
        return int(value.timestamp() * 1000)
    normalized = str(value).replace("Z", "+00:00")
    return int(datetime.fromisoformat(normalized).timestamp() * 1000)


def _status_for_frontend(status: str | None) -> str:
    """把项目后端状态映射成 open-swe 前端 AgentStatus。"""

    if status in {"running", "pushed", "pr_created", "cancelling"}:
        return "running"
    if status == "queued":
        return "queued"
    if status in {"completed", "awaiting_approval"}:
        return "awaiting_approval" if status == "awaiting_approval" else "finished"
    if status == "failed":
        return "error"
    if status == "cancelled":
        return "cancelled"
    if status == "interrupted":
        return "interrupted"
    return "idle"


def _repo_full_name(thread: dict[str, Any]) -> str:
    """把 Store 中拆开的 owner/repo 还原成前端显示的仓库全名。"""

    owner = thread.get("repo_owner") or ""
    repo = thread.get("repo_name") or ""
    if owner and repo:
        return f"{owner}/{repo}"
    return thread.get("repo_url") or ""


def _repo_provider(thread: dict[str, Any]) -> str:
    try:
        return parse_repo_url(str(thread.get("repo_url") or "")).provider
    except ValueError:
        return DEFAULT_REPO_PROVIDER


def _repository_identity(repo_url: str) -> tuple[str, str, str]:
    repo = parse_repo_url(repo_url)
    return repo.provider, repo.owner.casefold(), repo.repo.casefold()


def _pr_payload(thread: dict[str, Any]) -> dict[str, Any] | None:
    """把 Store 中的 PR 字段转换成前端期望的 PR 对象。

    当前项目只支持 Gitee，PR URL 通常形如：
    `https://gitee.com/owner/repo/pulls/123`。
    """

    pr_url = thread.get("pr_url")
    if not pr_url:
        return None
    number = 0
    try:
        number = int(str(pr_url).rstrip("/").split("/")[-1])
    except ValueError:
        number = 0
    return {
        "number": number,
        "title": thread.get("title") or "CODING Pull Request",
        "state": "open",
        "headRef": thread.get("branch_name") or "",
        "baseRef": "main" if _repo_provider(thread) == "github" else "master",
        "url": pr_url,
    }


def _user_visible_text(text: str) -> str:
    """返回用户可见文本。

    前端历史正文只来自 checkpoint 中的 user/assistant 消息。
    这里不再判断中文、英文，也不再过滤 DeepAgents 产生的英文摘要或过程文本。
    Store、run_events 是否参与正文展示，由 `_message_payload` 的数据来源控制，
    不再靠文本内容做二次过滤。
    """

    return text.strip()


def _user_visible_stream_text(text: str) -> str:
    """返回流式正文。

    POST SSE 中的 assistant token/chunk 会直接给前端展示。
    空白文本仍然由调用方丢弃，避免产生空消息。
    """

    return text


def _message_payload(thread: dict[str, Any]) -> list[dict[str, Any]]:
    """生成前端可展示的消息列表。

    PostgreSQL 模式优先从 thread_messages 投影读取，避免历史页面触发可能持续等待
    的 checkpoint delta 查询。SQLite 新消息也使用同一投影；没有投影的旧 SQLite
    会话才回退到 checkpoint。当前轮实时过程仍由 POST SSE 直接推送增量事件。
    """

    created_at = thread.get("created_at") or datetime.now().isoformat()
    messages: list[dict[str, Any]] = []
    thread_id = str(thread["thread_id"])

    projected = get_store().list_thread_messages(thread_id)
    for index, message in enumerate(projected):
        content = _user_visible_text(str(message.get("content") or ""))
        if not content:
            continue
        author = message.get("author") if message.get("author") in {"user", "agent", "system", "tool"} else "agent"
        message_timestamp = message.get("created_at") or created_at
        if isinstance(message_timestamp, datetime):
            message_timestamp = message_timestamp.isoformat()
        metadata = message.get("metadata") or {}
        chunks = [{"kind": "text", "text": content}]
        proposal = metadata.get("proposal") if isinstance(metadata, dict) else None
        plan_id = (proposal or {}).get("plan_id") if isinstance(proposal, dict) else None
        if plan_id:
            plan_record = get_store().get_thread_plan(str(plan_id))
            if plan_record:
                proposal = {
                    **proposal,
                    "status": plan_record.get("status") or proposal.get("status"),
                    "version": plan_record.get("version") or proposal.get("version"),
                }
            chunks = [{"kind": "proposal", **proposal}]
        intervention_id = metadata.get("intervention_id") if isinstance(metadata, dict) else None
        if intervention_id:
            intervention = get_store().get_thread_intervention(str(intervention_id))
            if intervention:
                chunks = [{
                    "kind": "intervention",
                    "intervention_id": intervention_id,
                    "status": intervention.get("status"),
                    **(intervention.get("payload") or {}),
                }]
        messages.append(
            {
                "id": message.get("message_id") or f"{thread_id}-projected-{index}",
                "author": author,
                "timestamp": message_timestamp,
                "chunks": chunks,
            }
        )
    # 旧 SQLite 走原有兼容回退；PostgreSQL 走 checkpoint_history 的有界 SQL reader，
    # 不调用会卡住的通用 delta history API。
    if not messages:
        for index, message in enumerate(visible_checkpoint_messages(thread_id)):
            content = str(message.get("content") or "").strip()
            if not content:
                continue
            content = _user_visible_text(content)
            if not content:
                continue
            author = message.get("author") if message.get("author") in {"user", "agent", "system", "tool"} else "agent"
            messages.append(
                {
                    "id": message.get("message_id") or f"{thread_id}-history-fallback-{index}",
                    "author": author,
                    "timestamp": message.get("created_at") or created_at,
                    "chunks": [{"kind": "text", "text": content}],
                }
            )

    store = get_store()
    list_runs = getattr(store, "list_runs", None)
    if list_runs:
        runs = list_runs(thread_id, limit=50)
        for run in reversed(runs):
            started_at = run.get("started_at") or created_at
            if isinstance(started_at, datetime):
                started_at = started_at.isoformat()
            finished_at = run.get("finished_at")
            if isinstance(finished_at, datetime):
                finished_at = finished_at.isoformat()
            messages.append({
                "id": f"{thread_id}-run-activity-{run['run_id']}",
                "author": "agent",
                "timestamp": started_at,
                "chunks": [{
                    "kind": "run_activity",
                    "activity": {
                        "run_id": run["run_id"],
                        "status": run.get("status") or "unknown",
                        "started_at": started_at,
                        "finished_at": finished_at,
                        "error": run.get("error"),
                    },
                }],
            })

    messages.sort(key=lambda message: (
        _timestamp_ms(message.get("timestamp")),
        1 if any(chunk.get("kind") == "run_activity" for chunk in message.get("chunks", []))
        else 0 if message.get("author") == "user" else 2,
        message["id"],
    ))
    return messages


def _thread_payload(thread: dict[str, Any]) -> dict[str, Any]:
    """组装前端完整 Thread DTO。

    这个 payload 会用于：
    - 左侧会话列表；
    - 打开某个历史会话；
    - 页面刷新后的稳定历史恢复。

    聊天正文来自 thread_messages/checkpoint；每次运行的过程卡则由 runs 元数据构成，
    展开时再按 run_id 单独读取 run_events。
    """

    repo_full_name = _repo_full_name(thread)
    store = get_store()
    thread_id = str(thread["thread_id"])
    latest_plan = store.get_latest_thread_plan(thread_id)
    get_active_intervention = getattr(store, "get_latest_active_thread_intervention", None)
    intervention = get_active_intervention(thread_id) if get_active_intervention else None
    pending_intervention = None
    if intervention:
        pending_intervention = {
            "intervention_id": intervention["intervention_id"],
            "status": intervention.get("status") or "pending",
            **(intervention.get("payload") or {}),
        }
    messages = _message_payload(thread)
    if pending_intervention and not any(
        chunk.get("kind") == "intervention"
        and chunk.get("intervention_id") == pending_intervention["intervention_id"]
        for message in messages
        for chunk in message.get("chunks", [])
    ):
        messages.append({
            "id": f"{thread_id}-intervention-{pending_intervention['intervention_id']}",
            "author": "agent",
            "timestamp": _timestamp_ms(intervention.get("created_at")),
            "chunks": [{"kind": "intervention", **pending_intervention}],
        })
    return {
        "id": thread["thread_id"],
        "projectId": thread.get("project_id"),
        "chatOnly": not bool(thread.get("project_id") or thread.get("repo_url")),
        "title": thread.get("title") or "CODING Task",
        "repo": repo_full_name,
        "repoFullName": repo_full_name,
        "provider": _repo_provider(thread),
        # branch_name 为空时表示尚未记录真实工作分支；不要伪装成当前分支 master。
        "branch": thread.get("branch_name"),
        "baseBranch": "main" if _repo_provider(thread) == "github" else "master",
        "model": get_env("MAIN_MODEL", "deepseek-v4-pro"),
        "effort": None,
        "source": "dashboard",
        "status": _status_for_frontend(thread.get("latest_run_status")),
        "createdAt": _timestamp_ms(thread.get("created_at")),
        "updatedAt": _timestamp_ms(thread.get("updated_at")),
        "draftContent": (getattr(store, "get_thread_draft", lambda _thread_id: None)(thread_id) or {}).get("content", ""),
        "messages": messages,
        "pendingIntervention": pending_intervention,
        "pr": _pr_payload(thread),
        "latestPlan": latest_plan,
        "diffStats": None,
        "changedFiles": [],
    }


def _thread_meta_payload(thread: dict[str, Any]) -> dict[str, Any]:
    """返回不含 messages 的会话元信息。

    实时流只能更新状态、分支、PR 等元信息，不能把历史 messages 重新推给前端，
    否则会覆盖前端当前轮已经追加的用户输入和流式正文。
    """

    payload = _thread_payload(thread)
    payload.pop("messages", None)
    return payload


@dashboard_router.get("/me")
def dashboard_me() -> dict[str, Any]:
    """返回 Dashboard 当前用户信息。

    本地部署版没有真实登录系统，这里返回一个固定的本地用户，让前端可以复用
    open-swe/FinQA 风格的用户初始化流程。
    """

    return {
        "login": "coding",
        "email": None,
        "avatar_url": None,
        "is_admin": True,
        "slack_oauth_enabled": False,
    }


@dashboard_router.get("/options")
def dashboard_options() -> dict[str, Any]:
    """返回前端模型下拉框和默认模型配置。

    模型名称来自 `.env` 中的 `MAIN_MODEL`，通常是 `deepseek-v4-pro`。
    前端只展示这些选项，真正创建模型对象仍由 `agent.core.model` 负责。
    """

    from agent.core.model import available_agent_models

    model = get_env("MAIN_MODEL", "deepseek-v4-pro")
    models = available_agent_models()
    return {
        "default_repo": DEFAULT_REPO_URL,
        "default_provider": DEFAULT_REPO_PROVIDER,
        "providers": [
            {"id": "github", "label": "GitHub", "url_placeholder": "https://github.com/owner/repo.git"},
            {"id": "gitee", "label": "Gitee", "url_placeholder": "https://gitee.com/owner/repo.git"},
        ],
        "repo_placeholder": "https://github.com/owner/repo.git",
        "models": [{
            "id": model_id, "label": model_id,
            "efforts": ["default"], "default_effort": "default",
            "supports_images": False,
        } for model_id in models],
        "default_agent_model": model,
        "default_agent_reasoning_effort": "default",
        "default_agent_subagent_model": model,
        "default_agent_subagent_reasoning_effort": "default",
    }


@dashboard_router.get("/threads")
def dashboard_threads(limit: int = 50) -> list[dict[str, Any]]:
    """读取最近会话列表。

    Vue 左侧列表会调用这个接口。返回中包含每个 thread 的稳定历史消息，
    但这些消息仍然来自 checkpoint，而不是 Store 的过程事件。
    """

    return [_thread_payload(thread) for thread in list_tasks(limit=limit)]


@dashboard_router.get("/projects")
def dashboard_projects() -> list[dict[str, Any]]:
    """Return projects with their conversations, grouped for the workspace sidebar."""
    store = get_store()
    projects = store.list_projects()
    threads = list_tasks(limit=2000)
    by_project: dict[str, list[dict[str, Any]]] = {}
    for thread in threads:
        project_id = thread.get("project_id")
        if project_id:
            by_project.setdefault(str(project_id), []).append({
                "id": thread["thread_id"], "projectId": project_id,
                "title": thread.get("title") or "CODING Task",
                "status": _status_for_frontend(thread.get("latest_run_status")),
                "updatedAt": _timestamp_ms(thread.get("updated_at")),
                "repo": _repo_full_name(thread),
            })
    return [{
        "id": project["project_id"], "name": project["name"],
        "provider": project.get("provider"), "repo": project.get("repo_url"),
        "repoFullName": "/".join(part for part in (project.get("repo_owner"), project.get("repo_name")) if part),
        "legacy": bool(project.get("is_legacy")),
        "conversations": by_project.get(project["project_id"], []),
    } for project in projects]


@dashboard_router.post("/projects")
def dashboard_create_project(body: DashboardProjectRequest) -> dict[str, Any]:
    name = body.name.strip()
    provider = body.provider.strip().lower()
    if not name or len(name) > 80:
        raise HTTPException(status_code=422, detail="项目名称须为 1 到 80 个字符")
    if provider not in {"github", "gitee"}:
        raise HTTPException(status_code=422, detail="仅支持 GitHub 和 Gitee")
    try:
        repository = parse_repo_url(body.repo, provider=provider)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    store = get_store()
    project = store.create_project(
        project_id=str(uuid.uuid4()), name=name, provider=repository.provider,
        repo_url=repository.clone_url, repo_owner=repository.owner, repo_name=repository.repo,
    )
    return {
        "id": project["project_id"], "name": project["name"],
        "provider": project["provider"], "repo": project["repo_url"],
        "repoFullName": repository.full_name, "legacy": False, "conversations": [],
    }


@dashboard_router.patch("/projects/{project_id}")
def dashboard_rename_project(project_id: str, body: DashboardProjectRenameRequest) -> dict[str, Any]:
    name = body.name.strip()
    if not name or len(name) > 80:
        raise HTTPException(status_code=422, detail="项目名称须为 1 到 80 个字符")
    project = get_store().update_project_name(project_id, name)
    if not project:
        raise HTTPException(status_code=404, detail="project not found")
    return {"id": project["project_id"], "name": project["name"]}


@dashboard_router.post("/projects/{project_id}/threads")
def dashboard_create_project_thread(project_id: str) -> dict[str, Any]:
    thread = get_store().create_thread_for_project(thread_id=str(uuid.uuid4()), project_id=project_id)
    if not thread:
        if get_store().get_project(project_id) is None:
            raise HTTPException(status_code=404, detail="project not found")
        raise HTTPException(status_code=409, detail="该历史项目没有可用仓库，不能创建新会话")
    return _thread_payload(thread)


@dashboard_router.post("/threads")
def dashboard_create_chat_thread() -> dict[str, Any]:
    """Create a standalone chat thread that is not bound to a repository project."""
    thread = get_store().create_chat_thread(thread_id=str(uuid.uuid4()))
    return _thread_payload(thread)


@dashboard_router.delete("/projects/{project_id}", status_code=204)
def dashboard_delete_project(project_id: str) -> None:
    """Delete a project and all of its conversation records after UI confirmation."""
    store = get_store()
    project = store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    thread_ids = store.list_project_thread_ids(project_id)
    active = {
        str(run.get("thread_id"))
        for run in store.list_active_runs()
        if str(run.get("thread_id")) in set(thread_ids)
    }
    if active:
        raise HTTPException(status_code=409, detail="项目中仍有运行中的任务，请先停止或等待任务完成后再删除。")
    for thread_id in thread_ids:
        if not delete_task(thread_id):
            raise HTTPException(status_code=409, detail="部分会话已变化，请刷新后重试删除项目。")
    if not store.delete_project(project_id):
        raise HTTPException(status_code=409, detail="项目仍有关联会话，请刷新后重试。")
    return None


@dashboard_router.put("/threads/{thread_id}/draft")
def dashboard_save_thread_draft(thread_id: str, body: DashboardThreadDraftRequest) -> dict[str, Any]:
    if len(body.content) > 100_000:
        raise HTTPException(status_code=413, detail="草稿不能超过 100 KB")
    draft = get_store().save_thread_draft(thread_id=thread_id, content=body.content)
    if draft is None:
        raise HTTPException(status_code=404, detail="thread not found")
    return {"content": draft["content"], "revision": draft["revision"], "updatedAt": draft["updated_at"]}


@dashboard_router.patch("/threads/{thread_id}")
def dashboard_update_thread_title(
    thread_id: str,
    body: DashboardThreadTitleRequest,
) -> dict[str, Any]:
    """更新会话标题，并返回最新的会话元信息。"""

    task = get_task(thread_id)
    if task is None:
        raise HTTPException(status_code=404, detail="thread not found")

    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="会话标题不能为空")
    if len(title) > 80:
        raise HTTPException(status_code=422, detail="会话标题不能超过 80 个字符")

    get_store().update_thread_title(thread_id, title)
    updated = get_task(thread_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="thread not found")
    return _thread_payload(updated)


@dashboard_router.get("/threads/{thread_id}")
def dashboard_thread_detail(thread_id: str) -> dict[str, Any]:
    """读取单个会话详情。

    用户点击左侧某个历史会话时调用。不存在时返回 404。
    """

    task = get_task(thread_id)
    if task is None:
        raise HTTPException(status_code=404, detail="thread not found")
    return _thread_payload(task)


@dashboard_router.get("/threads/{thread_id}/runs/{run_id}/events")
def dashboard_run_activity_events(thread_id: str, run_id: str) -> dict[str, Any]:
    """按 run_id 读取可展示的运行过程；拒绝读取其它会话的运行记录。"""

    if get_task(thread_id) is None:
        raise HTTPException(status_code=404, detail="thread not found")
    store = get_store()
    list_runs = getattr(store, "list_runs", None)
    list_events = getattr(store, "list_run_events_for_run", None)
    if not list_runs:
        return {"run_id": run_id, "events": []}
    run = next((item for item in list_runs(thread_id, limit=100) if item.get("run_id") == run_id), None)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    if not list_events:
        return {"run_id": run_id, "events": []}

    final_texts = {
        str(message.get("content") or "").strip()
        for message in store.list_thread_messages(thread_id)
        if message.get("run_id") == run_id and message.get("author") == "agent"
    }
    visible_events: list[dict[str, Any]] = []
    for event in list_events(thread_id, run_id):
        detail: dict[str, Any] = {}
        raw_detail = event.get("detail")
        if raw_detail:
            try:
                decoded = json.loads(raw_detail) if isinstance(raw_detail, str) else raw_detail
                if isinstance(decoded, dict):
                    detail = decoded
            except (TypeError, ValueError):
                detail = {}
        safe_detail: dict[str, Any] = {}
        if event.get("kind") == "todo" and isinstance(detail.get("todos"), list):
            safe_detail["todos"] = detail["todos"]
        elif event.get("kind") == "todo_guard":
            for field in ("total", "completed", "in_progress", "pending", "complete"):
                if isinstance(detail.get(field), (int, bool)):
                    safe_detail[field] = detail[field]
        elif event.get("title") == "正在生成内容" and isinstance(detail.get("text"), str):
            progress_text = detail["text"].strip()
            if progress_text and progress_text not in final_texts:
                safe_detail["text"] = progress_text[:12000]
        elif (
            event.get("title") in {"任务失败", "技术方案生成失败"}
            and event.get("status") == "error"
        ):
            # Runtime 仅在这里写入经过 mask_token 脱敏的最终异常；普通工具错误
            # 可能包含仓库内容或凭据，继续按默认策略隐藏。
            failure_text = raw_detail.strip() if isinstance(raw_detail, str) else ""
            if not failure_text and isinstance(detail.get("text"), str):
                failure_text = detail["text"].strip()
            if failure_text:
                safe_detail["text"] = failure_text[:4000]
        visible_events.append({
            "id": event.get("id"),
            "kind": event.get("kind"),
            "title": event.get("title"),
            "status": event.get("status"),
            "created_at": event.get("created_at").isoformat()
            if isinstance(event.get("created_at"), datetime) else event.get("created_at"),
            "detail": safe_detail,
        })
    return {"run_id": run_id, "events": visible_events}


def _post_streaming_response(
    *, thread_id: str, repo_url: str | None, content: str,
    model_id: str | None = None,
    interaction_action: str | None = None, plan_id: str | None = None,
    intervention_id: str | None = None,
) -> StreamingResponse:
    """Persist a run first, then stream its durable event log to this client."""
    store = get_store()
    if any(run.get("thread_id") == thread_id for run in store.list_active_runs()):
        raise HTTPException(status_code=409, detail="此会话已有运行中的任务，请切换会话或等待完成。")
    if repo_url is None:
        task = store.get_thread(thread_id)
        if task is None or task.get("project_id") or task.get("repo_url"):
            raise HTTPException(status_code=409, detail="无仓库聊天会话状态已变化，请重新打开会话。")
        if task.get("title") in {None, "新聊天", "新会话"}:
            store.update_thread_title(thread_id, content.strip().replace("\n", " ")[:80] or "新聊天")
        store.add_thread_message(
            message_id=f"{thread_id}-user-{uuid.uuid4()}", thread_id=thread_id,
            author="user", content=content, metadata={"source": "dashboard_chat"},
        )
    else:
        initialize_task_record(repo_url=repo_url, prompt=content, thread_id=thread_id)
        task = get_task(thread_id)
    if task is None:
        raise HTTPException(status_code=500, detail="task was not persisted")
    run_id = str(uuid.uuid4())
    payload = {
        "repo_url": repo_url,
        "chat_only": repo_url is None,
        "content": content,
        "model_id": model_id,
        "interaction_action": interaction_action,
        "plan_id": plan_id,
        "intervention_id": intervention_id,
    }
    try:
        store.enqueue_run(run_id=run_id, thread_id=thread_id, payload=payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="此会话已有运行中的任务，请切换会话或等待完成。") from exc
    store.update_thread_status(thread_id, "queued")
    initial = _thread_meta_payload(get_task(thread_id) or task)
    initial.update({"thread_id": thread_id, "run_id": run_id, "status": "queued"})
    store.append_run_stream_event(thread_id=thread_id, run_id=run_id, event="thread_snapshot", payload=initial)
    store.append_run_stream_event(
        thread_id=thread_id,
        run_id=run_id,
        event="user_message",
        payload={
            "thread_id": thread_id,
            "run_id": run_id,
            "message_id": f"{thread_id}-user-{run_id}",
            "author": "user",
            "content": content,
        },
    )
    startup_message_id = f"{thread_id}-assistant-startup-{run_id}"
    store.append_run_stream_event(
        thread_id=thread_id, run_id=run_id, event="message_start",
        payload={"thread_id": thread_id, "run_id": run_id, "message_id": startup_message_id, "author": "agent"},
    )
    store.append_run_stream_event(
        thread_id=thread_id, run_id=run_id, event="text_delta",
        payload={"thread_id": thread_id, "run_id": run_id, "message_id": startup_message_id,
                 "content": "任务已加入队列，等待执行…\n\n", "mode": "append"},
    )

    async def event_iter(after_seq: int = 0):
        cursor = max(0, after_seq)
        heartbeat_at = asyncio.get_running_loop().time() + 15
        while True:
            rows = store.list_run_stream_events(thread_id=thread_id, run_id=run_id, after_seq=cursor)
            for row in rows:
                cursor = int(row["seq"])
                yield _sse_part(row["event"], row["payload"], event_id=cursor)
                if row["event"] == "done":
                    return
            run = store.get_run(thread_id, run_id) or {}
            if run.get("status") in {"completed", "failed", "cancelled", "interrupted"} and not rows:
                yield _sse_part("done", {"run_id": run_id, "thread_id": thread_id, "status": run["status"]})
                return
            await asyncio.sleep(0.25)
            if asyncio.get_running_loop().time() >= heartbeat_at:
                yield ": keep-alive\n\n"
                heartbeat_at = asyncio.get_running_loop().time() + 15

    return StreamingResponse(
        event_iter(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@dashboard_router.get("/threads/{thread_id}/runs/{run_id}/stream")
async def dashboard_resume_run_stream(
    thread_id: str, run_id: str, after: int = Query(default=0, ge=0),
) -> StreamingResponse:
    store = get_store()
    if not store.get_run(thread_id, run_id):
        raise HTTPException(status_code=404, detail="运行记录不存在")

    async def event_iter():
        cursor = after
        heartbeat_at = asyncio.get_running_loop().time() + 15
        while True:
            rows = store.list_run_stream_events(thread_id=thread_id, run_id=run_id, after_seq=cursor)
            for row in rows:
                cursor = int(row["seq"])
                yield _sse_part(row["event"], row["payload"], event_id=cursor)
                if row["event"] == "done":
                    return
            run = store.get_run(thread_id, run_id) or {}
            if run.get("status") in {"completed", "failed", "cancelled", "interrupted"} and not rows:
                yield _sse_part("done", {"status": run["status"]})
                return
            await asyncio.sleep(0.25)
            if asyncio.get_running_loop().time() >= heartbeat_at:
                yield ": keep-alive\n\n"
                heartbeat_at = asyncio.get_running_loop().time() + 15

    return StreamingResponse(
        event_iter(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@dashboard_router.post("/threads/{thread_id}/runs/{run_id}/cancel")
async def dashboard_cancel_run(thread_id: str, run_id: str) -> dict[str, Any]:
    store = get_store()
    status = store.request_run_cancel(thread_id=thread_id, run_id=run_id)
    if status is None:
        raise HTTPException(status_code=409, detail="运行已结束或不存在")
    if status == "cancelled":
        store.append_run_stream_event(
            thread_id=thread_id, run_id=run_id, event="error",
            payload={"thread_id": thread_id, "run_id": run_id, "message": "任务已取消"},
        )
        store.append_run_stream_event(
            thread_id=thread_id, run_id=run_id, event="done", payload={"status": "cancelled"},
        )
        store.update_thread_status(thread_id, "cancelled")
    return {"thread_id": thread_id, "run_id": run_id, "status": status}


@dashboard_router.get("/runs/active")
async def dashboard_active_runs() -> list[dict[str, Any]]:
    return get_store().list_active_runs()


@dashboard_router.post("/threads/stream-message")
async def dashboard_stream_new_message(body: DashboardThreadMessageRequest) -> StreamingResponse:
    """创建新会话并通过 POST SSE 返回实时运行过程。"""

    if body.interaction_action is not None:
        raise HTTPException(status_code=422, detail="方案与人工介入操作必须来自已有会话。")
    model_id = _normalize_dashboard_model_id(body.model_id)
    repo_url = _normalize_dashboard_repo_url(body.repo, provider=body.provider) if body.repo else None
    thread_id = str(uuid.uuid4())
    if repo_url is None:
        get_store().create_chat_thread(thread_id=thread_id)
    return _post_streaming_response(
        thread_id=thread_id, repo_url=repo_url, content=body.content,
        model_id=model_id,
        interaction_action=body.interaction_action, plan_id=body.plan_id,
        intervention_id=body.intervention_id,
    )


@dashboard_router.post("/threads/{thread_id}/stream-message")
async def dashboard_stream_existing_message(
    thread_id: str,
    body: DashboardThreadMessageRequest,
) -> StreamingResponse:
    """在已有会话中追加一轮用户输入，并通过 POST SSE 返回实时运行过程。

    如果请求体没有带 repo，则复用当前 thread 在 Store 中保存的 repo_url。
    """

    task = get_task(thread_id)
    chat_only = bool(task and not task.get("project_id") and not task.get("repo_url"))
    model_id = _normalize_dashboard_model_id(body.model_id)
    repo_url = None if chat_only else _normalize_dashboard_repo_url(
        body.repo, provider=body.provider, fallback=(task or {}).get("repo_url"),
    )
    existing_repo = (task or {}).get("repo_url")
    if existing_repo and (repo_url is None or _repository_identity(str(existing_repo)) != _repository_identity(repo_url)):
        raise HTTPException(
            status_code=409,
            detail="同一会话不能切换 GitHub/Gitee 仓库；请新建会话后选择目标仓库。",
        )
    if existing_repo and repo_url:
        # Keep the persisted canonical casing/URL stable for case-insensitive providers.
        repo_url = parse_repo_url(str(existing_repo)).clone_url
    store = get_store()
    get_active_intervention = getattr(store, "get_latest_active_thread_intervention", None)
    active_intervention = get_active_intervention(thread_id) if get_active_intervention else None
    if active_intervention and (
        body.interaction_action != "resume_intervention"
        or body.intervention_id != active_intervention.get("intervention_id")
    ):
        raise HTTPException(
            status_code=409,
            detail="此会话正等待人工介入答复。请在会话中的‘需要你确认后继续’卡片提交答复，不能发送普通消息启动新一轮任务。",
        )
    if body.interaction_action in {"approve_plan", "reject_plan", "revise_plan"}:
        plan = store.get_thread_plan(body.plan_id or "")
        if not plan or plan.get("thread_id") != thread_id or plan.get("status") != "pending":
            raise HTTPException(status_code=409, detail="方案已处理或已失效，请刷新会话后重试。")
        if body.interaction_action == "revise_plan" and not body.content.strip():
            raise HTTPException(status_code=422, detail="请先描述需要调整的内容。")
    elif body.interaction_action == "resume_intervention":
        intervention = store.get_thread_intervention(body.intervention_id or "")
        if not intervention or intervention.get("thread_id") != thread_id or intervention.get("status") != "pending":
            raise HTTPException(status_code=409, detail="人工介入已处理或已失效，请刷新会话后重试。")
        if not body.content.strip():
            raise HTTPException(status_code=422, detail="请填写人工介入答复。")
    elif body.interaction_action is not None:
        raise HTTPException(status_code=422, detail="不支持的交互操作。")
    return _post_streaming_response(
        thread_id=thread_id, repo_url=repo_url, content=body.content,
        model_id=model_id,
        interaction_action=body.interaction_action, plan_id=body.plan_id,
        intervention_id=body.intervention_id,
    )


@dashboard_router.delete("/threads/{thread_id}", status_code=204)
def dashboard_delete_thread(thread_id: str) -> None:
    """删除 Dashboard 会话。

    删除动作由 runtime.delete_task 完成，它会清理业务 Store 和 LangGraph checkpoint。
    正常历史展示不从 Store 读正文，但删除时必须同时清理两边，避免残留状态。
    """

    deleted = delete_task(thread_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="thread not found")
    return None
