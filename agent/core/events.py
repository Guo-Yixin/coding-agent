from __future__ import annotations

import logging
import uuid

from agent.core.persistence import make_business_store

_event_store = None
logger = logging.getLogger("agent.run.events")


def _get_event_store():
    """获取专用于事件写入的 Store 实例。

    避免从这里导入 graph.get_store，否则会形成 runtime/graph/tools 的循环导入。
    """

    global _event_store
    if _event_store is None:
        _event_store = make_business_store()
    return _event_store


def record_event(
    thread_id: str,
    key: str,
    title: str,
    *,
    kind: str = "think",
    status: str = "in_progress",
    detail: str | None = None,
    run_id: str | None = None,
) -> None:
    """写入一个可展示在前端的运行步骤。

    这个模块独立于 runtime，避免 tools 导入 runtime 时形成循环依赖。
    """

    try:
        store = _get_event_store()
        if run_id is None:
            latest_run = getattr(store, "get_latest_run", lambda _thread_id: None)(thread_id)
            run_id = str(latest_run["run_id"]) if latest_run and latest_run.get("run_id") else None
        event_id = f"{thread_id}:{run_id}:{key}" if run_id else f"{thread_id}:{key}"
        store.add_run_event(
            event_id=event_id,
            thread_id=thread_id,
            kind=kind,
            title=title,
            status=status,
            detail=detail,
            run_id=run_id,
        )
        append_audit = getattr(store, "append_audit_event", None)
        if append_audit is not None:
            append_audit(
                event_id=str(uuid.uuid4()),
                event_type="run_event",
                thread_id=thread_id,
                run_id=run_id,
                payload={"key": key, "kind": kind, "title": title, "status": status},
            )
    except Exception:
        # 步骤记录只服务于前端展示，不能因为 SQLite 瞬时异常中断真正的 Agent 任务。
        logger.exception("记录运行步骤失败：thread_id=%s key=%s title=%s", thread_id, key, title)
