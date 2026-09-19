"""验证模型消息兼容清洗中间件。

运行方式：
    python scripts/verify_message_sanitize_middleware.py

验证目标：
1. AIMessage.content 中的 invalid_tool_call block 会被移除。
2. AIMessage.invalid_tool_calls 字段会被清空。
3. additional_kwargs 中的 invalid_tool_calls 会被清空。
4. 正常 AIMessage(tool_calls) + ToolMessage 组合会被保留。
5. 孤立 ToolMessage 会被丢弃。
6. content block 中的正常 tool_call 可以恢复为 AIMessage.tool_calls。
"""

from __future__ import annotations

import sys
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from agent.core.middleware.message_sanitize import sanitize_messages_for_model


def verify_invalid_tool_call_cleanup() -> None:
    """验证无效工具调用块会被清理，且不会留下孤立工具调用。"""

    messages = [
        HumanMessage(content="确认实施"),
        AIMessage(
            content=[
                {"type": "text", "text": "我准备调用工具。"},
                {"type": "invalid_tool_call", "id": "bad-call", "name": "write_file"},
            ],
            tool_calls=[
                {
                    "name": "read_file",
                    "args": {"path": "projects/demo/main.py"},
                    "id": "ok-call",
                }
            ],
            invalid_tool_calls=[
                {
                    "id": "bad-call",
                    "name": "write_file",
                    "args": "{",
                    "error": "JSON 解析失败",
                }
            ],
            additional_kwargs={
                "invalid_tool_calls": [{"id": "bad-call"}],
                "provider_extra": [{"type": "invalid_tool_call", "id": "bad-call"}],
            },
        ),
    ]

    cleaned = sanitize_messages_for_model(messages)
    ai_message = cleaned[1]

    assert isinstance(ai_message, AIMessage)
    assert ai_message.content == "我准备调用工具。"
    assert ai_message.invalid_tool_calls == []
    # 这组消息没有对应 ToolMessage，因此 tool_calls 会被清空，避免后续请求体失配。
    assert ai_message.tool_calls == []

    dumped = ai_message.model_dump()
    assert "invalid_tool_calls" not in str(ai_message.additional_kwargs)
    assert "invalid_tool_call" not in str(dumped["content"])


def verify_matched_tool_messages_are_kept() -> None:
    """验证完整工具调用组会被保留。"""

    messages = [
        HumanMessage(content="查看文件"),
        AIMessage(
            content="我读取文件。",
            tool_calls=[
                {
                    "name": "read_file",
                    "args": {"path": "projects/demo/main.py"},
                    "id": "call-ok",
                }
            ],
        ),
        ToolMessage(content="文件内容", tool_call_id="call-ok"),
        AIMessage(content="读取完成。"),
    ]
    cleaned = sanitize_messages_for_model(messages)

    assert len(cleaned) == 4
    assert isinstance(cleaned[1], AIMessage)
    assert len(cleaned[1].tool_calls) == 1
    assert isinstance(cleaned[2], ToolMessage)
    assert cleaned[2].tool_call_id == "call-ok"


def verify_orphan_tool_messages_are_removed() -> None:
    """验证孤立 ToolMessage 不会进入模型请求。"""

    messages = [
        HumanMessage(content="继续"),
        ToolMessage(content="孤立工具结果", tool_call_id="missing-call"),
        AIMessage(content="后续回答。"),
    ]
    cleaned = sanitize_messages_for_model(messages)

    assert len(cleaned) == 2
    assert all(not isinstance(message, ToolMessage) for message in cleaned)


def verify_tool_call_content_block_is_restored() -> None:
    """验证 content block 中的正常 tool_call 可以恢复，避免误删合法工具组。"""

    messages = [
        HumanMessage(content="查看文件"),
        AIMessage(
            content=[
                {"type": "text", "text": "我读取文件。"},
                {
                    "type": "tool_call",
                    "id": "call-from-content",
                    "name": "read_file",
                    "args": {"path": "projects/demo/main.py"},
                },
            ],
        ),
        ToolMessage(content="文件内容", tool_call_id="call-from-content"),
    ]
    cleaned = sanitize_messages_for_model(messages)

    assert len(cleaned) == 3
    assert isinstance(cleaned[1], AIMessage)
    assert cleaned[1].content == "我读取文件。"
    assert len(cleaned[1].tool_calls) == 1
    assert cleaned[1].tool_calls[0]["id"] == "call-from-content"


def main() -> None:
    verify_invalid_tool_call_cleanup()
    verify_matched_tool_messages_are_kept()
    verify_orphan_tool_messages_are_removed()
    verify_tool_call_content_block_is_restored()
    print("message-sanitize-ok")


if __name__ == "__main__":
    main()
