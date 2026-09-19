from __future__ import annotations

"""仓库级长期记忆写回中间件。

这个中间件负责在整轮 Agent 结束后，尝试把“稳定、可复用”的任务结论写回
仓库级记忆。它的定位是兜底机制：

1. 主要写回路径在 runtime.py。runtime.py 更清楚当前任务类型、最终输出内容、
   分支和 PR 等运行结果，因此成功任务优先由 runtime.py 主动调用
   repo_memory_update.py。
2. 本中间件在 after_agent/aafter_agent 阶段再次尝试提取最后一条 assistant
   消息，避免未来新增运行路径时忘记写回仓库记忆。
3. 本中间件不会把整段对话原样写入记忆，只把最终 assistant 消息交给
   repo_memory_update.py 做提炼和结构化更新。

安全边界：
- 如果最终消息疑似包含 `.env`、`.secrets`、api_key、私钥等敏感信息，
  直接跳过写入。
- 写入前会经过 mask_token 脱敏检查，避免把访问令牌沉淀到长期记忆中。
"""

import logging
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langgraph.config import get_config

from agent.core.graph import get_langgraph_store
from agent.core.repo_memory_update import RepoMemoryUpdate, update_repo_memory_from_text
from agent.tools.gitee_api import mask_token, parse_gitee_repo_url

logger = logging.getLogger("agent.run.middleware.memory_update")

# 长期记忆是跨会话复用的内容，一旦写入错误或敏感信息，后续任务都会受到影响。
# 这里列出最常见的敏感标记，只要最终 assistant 消息中出现这些内容，就跳过写回。
SENSITIVE_MARKERS = (".env", ".secrets", "api_key", "apikey", "private key", "私钥")


def _repo_url_from_config() -> str | None:
    """从 LangGraph 运行时配置中读取 repo_url。

    Runtime 对象本身没有 config 字段（见 langgraph.runtime.Runtime），
    必须通过 langgraph.config.get_config() 才能访问 RunnableConfig。
    """
    configurable = get_config().get("configurable", {})
    repo_url = configurable.get("repo_url") if isinstance(configurable, dict) else None
    return repo_url if isinstance(repo_url, str) and repo_url.strip() else None


def _task_kind_from_config() -> str:
    """从运行配置中读取任务类型。

    task_kind 用于 repo_memory_update.py 判断这条记忆来自哪类任务，例如：
    - planning：方案任务，适合沉淀设计结论和风险点。
    - coding：编码任务，适合沉淀修改模块、测试命令、分支和 PR。
    - qa/analysis/review：适合沉淀仓库结构、审查结论或排查经验。
    """
    configurable = get_config().get("configurable", {})
    return str(configurable.get("task_kind", "unknown")) if isinstance(configurable, dict) else "unknown"


def _last_assistant_text(state: AgentState) -> str:
    """从 AgentState 中提取最后一条 assistant/AI 消息文本。

    为什么只取最后一条 assistant 消息：
    - 中间的 assistant 消息经常是过程推理或阶段性描述，不一定稳定。
    - 最后一条 assistant 消息通常是面向用户的总结，最适合提炼长期记忆。

    为什么同时兼容 str 和 list：
    - 不同模型、不同流式事件模式下，LangChain message.content 可能是普通字符串。
    - 也可能是分块列表，例如 `[{"type": "text", "text": "..."}]`。
    - 这里统一抽取其中的文本部分，避免因为消息结构差异导致记忆无法更新。
    """
    for message in reversed(state.get("messages", [])):
        message_type = str(getattr(message, "type", "") or "").lower()
        if message_type not in {"ai", "assistant"}:
            continue
        content = getattr(message, "content", "")
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    # LangChain/OpenAI 风格的分块内容通常把文本放在 text 或 content 字段中。
                    text = item.get("text") or item.get("content")
                    if text:
                        parts.append(str(text))
            text = "\n".join(part.strip() for part in parts if part and part.strip()).strip()
            if text:
                return text
    return ""


def _message_type_summary(state: AgentState) -> str:
    """记录 after_agent 中最后几条消息类型，便于排查框架状态结构。

    当记忆没有写回时，日志里只输出消息类型摘要，不输出完整消息内容。
    这样既方便排查“最后一条消息是不是 assistant”，又避免把用户代码或敏感信息写进日志。
    """

    messages = list(state.get("messages", []))
    tail = []
    for message in messages[-5:]:
        tail.append(str(getattr(message, "type", type(message).__name__)))
    return f"count={len(messages)} tail={tail}"


class MemoryUpdateMiddleware(AgentMiddleware):
    """在整轮 Agent 结束后把稳定结论追加到仓库记忆。

    当前项目已经使用仓库维度的记忆文件：
    `/memories/{owner}/{repo}.md`。

    本中间件不直接拼接 Markdown，也不自己决定写入哪些部分；
    它只负责从 AgentState 中提取最终 assistant 文本，然后交给
    `repo_memory_update.py` 做清洗、提炼、去重和结构化写回。

    注意：这是兜底写回。正常情况下 runtime.py 会在任务成功结束后主动更新记忆。
    """

    state_schema = AgentState

    def after_agent(self, state: AgentState, runtime: Any) -> dict[str, Any] | None:
        # 1. 当前项目的记忆是“仓库级”的，所以必须先拿到 repo_url。
        #    如果没有 repo_url，就无法确定写入哪个 owner/repo 的 namespace。
        repo_url = _repo_url_from_config()
        if not repo_url:
            logger.warning("MemoryUpdateMiddleware: get_config 中没有 repo_url，跳过记忆更新")
            return None

        # 2. 提取最后一条 assistant 消息。
        #    这里不读取全部消息，避免把工具过程、测试日志和中间猜测写入长期记忆。
        final_text = _last_assistant_text(state)
        if not final_text or any(marker in mask_token(final_text).lower() for marker in SENSITIVE_MARKERS):
            # 3. 如果没有最终文本，或者最终文本疑似包含敏感信息，则跳过写回。
            #    这一步宁可少写，也不能把 token、私钥、.env 内容写入长期记忆。
            logger.info(
                "MemoryUpdateMiddleware: 助手消息无可写入的稳定结论，跳过更新：%s",
                _message_type_summary(state),
            )
            return None

        # 4. 解析 Gitee 仓库地址，并委托 repo_memory_update.py 执行真正的记忆更新。
        #    parse_gitee_repo_url 会保证这里只处理 Gitee 仓库，符合当前项目范围。
        repo = parse_gitee_repo_url(repo_url)
        update_repo_memory_from_text(
            store=get_langgraph_store(),
            repo=repo,
            update=RepoMemoryUpdate(task_kind=_task_kind_from_config(), final_text=final_text),
        )
        return None

    async def aafter_agent(self, state: AgentState, runtime: Any) -> dict[str, Any] | None:
        # DeepAgents 可能走同步或异步运行路径。异步钩子复用同步逻辑，保证两条路径行为一致。
        return self.after_agent(state, runtime)
