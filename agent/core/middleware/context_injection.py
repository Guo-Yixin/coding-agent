from __future__ import annotations

"""仓库级上下文注入中间件。

这个中间件解决的是“Agent 每一轮都从零开始理解仓库”的问题。

当前项目的仓库长期记忆保存在 LangGraph Store 中，并通过 DeepAgents 的
StoreBackend 暴露为类似 `/memories/{owner}/{repo}.md` 的虚拟文件。
但如果只依赖模型主动去读这个虚拟文件，模型可能会忘记读，或者在复杂任务中
先浪费很多工具调用扫描仓库。因此这里在整轮 Agent 开始前，把仓库标识、
记忆文件路径和已有记忆内容主动注入为一条 SystemMessage。

注意：
1. 这里不修改用户消息，也不替换系统提示词，只是在消息列表最前面追加一份
   “当前仓库上下文”。
2. 这里注入的是长期上下文摘要，不代表真实仓库状态；如果它和文件系统、
   Git 命令、测试输出冲突，Agent 必须以实时工具结果为准。
3. 这里不写入记忆。记忆写回只由 runtime.py 在 coding 任务成功结束后负责。
"""

import logging
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langchain_core.messages import SystemMessage
from langgraph.config import get_config

from agent.core.graph import get_langgraph_store
from agent.core.repo_memory import build_repo_memory_namespace, repo_memory_store_key, repo_memory_virtual_path
from agent.tools.gitee_api import mask_token, parse_gitee_repo_url

logger = logging.getLogger("agent.run.middleware.context_injection")

# 控制注入到模型上下文中的仓库记忆最大长度。
# 仓库记忆是长期积累内容，如果完全注入，复杂仓库可能会显著增加 token 成本。
# 这里保留前 6000 个字符，足够覆盖项目概览、启动命令、测试命令和关键模块。
MAX_REPO_MEMORY_CHARS = 6000


def _repo_url_and_content_from_config() -> tuple[str | None, str | None]:
    """从 LangGraph 运行时配置中读取 repo_url 和缓存的记忆内容。

    Runtime 对象本身没有 config 字段（见 langgraph.runtime.Runtime），
    必须通过 langgraph.config.get_config() 才能访问 RunnableConfig。

    返回值：
    - repo_url：当前任务绑定的 Gitee 仓库地址。
    - memory_content：runtime.py 预先读取并放入 configurable 的仓库记忆内容。

    为什么优先读取 `_repo_memory_content`：
    runtime.py 在准备任务时通常已经完成仓库解析和记忆初始化。如果这里能够
    直接复用缓存内容，就可以避免中间件再次访问 SQLite Store。只有缓存缺失时，
    before_agent 才会走兜底读取。
    """
    configurable = get_config().get("configurable", {})
    if not isinstance(configurable, dict):
        return None, None
    repo_url = configurable.get("repo_url")
    repo_url = repo_url if isinstance(repo_url, str) and repo_url.strip() else None
    memory_content = configurable.get("_repo_memory_content")
    memory_content = str(memory_content).strip() if isinstance(memory_content, str) and memory_content.strip() else None
    return repo_url, memory_content


def _build_repo_context_notice(
    *,
    owner: str,
    repo: str,
    repo_url: str,
    memory_content: str | None,
) -> str:
    """生成仓库上下文的 SystemMessage 文本。

    无论记忆文件是否存在，都至少注入仓库标识和记忆文件路径，让 Agent 知道
    自己在哪个仓库工作、可以从哪里读取长期上下文。这借鉴了 erp_harness01
    ContextInjectionMiddleware 的模式——基础上下文始终注入，不因文件不存在就跳过。

    这条 SystemMessage 只用于“提示模型当前仓库背景”，不作为权限边界。
    真正的读写边界仍然由 LocalShellBackend、工具参数清洗中间件和权限校验代码控制。
    """
    memory_path = repo_memory_virtual_path(owner, repo)
    lines = [
        "【当前仓库上下文】",
        f"仓库地址：{repo_url}",
        f"owner/repo：{owner}/{repo}",
        f"仓库记忆文件：{memory_path}",
    ]
    if memory_content:
        trimmed = memory_content.strip()
        if len(trimmed) > MAX_REPO_MEMORY_CHARS:
            # 只截断注入给模型的文本，不会修改 Store 中保存的原始记忆内容。
            trimmed = trimmed[:MAX_REPO_MEMORY_CHARS].rstrip() + "\n\n...（仓库记忆已截断）"
        lines += [
            "",
            f"仓库记忆内容（来自 `{memory_path}`，仅作为长期上下文参考。",
            "如果它与真实仓库文件、Git 状态或命令输出冲突，必须以真实仓库为准）：",
            "",
            mask_token(trimmed),
        ]
    else:
        lines += [
            "",
            # 没有记忆时也要告诉模型“应该在哪里沉淀记忆”。
            # 这样模型在需要时可以通过 backend 暴露的文件能力读取或更新虚拟记忆文件。
            "该仓库的记忆文件尚未创建。你可以通过 write_file 将仓库的结构、",
            "技术栈、启动命令、测试命令等稳定结论写入该文件，供后续任务参考。",
        ]
    return "\n".join(lines)


class ContextInjectionMiddleware(AgentMiddleware):
    """在整轮 Agent 开始前注入仓库级长期记忆上下文。

    记忆只在 `before_agent/abefore_agent` 注入一次，避免在每次模型调用前重复增加
    token 成本。`memory=[repo_memory_virtual_path(owner, repo)]` 仍然保留，便于 Agent
    主动读写当前仓库自己的记忆文件；
    本中间件负责让模型一开始就看到核心仓库上下文。

    即使仓库记忆尚未创建，也会注入基础仓库标识和文件路径，
    参考 erp_harness01 ContextInjectionMiddleware 的模式。
    """

    state_schema = AgentState

    def before_agent(self, state: AgentState, runtime: Any) -> dict[str, Any] | None:
        # 1. 从 LangGraph RunnableConfig 读取当前仓库地址和预加载的仓库记忆。
        #    这里不直接使用 runtime，是因为当前 LangGraph Runtime 不暴露 config 字段。
        repo_url, memory_content = _repo_url_and_content_from_config()
        if not repo_url:
            # 没有 repo_url 说明本轮任务没有绑定 Gitee 仓库。
            # 这种情况下不注入仓库上下文，避免给问答类或系统类任务制造错误背景。
            return None

        # 2. 解析 Gitee 仓库地址，得到 owner/repo。
        #    parse_gitee_repo_url 只接受 Gitee 地址，符合当前项目“只支持 Gitee”的规则。
        repo = parse_gitee_repo_url(repo_url)
        need_fallback_read = memory_content is None
        if need_fallback_read:
            # 3. 兜底：缓存的记忆内容不存在时，直接从 Store 读取。
            #    正常路径中 runtime.py 会提前初始化并缓存记忆；这里保留兜底逻辑，
            #    是为了避免未来新增运行入口时忘记把 `_repo_memory_content` 放入 config。
            namespace = build_repo_memory_namespace(repo.owner, repo.repo)
            item = get_langgraph_store().get(namespace, repo_memory_store_key(repo.owner, repo.repo))
            memory_content = str(item.value.get("content") or "").strip() if item is not None else None

        if memory_content:
            logger.info(
                "注入仓库记忆上下文：repo=%s/%s length=%s",
                repo.owner, repo.repo, len(memory_content),
            )
        else:
            logger.info(
                "仓库记忆尚不存在，注入基础上下文：repo=%s/%s",
                repo.owner, repo.repo,
            )

        # 4. 组装面向模型的仓库上下文。这里会自动脱敏 token，防止日志或模型上下文泄露凭证。
        notice = _build_repo_context_notice(
            owner=repo.owner,
            repo=repo.repo,
            repo_url=repo.clone_url,
            memory_content=memory_content,
        )
        # 5. 把仓库上下文插入消息列表最前面。
        #    使用 SystemMessage 是为了让模型把它当作高优先级上下文，而不是普通用户输入。
        messages = list(state.get("messages", []))
        return {"messages": [SystemMessage(content=notice), *messages]}

    async def abefore_agent(self, state: AgentState, runtime: Any) -> dict[str, Any] | None:
        # DeepAgents 可能走同步或异步运行路径。异步钩子复用同步逻辑，保证两条路径行为一致。
        return self.before_agent(state, runtime)
