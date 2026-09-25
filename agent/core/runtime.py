from __future__ import annotations

"""Agent 运行时编排层。

这个文件是 FastAPI 版本 CODING 的任务调度中心，主要负责把一次用户输入
转换成一次可追踪、可恢复、可展示的 Agent 运行。它不直接实现模型推理，也不直接
解析 DeepAgents 的底层事件；它的职责边界是：

1. 判断用户任务应该走哪条运行路径，例如同步仓库、查看工作区、生成方案或实施代码。
2. 维护 thread/run 业务状态，让前端能看到任务是否 running、completed 或 failed。
3. 按任务类型构造 DeepAgent 运行配置，并把真实执行交给 agent.server.get_agent。
4. 通过 streaming_runtime.py 消费 DeepAgents V3 event stream，把运行过程展示给前端。
5. 在任务结束后更新仓库级长期记忆，并在删除会话时同步清理 Store 与 checkpoint。

开发调试时可以把 runtime.py 理解成“产品流程控制层”：它保证用户没有确认方案前不会
进入 coding，也保证 Store 只保存业务数据，真实对话历史以 LangGraph checkpoint 为准。
"""

import logging
import json
import uuid
from collections.abc import Callable
from typing import Any

from agent.backends.local_shell import LocalShellBackend
from agent.backends.workspace import Workspace
from agent.core.events import record_event
from agent.core.graph import get_checkpointer, get_langgraph_store, get_store
from agent.core.checkpoint_history import visible_checkpoint_messages
from agent.core.repo_memory import ensure_repo_memory_initialized, repo_project_dir
from agent.core.repository_workspace import prepare_repository_workspace, task_branch_name
from agent.core.repo_memory_update import RepoMemoryUpdate, update_repo_memory_from_text
from agent.core.settings import PERSISTENCE_BACKEND, WORKSPACE_ROOT
from agent.core.streaming_runtime import run_agent_with_event_stream
from agent.core.todo_completion import summarize_latest_todos
from agent.core.task_intent import classify_task_kind, is_pull_only_task, is_workspace_listing_task
from agent.core.worker import WorkerLeaseManager
from agent.env_utils import get_env
from agent.server import get_agent
from agent.tools.gitee_api import mask_token
from agent.repository import parse_repo_url

logger = logging.getLogger("agent.run.runtime")

# event_sink 是 FastAPI SSE 层传进来的回调。
# runtime 自己不关心 HTTP 细节，只把“有新内容了”通知给上层。
RuntimeEventSink = Callable[[str, dict[str, Any]], None]


def _record_todo_completion_guard(store: Any, *, thread_id: str, run_id: str) -> dict[str, int | bool] | None:
    """Persist a visible warning when a normal run ends with unfinished todos."""

    list_run_events = getattr(store, "list_run_events_for_run", None)
    if list_run_events is None:
        return None
    try:
        summary = summarize_latest_todos(list_run_events(thread_id, run_id))
    except Exception:
        # Activity telemetry must not turn an otherwise successful Agent run into a failure.
        logger.exception("读取任务清单终态失败：thread_id=%s run_id=%s", thread_id, run_id)
        return None
    if summary and not summary["complete"]:
        record_event(
            thread_id,
            "todo:completion-check",
            "运行已结束，但任务清单仍有未完成项",
            kind="todo_guard",
            status="warning",
            detail=json.dumps(summary, ensure_ascii=False),
            run_id=run_id,
        )
    return summary


def _build_agent_for_runtime(
    *,
    thread_id: str,
    task_kind: str,
    repo_url: str | None = None,
    model_id: str | None = None,
):
    """为 FastAPI runtime 构造 open-swe 风格的 Agent config。

    open-swe 由 LangGraph Server 注入 `RunnableConfig`。本地部署版不用
    langgraph dev，所以在这里显式组装 config，再交给 `agent.server.get_agent`。

    `thread_id` 用于绑定 LangGraph checkpoint、Store 业务记录和前端事件流。
    `task_kind` 会影响系统提示词、工具权限、中间件行为和运行保护阈值。
    `repo_url` 会继续向下传给 Agent 工厂，用于初始化仓库映射、仓库记忆和运行上下文。

    注意：这里每次运行都会重新取得一个 Agent runnable。真正的对话状态不靠这个
    Python 对象长期驻留，而是靠 checkpoint 和 StoreBackend 持久化。
    """

    configurable: dict[str, Any] = {
        # thread_id 是 checkpointer 的主键，也是前端当前会话的唯一标识。
        "thread_id": thread_id,
        # task_kind 会一路传到 agent.server.get_agent，用来选择系统提示词和运行规则。
        "task_kind": task_kind,
        # 这个标记用于区分“真实执行”和“框架探测图结构”。
        "__is_for_execution__": True,
    }
    if repo_url:
        # 仓库地址在 Agent 工厂中会被用于初始化本地仓库上下文和仓库记忆。
        configurable["repo_url"] = repo_url
    if model_id:
        configurable["model_id"] = model_id
    return get_agent({"configurable": configurable})


def _prepare_selected_repository(
    repo: Any,
    *,
    thread_id: str,
    create_task_branch: bool = False,
):
    """Prepare the selected repository before any Agent can inspect or edit files."""

    backend = LocalShellBackend(Workspace(WORKSPACE_ROOT), provider=repo.provider)
    return prepare_repository_workspace(
        repo,
        backend,
        thread_id=thread_id,
        create_task_branch=create_task_branch,
    )


def _ensure_repo_memory_for_repo(repo: Any, project_dir: str) -> None:
    """根据固定项目目录初始化仓库级长期记忆文件。

    记忆正文通过 DeepAgents StoreBackend 写入 LangGraph Store，不再额外建立
    SQLite 索引表。已有记忆不会被覆盖。

    仓库记忆的初始化只做“没有则创建”的动作。后续 coding、planning、review
    任务完成后的经验总结，由 repo_memory_update.py 负责结构化写回。
    """

    created = ensure_repo_memory_initialized(
        store=get_langgraph_store(),
        repo=repo,
        project_dir=project_dir.replace("\\", "/"),
    )
    if created:
        logger.info("已初始化仓库记忆：repo=%s/%s", repo.owner, repo.repo)


def _detect_current_branch(repo: Any) -> str | None:
    """读取当前仓库实际工作分支，供 Dashboard 会话元信息展示。"""

    project_dir = repo_project_dir(repo)
    backend = LocalShellBackend(Workspace(WORKSPACE_ROOT), provider=repo.provider)
    target = backend.workspace.resolve(project_dir)
    if not (target / ".git").exists():
        return None

    result = backend.run("git branch --show-current", cwd=project_dir, timeout=60)
    if result.exit_code != 0:
        logger.warning("读取当前 Git 分支失败：repo=%s/%s", repo.owner, repo.repo)
        return None

    branch = result.stdout.strip().splitlines()
    return branch[0].strip() if branch and branch[0].strip() else None


def _message_content_to_text(content: Any) -> str:
    """把 LangChain message.content 规整成可展示文本。

    LangChain/DeepAgents 的 message.content 可能是普通字符串，也可能是多模态
    content block 列表。runtime 在提取最终回答、技术方案和记忆摘要时，只需要
    文本部分，所以这里统一转换，避免每个调用点重复兼容不同消息结构。
    """

    if isinstance(content, str):
        # 最常见情况：普通文本消息。
        return content.strip()
    if isinstance(content, list):
        # 多模态或 content block 消息：只提取文本块，忽略图片、工具块等非正文内容。
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if text:
                    parts.append(str(text))
        return "\n".join(part.strip() for part in parts if part and part.strip()).strip()
    return str(content).strip() if content is not None else ""


def _extract_final_assistant_text(messages: list[dict[str, Any]]) -> str:
    """提取 DeepAgent 最后一条 assistant/ai 消息作为用户可见回答。

    任务结束后，仓库记忆更新只需要最终总结，不应该把中间工具消息、todo 状态或
    调试事件写进长期记忆。因此这里从后往前找最后一条有正文的 AI/assistant 消息。
    """

    for message in reversed(messages):
        message_type = str(message.get("type") or "").lower()
        if message_type not in {"ai", "assistant"}:
            continue
        text = _message_content_to_text(message.get("content"))
        if text:
            return text
    return ""


def _extract_best_plan_text(messages: list[dict[str, Any]]) -> str:
    """从多条 assistant 消息中提取最完整的技术方案。

    DeepAgents 有时会把“完整方案”和“是否确认实施该方案？”拆成不同 assistant
    消息。如果只取最后一条，前端就只剩确认句。方案任务应优先选择包含方案关键词
    且篇幅最长的 assistant 消息；没有命中时再退回最长 assistant 消息。

    这个函数只用于兜底校验和仓库记忆更新。前端实时展示不依赖它，前端看到的正文
    来自 streaming_runtime.py 对 DeepAgents V3 文本 chunk 的实时消费。
    """

    candidates: list[str] = []
    for message in messages:
        message_type = str(message.get("type") or "").lower()
        if message_type not in {"ai", "assistant"}:
            continue
        text = _message_content_to_text(message.get("content"))
        if text:
            candidates.append(text)
    if not candidates:
        return ""

    plan_keywords = [
        "方案",
        "技术方案",
        "修复技术方案",
        "实施步骤",
        "修复依据",
        "验证方案",
        "风险",
        "涉及模块",
        "数据结构",
        "是否确认实施该方案",
    ]
    plan_candidates = [
        text for text in candidates if any(keyword in text for keyword in plan_keywords)
    ]
    selected_pool = plan_candidates or candidates
    return max(selected_pool, key=len).strip()


def _record_thread_message(
    *,
    thread_id: str,
    author: str,
    content: str,
    run_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """把一条用户可见正文写入业务 Store 的消息投影。

    LangGraph checkpoint 仍然是 Agent 恢复所需的事实来源，但 Dashboard 历史不应
    为了展示正文去遍历 PostgreSQL checkpoint 的 delta 链。这个投影是稳定、可分页、
    不会触发 checkpoint 长查询的展示来源；Store 自己负责对重试时重复的用户正文做
    幂等去重。
    """

    normalized = content.strip()
    if not normalized:
        return
    get_store().add_thread_message(
        message_id=f"{thread_id}-{author}-{uuid.uuid4()}",
        thread_id=thread_id,
        author=author,
        content=normalized,
        run_id=run_id,
        metadata=metadata or {},
    )


def _visible_thread_messages(thread_id: str) -> list[dict[str, Any]]:
    """读取消息投影，必要时只在 SQLite 旧数据上回退到 checkpoint。

    PostgreSQL 的通用 checkpoint delta reader 在旧链路上可能持续等待，因此空投影
    只回退到 checkpoint_history 提供的有界 SQL reader，而不是调用通用 delta API。
    新运行会同步写入 user/agent 消息；旧 PostgreSQL 会话也能通过有界读取恢复。
    """

    projected = get_store().list_thread_messages(thread_id)
    if projected:
        return projected
    if PERSISTENCE_BACKEND == "postgres":
        return visible_checkpoint_messages(thread_id)
    return visible_checkpoint_messages(thread_id)


def _build_agent_user_content(
    *,
    repo_url: str,
    task_kind: str,
    prompt: str,
    display_prompt: str | None = None,
    approved_plan: str | None = None,
    thread_id: str | None = None,
) -> str:
    """构造发送给 DeepAgent 的用户内容，避免只读任务被误导去创建 PR。

    runtime 已经通过 task_kind 做了第一层路由，但模型仍然会看到完整自然语言任务。
    为了降低误操作风险，这里再次把“本轮任务类型”和“允许/禁止的行为”写进用户内容：

    - coding：允许修改代码、运行测试、提交并创建或复用 Gitee Pull Request。
    - 非 coding：只能读取仓库、分析、回答或生成方案，禁止写文件和提交。

    如果是用户确认后的 coding 任务，`approved_plan` 会作为实施依据一并传入。
    这样 Agent 执行的是上一轮完整技术方案，而不是“确认实施”这几个字。

    `display_prompt` 是用户在网页输入框里真正输入的文本。确认实施场景下，
    `prompt` 往往会被 runtime 还原成上一轮开发需求，而不是“确认实施”本身。
    因为聊天历史只从 checkpoint 读取，所以这里必须把 `display_prompt` 一并
    写入 HumanMessage。后续 checkpoint_history.py 会优先提取这段内容展示到
    前端，避免刷新历史后丢失用户刚刚输入的确认指令。
    """

    visible_prompt = (display_prompt or prompt).strip()
    repo = parse_repo_url(repo_url)
    repo_working_dir = "/" + repo_project_dir(repo).replace("\\", "/")
    if task_kind == "coding":
        branch_instruction = (
            f"当前任务分支为 `{task_branch_name(thread_id)}`；请保留该分支，不要切回 main/master。"
            if thread_id
            else "请从仓库远端默认分支创建 codex/ 前缀任务分支。"
        )
        plan_instruction = ""
        if approved_plan:
            plan_instruction = f"\n\n用户已经确认以下技术方案，请按该方案实施；如执行中发现必要调整，请在最终总结中说明：\n{approved_plan}"
        task_instruction = (
            "这是开发实现任务。请按系统开发流程完成任务，必要时修改代码、验证，并创建或复用 GitHub/Gitee Pull Request。"
            f"{branch_instruction}创建 PR 时不要猜测 base；留空让对应平台 API 使用仓库真实默认分支。"
            f"{plan_instruction}"
        )
    else:
        task_instruction = (
            "这是只读任务。请使用 write_todos 生成适合该任务的清单；"
            "可以准备并读取仓库，但禁止修改文件、提交、push 或创建 Pull Request；"
            "完成后直接用中文回答用户问题。"
        )
    return (
        f"用户可见输入：\n{visible_prompt}\n\n"
        "内部执行上下文：以下内容用于 Agent 判断和执行，不要原样展示为用户输入。\n\n"
        f"GitHub/Gitee 仓库地址：{repo_url}\n\n"
        f"本轮仓库专属工作目录：{repo_working_dir}。所有仓库文件读取、修改和 Git 命令必须针对该目录；"
        "命令执行的默认 cwd 已是该目录根，请使用仓库相对路径，不要再次 cd 到仓库目录名。"
        "不要从 projects 下选择其它同名/相似目录，也不要更改 origin。\n\n"
        f"任务类型：{task_kind}\n\n"
        f"用户任务：\n{prompt}\n\n"
        f"{task_instruction}"
    )


def _build_plan_user_content(
    *,
    repo_url: str,
    prompt: str,
    previous_plan: str | None = None,
    revision_prompt: str | None = None,
) -> str:
    """构造专门用于生成技术方案的只读任务内容。

    技术方案现在作为普通 Agent 回答直接展示在网页中，不再保存到 thread_plans
    或 Markdown 文件。用户确认后，后端会读取上一条方案消息作为实施依据。

    `previous_plan + revision_prompt` 用于“修改上一版方案”的场景。此时不能只把
    新要求发给模型，否则模型容易只补充一小段；这里明确要求重新输出完整新版方案。
    """

    repo = parse_repo_url(repo_url)
    repo_working_dir = "/" + repo_project_dir(repo).replace("\\", "/")
    workspace_instruction = (
        f"所选仓库唯一工作目录：{repo_working_dir}；命令默认 cwd 已是此仓库根。请只从该目录读取仓库内容；"
        "不要把 projects 下其他目录当成本轮仓库，也不要修改 origin。\n\n"
    )
    if previous_plan and revision_prompt:
        return (
            f"GitHub/Gitee 仓库地址：{repo_url}\n\n"
            f"{workspace_instruction}"
            f"原始用户需求：\n{prompt}\n\n"
            f"上一版技术方案：\n{previous_plan}\n\n"
            f"用户新的修改要求：\n{revision_prompt}\n\n"
            "请基于上一版方案和新的修改要求，重新输出一份完整的新技术方案。\n"
            "不要只输出差异说明，不要只回答新增部分；必须把修订后的完整方案重新组织出来。\n"
            "请只生成技术方案，不要修改文件、不要提交、不要 push、不要创建 Pull Request。\n"
            "方案必须使用中文 Markdown，建议包含：\n"
            "1. 需求理解\n"
            "2. 涉及模块和需要阅读的文件\n"
            "3. 数据结构、接口或页面变化\n"
            "4. 具体实施步骤\n"
            "5. 验证方案\n"
            "6. 风险点和需要用户确认的事项\n"
            "最后必须单独输出一句：是否确认实施该方案？"
        )

    return (
        f"GitHub/Gitee 仓库地址：{repo_url}\n\n"
        f"{workspace_instruction}"
        f"用户需求：\n{prompt}\n\n"
        "请只生成技术方案，不要修改文件、不要提交、不要 push、不要创建 Pull Request。\n"
        "方案必须使用中文 Markdown，建议包含：\n"
        "1. 需求理解\n"
        "2. 涉及模块和需要阅读的文件\n"
        "3. 数据结构、接口或页面变化\n"
        "4. 具体实施步骤\n"
        "5. 验证方案\n"
        "6. 风险点和需要用户确认的事项\n"
        "最后必须单独输出一句：是否确认实施该方案？"
    )


def _is_approval_prompt(prompt: str) -> bool:
    """判断用户是否在等待方案确认阶段明确要求开始实施。

    这是“先方案、再实施”流程的关键入口。用户可能输入“确认”“同意”“开始实施”
    等非常短的指令，runtime 不能把这些短文本当成新的开发需求，而应该回到
    checkpoint 中寻找上一轮技术方案。

    这里故意使用本地规则判断，而不是交给模型判断，因为它会影响是否允许进入
    coding 任务，属于权限相关的流程控制。
    """

    # 先压缩空白并统一小写，兼容用户输入“确认  实施”等轻微格式差异。
    normalized = " ".join((prompt or "").lower().split())
    approval_phrases = [
        "确认",
        "确认实施",
        "同意",
        "同意方案",
        "按方案实施",
        "开始实施",
        "可以实施",
        "按照方案来",
        "就按这个方案",
        "实施",
    ]
    rejection_phrases = ["不确认", "先不要", "不要实施", "修改方案", "重新设计", "调整方案"]
    # 必须同时满足“有确认语义”和“没有否定语义”，避免“不要实施”误触发 coding。
    return any(phrase in normalized for phrase in approval_phrases) and not any(
        phrase in normalized for phrase in rejection_phrases
    )


def _is_plan_revision_prompt(prompt: str) -> bool:
    """判断用户是否明确要求修改上一版技术方案。

    这里必须比任务分类更严格。原因是当前会话中可能存在一份“等待确认”的方案，
    但用户后续输入不一定是在修改方案，也可能只是普通问答，例如：
    “当前项目的记忆文件内容是什么？”。这类问题不能因为历史里有待确认方案，
    就被强行改写成“重新生成技术方案”。

    换句话说：只有用户明确表达“修改/补充/重新生成方案”时，才会触发方案修订。
    这能避免历史中的待确认方案劫持后续普通问答。
    """

    # 方案修订属于高影响路由，只接受明确关键词，不做模糊猜测。
    normalized = " ".join((prompt or "").lower().split())
    revision_markers = [
        "修改方案",
        "调整方案",
        "重新设计方案",
        "重新生成方案",
        "重新输出方案",
        "再生成新的方案",
        "生成新的方案",
        "修订方案",
        "补充方案",
        "完善方案",
        "改一下方案",
        "改一下这个方案",
        "按这个要求修改方案",
        "基于上一版方案",
        "上一版方案",
        "原来的方案",
        "这个方案里面",
        "方案中增加",
        "方案里增加",
    ]
    return any(marker in normalized for marker in revision_markers)


def _message_metadata(message: dict[str, Any]) -> dict[str, Any]:
    """解析消息投影或 checkpoint 兼容结构中的 metadata。

    metadata 可能是 dict，也可能是旧数据中的 JSON 字符串。

    目前最重要的 metadata 是 source_prompt。它用于从“确认实施”恢复出上一轮
    真正的用户需求，避免把“确认”当成 coding 需求传给 Agent。
    """

    metadata = message.get("metadata")
    if isinstance(metadata, dict):
        return metadata
    if isinstance(metadata, str) and metadata.strip():
        try:
            parsed = json.loads(metadata)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _latest_confirmable_plan_message(thread_id: str) -> dict[str, Any] | None:
    """读取当前线程最近一条等待确认的技术方案消息。

    页面展示和确认实施优先读取 thread_messages 投影。SQLite 旧数据仍可回退到
    checkpoint；PostgreSQL 不回退到可能阻塞的 checkpoint delta reader。
    """

    for message in reversed(_visible_thread_messages(thread_id)):
        if message.get("author") != "agent":
            continue
        content = str(message.get("content") or "").strip()
        if _is_confirmable_plan_text(content):
            return message
    return None


def _is_confirmable_plan_text(text: str) -> bool:
    """判断 checkpoint 中的 assistant 正文是否像一份可确认实施的方案。

    三层结构改造后，完整方案正文只从 checkpoint 历史里读取。这里用中文方案
    关键词做保守判断，避免普通问答被误识别成可实施方案。

    判断规则宁可保守，也不要激进。误判为“不是方案”最多让用户重新说明；误判为
    “可实施方案”则可能把普通回答带入 coding 流程，风险更高。
    """

    stripped = text.strip()
    if not stripped:
        return False
    rejection_markers = [
        "当前任务是**只读模式**",
        "当前任务是只读模式",
        "我不会执行代码修改",
        "无法执行代码修改",
        "请切换为编码任务",
    ]
    if any(marker in stripped for marker in rejection_markers):
        return False
    plan_markers = [
        "是否确认实施该方案",
        "技术方案",
        "修复技术方案",
        "实施步骤",
        "修复依据",
        "验证方案",
    ]
    return any(marker in stripped for marker in plan_markers)


def _latest_confirmable_plan_from_checkpoint(thread_id: str) -> dict[str, Any] | None:
    """从 checkpoint 历史中读取最近一条可确认实施的方案。

    Agent 已经在网页上输出完整方案后，该方案会进入 LangGraph checkpoint。
    用户后续输入“确认”时，runtime 从 checkpoint 反查最近的方案正文，
    再把这份方案传给 coding 任务作为实施依据。

    查找方向是从后往前，保证多轮修改方案后总是采用最新的一版。
    这里返回的是 runtime 自己组装的简化消息结构，不直接暴露 checkpoint 内部结构。
    """

    for message in reversed(visible_checkpoint_messages(thread_id)):
        if message.get("author") != "agent":
            continue
        content = str(message.get("content") or "").strip()
        if not _is_confirmable_plan_text(content):
            continue
        return {
            "message_id": message.get("message_id") or f"checkpoint-plan:{thread_id}",
            "thread_id": thread_id,
            "run_id": None,
            "author": "agent",
            "content": content,
            "metadata": {
                "task_kind": "planning",
                "awaiting_confirmation": True,
                "source": "checkpoint",
            },
        }
    return None


def _plan_source_prompt(message: dict[str, Any], fallback: str) -> str:
    """读取方案消息里保存的原始需求。

    首次生成方案时，metadata.source_prompt 保存用户原始需求；方案被多次修订时，
    这里继续沿用上一版 source_prompt，避免只把“再改一下”当成完整开发目标。

    如果历史消息缺少 metadata，就使用 fallback。这个 fallback 通常来自最近一条
    非确认类用户消息，保证旧数据也能继续运行。
    """

    metadata = _message_metadata(message)
    source_prompt = str(metadata.get("source_prompt") or "").strip()
    return source_prompt or fallback


def _latest_non_approval_user_prompt(thread_id: str, fallback: str) -> str:
    """从可展示消息历史读取最近一条不是“确认/开始实施”的用户消息。

    方案确认时，如果方案消息没有携带 metadata.source_prompt，就从投影或 SQLite
    checkpoint 兼容回退中找真实用户需求。

    例如用户依次输入：
    1. “帮我增加部门管理模块”
    2. Agent 输出方案
    3. “确认实施”

    第 3 步进入 coding 时，真正要传给 Agent 的需求应该是第 1 步，而不是第 3 步。
    """

    for message in reversed(_visible_thread_messages(thread_id)):
        if message.get("author") != "user":
            continue
        content = str(message.get("content") or "").strip()
        if content and not _is_approval_prompt(content):
            return content
    return fallback


def _revision_source_prompt(*, previous_source_prompt: str, revision_prompt: str) -> str:
    """把原始需求和本次修订要求合并成新版方案的 source_prompt。

    source_prompt 是后续 coding 阶段还原完整任务目标的依据。多次修改方案时，
    这里会把补充要求追加到原始需求后面，避免后续实施阶段丢失用户逐轮补充的信息。
    """

    revision_prompt = revision_prompt.strip()
    if not revision_prompt:
        return previous_source_prompt
    if "补充/修改要求：" in previous_source_prompt:
        return f"{previous_source_prompt.rstrip()}\n- {revision_prompt}"
    return f"{previous_source_prompt.rstrip()}\n\n补充/修改要求：\n- {revision_prompt}"


def initialize_task_record(
    *,
    repo_url: str,
    prompt: str,
    thread_id: str | None = None,
    record_user_message: bool = True,
) -> str:
    """先创建 dashboard 可见的 thread 记录。

    FastAPI 版本不再像 langgraph dev 那样由 LangGraph 服务直接管理线程。
    前端创建任务时需要马上拿到 thread_id 跳转页面，所以这里先写入业务 Store，
    后台任务再继续执行真正的 Agent 或 git pull。

    Store 中的 thread 记录是前端任务列表和任务状态的业务索引，不等同于
    LangGraph checkpoint。Agent 恢复仍依赖 checkpoint，同时把用户可见正文投影到
    thread_messages，供 Dashboard 在 PostgreSQL 上稳定读取。

    `record_user_message` 保留给轻量任务和兼容调用方，用于控制是否记录本轮用户输入。
    """

    # 如果是全新会话，由 runtime 生成 thread_id；如果是继续对话，复用前端传入的 thread_id。
    thread_id = thread_id or str(uuid.uuid4())
    repo = parse_repo_url(repo_url)
    get_store().upsert_thread(
        thread_id=thread_id,
        title=prompt[:80] or f"{repo.provider.title()}: {repo.owner}/{repo.repo}",
        user_prompt=prompt,
        repo_url=repo.clone_url,
        repo_owner=repo.owner,
        repo_name=repo.repo,
        latest_run_status="running",
    )
    if record_user_message:
        _record_thread_message(
            thread_id=thread_id,
            author="user",
            content=prompt,
            metadata={"source": "dashboard"},
        )
    return thread_id


def run_workspace_listing_task(*, repo_url: str, prompt: str, thread_id: str | None = None) -> dict[str, Any]:
    """直接列出本地工作区项目，不调用模型。

    这是一个“直达分支”：用户只是问本地工作区有哪些项目时，没有必要构建 Agent。
    函数仍然会写 thread/run/run_events，是为了前端展示方式和普通任务保持一致。
    """

    should_record_user_message = True
    thread_id = initialize_task_record(
        repo_url=repo_url,
        prompt=prompt,
        thread_id=thread_id,
        record_user_message=should_record_user_message,
    )
    store = get_store()
    # run_id 区分同一个 thread 内的多轮运行，前端实时事件依赖它避免跨轮覆盖。
    run_id = str(uuid.uuid4())
    store.record_run(run_id=run_id, thread_id=thread_id, status="running")
    workspace = Workspace(WORKSPACE_ROOT)
    backend = LocalShellBackend(workspace)
    try:
        # 所有可见步骤都通过 record_event 写入 run_events，前端可以复用同一套事件展示组件。
        record_event(thread_id, "workspace", "定位本地工作区", status="completed", detail=str(WORKSPACE_ROOT))
        record_event(thread_id, "list:projects", "查看项目目录", kind="search", status="in_progress", detail="projects")
        projects = backend.list_files("projects")
        detail = "\n".join(projects) if projects else "projects 目录暂无项目"
        record_event(thread_id, "list:projects", "查看项目目录", kind="search", status="completed", detail=detail)
        store.update_thread_status(thread_id, "completed")
        store.record_run(run_id=run_id, thread_id=thread_id, status="completed", finished=True)
        record_event(thread_id, "done", "任务完成", status="completed")
        logger.info("工作区项目查询完成：thread_id=%s projects=%s", thread_id, len(projects))
        return {"thread_id": thread_id, "run_id": run_id, "status": "completed", "projects": projects}
    except Exception as exc:
        # 即使是不调用模型的轻量任务，也要统一更新 Store 状态和 run 结束时间，
        # 否则前端会一直显示 running。
        store.update_thread_status(thread_id, "failed")
        record_event(thread_id, "failed", "任务失败", status="error", detail=mask_token(str(exc)))
        store.record_run(
            run_id=run_id,
            thread_id=thread_id,
            status="failed",
            error=mask_token(str(exc)),
            finished=True,
        )
        logger.exception("工作区项目查询失败：thread_id=%s run_id=%s error=%s", thread_id, run_id, mask_token(str(exc)))
        raise


def run_pull_only_task(*, repo_url: str, prompt: str, thread_id: str | None = None) -> dict[str, Any]:
    """执行只拉取远程代码的轻量任务。

    这个分支不调用大模型，也不创建 PR。它只确保 GitHub/Gitee 仓库在本地工作区存在，
    然后执行 fetch 和 pull，适合用户在前端输入“先把远程代码 pull 一下”的场景。

    由于它不需要推理，所以不走 DeepAgent，不消耗模型调用次数。它仍然会初始化
    仓库映射和仓库记忆，保证后续 planning/coding 任务能复用同一个本地目录。
    """

    should_record_user_message = True
    thread_id = initialize_task_record(
        repo_url=repo_url,
        prompt=prompt,
        thread_id=thread_id,
        record_user_message=should_record_user_message,
    )
    store = get_store()
    run_id = str(uuid.uuid4())
    store.record_run(run_id=run_id, thread_id=thread_id, status="running")
    repo = parse_repo_url(repo_url)
    workspace = Workspace(WORKSPACE_ROOT)
    backend = LocalShellBackend(workspace, provider=repo.provider)
    project_dir = repo_project_dir(repo)
    _ensure_repo_memory_for_repo(repo, project_dir)

    try:
        logger.info("开始执行 pull-only 任务：thread_id=%s repo=%s/%s", thread_id, repo.owner, repo.repo)
        record_event(thread_id, "workspace", "准备本地工作区", status="in_progress")
        record_event(thread_id, "sync", "校验远端并同步默认分支", kind="execute", status="in_progress")
        prepared = prepare_repository_workspace(repo, backend, thread_id=thread_id)
        record_event(
            thread_id,
            "sync",
            "校验远端并同步默认分支",
            kind="execute",
            status="completed",
            detail=f"{prepared.directory} · {prepared.default_branch}",
        )
        store.update_thread_status(thread_id, "completed")
        store.record_run(run_id=run_id, thread_id=thread_id, status="completed", finished=True)
        record_event(thread_id, "done", "任务完成", status="completed")
        logger.info("pull-only 任务完成：thread_id=%s repo_dir=%s", thread_id, project_dir)
        return {"thread_id": thread_id, "run_id": run_id, "status": "completed"}
    except Exception as exc:
        store.update_thread_status(thread_id, "failed")
        record_event(thread_id, "failed", "任务失败", status="error", detail=mask_token(str(exc)))
        store.record_run(
            run_id=run_id,
            thread_id=thread_id,
            status="failed",
            error=mask_token(str(exc)),
            finished=True,
        )
        logger.exception("pull-only 任务失败：thread_id=%s run_id=%s error=%s", thread_id, run_id, mask_token(str(exc)))
        raise


def run_plan_response_task(
    *,
    repo_url: str,
    prompt: str,
    thread_id: str | None = None,
    previous_plan_message: dict[str, Any] | None = None,
    revision_prompt: str | None = None,
    event_sink: RuntimeEventSink | None = None,
    model_id: str | None = None,
) -> dict[str, Any]:
    """为编码需求生成技术方案，并把方案作为普通回答直接展示。

    方案以版本化记录写入 thread_plans，并同步把卡片 payload 投影到 thread_messages；
    Dashboard 刷新只读取该轻量投影和业务表，不遍历 PostgreSQL checkpoint delta 链。
    如果传入 previous_plan_message，则表示用户在等待确认阶段提出了补充要求；
    此时会基于上一版方案重新输出完整新版方案，而不是只输出差异。

    这个函数始终以 planning task_kind 运行。即使用户原始需求看起来像 coding，
    只要还没有确认方案，就只能生成方案，不能改文件、不能提交、不能创建 PR。
    """

    thread_id = thread_id or str(uuid.uuid4())
    store = get_store()
    logger.info("开始生成技术方案：thread_id=%s repo_url=%s", thread_id, repo_url)
    repo = parse_repo_url(repo_url)

    plan_source_prompt = prompt
    previous_plan_text: str | None = None
    if previous_plan_message is not None:
        # 方案修订场景：保留上一版方案正文，同时合并用户本轮补充要求。
        # 这样模型能输出“完整新版方案”，而不是只输出增量描述。
        previous_plan_text = str(previous_plan_message.get("content") or "").strip()
        plan_source_prompt = _revision_source_prompt(
            previous_source_prompt=_plan_source_prompt(previous_plan_message, prompt),
            revision_prompt=revision_prompt or prompt,
        )
    store.upsert_thread(
        thread_id=thread_id,
        title=(revision_prompt or prompt)[:80] or f"{repo.provider.title()}: {repo.owner}/{repo.repo}",
        # user_prompt 只保存本轮用户真实输入，用于 Dashboard user_message 展示。
        # plan_source_prompt 是方案生成/后续实施的完整需求，不能混用为前端展示文本。
        user_prompt=revision_prompt or prompt,
        repo_url=repo.clone_url,
        repo_owner=repo.owner,
        repo_name=repo.repo,
        latest_run_status="running",
    )
    display_prompt = revision_prompt or prompt
    _record_thread_message(
        thread_id=thread_id,
        author="user",
        content=display_prompt,
        metadata={"source": "dashboard"},
    )
    run_id = str(uuid.uuid4())
    previous_metadata = _message_metadata(previous_plan_message or {})
    previous_proposal = previous_metadata.get("proposal") or {}
    supersedes_plan_id = previous_metadata.get("plan_id") or previous_proposal.get("plan_id")
    previous_version = previous_metadata.get("version") or previous_proposal.get("version") or 0
    version = int(previous_version) + 1 if previous_plan_message else 1
    previous_plan_status = previous_metadata.get("status") or previous_proposal.get("status") or "pending"
    plan_id = str(uuid.uuid4())
    store.record_run(run_id=run_id, thread_id=thread_id, status="running")
    try:
        record_event(thread_id, "created", "任务已创建", status="completed", run_id=run_id)
        record_event(thread_id, "repo", "解析 GitHub/Gitee 仓库", status="completed", run_id=run_id)
        record_event(thread_id, "workspace", "准备所选仓库工作区", status="in_progress")
        prepared_workspace = _prepare_selected_repository(repo, thread_id=thread_id)
        record_event(
            thread_id,
            "workspace",
            "校验仓库来源并定位默认分支",
            status="completed",
            detail=f"{prepared_workspace.directory} · {prepared_workspace.default_branch}",
        )
        record_event(thread_id, "agent", "构建方案生成 Agent", status="in_progress")
        # 方案任务需要读取仓库结构，因此先确保加载的是用户所选仓库。
        agent = _build_agent_for_runtime(
            thread_id=thread_id, task_kind="planning", repo_url=repo.clone_url, model_id=model_id
        )
        record_event(thread_id, "agent", "构建方案生成 Agent", status="completed")
        # 事件流消费由 streaming_runtime.py 负责。runtime 只关心最终是否成功、
        # 以及最终 messages 里是否能提取到一份可确认的技术方案。
        result = run_agent_with_event_stream(
            agent=agent,
            thread_id=thread_id,
            run_id=run_id,
            content=_build_plan_user_content(
                repo_url=repo.clone_url,
                prompt=_plan_source_prompt(previous_plan_message, prompt)
                if previous_plan_message is not None
                else prompt,
                previous_plan=previous_plan_text,
                revision_prompt=revision_prompt,
            ),
            task_kind="planning",
            event_sink=event_sink,
            model_id=model_id,
        )
        _record_todo_completion_guard(store, thread_id=thread_id, run_id=run_id)
        store.finish_open_run_events(thread_id, status="completed", run_id=run_id)
        messages = result.get("messages", [])
        plan_text = _extract_best_plan_text(messages)
        if not plan_text:
            raise RuntimeError("技术方案生成失败：模型没有返回可用方案")
        _record_thread_message(
            thread_id=thread_id,
            author="agent",
            content=plan_text,
            run_id=run_id,
            metadata={
                "source": "runtime",
                "task_kind": "planning",
                "awaiting_confirmation": True,
                "source_prompt": plan_source_prompt,
                "proposal": {
                    "plan_id": plan_id,
                    "version": version,
                    "status": "pending",
                    "source_prompt": plan_source_prompt,
                    "plan_text": plan_text,
                },
            },
        )
        store.add_thread_plan(
            plan_id=plan_id,
            thread_id=thread_id,
            run_id=run_id,
            prompt=plan_source_prompt,
            plan_text=plan_text,
            plan_path="",
            status="pending",
            version=version,
            supersedes_plan_id=supersedes_plan_id,
        )
        if supersedes_plan_id:
            store.transition_thread_plan(
                supersedes_plan_id,
                thread_id=thread_id,
                expected_status=str(previous_plan_status),
                status="superseded",
                decision_feedback=revision_prompt,
            )
        store.update_thread_status(thread_id, "completed")
        store.record_run(run_id=run_id, thread_id=thread_id, status="completed", finished=True)
        record_event(thread_id, "plan", "技术方案已输出，等待确认", kind="other", status="completed")
        logger.info("技术方案输出完成：thread_id=%s", thread_id)
        return {
            "thread_id": thread_id,
            "run_id": run_id,
            "status": "completed",
        }
    except Exception as exc:
        store.finish_open_run_events(thread_id, status="error", run_id=run_id)
        store.update_thread_status(thread_id, "failed")
        record_event(thread_id, "failed", "技术方案生成失败", status="error", detail=mask_token(str(exc)))
        store.record_run(
            run_id=run_id,
            thread_id=thread_id,
            status="failed",
            error=mask_token(str(exc)),
            finished=True,
        )
        logger.exception("技术方案生成失败：thread_id=%s run_id=%s error=%s", thread_id, run_id, mask_token(str(exc)))
        raise


def run_agent_task(
    *,
    repo_url: str,
    prompt: str,
    thread_id: str | None = None,
    event_sink: RuntimeEventSink | None = None,
    interaction_action: str | None = None,
    plan_id: str | None = None,
    intervention_id: str | None = None,
    model_id: str | None = None,
) -> dict[str, Any]:
    """运行一次普通 Agent 任务的总入口。

    这是 runtime.py 最重要的函数。FastAPI 后台任务最终会调用它完成一次用户输入。
    它的职责不是直接解决问题，而是决定本轮应该走哪条流程：

    1. 工作区查询和 git pull 这类简单任务直接执行，不调用模型。
    2. 首轮 coding 需求先转成 planning，输出技术方案并等待用户确认。
    3. 用户确认后，从 checkpoint 找到上一轮方案，再切换为 coding。
    4. 普通 qa、analysis、review 等只读任务直接构建对应 task_kind 的 DeepAgent。
    5. 任务结束后更新 Store 状态、run_events 和仓库级长期记忆。

    注意：checkpoint 仍负责 Agent 状态恢复；用户可见消息同步投影到 thread_messages，
    Dashboard 和 PostgreSQL 方案确认优先读取该投影。
    """

    # 新任务创建新 thread；继续对话时使用前端已有 thread_id，确保 checkpoint 接上历史。
    thread_id = thread_id or str(uuid.uuid4())
    store = get_store()
    existing_thread = store.get_thread(thread_id)
    get_active_intervention = getattr(store, "get_latest_active_thread_intervention", None)
    active_intervention = get_active_intervention(thread_id) if get_active_intervention else None
    if active_intervention and (
        interaction_action != "resume_intervention"
        or intervention_id != active_intervention.get("intervention_id")
    ):
        raise ValueError("此会话正等待人工介入答复，请通过介入卡片提交答复后继续")
    # 两个直达分支都不需要 LLM，能显著减少模型调用和等待时间；先检查待处理 HITL，
    # 避免任何普通消息（包括看似只读的快捷任务）绕过当前中断。
    if not interaction_action and is_workspace_listing_task(prompt):
        return run_workspace_listing_task(repo_url=repo_url, prompt=prompt, thread_id=thread_id)
    if not interaction_action and is_pull_only_task(prompt):
        return run_pull_only_task(repo_url=repo_url, prompt=prompt, thread_id=thread_id)
    # 恢复动作不做普通意图分类：“1/确认/继续”等只能作为 checkpoint 的 resume 值，
    # 不能重新被判为 qa 并启动一轮新任务。
    task_kind = (
        "coding"
        if interaction_action in {"resume_intervention", "approve_plan"}
        else classify_task_kind(prompt)
    )
    approved_plan_text: str | None = None
    explicit_plan: dict[str, Any] | None = None
    # display_prompt 是本轮用户真实输入，用于前端展示；coding_prompt 是传给 Agent 的执行目标。
    # 在“确认实施”场景下，二者不能混用：用户真实输入可能只有“确认”，而执行目标应是上一轮方案。
    display_prompt = prompt
    coding_prompt = prompt
    resume_value: dict[str, Any] | None = None
    if interaction_action == "resume_intervention":
        if not existing_thread or not intervention_id or not prompt.strip():
            raise ValueError("人工介入回复缺少有效会话、问题标识或答复内容")
        intervention = store.resolve_thread_intervention(
            intervention_id, thread_id=thread_id, response=prompt.strip()
        )
        if not intervention:
            raise ValueError("该人工介入已处理或已失效，请刷新会话后重试")
        resume_value = {"response": prompt.strip()}
        task_kind = "coding"

    if interaction_action and interaction_action != "resume_intervention":
        if not existing_thread or not plan_id:
            raise ValueError("方案操作缺少有效会话或方案标识")
        explicit_plan = store.get_thread_plan(plan_id)
        if not explicit_plan or explicit_plan.get("thread_id") != thread_id:
            raise ValueError("方案不存在或不属于当前会话")
        if interaction_action == "reject_plan":
            transitioned = store.transition_thread_plan(
                plan_id, thread_id=thread_id, expected_status="pending", status="rejected"
            )
            if not transitioned:
                raise ValueError("该方案已处理或已失效，请刷新会话后重试")
            _record_thread_message(
                thread_id=thread_id, author="user", content=prompt,
                metadata={"source": "plan_decision", "plan_id": plan_id, "action": "reject"},
            )
            _record_thread_message(
                thread_id=thread_id,
                author="agent",
                content="已拒绝实施本方案。我不会修改仓库；如需继续，可以在对话中说明新的目标。",
                metadata={"source": "plan_decision", "plan_id": plan_id, "action": "rejected"},
            )
            store.update_thread_status(thread_id, "completed")
            return {"thread_id": thread_id, "status": "completed", "decision": "rejected"}
        if interaction_action == "revise_plan":
            if explicit_plan.get("status") != "pending" or not prompt.strip():
                raise ValueError("只能调整待确认方案，且需要填写调整要求")
            reserved_plan = store.transition_thread_plan(
                plan_id, thread_id=thread_id, expected_status="pending", status="revising",
                decision_feedback=prompt,
            )
            if not reserved_plan:
                raise ValueError("该方案正在被处理，请刷新会话后重试")
            previous = {
                "author": "agent",
                "content": explicit_plan.get("plan_text") or "",
                "metadata": {
                    "source_prompt": explicit_plan.get("prompt") or "",
                    "plan_id": plan_id,
                    "version": explicit_plan.get("version") or 1,
                    "status": "revising",
                },
            }
            try:
                return run_plan_response_task(
                    repo_url=repo_url,
                    prompt=str(explicit_plan.get("prompt") or prompt),
                    thread_id=thread_id,
                    previous_plan_message=previous,
                    revision_prompt=prompt,
                    event_sink=event_sink,
                    model_id=model_id,
                )
            except Exception:
                store.transition_thread_plan(
                    plan_id, thread_id=thread_id, expected_status="revising", status="pending"
                )
                raise
        if interaction_action == "approve_plan":
            if explicit_plan.get("status") != "pending":
                raise ValueError("该方案已处理或已失效，请刷新会话后重试")
            transitioned = store.transition_thread_plan(
                plan_id, thread_id=thread_id, expected_status="pending", status="approved"
            )
            if not transitioned:
                raise ValueError("该方案已处理或已失效，请刷新会话后重试")
            approved_plan_text = str(explicit_plan.get("plan_text") or "")
            coding_prompt = str(explicit_plan.get("prompt") or prompt)
            task_kind = "coding"
        else:
            raise ValueError("未知的方案操作")

    if existing_thread and _is_approval_prompt(prompt) and not interaction_action:
        # 说明重点：
        # “确认实施”不能直接等价于“执行当前这几个字”。
        # 必须先回到当前 thread 的历史消息里，找到最近一条仍在等待确认的技术方案；
        # 再用该方案的 source_prompt 还原用户最初的开发需求，避免把“确认”当作新需求执行。
        plan_message = _latest_confirmable_plan_message(thread_id)
        if plan_message is not None:
            metadata = _message_metadata(plan_message)
            approved_plan_text = str(plan_message.get("content") or "")
            coding_prompt = str(
                metadata.get("source_prompt")
                or _latest_non_approval_user_prompt(thread_id, existing_thread.get("user_prompt") or prompt)
            )
            task_kind = "coding"
    elif existing_thread and not interaction_action:
        # 如果当前会话已经有一版等待确认的技术方案，而用户没有确认实施，
        # 只有用户明确说“修改/重新生成/补充方案”时，才把这轮输入视为方案修订。
        # 普通问答、代码审查、查看记忆文件等只读任务不能被历史方案劫持。
        plan_message = _latest_confirmable_plan_message(thread_id) if _is_plan_revision_prompt(prompt) else None
        if plan_message is not None and prompt.strip():
            # 方案修订仍然是 planning，只重新生成完整新版方案，不进入 coding。
            return run_plan_response_task(
                repo_url=repo_url,
                prompt=_plan_source_prompt(plan_message, _latest_non_approval_user_prompt(thread_id, prompt)),
                thread_id=thread_id,
                previous_plan_message=plan_message,
                revision_prompt=prompt,
                event_sink=event_sink,
                model_id=model_id,
            )
    if existing_thread and approved_plan_text is None and not interaction_action and _is_approval_prompt(prompt):
        # 没有可确认的技术方案时，把“确认”当作普通问题处理，避免误执行旧任务。
        task_kind = classify_task_kind(prompt)

    if approved_plan_text is not None:
        task_kind = "coding"

    if task_kind == "coding" and approved_plan_text is None and interaction_action != "resume_intervention":
        # 这是本项目“人在回路”的核心控制点：
        # 只要是 coding 请求，且没有找到用户确认过的方案，就先转入 planning。
        # 这个判断在 runtime 层完成，而不是只写在 Prompt 里，目的是把“先方案、再实施”
        # 做成确定性的产品流程，降低 Agent 首轮直接误改代码的风险。
        return run_plan_response_task(
            repo_url=repo_url, prompt=prompt, thread_id=thread_id, event_sink=event_sink, model_id=model_id
        )

    # 到这里说明本轮不是直达任务，也不是“未确认的 coding 需求”。
    # 接下来进入通用 Agent 执行分支：qa/analysis/review/coding 都会通过事件流运行。
    logger.info("任务开始：thread_id=%s repo_url=%s", thread_id, repo_url)
    repo = parse_repo_url(repo_url)
    logger.info("仓库解析成功：provider=%s owner=%s repo=%s", repo.provider, repo.owner, repo.repo)
    store.upsert_thread(
        thread_id=thread_id,
        title=coding_prompt[:80] or f"{repo.provider.title()}: {repo.owner}/{repo.repo}",
        # user_prompt 只用于 Dashboard 展示“本轮用户真实输入”。
        # coding_prompt 可能是从上一轮方案还原出的完整执行需求，不能写回这里，
        # 否则用户输入“确认实施”后，前端会收到上一轮需求文本并误判重复。
        user_prompt=display_prompt,
        repo_url=repo.clone_url,
        repo_owner=repo.owner,
        repo_name=repo.repo,
        latest_run_status="running",
    )
    # Dashboard SSE 已经会在初始化阶段写入用户消息；这里再次调用是幂等的，
    # 也保证直接调用 run_agent_task 的脚本/测试不会丢失历史输入。
    _record_thread_message(
        thread_id=thread_id,
        author="user",
        content=display_prompt,
        metadata={"source": "runtime", "task_kind": task_kind},
    )
    # 每轮 Agent 执行都有独立 run_id。前端事件列表按 run_id 追加，不能复用上一轮 id。
    run_id = str(uuid.uuid4())
    store.record_run(run_id=run_id, thread_id=thread_id, status="running")
    logger.info("业务 Store 已记录运行：thread_id=%s run_id=%s", thread_id, run_id)
    try:
        if approved_plan_text is not None:
            record_event(thread_id, "plan:approved", "用户已确认技术方案", kind="other", status="completed", run_id=run_id)
        record_event(thread_id, "created", "任务已创建", status="completed", run_id=run_id)
        record_event(thread_id, "repo", "解析 GitHub/Gitee 仓库", status="completed", run_id=run_id)
        record_event(thread_id, "workspace", "准备所选仓库工作区", status="in_progress")
        prepared_workspace = _prepare_selected_repository(
            repo,
            thread_id=thread_id,
            create_task_branch=(task_kind == "coding"),
        )
        record_event(
            thread_id,
            "workspace",
            "校验仓库来源并绑定任务工作目录",
            status="completed",
            detail=f"{prepared_workspace.directory} · {prepared_workspace.current_branch}",
        )
        record_event(thread_id, "agent", "构建 Agent 运行图", status="in_progress")
        # Agent 在仓库校验成功后才创建，backend 默认 cwd 已绑定到本轮仓库。
        agent = _build_agent_for_runtime(
            thread_id=thread_id, task_kind=task_kind, repo_url=repo.clone_url, model_id=model_id
        )
        logger.info("Agent 图已构建：thread_id=%s", thread_id)
        record_event(thread_id, "agent", "构建 Agent 运行图", status="completed")
        logger.info("开始通过官方事件流调用 Agent：thread_id=%s", thread_id)
        # runtime 只负责“决定跑什么”和“最终状态落库”。
        # 运行过程中的 text delta、write_todos、tool call、subagent 事件解析，
        # 统一交给 streaming_runtime.py，避免调度层和事件解析层混在一起。
        with WorkerLeaseManager(store).hold(run_id):
            result = run_agent_with_event_stream(
                agent=agent,
                thread_id=thread_id,
                run_id=run_id,
                content=_build_agent_user_content(
                    repo_url=repo.clone_url,
                    task_kind=task_kind,
                    prompt=coding_prompt,
                    display_prompt=display_prompt,
                    approved_plan=approved_plan_text,
                    thread_id=thread_id,
                ),
                task_kind=task_kind,
                event_sink=event_sink,
                resume_value=resume_value,
                model_id=model_id,
            )
        if interaction_action == "resume_intervention":
            store.finish_thread_intervention(intervention_id, thread_id=thread_id)
        interrupts = result.get("interrupts") or []
        if interrupts:
            for payload in interrupts:
                intervention_id = str(uuid.uuid4())
                store.create_thread_intervention(
                    intervention_id=intervention_id,
                    thread_id=thread_id,
                    run_id=run_id,
                    payload=payload,
                )
                _record_thread_message(
                    thread_id=thread_id,
                    author="agent",
                    content=str(payload.get("question") or "需要你提供进一步确认。"),
                    run_id=run_id,
                    metadata={"source": "human_intervention", "intervention_id": intervention_id},
                )
            store.finish_open_run_events(thread_id, status="completed", run_id=run_id)
            current_branch = _detect_current_branch(repo)
            store.update_thread_status(thread_id, "awaiting_approval", branch_name=current_branch)
            store.record_run(run_id=run_id, thread_id=thread_id, status="awaiting_approval", finished=True)
            record_event(thread_id, "human:intervention", "等待你答复后继续", status="completed")
            return {"thread_id": thread_id, "run_id": run_id, "status": "awaiting_approval", "interrupts": interrupts}
        todo_summary = _record_todo_completion_guard(store, thread_id=thread_id, run_id=run_id)
        store.finish_open_run_events(thread_id, status="completed", run_id=run_id)
        current_branch = _detect_current_branch(repo)
        store.update_thread_status(thread_id, "completed", branch_name=current_branch)
        store.record_run(run_id=run_id, thread_id=thread_id, status="completed", finished=True)
        run_title = "任务完成" if not todo_summary or todo_summary["complete"] else "任务运行结束（清单未完成）"
        record_event(thread_id, "done", run_title, status="completed")
        messages = result.get("messages", [])
        final_answer = _extract_final_assistant_text(messages)
        if final_answer:
            _record_thread_message(
                thread_id=thread_id,
                author="agent",
                content=final_answer,
                run_id=run_id,
                metadata={"source": "runtime", "task_kind": task_kind},
            )
            # 仓库记忆只记录最终稳定结论，不记录所有中间 chunk。
            # branch/pr 信息来自 Store 中的最新业务状态，通常由 Gitee 工具在执行过程中写入。
            latest_thread = store.get_thread(thread_id) or {}
            update_repo_memory_from_text(
                store=get_langgraph_store(),
                repo=repo,
                update=RepoMemoryUpdate(
                    task_kind=task_kind,
                    final_text=final_answer,
                    branch_name=latest_thread.get("branch_name"),
                    pr_url=latest_thread.get("pr_url"),
                ),
            )
        logger.info("任务完成：thread_id=%s run_id=%s messages=%s", thread_id, run_id, len(messages))
        return {"thread_id": thread_id, "run_id": run_id, "status": "completed", "messages": messages}
    except Exception as exc:
        if interaction_action == "resume_intervention" and intervention_id:
            store.finish_thread_intervention(intervention_id, thread_id=thread_id, status="pending")
        # 异常路径必须同时关闭未完成事件、更新 thread 状态和 run 状态。
        # 如果漏掉其中任何一项，前端可能会一直停留在“ 运行中”。
        store.finish_open_run_events(thread_id, status="error", run_id=run_id)
        store.update_thread_status(thread_id, "failed")
        record_event(
            thread_id,
            "model",
            f"调用 {model_id or get_env('MAIN_MODEL', 'deepseek-v4-pro').strip()}",
            status="error",
        )
        record_event(thread_id, "failed", "任务失败", status="error", detail=mask_token(str(exc)))
        store.record_run(
            run_id=run_id,
            thread_id=thread_id,
            status="failed",
            error=mask_token(str(exc)),
            finished=True,
        )
        logger.exception("任务失败：thread_id=%s run_id=%s error=%s", thread_id, run_id, mask_token(str(exc)))
        raise


def get_task(thread_id: str) -> dict[str, Any] | None:
    """读取单个任务摘要，并附带 reviewer findings。

    这个函数主要服务 Dashboard API。它读取的是业务摘要，不是完整聊天历史。
    完整用户/assistant 消息应从 checkpoint_history 相关接口读取。
    """

    store = get_store()
    thread = store.get_thread(thread_id)
    if thread is None:
        return None
    thread["findings"] = store.list_findings(thread_id)
    thread["latest_run"] = store.get_latest_run(thread_id)
    thread["run_events"] = store.list_run_events(thread_id)
    return thread


def list_tasks(limit: int = 50) -> list[dict[str, Any]]:
    """读取最近任务列表，供页面展示历史运行记录。

    返回值包含最新 run 和 run_events，方便列表页展示任务状态、运行耗时和简要步骤。
    这里不会读取 checkpoint 正文，避免任务列表接口变重。
    """

    store = get_store()
    threads = store.list_threads(limit=limit)
    for thread in threads:
        thread_id = thread["thread_id"]
        thread["latest_run"] = store.get_latest_run(thread_id)
        thread["run_events"] = store.list_run_events(thread_id)
    return threads


def delete_task(thread_id: str) -> bool:
    """删除一个 dashboard 会话。

    Store 负责删除业务索引、运行记录和结构化 findings；checkpointer 负责删除
    LangGraph thread state 和历史 messages。两者都清理后，页面历史和 Agent 上下文
    才会真正消失。

    这是当前项目里 Store 和 checkpoint 同时参与的少数场景之一。正常展示和历史恢复
    不从 Store 读正文，但删除会话时必须两边都清理，避免残留上下文影响后续同名任务。
    """

    deleted = get_store().delete_thread(thread_id)
    if not deleted:
        return False
    try:
        get_checkpointer().delete_thread(thread_id)
    except Exception:
        # 删除业务会话已经成功，checkpoint 清理失败不应该让前端误以为删除失败；
        # 记录日志后由后续维护脚本处理残留 checkpoint。
        logger.exception("删除 checkpoint 失败：thread_id=%s", thread_id)
    return True
