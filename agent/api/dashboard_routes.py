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
import threading
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent.core.checkpoint_history import visible_checkpoint_messages
from agent.core.graph import get_store
from agent.core.runtime import delete_task, get_task, initialize_task_record, list_tasks, run_agent_task
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


class DashboardThreadTitleRequest(BaseModel):
    """前端编辑 Dashboard 会话标题时的请求体。"""

    title: str


def _sse_part(event: str, data: dict[str, Any]) -> str:
    """输出标准命名 SSE 事件。

    新的 POST SSE 主链路采用 `event: xxx` + `data: json`，与
    `finqa_deepagent_observability` 项目保持一致。前端解析器已经兼容命名事件，
    不再需要把 event 包在 data JSON 里面。
    """

    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


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

    if status in {"running", "pushed", "pr_created"}:
        return "running"
    if status in {"completed", "awaiting_approval"}:
        return "finished"
    if status == "failed":
        return "error"
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
        messages.append(
            {
                "id": message.get("message_id") or f"{thread_id}-projected-{index}",
                "author": author,
                "timestamp": message_timestamp,
                "chunks": [{"kind": "text", "text": content}],
            }
        )
    if messages:
        return messages

    # 旧 SQLite 走原有兼容回退；PostgreSQL 走 checkpoint_history 的有界 SQL reader，
    # 不调用会卡住的通用 delta history API。
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
    return messages


def _thread_payload(thread: dict[str, Any]) -> dict[str, Any]:
    """组装前端完整 Thread DTO。

    这个 payload 会用于：
    - 左侧会话列表；
    - 打开某个历史会话；
    - 页面刷新后的稳定历史恢复。

    其中 `messages` 只来自 `_message_payload()`，也就是 checkpoint 历史；
    不会从 Store 的 run_events 或其它兜底表里拼接聊天正文。
    """

    repo_full_name = _repo_full_name(thread)
    return {
        "id": thread["thread_id"],
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
        "messages": _message_payload(thread),
        "pr": _pr_payload(thread),
        "latestPlan": None,
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

    model = get_env("MAIN_MODEL", "deepseek-v4-pro")
    return {
        "default_repo": DEFAULT_REPO_URL,
        "default_provider": DEFAULT_REPO_PROVIDER,
        "providers": [
            {"id": "github", "label": "GitHub", "url_placeholder": "https://github.com/owner/repo.git"},
            {"id": "gitee", "label": "Gitee", "url_placeholder": "https://gitee.com/owner/repo.git"},
        ],
        "repo_placeholder": "https://github.com/owner/repo.git",
        "models": [
            {
                "id": model,
                "label": model,
                "efforts": ["default"],
                "default_effort": "default",
                "supports_images": False,
            }
        ],
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


def _post_streaming_response(*, thread_id: str, repo_url: str, content: str) -> StreamingResponse:
    """直接执行本轮 Agent，并把过程事件作为同一个 POST SSE 响应返回。

    旧版链路是“POST 创建后台任务 + GET 轮询 run_events”。这种两段式链路在多轮
    对话里容易出现时序竞争：用户输入由前端本地追加，任务计划来自 run_events，
    历史正文来自 checkpoint，三者不是同一个顺序源。

    新链路参考 `finqa_deepagent_observability`：请求体中携带本轮用户输入，后端
    在同一条 StreamingResponse 中先发送 user_message，再直接运行 Agent。Store
    仍会记录任务摘要、PR、run_events 和仓库记忆，但前端实时正文不再依赖 Store
    轮询。
    """

    # 先创建或更新 thread 业务记录。
    # 注意：这里不负责把用户消息写入 Store；用户消息展示由 SSE 的 user_message 事件负责，
    # 稳定历史恢复由 LangGraph checkpoint 负责。
    initialize_task_record(repo_url=repo_url, prompt=content, thread_id=thread_id)

    # 立即读取刚刚创建或更新后的 thread 摘要，后面要用它生成首个 thread_snapshot 事件。
    initial_task = get_task(thread_id)

    # 如果业务 Store 没有读到 thread，说明初始化失败；此时不能继续建立 SSE，否则前端会拿到残缺状态。
    if initial_task is None:
        # 用 HTTP 500 明确告诉前端：不是用户输入问题，而是后端持久化异常。
        raise HTTPException(status_code=500, detail="task was not persisted")

    async def event_iter():
        """StreamingResponse 的异步事件生成器。

        Agent 本身在工作线程中同步运行；SSE 响应在 asyncio 事件循环中异步发送。
        二者通过 `asyncio.Queue` 桥接，保证后端边运行边把事件推给前端。
        """

        # 获取当前 FastAPI 请求所在的 asyncio 事件循环；worker 线程投递事件时需要回到这个 loop。
        loop = asyncio.get_running_loop()

        # 创建本轮 SSE 的内存队列。worker 线程负责生产事件，event_iter 负责消费并 yield 给浏览器。
        queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()

        def enqueue(event: str, data: dict[str, Any]) -> None:
            """线程安全地把 worker 线程中的事件投递回 asyncio 队列。"""

            # 复制一份事件数据，避免调用方后续修改原 dict 时影响已经进入队列的 payload。
            payload = dict(data)

            # 所有发给前端的事件都补齐 thread_id，前端可以据此判断事件属于哪个会话。
            payload.setdefault("thread_id", thread_id)

            # worker 运行在普通线程，不能直接 await queue.put；必须通过事件循环线程安全投递。
            loop.call_soon_threadsafe(queue.put_nowait, (event, payload))

        def event_sink(event: str, data: dict[str, Any]) -> None:
            """runtime/streaming_runtime 使用的统一实时事件出口。

            `text_delta` 会先过滤空白，避免前端创建没有内容的 assistant 消息；
            其它事件会原样进入 SSE 队列。
            """

            # 复制事件数据，避免 streaming_runtime 复用同一个 dict 时产生副作用。
            payload = dict(data)

            # 文本增量是用户最敏感的展示内容，需要先做空白过滤和可见文本规整。
            if event == "text_delta":
                # 当前实现不再过滤英文/中文，只做统一字符串化，保留模型真实 assistant 输出。
                payload["content"] = _user_visible_stream_text(str(payload.get("content") or ""))

                # 空字符串或纯空白不推给前端，避免创建空 AIMessage。
                if not payload["content"].strip():
                    return

            # 其它事件，例如 message_start、todo_delta、thread_done，直接进入 SSE 队列。
            enqueue(event, payload)

        def worker() -> None:
            """在后台线程中运行一次 Agent 任务。

            不能直接在 event_iter 中同步调用 `run_agent_task`，否则 FastAPI 无法边运行边
            yield SSE 数据。worker 结束后发送 `thread_done` 和 `done`，通知前端收尾。
            """

            # worker 线程内部必须捕获异常，否则线程异常只会写到后端日志，前端收不到失败事件。
            try:
                # 真正运行 Agent 的入口。runtime 会做任务分类、方案确认、Agent 构建和事件流消费。
                run_agent_task(
                    # 本轮任务绑定的 Gitee 仓库地址，已经在外层 API 边界做过规范化。
                    repo_url=repo_url,
                    # 用户本轮真实输入，runtime 会根据任务类型决定是否包装内部执行上下文。
                    prompt=content,
                    # 当前会话 id，用于绑定 Store、checkpoint、SSE 和 Agent config。
                    thread_id=thread_id,
                    # 把 runtime/streaming_runtime 产生的实时事件送回本函数的 SSE 队列。
                    event_sink=event_sink,
                )

                # Agent 正常结束后，重新读取最新 thread 摘要，里面可能已经包含分支、PR、状态等新信息。
                latest = get_task(thread_id) or initial_task

                # 告诉前端本轮任务最终元信息；注意该 payload 不带 messages，不覆盖前端已有正文。
                enqueue("thread_done", _thread_meta_payload(latest))

                # 发送 done 事件，通知 event_iter 结束 while 循环，也通知前端结束 streaming 状态。
                enqueue("done", {})
            except Exception as exc:
                # 失败时也尽量读取最新 thread，保证前端能看到 failed 状态或错误后的元信息。
                latest = get_task(thread_id) or initial_task

                # 把异常转成 SSE error 事件。这里不做复杂格式化，详细堆栈仍然看后端日志。
                enqueue("error", {"message": str(exc), "detail": str(exc)})

                # 即使失败，也推送最终 thread 元信息，避免前端状态停留在 running。
                enqueue("thread_done", _thread_meta_payload(latest))

                # 失败路径同样必须发送 done，否则浏览器会一直等待 SSE 结束。
                enqueue("done", {})

        # 第一个事件只发送 thread 元信息，不发送 messages。
        # 前端当前轮用户输入和 assistant 流式正文必须由后续事件追加，不能被 snapshot 覆盖。
        # 这一步对应“先告诉前端当前会话是谁、状态是什么、仓库是什么”。
        yield _sse_part("thread_snapshot", _thread_meta_payload(initial_task))

        # 先把用户真实输入立即推给前端。这样即使 Agent 初始化较慢，页面也能立刻看到本轮输入。
        # 前端会用这个正式 user_message 稳定或追加本轮用户气泡。
        yield _sse_part(
            "user_message",
            {
                # 明确事件归属的会话 id。
                "thread_id": thread_id,
                # 为本轮用户消息生成稳定 id，避免刷新或后续事件合并时没有主键。
                "message_id": f"{thread_id}-user-{uuid.uuid4()}",
                # author=user 表示前端应按用户消息样式渲染。
                "author": "user",
                # content 必须是用户真实输入，不能替换成 runtime 内部包装后的 prompt。
                "content": content,
            },
        )

        # 启动占位 assistant 消息，用于给用户一个明确的“任务已开始”反馈。
        # 后续真正的模型 token 会通过 streaming_runtime.py 继续创建或更新 assistant 消息。
        # 这个启动消息可以降低 Agent 初始化阶段的“页面无响应”感。
        startup_message_id = f"{thread_id}-assistant-startup-{uuid.uuid4()}"

        # 先告诉前端创建一条 agent 消息容器。
        yield _sse_part(
            "message_start",
            {
                # message_start 也携带 thread_id，方便前端在多会话状态下做归属判断。
                "thread_id": thread_id,
                # 后续启动提示 text_delta 会写入这条 message。
                "message_id": startup_message_id,
                # author=agent 表示这是 AI/assistant 侧消息。
                "author": "agent",
            },
        )

        # 再给刚创建的启动消息写入一段简短提示文本。
        yield _sse_part(
            "text_delta",
            {
                # 当前会话 id。
                "thread_id": thread_id,
                # 对应上面的启动 assistant message。
                "message_id": startup_message_id,
                # 用户可见启动提示，说明后端已经收到任务并正在准备运行上下文。
                "content": "正在理解需求并准备仓库上下文...\n\n",
                # append 表示前端把这段文本追加到当前 message。
                "mode": "append",
            },
        )

        # 创建后台线程执行 Agent。线程名带 thread_id，方便从日志或调试工具定位。
        thread = threading.Thread(target=worker, name=f"coding-stream-{thread_id}", daemon=True)

        # 启动 worker 后，Agent 才真正开始运行；event_iter 继续留在 asyncio loop 里发送 SSE。
        thread.start()

        # 持续消费 worker/event_sink 投递到 queue 中的事件。
        while True:
            # 持续从队列取事件并写入 SSE 响应。收到 done 后结束本次 HTTP 连接。
            event, data = await queue.get() # 阻塞等待事件。

            # 把内部事件名和 payload 转成标准 SSE 文本块。
            yield _sse_part(event, data)

            # done 是本轮流式响应的终止事件，收到后退出生成器。
            if event == "done":
                break

    # 返回 FastAPI StreamingResponse，让浏览器可以边接收边渲染本轮 Agent 输出。
    return StreamingResponse(
        # event_iter 是异步生成器，每次 yield 都会向 HTTP 响应体写入一段 SSE。
        event_iter(),
        # SSE 必须使用 text/event-stream，前端才会按事件流处理。
        media_type="text/event-stream",
        # 这些 header 用来降低代理和浏览器缓冲对实时输出的影响。
        headers={
            # 禁止缓存，并提示代理不要对响应做转换。
            "Cache-Control": "no-cache, no-transform",
            # 保持长连接，Agent 未结束前不要主动关闭。
            "Connection": "keep-alive",
            # Nginx 识别该 header 后会关闭响应缓冲，让 SSE 更实时。
            "X-Accel-Buffering": "no",
        },
    )


@dashboard_router.post("/threads/stream-message")
async def dashboard_stream_new_message(body: DashboardThreadMessageRequest) -> StreamingResponse:
    """创建新会话并通过 POST SSE 返回实时运行过程。"""

    repo_url = _normalize_dashboard_repo_url(body.repo, provider=body.provider)
    thread_id = str(uuid.uuid4())
    return _post_streaming_response(thread_id=thread_id, repo_url=repo_url, content=body.content)


@dashboard_router.post("/threads/{thread_id}/stream-message")
async def dashboard_stream_existing_message(
    thread_id: str,
    body: DashboardThreadMessageRequest,
) -> StreamingResponse:
    """在已有会话中追加一轮用户输入，并通过 POST SSE 返回实时运行过程。

    如果请求体没有带 repo，则复用当前 thread 在 Store 中保存的 repo_url。
    """

    task = get_task(thread_id)
    repo_url = _normalize_dashboard_repo_url(
        body.repo,
        provider=body.provider,
        fallback=(task or {}).get("repo_url"),
    )
    return _post_streaming_response(thread_id=thread_id, repo_url=repo_url, content=body.content)


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
