"""Agent 单轮运行保护阈值。

长任务运行时需要防止两类问题：
1. 模型不断调用工具，导致费用和耗时失控；
2. 某些任务卡在长时间等待或重复循环，无法及时返回。

本模块提供轻量级运行限制：按任务类型配置最大工具调用次数和最大运行秒数。
它不依赖具体模型供应商，也不解析完整 token 计费信息，只基于 LangGraph 事件流做稳定的运行保护。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from agent.env_utils import get_env


TASK_KIND_DEFAULT_LIMITS: dict[str, tuple[int, int]] = {
    # qa/inspect/sync 通常应快速完成，默认阈值更保守。
    "qa": (60, 600),
    "inspect": (30, 300),
    "sync": (40, 300),
    # analysis/planning 需要更多读取和推理，但原则上不应长时间执行写操作。
    "analysis": (120, 900),
    "planning": (120, 900),
    # review 需要读取规则、PR 上下文和 diff，通常比 analysis 略重，但不应进入长时间编码循环。
    "review": (180, 1200),
    # coding 任务通常包含读代码、编辑、测试、提交等步骤，需要更高工具调用上限。
    "coding": (300, 1800),
}

# 兜底默认值：当 task_kind 未命中上方配置时使用。
DEFAULT_MAX_TOOL_CALLS = 240
DEFAULT_MAX_SECONDS = 1800


class AgentRunLimitExceeded(RuntimeError):
    """Agent 本轮运行超过保护上限。

    runtime 捕获该异常后应停止继续消费事件流，并向用户返回明确的超限原因。
    """


@dataclass
class AgentRunLimits:
    """Agent Loop 的轻量保护阈值。

    open-swe 的模型循环主要由 `ModelCallLimitMiddleware` 保护。CODING
    运行在 FastAPI 内，这里只保留更可靠的时间和工具调用上限。不要用 raw event
    里的 `message-start` 统计模型调用次数，因为 DeepAgents 的流式片段、子 Agent
    和中间 assistant message 都可能产生该事件，容易误判。
    """

    max_tool_calls: int
    max_seconds: int
    task_kind: str = "default"

    @classmethod
    def from_env(cls, task_kind: str | None = None) -> "AgentRunLimits":
        """按任务类型读取运行保护阈值。

        配置优先级：
        1. `AGENT_<TASK_KIND>_MAX_TOOL_CALLS` / `AGENT_<TASK_KIND>_MAX_SECONDS`
        2. `AGENT_MAX_TOOL_CALLS` / `AGENT_MAX_SECONDS`
        3. 代码内置的任务类型默认值

        这样复杂 coding 任务可以使用更高阈值，同时 qa、inspect、sync 仍保持保守。
        """

        # 任务类型统一转小写，用于匹配默认配置和拼接环境变量前缀。
        normalized_kind = (task_kind or "default").lower()
        default_tool_calls, default_seconds = TASK_KIND_DEFAULT_LIMITS.get(
            normalized_kind,
            (DEFAULT_MAX_TOOL_CALLS, DEFAULT_MAX_SECONDS),
        )
        env_prefix = f"AGENT_{normalized_kind.upper()}_"
        return cls(
            max_tool_calls=int(
                # 先读任务类型专属配置，再读全局配置，最后落到代码默认值。
                get_env(
                    f"{env_prefix}MAX_TOOL_CALLS",
                    get_env("AGENT_MAX_TOOL_CALLS", str(default_tool_calls)),
                )
            ),
            max_seconds=int(
                # 秒级限制用于覆盖模型不再调用工具但整体任务仍长时间运行的情况。
                get_env(
                    f"{env_prefix}MAX_SECONDS",
                    get_env("AGENT_MAX_SECONDS", str(default_seconds)),
                )
            ),
            task_kind=normalized_kind,
        )


class AgentRunLimitTracker:
    """根据 LangGraph 事件流统计本轮 Agent 运行规模。

    Tracker 是单轮任务级对象，不应跨 thread 或跨 run 复用。
    每次创建时记录开始时间，并随着事件流推进累计工具调用次数。
    """

    def __init__(self, limits: AgentRunLimits | None = None, task_kind: str | None = None):
        # 调用方可以直接传入 limits，便于测试；正常运行时按 task_kind 从环境变量加载。
        self.limits = limits or AgentRunLimits.from_env(task_kind)
        self.started_at = time.monotonic()
        self.tool_calls = 0

    def observe_event(self, event: Any) -> None:
        """读取一个 raw event 并检查是否超过限制。

        Args:
            event: LangGraph 流式执行产生的原始事件。

        Raises:
            AgentRunLimitExceeded: 运行时长或工具调用次数超过当前阈值。
        """

        # 每个事件到达时都先检查时间，避免没有工具调用的长时间运行绕过限制。
        self._check_time()
        if not isinstance(event, dict):
            return

        method = event.get("method")
        if method in {"tool_calls", "tools"}:
            payload = self._first_payload(event)
            event_name = payload.get("event") if isinstance(payload, dict) else None
            if method == "tool_calls" or event_name == "tool-started":
                # 兼容不同事件形态：有的流直接用 tool_calls，有的在 tools 事件里标记 tool-started。
                self.tool_calls += 1
                self._check_tool_calls()

    def _first_payload(self, event: dict[str, Any]) -> Any:
        """从 LangGraph 事件中提取第一个 payload。

        不同版本或不同节点输出的 `params.data` 可能是 tuple、list 或单个对象。
        这里只取第一个 payload，用于读取工具事件名称。
        """

        params = event.get("params")
        if not isinstance(params, dict):
            return None
        data = params.get("data")
        if isinstance(data, tuple):
            return data[0] if data else None
        if isinstance(data, list):
            return data[0] if data else None
        return data

    def _check_time(self) -> None:
        """检查当前运行耗时是否超过阈值。"""

        elapsed = time.monotonic() - self.started_at
        if elapsed > self.limits.max_seconds:
            raise AgentRunLimitExceeded(
                f"本轮运行已超过 {self.limits.max_seconds} 秒保护上限"
                f"（任务类型：{self.limits.task_kind}）"
            )

    def _check_tool_calls(self) -> None:
        """检查工具调用次数是否超过阈值。"""

        if self.tool_calls > self.limits.max_tool_calls:
            raise AgentRunLimitExceeded(
                f"本轮工具调用已超过 {self.limits.max_tool_calls} 次保护上限"
                f"（任务类型：{self.limits.task_kind}）。"
                "复杂开发任务可以提高 AGENT_CODING_MAX_TOOL_CALLS，"
                "或让智能体分阶段继续完成 Git 提交、推送和 Pull Request。"
            )
