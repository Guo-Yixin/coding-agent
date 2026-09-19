"""工具运行上下文读取模块。

LangGraph/DeepAgents 调用工具时，会把 thread_id、任务类型等运行期信息放入 configurable。
工具函数本身不适合显式传入这些业务上下文参数，否则模型调用工具时需要理解大量内部字段。
本模块统一从 LangGraph config 中读取上下文，让工具接口保持面向模型的简洁参数。
"""

from __future__ import annotations

from typing import Any

from langgraph.config import get_config

from agent.core.task_intent import TaskKind, is_read_only_task


def get_runtime_configurable() -> dict[str, Any]:
    """读取当前工具调用所属的 LangGraph configurable。
    """

    try:
        # `get_config()` 只有在 LangGraph 正在执行节点或工具时才可用。
        # 如果工具在单元测试或脚本中被直接调用，这里会返回空字典作为降级结果。
        config = get_config()
    except RuntimeError:
        return {}
    configurable = config.get("configurable", {}) if isinstance(config, dict) else {}
    # 防御式校验，避免调用方传入非 dict configurable 导致工具层异常扩散。
    return configurable if isinstance(configurable, dict) else {}


def get_runtime_thread_id() -> str | None:
    """读取当前 thread_id。

    thread_id 是工具写事件、写 Store、更新任务状态时的业务关联键。
    没有 thread_id 时，工具仍应返回可恢复错误，而不是写入无归属的数据。
    """

    value = get_runtime_configurable().get("thread_id")
    return value if isinstance(value, str) and value else None


def get_runtime_task_kind() -> TaskKind:
    """读取当前任务类型，非法值回退为 coding。

    任务类型用于判断当前请求是否允许写操作，例如分析类任务不能直接创建 PR。
    回退为 coding 是为了兼容旧调用链没有传 task_kind 的情况。
    """

    value = get_runtime_configurable().get("task_kind", "coding")
    # 只接受系统已知枚举值，避免模型或外部请求伪造任意任务类型影响权限判断。
    if value in {"coding", "analysis", "planning", "qa", "sync", "inspect"}:
        return value
    return "coding"


def runtime_is_read_only_task() -> bool:
    """判断当前任务是否为只读模式。

    工具层通过这个函数集中复用任务权限规则，避免每个工具各自维护一份判断逻辑。
    """

    return is_read_only_task(get_runtime_task_kind())
