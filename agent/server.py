from __future__ import annotations

"""DeepAgents 工厂模块。

这个文件是本地部署版 Agent 的“装配中心”，负责把模型、工具、子 Agent、
本地文件系统 backend、长期记忆 backend、权限规则、中间件和 checkpoint 串起来。

需要特别注意：
- FastAPI 每一轮任务都会调用 `get_agent()` 取得一个新的 Agent runnable。
- Agent Python 对象不是长期状态容器；真正的会话状态由 LangGraph checkpointer 保存。
- 本地工作区、仓库记忆和工具侧状态由 backend / StoreBackend 负责管理。
"""

import logging
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, StoreBackend
from deepagents.middleware.subagents import GENERAL_PURPOSE_SUBAGENT, SubAgent
from deepagents.middleware.summarization import create_summarization_tool_middleware
from langchain.agents.middleware import ModelCallLimitMiddleware, TodoListMiddleware
from langchain_core.language_models import BaseChatModel
from langgraph.graph.state import RunnableConfig
from langgraph.store.base import BaseStore

from agent.backends.local_shell import LocalShellBackend
from agent.backends.workspace import Workspace
from agent.core.graph import get_langgraph_store
from agent.core.middleware import (
    ContextInjectionMiddleware,
    MessageSanitizeMiddleware,
    SanitizeToolInputsMiddleware,
    ToolErrorMiddleware,
)
from agent.core.model import make_main_model
from agent.core.repo_memory import (
    build_repo_memory_namespace,
    ensure_repo_memory_initialized,
    repo_project_dir,
    repo_memory_store_key,
    repo_memory_virtual_path,
)
from agent.core.settings import WORKSPACE_ROOT
from agent.core.task_intent import TaskKind
from agent.prompt import get_system_prompt
from agent.tools import (
    add_review_finding,
    fetch_url,
    get_gitee_pull_request_context,
    create_gitee_issue,
    get_gitee_issue_context,
    get_github_actions_status,
    get_github_issue_context,
    get_github_pull_request_context,
    get_review_diff_summary,
    hybrid_code_search,
    list_review_findings,
    load_default_review_rules,
    open_gitee_pull_request,
    open_github_pull_request,
    create_github_issue,
    publish_github_issue_comment,
    publish_github_pr_comment,
    publish_gitee_issue_comment,
    rerun_github_actions,
    cancel_github_actions,
    publish_gitee_pr_comment,
    validate_review_finding_location,
    web_search,
    request_human_intervention,
)
from agent.repository import parse_repo_url

logger = logging.getLogger(__name__)

# LangGraph 图执行层的最大 super-step 数。它限制的是“图可以走多少步”，
# 不是单纯限制 LLM 调用次数。这里设大一些，避免复杂 coding 任务被图层过早打断。
DEFAULT_RECURSION_LIMIT = 9999

# 模型调用层的保护阈值。它由 ModelCallLimitMiddleware 执行，
# 用来防止 Agent 在工具失败、上下文异常或模型反复决策时无限循环。
MODEL_CALL_RECURSION_LIMIT = 5000

# 本地部署版只保留本地 workspace，不接入 之前项目 的远程 sandbox。
# 这里仍然按照 之前项目 的方式按 thread 缓存 backend，方便同一轮/同一会话复用
# 工作区上下文，也方便后续讲解“thread -> backend -> Agent”的生命周期。
_BACKENDS: dict[str, LocalShellBackend] = {}


def graph_loaded_for_execution(config: RunnableConfig) -> bool:
    """判断当前 Agent 是否用于真实执行。

    之前项目 在 LangGraph Server 中会区分“图结构探测”和“真实运行”。
    CODING 不使用 langgraph dev，但保留这个判断，可以让项目代码结构
    尽量贴近 之前项目，并避免没有 thread_id 时误创建完整工具链。
    """

    configurable = (config or {}).get("configurable") or {}
    return bool(configurable.get("__is_for_execution__", False))


def ensure_backend_for_thread(
    thread_id: str,
    *,
    provider: str | None = None,
    working_dir: str | None = None,
) -> LocalShellBackend:
    """获取或创建绑定到 thread 的本地 backend。

    这个函数对应 之前项目 的 `ensure_sandbox_for_thread`，但做了功能减法：
    - 不创建远程 sandbox；
    - 不处理 GitHub proxy；
    - 不接入 LangSmith metadata；
    - 只负责复用当前机器上的 `AI_WORKSPACE_ROOT` 工作区。
    """

    backend = _BACKENDS.get(thread_id)
    if backend is None:
        logger.info("为 thread 创建 LocalShellBackend：%s", thread_id)
        backend = LocalShellBackend(provider=provider, working_dir=working_dir)
        _BACKENDS[thread_id] = backend
    else:
        logger.info("复用 thread 的 LocalShellBackend：%s", thread_id)
        if provider:
            backend.provider = provider
        if working_dir:
            backend.set_working_dir(working_dir)
    return backend


def _general_purpose_subagent(model: BaseChatModel) -> SubAgent:
    """构建 之前项目 风格的通用分析子 Agent。

    子 Agent 只负责阅读、分析、总结和给主 Agent 提供建议。它不能直接修改
    `/projects` 下的源码，也不能改 `/skills`、`/policies`、`/runtimes`。
    这样可以让主 Agent 保持最终执行权，降低子 Agent 误改代码的风险。
    """

    return {
        "name": GENERAL_PURPOSE_SUBAGENT["name"],
        "description": GENERAL_PURPOSE_SUBAGENT["description"],
        "system_prompt": GENERAL_PURPOSE_SUBAGENT["system_prompt"],
        "model": model,
        "skills": ["/skills/"],
    }


def _code_reviewer_subagent(model: BaseChatModel) -> SubAgent:
    """构建只读代码审查子 Agent。

    Reviewer 子 Agent 的职责是读取规则、读取 Gitee PR 上下文、分析 diff、
    记录结构化 finding，并输出中文审查报告。第一版不允许它修改 `/projects`
    中的源码，也不允许提交、push 或创建 PR，避免“审查”和“修复”职责混在一起。
    """

    return {
        "name": "code_reviewer",
        "description": (
            "用于审查 GitHub/Gitee Pull Request 或本地分支 diff 的子 Agent。"
            "它会读取审查规则、PR 上下文和变更文件，记录结构化 finding，"
            "最后输出中文审查报告。"
        ),
        "system_prompt": (
            "你是 CODING 的代码审查子 Agent，只负责 review，不负责修改代码。\n"
            "你必须使用中文输出，代码标识符、路径、命令和 API 名称可以保留英文。\n"
            "审查流程：\n"
            "1. 按 code-review skill 先用 read_file 读取工作区规则和仓库规则；读不到时调用 load_default_review_rules。\n"
            "2. 如果用户提供 GitHub/Gitee PR 编号，按仓库平台调用对应的 Pull Request Context 工具，读取 PR 详情、提交、文件、普通评论、Review Comment 和 CI 状态。\n"
            "3. 调用 get_review_diff_summary 获取本地 diff 摘要和变更行号。\n"
            "4. 只记录会导致真实风险的问题，不记录纯风格偏好。\n"
            "5. finding 必须包含 file、line、severity、title、description。\n"
            "6. 记录 finding 前，尽量确认文件属于本次 diff；无法确认行号时使用文件级 finding。\n"
            "7. 使用 add_review_finding 保存结构化发现，再用 list_review_findings 汇总。\n"
            "8. 最终报告必须包含结论、阻塞问题、高风险问题、一般建议和测试建议。\n"
            "9. 不要修改文件、不要提交、不要 push、不要创建 Pull Request。\n"
        ),
        "model": model,
        "tools": [
            get_gitee_pull_request_context,
            get_github_pull_request_context,
            load_default_review_rules,
            get_review_diff_summary,
            validate_review_finding_location,
            add_review_finding,
            list_review_findings,
        ],
        "skills": ["/skills/"],
    }


def _task_kind_from_config(configurable: dict[str, Any]) -> TaskKind:
    """从 config 中读取任务类型，非法值统一回退为 coding。"""

    value = configurable.get("task_kind", "coding")
    if value in {"coding", "analysis", "planning", "qa", "sync", "inspect", "review"}:
        return value
    return "coding"


def _prepare_repo_backend_context(
    *,
    repo_url: Any,
    backend: LocalShellBackend,
) -> tuple[Any, list[str] | None, str | None]:
    """为指定 Gitee 仓库准备 repo 级 backend 和长期记忆。

    `LocalShellBackend` 负责真实的 Windows 文件和命令执行；如果任务绑定了
    Gitee 仓库，这里再把 `/memories/` 路径挂到 DeepAgents `StoreBackend` 上。
    同时读取记忆文件内容返回，避免后续 middleware 重复查询数据库。
    返回: (CompositeBackend, [memory_virtual_path], memory_content_str | None)
    """

    if not isinstance(repo_url, str) or not repo_url.strip():
        # 没有仓库地址时，只能使用普通本地 backend；例如纯问答或测试入口探测。
        return backend, None, None

    # 仓库地址是仓库记忆命名空间的唯一来源，格式必须能解析为 owner/repo。
    repo = parse_repo_url(repo_url)
    langgraph_store = get_langgraph_store()
    project_dir = repo_project_dir(repo)

    # 初始化只在记忆不存在时写入模板；已有记忆不会被覆盖。
    ensure_repo_memory_initialized(
        store=langgraph_store,
        repo=repo,
        project_dir=project_dir,
    )
    # 顺带读一次记忆内容，传给 ContextInjectionMiddleware 避免重复查询
    memory_provider = repo.provider if repo.provider != "gitee" else None
    memory_path = repo_memory_virtual_path(repo.owner, repo.repo, memory_provider)
    memory_content: str | None = None
    memory_item = langgraph_store.get(
        build_repo_memory_namespace(repo.owner, repo.repo, memory_provider),
        repo_memory_store_key(repo.owner, repo.repo, memory_provider),
    )
    if memory_item is not None:
        content = str(memory_item.value.get("content") or "").strip()
        if content:
            memory_content = content

    # 返回 CompositeBackend 后，Agent 内部读 /memories/... 会走 StoreBackend，
    # 读 /projects/...、执行命令和读取 skills 仍然走 LocalShellBackend。
    return (
        create_repo_backend(
            local_backend=backend,
            store=langgraph_store,
            owner=repo.owner,
            repo=repo.repo,
            provider=memory_provider,
        ),
        [memory_path],
        memory_content,
    )

def create_repo_backend(
    *,
    local_backend: LocalShellBackend,
    store: BaseStore,
    owner: str,
    repo: str,
    provider: str | None = None,
) -> CompositeBackend:
    """创建当前仓库专用的 CompositeBackend。

    - `/projects`、`/skills`、`/runtimes` 和 `execute()` 继续走 LocalShellBackend。
    - `/memories/` 走 DeepAgents 原生 StoreBackend，底层由 LangGraph Store 持久化。
    """
    namespace = build_repo_memory_namespace(owner, repo, provider)
    return CompositeBackend(
        # default backend 覆盖绝大多数路径和命令执行能力。
        default=local_backend,
        routes={
            # /memories/ 是虚拟路径，不对应 Windows 真实目录。
            # DeepAgents 原生 memory=[...] 会通过这里落到 LangGraph Store。
            "/memories/": StoreBackend(
                store=store,
                namespace=lambda _rt, _namespace=namespace: _namespace,
            )
        },
    )


def get_agent(config: RunnableConfig):
    """按照 指定 thread 构建 DeepAgent。

    之前项目 的入口是 `async def get_agent(config)`，因为它需要异步解析用户身份、
    远程 sandbox、团队模型配置等。本地部署版全部使用本地配置，因此这里保留同名
    工厂函数，但实现为同步函数，方便 FastAPI 后台任务直接调用。
    """

    # 复制 config，避免调用方传入的 dict 被 Agent 工厂就地改写。
    config = dict(config or {})
    configurable = dict(config.get("configurable") or {})
    thread_id = configurable.get("thread_id")
    config["configurable"] = configurable
    config["recursion_limit"] = config.get("recursion_limit", DEFAULT_RECURSION_LIMIT)

    if not isinstance(thread_id, str) or not thread_id or not graph_loaded_for_execution(config):
        # 说明重点：
        # 有些框架或调试脚本会“探测”Agent 图结构，但这不代表要真正执行任务。
        # 这里返回空 Agent，是为了避免没有 thread_id 时就创建 backend、加载工具、
        # 甚至触发文件系统副作用。真实任务必须带 thread_id 且标记执行态。
        logger.info("没有 thread_id 或不是执行态，返回空 Agent")
        return create_deep_agent(system_prompt="", tools=[]).with_config(config)

    # task_kind 是系统提示词、权限策略和运行保护策略的共同输入。
    task_kind = _task_kind_from_config(configurable)

    repo_url = configurable.get("repo_url")
    repo_provider = None
    repo_working_dir = None
    if isinstance(repo_url, str) and repo_url.strip():
        repo = parse_repo_url(repo_url)
        repo_provider = repo.provider
        repo_working_dir = "/" + repo_project_dir(repo).replace("\\", "/")
    # backend 按 thread 复用，避免同一个会话内反复初始化 Windows 工作区封装。
    backend = ensure_backend_for_thread(
        thread_id,
        provider=repo_provider,
        working_dir=repo_working_dir,
    )
    langgraph_store = get_langgraph_store()
    # server.py 在创建 Agent 之前，已经顺手读到了当前仓库记忆内容；
    # 那就把内容放进 config，后面的 ContextInjectionMiddleware 直接用，
    # 避免 middleware 再查一次 LangGraph Store。
    agent_backend, memory_paths, repo_memory_content = _prepare_repo_backend_context(repo_url=repo_url, backend=backend)
    if repo_memory_content:
        configurable["_repo_memory_content"] = repo_memory_content

    # 本地部署版暂时主 Agent 和子 Agent 共用 deepseek-v4-pro。
    # 后续如果要演示 之前项目 的 profile / fallback / team defaults，
    # 可以从这里拆出 main_model 和 subagent_model 的不同配置。
    # 这里每次创建 Agent 都重新创建 model wrapper，但模型调用状态不依赖该对象保存。
    main_model = make_main_model()
    subagent_model = make_main_model()

    from agent.core.graph import get_checkpointer

    logger.info("返回带 backend 的 Agent：thread_id=%s task_kind=%s", thread_id, task_kind)
    # 这里是整套 Agent 能力的装配点。开发调试时建议从这些参数逐个展开：
    # model 决定推理能力；tools 提供业务动作；system_prompt 提供任务规则；
    # subagents 负责分析委派；backend/permissions 决定文件系统边界；
    # middleware 做上下文注入、消息兼容清洗、参数清洗、上下文压缩和异常恢复；
    # skills 提供任务方法论；
    # checkpointer 保存 LangGraph thread state。
    return create_deep_agent(  # 创建一个Agent
        model=main_model,
        tools=[
            web_search,
            request_human_intervention,
            fetch_url,
            hybrid_code_search,
            open_gitee_pull_request,
            publish_gitee_pr_comment,
            get_gitee_pull_request_context,
            get_github_pull_request_context,
            create_gitee_issue,
            publish_gitee_issue_comment,
            get_gitee_issue_context,
            open_github_pull_request,
            publish_github_pr_comment,
            create_github_issue,
            publish_github_issue_comment,
            get_github_actions_status,
            get_github_issue_context,
            rerun_github_actions,
            cancel_github_actions,
            load_default_review_rules,
            get_review_diff_summary,
            validate_review_finding_location,
            add_review_finding,
            list_review_findings,
        ],
        system_prompt=get_system_prompt(task_kind),
        subagents=[_general_purpose_subagent(subagent_model), _code_reviewer_subagent(subagent_model)],
        # DeepAgents 0.7+ 要求传入已初始化的 BackendProtocol 实例，不能再传
        # 0.6.x 时代的 backend factory。agent_backend 已经包含本地工作区和
        # /memories/ 的 StoreBackend 路由，因此直接复用即可。
        backend=agent_backend,
        # DeepAgents 0.7 的 FilesystemMiddleware 不允许 execute-capable
        # SandboxBackend 同时使用工具级 permissions。LocalShellBackend 已经
        # 在 Windows 工作区解析、命令执行和写入策略层完成边界控制，因此这里
        # 不再传入 DeepAgents 0.6 时代的 permissions 参数。
        # 精简对话工具 compact_conversation
        # 你有一个名为 compact_conversation 的工具可用。该工具会刷新你的上下文窗口，以减少上下文膨胀和成本。
        #
        # 在以下情况中应使用该工具：
        #
        # 用户要求转到一个全新的任务，而之前的上下文可能与此无关。
        #
        # 你已经完成结果的提取或合成，不再需要之前的工作上下文时。
        middleware=[
            # write_todos 由 TodoListMiddleware 注入；系统提示要求每轮任务跟踪此 Todo。
            TodoListMiddleware(),
            ContextInjectionMiddleware(),
            MessageSanitizeMiddleware(),
            SanitizeToolInputsMiddleware(backend=backend),
            create_summarization_tool_middleware(main_model, agent_backend),
            ModelCallLimitMiddleware(run_limit=MODEL_CALL_RECURSION_LIMIT, exit_behavior="end"),
            ToolErrorMiddleware(backend=backend),
        ],
        skills=["/skills/"],
        # memory 只声明 Agent 可以访问的长期记忆文件路径；
        # 具体读写会通过上面的 /memories/ StoreBackend 路由完成。
        memory=memory_paths,

        # checkpointer 是聊天历史、工具消息和图状态的权威来源。
        # 前端历史恢复应读取 checkpoint，不应读取业务 Store 事件。
        checkpointer=get_checkpointer(),

        # store 传给 DeepAgents/中间件，主要服务长期记忆等业务数据，不参与前端历史展示。
        store=langgraph_store,
    ).with_config(config)
