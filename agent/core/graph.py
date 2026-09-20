from __future__ import annotations

from agent.core.persistence import make_business_store, make_checkpointer, make_langgraph_store
from agent.core.settings import CHECKPOINT_DB_PATH, LANGGRAPH_STORE_DB_PATH, STORE_DB_PATH
from agent.core.task_intent import TaskKind
from agent.store import LocalSqliteStore

_store: LocalSqliteStore | None = None
_checkpointer = None
_langgraph_store = None


def get_store() -> LocalSqliteStore:
    """获取业务 SQLite Store。

    Store 保存的是平台业务数据，例如任务列表、仓库地址、PR URL、review findings。
    它和 LangGraph checkpoint 是两套数据：
    - Store 面向页面和业务查询。
    - Checkpoint 面向 Agent 的 thread state 和消息历史恢复。
    """

    global _store
    if _store is None:
        _store = make_business_store()
    return _store


def get_checkpointer():
    """获取 LangGraph SQLite checkpointer。

    checkpointer 负责保存 Agent 运行过程中的 messages、工具调用状态和 thread state。
    本地部署版显式把 checkpoint 写到 data/checkpoints.sqlite，方便本地验证重启恢复。
    """

    global _checkpointer
    if _checkpointer is None:
        _checkpointer = make_checkpointer(CHECKPOINT_DB_PATH)
    return _checkpointer


def get_langgraph_store():
    """获取 DeepAgents StoreBackend 使用的 LangGraph SQLite Store。

    业务数据仍然写入 `store.sqlite`，checkpoint 仍然写入 `checkpoints.sqlite`。
    这里的 store 专门服务 `/memories/...` 长期记忆文件，内部表结构由
    LangGraph Store 自己创建和维护。
    """

    global _langgraph_store
    if _langgraph_store is None:
        _langgraph_store = make_langgraph_store(LANGGRAPH_STORE_DB_PATH)
    return _langgraph_store


def build_agent(thread_id: str, task_kind: TaskKind = "coding"):
    """构建一个绑定 thread_id 的 DeepAgent 兼容入口。

    真实创建逻辑已经迁移到 `agent.server.get_agent(config)`，这样项目结构更接近
    open-swe 的 LangGraph Server 入口。保留这个函数是为了兼容项目脚本和已有
    FastAPI runtime 调用点。
    """

    from agent.server import get_agent

    return get_agent(
        {
            "configurable": {
                "thread_id": thread_id,
                "task_kind": task_kind,
                "__is_for_execution__": True,
            }
        }
    )
