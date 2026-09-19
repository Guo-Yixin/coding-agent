from __future__ import annotations

import logging

from agent.core.settings import STORE_DB_PATH
from agent.store import LocalSqliteStore

_event_store: LocalSqliteStore | None = None
logger = logging.getLogger("agent.run.events")


def _get_event_store() -> LocalSqliteStore:
    """获取专用于事件写入的 Store 实例。

    避免从这里导入 graph.get_store，否则会形成 runtime/graph/tools 的循环导入。
    """

    global _event_store
    if _event_store is None:
        _event_store = LocalSqliteStore(STORE_DB_PATH)
    return _event_store


def record_event(
    thread_id: str,
    key: str,
    title: str,
    *,
    kind: str = "think",
    status: str = "in_progress",
    detail: str | None = None,
) -> None:
    """写入一个可展示在前端的运行步骤。

    这个模块独立于 runtime，避免 tools 导入 runtime 时形成循环依赖。
    """

    try:
        _get_event_store().add_run_event(
            event_id=f"{thread_id}:{key}",
            thread_id=thread_id,
            kind=kind,
            title=title,
            status=status,
            detail=detail,
        )
    except Exception:
        # 步骤记录只服务于前端展示，不能因为 SQLite 瞬时异常中断真正的 Agent 任务。
        logger.exception("记录运行步骤失败：thread_id=%s key=%s title=%s", thread_id, key, title)
