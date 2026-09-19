from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.core.graph import get_store
from agent.core.middleware import run_limits
from agent.core.middleware.run_limits import AgentRunLimitExceeded, AgentRunLimits
from agent.core.streaming_runtime import run_agent_with_event_stream


class ToolLimitStream:
    """构造会触发工具调用上限的官方事件流。"""

    def __iter__(self):
        for _ in range(2):
            yield {
                "method": "tools",
                "params": {"data": {"event": "tool-started", "tool_name": "ls"}},
            }

    @property
    def output(self) -> dict[str, list]:
        return {"messages": []}


class ToolLimitAgent:
    def stream_events(self, *args, **kwargs) -> ToolLimitStream:
        return ToolLimitStream()


def main() -> None:
    """验证 Agent Loop 工具保护上限会中止运行并写入前端事件。"""

    original_get_env = run_limits.get_env

    def fake_get_env_empty(name: str, default: str = "") -> str:
        del name
        return default

    run_limits.get_env = fake_get_env_empty
    try:
        coding_limits = AgentRunLimits.from_env("coding")
        if coding_limits.max_tool_calls != 300 or coding_limits.max_seconds != 1800:
            raise AssertionError(f"coding 默认阈值不正确：{coding_limits}")

        qa_limits = AgentRunLimits.from_env("qa")
        if qa_limits.max_tool_calls != 60 or qa_limits.max_seconds != 600:
            raise AssertionError(f"qa 默认阈值不正确：{qa_limits}")

        def fake_get_env_limit(name: str, default: str = "") -> str:
            if name == "AGENT_MAX_TOOL_CALLS":
                return "1"
            return default

        run_limits.get_env = fake_get_env_limit
        thread_id = f"limit-test-{uuid4()}"
        run_id = f"run-{uuid4()}"
        try:
            run_agent_with_event_stream(agent=ToolLimitAgent(), thread_id=thread_id, run_id=run_id, content="test")
        except AgentRunLimitExceeded:
            pass
        else:
            raise AssertionError("超过工具调用上限时应抛出 AgentRunLimitExceeded")

        events = get_store().list_run_events(thread_id)
        titles = {f"{event['title']}:{event['status']}" for event in events}
        if "达到运行保护上限:error" not in titles:
            raise AssertionError(f"缺少运行保护上限事件，实际: {titles}")

        def fake_get_env_coding(name: str, default: str = "") -> str:
            values = {
                "AGENT_MAX_TOOL_CALLS": "1",
                "AGENT_CODING_MAX_TOOL_CALLS": "345",
                "AGENT_CODING_MAX_SECONDS": "2345",
            }
            return values.get(name, default)

        run_limits.get_env = fake_get_env_coding
        coding_override = AgentRunLimits.from_env("coding")
        if coding_override.max_tool_calls != 345 or coding_override.max_seconds != 2345:
            raise AssertionError(f"coding 专用阈值覆盖失败：{coding_override}")
    finally:
        run_limits.get_env = original_get_env
    print("run limits verification passed")


if __name__ == "__main__":
    main()
