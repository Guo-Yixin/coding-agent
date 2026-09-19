from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.core.events import record_event
from agent.core.graph import get_store


def main() -> None:
    """并发写入 run_events，验证 SQLite Store 不再出现事务状态错误。

    前端 SSE 会持续读 Store，后台 Agent 和工具会持续写 Store。
    这个脚本用多线程模拟高频事件写入，专门防止
    `cannot commit - no transaction is active` 这类回归。
    """

    thread_id = f"sqlite-concurrency-{uuid4()}"
    get_store().upsert_thread(
        thread_id=thread_id,
        title="SQLite concurrency verification",
        latest_run_status="running",
    )

    def write_event(index: int) -> None:
        record_event(
            thread_id,
            f"event:{index}",
            "并发写入验证",
            kind="other",
            status="completed",
            detail=str(index),
        )

    with ThreadPoolExecutor(max_workers=12) as executor:
        list(executor.map(write_event, range(120)))

    events = get_store().list_run_events(thread_id)
    if len(events) != 120:
        raise AssertionError(f"并发事件数量不正确：expected=120 actual={len(events)}")
    print("sqlite concurrency verification passed")


if __name__ == "__main__":
    main()
