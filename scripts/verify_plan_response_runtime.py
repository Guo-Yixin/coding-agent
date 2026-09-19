from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.core import runtime
from agent.core.graph import get_store


class FakeAgent:
    """模拟 DeepAgent，只返回一条技术方案消息。"""


CAPTURED_CONTENTS: list[str] = []


def fake_build_agent_for_runtime(*, thread_id: str, task_kind: str, repo_url: str | None = None):
    del thread_id, task_kind, repo_url
    return FakeAgent()


def fake_run_agent_with_event_stream(
    *,
    agent,
    thread_id: str,
    run_id: str = "fake-run",
    content: str,
    task_kind: str | None = None,
    event_sink=None,
):
    del agent, thread_id, run_id, task_kind, event_sink
    CAPTURED_CONTENTS.append(content)
    return {
        "messages": [
            {
                "type": "ai",
                "content": "## 技术方案\n\n1. 读取现有数据存储。\n2. 设计 SQLite DAO。",
            },
            {
                "type": "ai",
                "content": "是否确认实施该方案？",
            },
        ]
    }


def main() -> None:
    original_build_agent_for_runtime = runtime._build_agent_for_runtime
    original_runner = runtime.run_agent_with_event_stream
    original_latest_plan = runtime._latest_confirmable_plan_message
    runtime._build_agent_for_runtime = fake_build_agent_for_runtime
    runtime.run_agent_with_event_stream = fake_run_agent_with_event_stream
    thread_id = f"plan-response-runtime-{uuid4()}"
    try:
        result = runtime.run_plan_response_task(
            repo_url="https://gitee.com/clumsypsc/test_coding_repo",
            prompt="我想把这个项目的数据存储改为：sqlite数据库",
            thread_id=thread_id,
        )
        if result["status"] != "completed":
            raise AssertionError(f"方案响应任务应直接 completed，实际：{result['status']}")

        store = get_store()
        if store.list_thread_plans(thread_id):
            raise AssertionError("方案响应任务不应该写入 thread_plans")
        if store.list_thread_messages(thread_id):
            raise AssertionError("方案响应任务不应该再写入 Store.thread_messages")
        thread = store.get_thread(thread_id)
        if not thread or thread.get("user_prompt") != "我想把这个项目的数据存储改为：sqlite数据库":
            raise AssertionError(f"方案响应任务应保留本轮用户输入用于展示，实际：{thread}")

        content = runtime._extract_best_plan_text(fake_run_agent_with_event_stream(
            agent=FakeAgent(),
            thread_id=thread_id,
            content="",
            task_kind="planning",
        )["messages"])

        # 正常运行时待确认方案来自 checkpoint。这里直接模拟 checkpoint 返回值，
        # 避免验证脚本重新依赖 Store.thread_messages。
        runtime._latest_confirmable_plan_message = lambda _: {
            "message_id": f"checkpoint-plan:{thread_id}",
            "thread_id": thread_id,
            "run_id": None,
            "author": "agent",
            "content": content,
            "metadata": {
                "task_kind": "planning",
                "awaiting_confirmation": True,
                "source_prompt": "我想把这个项目的数据存储改为：sqlite数据库",
                "source": "checkpoint",
            },
        }

        revision_result = runtime.run_agent_task(
            repo_url="https://gitee.com/clumsypsc/test_coding_repo",
            prompt="一个用户只能授予一个角色，再生成新的方案",
            thread_id=thread_id,
        )
        if revision_result["status"] != "completed":
            raise AssertionError(f"方案修订任务应 completed，实际：{revision_result['status']}")
        thread = store.get_thread(thread_id)
        if not thread or thread.get("user_prompt") != "一个用户只能授予一个角色，再生成新的方案":
            raise AssertionError(f"方案修订任务应展示本轮修订输入，实际：{thread}")
        if not any("上一版技术方案" in item and "用户新的修改要求" in item for item in CAPTURED_CONTENTS):
            raise AssertionError("方案修订任务没有把上一版方案和本次修改要求传给模型")

        if store.list_thread_messages(thread_id):
            raise AssertionError("方案修订后也不应该写入 Store.thread_messages")

        captured_before_qa = len(CAPTURED_CONTENTS)
        qa_result = runtime.run_agent_task(
            repo_url="https://gitee.com/clumsypsc/test_coding_repo",
            prompt="当前项目的记忆文件内容是什么？",
            thread_id=thread_id,
        )
        if qa_result["status"] != "completed":
            raise AssertionError(f"普通问答任务应 completed，实际：{qa_result['status']}")
        qa_content = CAPTURED_CONTENTS[captured_before_qa]
        if "上一版技术方案" in qa_content or "用户新的修改要求" in qa_content:
            raise AssertionError("普通问答不应被包装成上一版方案修订任务")
        if "是否确认实施该方案" in qa_content:
            raise AssertionError("普通问答不应注入方案确认提示")
    finally:
        runtime._build_agent_for_runtime = original_build_agent_for_runtime
        runtime.run_agent_with_event_stream = original_runner
        runtime._latest_confirmable_plan_message = original_latest_plan

    print("plan response runtime verification passed")


if __name__ == "__main__":
    main()
