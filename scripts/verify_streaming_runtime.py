from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.core.graph import get_store
from agent.core.streaming_runtime import run_agent_with_event_stream


class FakeStream:
    """模拟官方 `stream_events(version="v3")` 返回的同步流对象。

    这个验证脚本不访问真实模型，只检查我们自己的桥接层是否能把
    raw messages、tool_calls、subagents 三类事件写入 SQLite run_events。
    """

    def __iter__(self):
        yield {
            "method": "messages",
            "params": {
                "namespace": (),
                "data": [
                    {
                        "event": "content-block-delta",
                        "delta": {"type": "text-delta", "text": "正在"},
                    }
                ],
            },
        }
        yield {
            "method": "messages",
            "params": {
                "namespace": (),
                "data": [
                    {
                        "event": "content-block-delta",
                        "delta": {"type": "text-delta", "text": "分析任务"},
                    }
                ],
            },
        }
        yield {
            "method": "tool_calls",
            "params": {
                "data": {
                    "id": "todos-1",
                    "tool_name": "write_todos",
                    "input": {
                        "todos": [
                            {"content": "读取仓库上下文", "status": "completed"},
                            {"content": "归纳目录结构", "status": "in_progress"},
                        ]
                    },
                    "completed": True,
                    "error": None,
                }
            },
        }
        yield {
            "method": "subagents",
            "params": {"data": {"name": "reviewer", "status": "completed", "path": ["reviewer"]}},
        }

    @property
    def output(self) -> dict[str, list]:
        return {"messages": []}


class FakeAgent:
    """提供和 DeepAgent 一样的 stream_events 方法，避免验证时消耗模型。"""

    def stream_events(self, *args, **kwargs) -> FakeStream:
        return FakeStream()


def main() -> None:
    thread_id = f"stream-test-{uuid4()}"
    run_id = f"run-{uuid4()}"
    run_agent_with_event_stream(agent=FakeAgent(), thread_id=thread_id, run_id=run_id, content="test")
    events = get_store().list_run_events(thread_id)
    event_ids = {event["id"] for event in events}
    if f"{thread_id}:stream:{run_id}:assistant:1" not in event_ids:
        raise AssertionError(f"正文事件 id 未按 run_id 分组，实际事件 id：{sorted(event_ids)}")
    if f"{thread_id}:todos:{run_id}:todos-1" not in event_ids:
        raise AssertionError(f"任务计划事件 id 未按 run_id 分组，实际事件 id：{sorted(event_ids)}")
    titles = [f"{event['title']}:{event['status']}" for event in events]
    expected = {
        "调用 deepseek-v4-pro:completed",
        "正在生成内容:in_progress",
        "子智能体：reviewer:completed",
    }
    expected.add("任务清单:completed")
    missing = expected.difference(titles)
    if missing:
        raise AssertionError(f"streaming runtime 验证失败，缺少事件：{sorted(missing)}，实际事件：{titles}")
    if any(title.startswith("智能体输出 ") for title in titles):
        raise AssertionError(f"不应该再生成智能体输出折叠事件，实际事件：{titles}")
    print("streaming runtime verification passed")


if __name__ == "__main__":
    main()
