from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.api import dashboard_routes
from agent.core.checkpoint_history import _extract_user_prompt


def _visible_text(messages: list[dict]) -> str:
    """把前端消息结构中的正文拼接出来，便于测试断言。"""

    return "\n".join(
        chunk["text"]
        for message in messages
        for chunk in message.get("chunks", [])
        if chunk.get("kind") == "text"
    )


def main() -> None:
    """验证 dashboard 历史消息只来自 checkpoint，并且不再过滤 assistant 文本语言。"""

    original_visible_checkpoint_messages = dashboard_routes.visible_checkpoint_messages

    try:
        dashboard_routes.visible_checkpoint_messages = lambda thread_id: [
            {
                "message_id": "checkpoint-u1",
                "author": "user",
                "content": "先帮我分析目录结构",
                "source": "checkpoint",
            },
            {
                "message_id": "checkpoint-a1",
                "author": "agent",
                "content": (
                    "SESSION INTENT\n\n"
                    "Completed implementations:\n"
                    "1. Initial health endpoint (`GET /health`).\n\n"
                    "## 中文结果\n"
                    "项目入口是 `main.py`。"
                ),
                "source": "checkpoint",
            },
        ]

        thread = {
            "thread_id": "dashboard-message-test",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:10+00:00",
            "title": "Store 标题不应该覆盖 checkpoint",
            "user_prompt": "Store 用户输入不应该展示",
            "repo_url": "https://gitee.com/clumsypsc/test_coding_repo",
            "latest_run_status": "completed",
            "latest_run": None,
            "run_events": [
                {
                    "id": "dashboard-message-test:todos:1",
                    "kind": "todo",
                    "title": "任务清单",
                    "status": "completed",
                    "detail": '{"todos":[{"content":"不应该从 run_events 进入历史","status":"completed"}]}',
                }
            ],
            "messages": [
                {
                    "message_id": "store-u1",
                    "author": "user",
                    "content": "Store 中的旧用户消息",
                    "created_at": "2026-01-01T00:00:00+00:00",
                },
                {
                    "message_id": "store-a1",
                    "author": "agent",
                    "content": "Store 中的旧 AI 消息",
                    "created_at": "2026-01-01T00:00:01+00:00",
                },
            ],
        }

        messages = dashboard_routes._message_payload(thread)
        text = _visible_text(messages)

        for expected in [
            "先帮我分析目录结构",
            "SESSION INTENT",
            "Completed implementations",
            "中文结果",
            "main.py",
        ]:
            if expected not in text:
                raise AssertionError(f"checkpoint 历史缺少：{expected}")

        for forbidden in [
            "Store 中的旧用户消息",
            "Store 中的旧 AI 消息",
            "不应该从 run_events 进入历史",
            "任务计划",
            "任务状态",
        ]:
            if forbidden in text:
                raise AssertionError(f"历史展示不应该包含 Store/run_events 内容：{forbidden}")

        dashboard_routes.visible_checkpoint_messages = lambda thread_id: []
        fallback_messages = dashboard_routes._message_payload(
            {
                **thread,
                "thread_id": "dashboard-empty-checkpoint",
                "title": "兜底标题",
                "user_prompt": "checkpoint 为空时不应该用 Store/user_prompt 兜底",
                "messages": [{"author": "agent", "content": "Store 不应该兜底"}],
            }
        )
        fallback_text = _visible_text(fallback_messages)
        if fallback_text.strip():
            raise AssertionError(f"checkpoint 为空时不应该从 Store 或 user_prompt 兜底：{fallback_text}")

        wrapped_revision_prompt = (
            "Gitee 仓库地址：https://gitee.com/msb-goldbin/abc-test\n\n"
            "原始用户需求：\n增加邮箱绑定功能\n\n"
            "上一版技术方案：\n## 技术方案\n...\n\n"
            "用户新的修改要求：\n当前项目的记忆文件内容是什么？\n\n"
            "请基于上一版方案和新的修改要求，重新输出一份完整的新技术方案。\n"
            "不要只输出差异说明。"
        )
        extracted_prompt = _extract_user_prompt(wrapped_revision_prompt)
        if extracted_prompt != "当前项目的记忆文件内容是什么？":
            raise AssertionError(f"用户输入提取不应该包含内部方案规则：{extracted_prompt}")

        print("dashboard message verification passed")
    finally:
        dashboard_routes.visible_checkpoint_messages = original_visible_checkpoint_messages


if __name__ == "__main__":
    main()
