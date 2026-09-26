from __future__ import annotations

"""DeepAgents V3 事件流适配层。

runtime.py 负责决定“跑什么任务”，server.py 负责创建“具备哪些能力的 Agent”，
而本文件只负责一件事：把 DeepAgents 官方 `stream_events(version="v3")` 输出的
raw protocol events 转换成本地部署版前端能稳定消费的事件。

设计目标：
- 非空 assistant 文本按 token/chunk 实时展示，不能等最终 output 一次性出现。
- `write_todos` 工具调用要转换为结构化任务计划，方便前端显示进度列表。
- 工具消息和子 Agent 生命周期只做简洁记录，避免页面被大量底层细节淹没。
- 每轮 run 使用独立 run_id，防止多轮对话互相覆盖。
"""

import logging
import json
import os
import re
from collections.abc import Callable, Iterable
from typing import Any
from langgraph.types import Command

from langchain_core.messages import BaseMessage

from agent.core.events import record_event
from agent.core.middleware.run_limits import AgentRunLimitExceeded, AgentRunLimitTracker
from agent.env_utils import get_env
from agent.tools.gitee_api import mask_token

logger = logging.getLogger("agent.run.streaming")

# 由 FastAPI SSE 层传入的事件回调。
# streaming_runtime 不直接依赖 Response/EventSource，只把解析出的业务事件往外抛。
StreamEventSink = Callable[[str, dict[str, Any]], None]


def _safe_attr(value: Any, name: str, default: Any = None) -> Any:
    """安全读取官方流对象字段。

    Deep Agents / LangGraph 的 v3 streaming 协议还带有 experimental 提示，
    不同小版本的字段可能是属性，也可能是轻量对象方法。这里统一容错读取，
    避免某个字段缺失时直接打断整个 Agent 任务。
    """

    try:
        return getattr(value, name, default)
    except Exception:
        return default


def _safe_field(value: Any, name: str, default: Any = None) -> Any:
    """兼容官方事件对象和普通 dict。"""

    if isinstance(value, dict):
        return value.get(name, default)
    return _safe_attr(value, name, default)


def _stringify(value: Any, *, limit: int = 1200) -> str:
    """把事件对象中的输入、输出压缩成适合前端展示的短文本。

    前端步骤区只需要告诉开发者“正在做什么”，不应该塞入大段 token、
    大段文件内容或未脱敏的异常。真正的详细排查仍看后端日志。
    """

    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        text = repr(value)
    text = mask_token(text)
    if len(text) > limit:
        return f"{text[:limit]}..."
    return text


def _event_payloads(event: Any) -> list[Any]:
    """从 raw protocol event 中取出 params.data。

    官方文档中的 messages 事件形态是 `event["params"]["data"][0]`。
    实际小版本中 data 可能是单个 dict，也可能是 list，这里统一规整成列表。
    """

    if not isinstance(event, dict):
        return []
    params = event.get("params")
    if not isinstance(params, dict):
        return []
    data = params.get("data")
    if data is None:
        return []
    if isinstance(data, list):
        # 一些版本直接把 payload 列表放在 data 中。
        return data
    if isinstance(data, tuple):
        # LangGraph v3 的真实 messages 事件形态通常是：
        # params.data = (payload, metadata)。第 0 项才是 content-block-delta 等正文事件。
        return [data[0]] if data else []
    # 单个 payload 也统一包装成 list，调用方就不用关心 data 的具体形态。
    return [data]


def _text_delta_from_event(event: Any) -> str:
    """按官方 raw event 协议提取正文 token。

    Deep Agents 文档建议 UI 需要精确流式正文时直接读取 raw protocol events：
    method=messages、event=content-block-delta、delta.type=text-delta。
    """

    if not isinstance(event, dict) or event.get("method") != "messages":
        return ""
    deltas: list[str] = []
    for payload in _event_payloads(event):
        if not isinstance(payload, dict):
            continue
        if payload.get("event") != "content-block-delta":
            continue
        block = payload.get("delta") or {}
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text-delta":
            # 只有 text-delta 是用户可见正文；工具调用参数、metadata 不在这里展示。
            deltas.append(str(block.get("text") or ""))
    return "".join(deltas)


def _text_block_marker_from_event(event: Any) -> tuple[str, int | None] | None:
    """识别 raw messages 中的文本块边界。

    DeepAgents v3 会把 assistant 的一次回复拆成若干 content block。只有
    `content-block-delta/text-delta` 真正携带 token，但 `content-block-start` 和
    `content-block-finish` 能告诉我们“这一段 assistant 文本开始/结束了”。这里返回：

    - `("start", index)`：新的文本块开始，后续 token 应进入新的 AIMessage。
    - `("finish", index)`：当前文本块结束，后续非空文本应开启下一条 AIMessage。

    不同小版本的 payload 字段可能略有差异，所以只做保守识别；识别不到时返回 None，
    调用方会继续把 token 归入当前文本块。
    """

    payload = _message_event_payload(event)
    if not isinstance(payload, dict):
        return None

    event_name = str(payload.get("event") or "")
    index_value = payload.get("index")
    try:
        block_index = int(index_value) if index_value is not None else None
    except (TypeError, ValueError):
        block_index = None

    if event_name == "content-block-start":
        # 文本块开始时，后续 delta 应该进入新的 AIMessage。
        content = payload.get("content")
        if isinstance(content, dict):
            content_type = str(content.get("type") or "")
            if content_type in {"text", "text_delta", "output_text"}:
                return "start", block_index
        # 有些版本的 text block start 不带 content.type；只要不是工具调用块，就按文本块处理。
        if not isinstance(content, dict) or str(content.get("type") or "") not in {"tool_call", "tool_call_chunk"}:
            return "start", block_index

    if event_name == "content-block-finish":
        # 文本块结束时，当前累计文本必须最后刷新一次，避免尾部内容丢失。
        content = payload.get("content")
        if isinstance(content, dict) and str(content.get("type") or "") in {"tool_call", "tool_call_chunk"}:
            return None
        return "finish", block_index

    return None


def _message_event_payload(event: Any) -> dict[str, Any] | None:
    """读取 raw messages 事件中的第一个 payload。"""

    if not isinstance(event, dict) or event.get("method") != "messages":
        return None
    for payload in _event_payloads(event):
        if isinstance(payload, dict):
            return payload
    return None


def _tool_chunk_from_message_event(event: Any) -> dict[str, Any] | None:
    """从 raw messages 事件中读取工具调用 chunk。

    当前 DeepAgents 版本会把工具调用参数作为 message content block 输出：
    content-block-delta -> delta.type=block-delta -> fields.type=tool_call_chunk。
    write_todos 的 JSON 参数会以 fields.args 逐步增长。
    """

    payload = _message_event_payload(event)
    if not payload:
        return None

    if payload.get("event") == "content-block-start":
        content = payload.get("content")
        if isinstance(content, dict) and content.get("type") == "tool_call_chunk":
            return content

    if payload.get("event") == "content-block-delta":
        delta = payload.get("delta")
        if isinstance(delta, dict) and delta.get("type") == "block-delta":
            fields = delta.get("fields")
            if isinstance(fields, dict) and fields.get("type") == "tool_call_chunk":
                return fields

    if payload.get("event") == "content-block-finish":
        content = payload.get("content")
        if isinstance(content, dict) and content.get("type") == "tool_call":
            return content

    return None


def _should_flush_stream_text(*, accumulated_text: str, last_flushed_length: int, delta: str) -> bool:
    """判断是否需要把模型正文增量刷新到业务事件表。

    DeepAgents 的 raw message 事件可能按 token 级别返回，如果每个 token 都写一次 SQLite，
    页面虽然实时，但本地数据库提交会过于频繁。这里做轻量合并：
    - 首段内容立即展示，让用户知道模型已经开始输出；
    - 累计新增 24 个字符左右刷新一次；
    - 遇到换行也刷新，Markdown 标题、列表和段落会更快出现在页面上。
    """

    if not accumulated_text:
        return False
    if last_flushed_length == 0:
        return True
    if len(accumulated_text) - last_flushed_length >= 24:
        return True
    return "\n" in delta


def _tool_call_from_event(event: Any) -> Any | None:
    """尽量从 raw tool_calls event 中提取工具调用对象。

    工具事件在不同 DeepAgents 小版本中的字段可能不完全一致；本函数只做保守解析。
    解析不到时返回 None，具体文件/命令/Gitee 工具仍会通过工具内部 record_event 展示。
    """

    if not isinstance(event, dict) or event.get("method") != "tool_calls":
        return None
    for payload in _event_payloads(event):
        if isinstance(payload, dict):
            return payload
        if payload is not None:
            return payload
    return None


def _subagent_from_event(event: Any) -> Any | None:
    """尽量从 raw subagents event 中提取子智能体对象。"""

    if not isinstance(event, dict) or event.get("method") != "subagents":
        return None
    for payload in _event_payloads(event):
        if payload is not None:
            return payload
    return None


def _normalize_todo_status(status: Any) -> str:
    """把 DeepAgents / LangChain 的 todo 状态规整为前端支持的三种状态。"""

    text = str(status or "pending").lower()
    if text in {"in_progress", "in-progress", "active", "doing"}:
        return "in_progress"
    if text in {"completed", "complete", "done"}:
        return "completed"
    return "pending"


def _extract_todos(tool_call: Any) -> list[dict[str, str]]:
    """从 write_todos 官方 tool_call 中提取任务清单。"""

    call_input = _safe_field(tool_call, "input")
    if call_input is None:
        call_input = _safe_field(tool_call, "args")
    if isinstance(call_input, str):
        try:
            # 官方最终 tool_call 往往会给完整 JSON 字符串。
            call_input = json.loads(call_input)
        except ValueError:
            # 如果不是 JSON，就退化成一个普通 pending todo，避免任务计划完全不可见。
            return [{"content": call_input, "status": "pending"}] if call_input.strip() else []

    raw_todos: Any
    if isinstance(call_input, dict):
        raw_todos = call_input.get("todos") or call_input.get("items") or []
    else:
        raw_todos = call_input

    if not isinstance(raw_todos, list):
        return []

    todos: list[dict[str, str]] = []
    for item in raw_todos:
        if isinstance(item, str):
            # 兼容极简 ["做 A", "做 B"] 形式。
            content = item.strip()
            status = "pending"
        elif isinstance(item, dict):
            # DeepAgents write_todos 标准形态一般是 {"content": "...", "status": "..."}。
            content = str(item.get("content") or item.get("task") or item.get("title") or "").strip()
            status = _normalize_todo_status(item.get("status"))
        else:
            content = str(item).strip()
            status = "pending"
        if content:
            todos.append({"content": content, "status": status})
    return todos


def _record_write_todos(thread_id: str, run_id: str, tool_call: Any, index: int) -> bool:
    """只把 DeepAgents 内置 write_todos 转成结构化任务清单事件。"""

    tool_name = str(_safe_field(tool_call, "tool_name", "") or _safe_field(tool_call, "name", "") or "")
    if tool_name != "write_todos":
        return False
    todos = _extract_todos(tool_call)
    if not todos:
        return True
    call_id = str(_safe_field(tool_call, "id", "") or _safe_field(tool_call, "tool_call_id", "") or index)
    record_event(
        thread_id,
        f"todos:{run_id}:{call_id}",
        "任务清单",
        kind="todo",
        status="completed",
        detail=json.dumps({"todos": todos}, ensure_ascii=False),
        run_id=run_id,
    )
    return True


def _decode_json_string_fragment(value: str) -> str:
    """解码正则截取出的 JSON 字符串片段。"""

    try:
        return json.loads(f'"{value}"')
    except ValueError:
        return value


def _todos_from_args_text(args_text: str) -> list[dict[str, str]]:
    """从 write_todos 的参数文本中提取已形成的 todo。

    args_text 在 raw chunk 中经常是“不完整但逐步增长”的 JSON 字符串。完整时直接
    json.loads；不完整时用保守正则提取已经闭合的 content/status 对象，让前端能更早
    看到任务计划逐项出现。
    """

    if not args_text.strip():
        return []
    try:
        parsed = json.loads(args_text)
    except ValueError:
        parsed = None

    if isinstance(parsed, dict):
        # JSON 已经完整时，复用标准提取逻辑。
        return _extract_todos({"input": parsed})

    todos: list[dict[str, str]] = []
    pattern = re.compile(
        r'\{\s*"content"\s*:\s*"(?P<content>(?:\\.|[^"\\])*)"\s*,\s*"status"\s*:\s*"(?P<status>[^"]*)"',
        re.DOTALL,
    )
    for match in pattern.finditer(args_text):
        # JSON 尚未闭合时，只提取已经完整出现的 todo 对象。
        content = _decode_json_string_fragment(match.group("content")).strip()
        status = _normalize_todo_status(match.group("status"))
        if content:
            todos.append({"content": content, "status": status})
    return todos


def _record_todos(
    thread_id: str,
    run_id: str,
    call_id: str,
    todos: list[dict[str, str]],
    *,
    status: str,
    event_sink: StreamEventSink | None = None,
) -> None:
    """写入结构化任务计划事件。"""

    if not todos:
        return
    record_event(
        thread_id,
        f"todos:{run_id}:{call_id}",
        "任务清单",
        kind="todo",
        status=status,
        detail=json.dumps({"todos": todos}, ensure_ascii=False),
        run_id=run_id,
    )
    if event_sink is not None:
        # 立即推给前端，让任务计划列表在工具调用参数逐步生成时也能更新。
        event_sink(
            "todo_delta",
            {
                "message_id": f"{thread_id}-live-plan-{run_id}",
                "run_id": run_id,
                "todos": todos,
            },
        )


def _message_dict(message: Any) -> dict[str, Any]:
    """把最终输出中的 LangChain 消息对象转换为普通字典。"""

    if isinstance(message, BaseMessage):
        result = {"type": message.type, "content": message.content}
        if os.environ.get("CODING_AGENT_EVAL_MODE", "").strip() == "1":
            usage = getattr(message, "usage_metadata", None)
            if isinstance(usage, dict):
                result["usage_metadata"] = usage
            response_metadata = getattr(message, "response_metadata", None)
            if isinstance(response_metadata, dict) and isinstance(response_metadata.get("token_usage"), dict):
                result["response_metadata"] = {"token_usage": response_metadata["token_usage"]}
        return result
    return {"type": type(message).__name__, "content": str(message)}


def _messages_from_output(output: Any) -> list[dict[str, Any]]:
    """从 stream.output 中提取最终 messages。

    官方 Deep Agents 返回值通常是 `{"messages": [...]}`；为了本地部署版稳定运行，
    这里也兼容对象属性和其它返回结构。
    """

    if isinstance(output, dict):
        messages = output.get("messages") or []
    else:
        messages = _safe_attr(output, "messages", []) or []
    if not isinstance(messages, Iterable) or isinstance(messages, (str, bytes)):
        return []
    return [_message_dict(message) for message in messages]


def _record_assistant_stream_message(
    thread_id: str,
    run_id: str,
    index: int,
    text: str,
    *,
    event_sink: StreamEventSink | None = None,
) -> None:
    """把某一段非空 assistant 文本写成独立的前端事件。

    `stream:{run_id}:assistant:{index}` 表示运行过程中第 index 段 assistant 文本。
    前端会把不同 index 展示成不同的
    AIMessage，因此 Todo 后面的“正在说明/总结/代码处理过程”不会互相覆盖。
    """

    if not text.strip():
        return
    # record_event 是后端持久化/兜底通道；event_sink 是本轮 SSE 实时通道。
    # 两者都使用同一个 run_id + assistant_index，避免刷新和实时显示的 id 规则不一致。
    record_event(
        thread_id,
        f"stream:{run_id}:assistant:{index}",
        "正在生成内容",
        kind="other",
        status="in_progress",
        detail=json.dumps({"text": text}, ensure_ascii=False),
        run_id=run_id,
    )
    if event_sink is not None:
        message_id = f"{thread_id}-live-assistant-{run_id}-{index}"
        # message_start 保证前端先创建一条 AIMessage 容器，再接收 text_delta。
        event_sink(
            "message_start",
            {
                "message_id": message_id,
                "author": "agent",
                "run_id": run_id,
                "assistant_index": str(index),
            },
        )
        event_sink(
            "text_delta",
            {
                "message_id": message_id,
                "run_id": run_id,
                "assistant_index": str(index),
                "content": text,
                # replace 表示这里传的是“当前累计全文”，不是单 token 增量。
                # 前端应整体替换该 message 的内容，避免重复拼接。
                "mode": "replace",
            },
        )


def _tool_event_from_raw(event: Any) -> dict[str, Any] | None:
    """读取 raw tools 生命周期事件。"""

    if not isinstance(event, dict) or event.get("method") != "tools":
        return None
    params = event.get("params")
    if not isinstance(params, dict):
        return None
    data = params.get("data")
    return data if isinstance(data, dict) else None


def _record_subagent(thread_id: str, run_id: str, subagent: Any, index: int) -> None:
    """记录 Deep Agents 子智能体生命周期。

    第一版 UI 不单独做子智能体卡片，只用一条简洁步骤展示 delegated task。
    """

    name = str(_safe_field(subagent, "name", "") or "subagent")
    status = str(_safe_field(subagent, "status", "") or "started")
    event_status = "completed" if status == "completed" else "error" if status == "failed" else "in_progress"
    path = _safe_field(subagent, "path")
    record_event(
        thread_id,
        f"stream:{run_id}:subagent:{index}:{name}",
        f"子智能体：{name}",
        kind="think",
        status=event_status,
        detail=_stringify(path, limit=500) or None,
        run_id=run_id,
    )


def _consume_raw_event_stream(
    *,
    stream: Any,
    thread_id: str,
    run_id: str,
    task_kind: str | None = None,
    event_sink: StreamEventSink | None = None,
) -> tuple[int, int]:
    """按官网 raw protocol event 消费 DeepAgents 输出。

    这个函数解决“技术方案正文只能最终一次性展示”的问题：
    1. 直接读取 `method=messages` 的 `content-block-delta/text-delta`，把累计正文写入
       `stream:message`，前端 SSE 会持续拿到越来越完整的 Markdown 正文。
    2. 同时继续读取 `method=tool_calls` 和 `method=subagents`，保留 write_todos 任务计划、
       工具步骤和子 Agent 生命周期展示。

    如果某个 DeepAgents 小版本没有在 raw event 中暴露 tool_calls，工具内部的 record_event
    仍然会记录读文件、命令、Gitee 等步骤；但 write_todos 只有 raw tool_calls 可见时才会出现。
    """

    '''
    assistant_message_index	当前是第几段 assistant 文本
    current_assistant_index	当前正在接收 token 的 assistant 文本块 ID
    current_assistant_text	当前 assistant 文本累计内容
    last_flushed_length	上次已经推给前端的文本长度
    tool_call_index	工具调用计数
    subagent_index	子 Agent 事件计数
    write_todo_args_by_call	记录某个 write_todos 工具调用目前累计到的 args
    write_todo_last_payload_by_call	避免重复发送相同 todo
    saw_write_todos	本轮是否看到了任务计划工具
    '''

    tool_call_index = 0
    subagent_index = 0
    assistant_message_index = 0
    current_assistant_index = 0
    current_assistant_text = ""
    last_flushed_length = 0
    write_todo_args_by_call: dict[str, str] = {}
    write_todo_last_payload_by_call: dict[str, str] = {}
    saw_write_todos = False
    limit_tracker = AgentRunLimitTracker(task_kind=task_kind)

    for event in stream:
        # 每个 raw event 都先交给保护器计数。它可以识别模型调用过多、工具循环等异常。
        limit_tracker.observe_event(event)
        marker = _text_block_marker_from_event(event)
        if marker is not None:
            marker_kind, _block_index = marker
            if marker_kind == "start":
                # 新文本块开始前，如果上一段还有未刷新的尾巴，先落库/推送。
                if current_assistant_text and last_flushed_length != len(current_assistant_text):
                    _record_assistant_stream_message(
                        thread_id,
                        run_id,
                        current_assistant_index or assistant_message_index or 1,
                        current_assistant_text,
                        event_sink=event_sink,
                    )
                assistant_message_index += 1
                current_assistant_index = assistant_message_index
                current_assistant_text = ""
                last_flushed_length = 0
                continue
            if marker_kind == "finish":
                # 文本块结束时做最终刷新，然后清空当前块状态。
                if current_assistant_text and last_flushed_length != len(current_assistant_text):
                    _record_assistant_stream_message(
                        thread_id,
                        run_id,
                        current_assistant_index or assistant_message_index or 1,
                        current_assistant_text,
                        event_sink=event_sink,
                    )
                current_assistant_index = 0
                current_assistant_text = ""
                last_flushed_length = 0
                continue

        delta = _text_delta_from_event(event)
        if delta:
            if current_assistant_index == 0:
                # 有些模型流不会显式给 content-block-start，这里按第一个 delta 自动开块。
                assistant_message_index += 1
                current_assistant_index = assistant_message_index
                current_assistant_text = ""
                last_flushed_length = 0
            current_assistant_text += delta
            if _should_flush_stream_text(
                accumulated_text=current_assistant_text,
                last_flushed_length=last_flushed_length,
                delta=delta,
            ):
                _record_assistant_stream_message(
                    thread_id,
                    run_id,
                    current_assistant_index,
                    current_assistant_text,
                    event_sink=event_sink,
                )
                last_flushed_length = len(current_assistant_text)
            continue

        tool_chunk = _tool_chunk_from_message_event(event)
        if tool_chunk is not None:
            tool_name = str(tool_chunk.get("name") or "")
            if tool_name == "write_todos":
                # write_todos 的参数本身就是任务清单，因此要尽早解析出来给前端展示。
                saw_write_todos = True
                call_id = str(tool_chunk.get("id") or tool_chunk.get("tool_call_id") or "write_todos")
                args = tool_chunk.get("args")
                if isinstance(args, dict):
                    # 完整 dict：通常代表工具调用参数已经完整。
                    todos = _extract_todos({"input": args})
                    payload_text = json.dumps(todos, ensure_ascii=False)
                    if payload_text != write_todo_last_payload_by_call.get(call_id):
                        _record_todos(
                            thread_id,
                            run_id,
                            call_id,
                            todos,
                            status="completed",
                            event_sink=event_sink,
                        )
                        write_todo_last_payload_by_call[call_id] = payload_text
                elif isinstance(args, str):
                    # 字符串 chunk：JSON 可能还没闭合，用正则提取已完整的 todo。
                    write_todo_args_by_call[call_id] = args
                    todos = _todos_from_args_text(args)
                    payload_text = json.dumps(todos, ensure_ascii=False)
                    if todos and payload_text != write_todo_last_payload_by_call.get(call_id):
                        _record_todos(
                            thread_id,
                            run_id,
                            call_id,
                            todos,
                            status="in_progress",
                            event_sink=event_sink,
                        )
                        write_todo_last_payload_by_call[call_id] = payload_text
            continue

        tool_call = _tool_call_from_event(event)
        if tool_call is not None:
            # 老版本/其它事件流形态可能把工具调用放在 method=tool_calls。
            tool_call_index += 1
            if os.environ.get("CODING_AGENT_EVAL_MODE", "").strip() == "1":
                from agent.evals.telemetry import record_eval_event

                record_eval_event(
                    "tool_call",
                    {
                        "tool_name": str(_safe_field(tool_call, "tool_name", "") or _safe_field(tool_call, "name", "") or "unknown"),
                        "tool_call_id": str(_safe_field(tool_call, "id", "") or _safe_field(tool_call, "tool_call_id", "") or tool_call_index),
                    },
                )
            if _record_write_todos(thread_id, run_id, tool_call, tool_call_index):
                saw_write_todos = True
                continue
            logger.debug(
                "忽略官方 raw tool_call 展示事件：thread_id=%s index=%s item=%s",
                thread_id,
                tool_call_index,
                tool_call,
            )
            continue

        tool_event = _tool_event_from_raw(event)
        if tool_event is not None:
            if os.environ.get("CODING_AGENT_EVAL_MODE", "").strip() == "1":
                from agent.evals.telemetry import record_eval_event

                lifecycle = str(tool_event.get("event") or "unknown")
                record_eval_event(
                    "tool_call" if lifecycle == "tool-started" else "tool_result",
                    {
                        "tool_name": str(tool_event.get("tool_name") or "unknown"),
                        "tool_call_id": str(tool_event.get("tool_call_id") or ""),
                        "lifecycle": lifecycle,
                        "failed": any(marker in lifecycle.lower() for marker in ("error", "fail")),
                    },
                )
            # method=tools 是另一种工具生命周期事件。这里主要用于补充 write_todos 状态。
            tool_name = str(tool_event.get("tool_name") or "")
            if tool_name == "write_todos":
                saw_write_todos = True
                call_id = str(tool_event.get("tool_call_id") or "write_todos")
                tool_input = tool_event.get("input")
                if isinstance(tool_input, dict):
                    todos = _extract_todos({"input": tool_input})
                    payload_text = json.dumps(todos, ensure_ascii=False)
                    if todos and payload_text != write_todo_last_payload_by_call.get(call_id):
                        event_status = "completed" if tool_event.get("event") == "tool-finished" else "in_progress"
                        _record_todos(
                            thread_id,
                            run_id,
                            call_id,
                            todos,
                            status=event_status,
                            event_sink=event_sink,
                        )
                        write_todo_last_payload_by_call[call_id] = payload_text
            continue

        subagent = _subagent_from_event(event)
        if subagent is not None:
            # 子 Agent 事件只做简洁记录，详细分析报告仍来自 assistant 文本。
            subagent_index += 1
            _record_subagent(thread_id, run_id, subagent, subagent_index)

    if current_assistant_text and last_flushed_length != len(current_assistant_text):
        # 流结束后兜底刷新一次，避免最后不足 24 字且没有换行的文本丢失。
        _record_assistant_stream_message(
            thread_id,
            run_id,
            current_assistant_index or assistant_message_index or 1,
            current_assistant_text,
            event_sink=event_sink,
        )
    return tool_call_index if saw_write_todos else 0, subagent_index


def run_agent_with_event_stream(
    *,
    agent: Any,
    thread_id: str,
    run_id: str,
    content: str,
    task_kind: str | None = None,
    event_sink: StreamEventSink | None = None,
    resume_value: Any | None = None,
    model_id: str | None = None,
) -> dict[str, Any]:
    """使用官方 v3 event streaming 驱动 DeepAgent。

    这个函数是 FastAPI 版本替代 `langgraph dev` 的核心桥接层：
    - DeepAgent 继续按官方 `stream_events(version="v3")` 运行。
    - 后端把 message、tool_calls、subagents 转成项目的 `run_events`。
    - 每一轮运行都把 run_id 写进事件 id，保证 plan、coding、review 多轮内容
      不会在前端互相覆盖或拼接到同一个消息里。
    - 前端仍只消费我们自己的 `/dashboard/api/.../stream`，不用绑定 LangGraph 本地服务。
    """

    agent_input = Command(resume=resume_value) if resume_value is not None else {"messages": [{"role": "user", "content": content}]}
    stream = agent.stream_events(
        agent_input,
        version="v3",
        config={"configurable": {"thread_id": thread_id}},
    )
    model_name = model_id or get_env("MAIN_MODEL", "deepseek-v4-pro").strip()
    model_title = f"调用 {model_name}"
    record_event(thread_id, "model", model_title, kind="other", status="in_progress", run_id=run_id)
    # raw protocol events 是当前版本里唯一能拿到 token/chunk 的通道。
    # 这里同时解析 text-delta 和 write_todos 的 tool_call_chunk，保证正文和任务计划都能流式更新。
    try:
        tool_call_index, subagent_index = _consume_raw_event_stream(
            stream=stream,
            thread_id=thread_id,
            run_id=run_id,
            task_kind=task_kind,
            event_sink=event_sink,
        )
    except AgentRunLimitExceeded as exc:
        record_event(
            thread_id,
            "agent:run-limit",
            "达到运行保护上限",
            kind="other",
            status="error",
            detail=str(exc),
        )
        record_event(
            thread_id, "model", model_title, kind="other", status="error", detail=str(exc), run_id=run_id
        )
        raise

    output = stream.output
    raw_interrupts = output.get("__interrupt__", []) if isinstance(output, dict) else []
    interrupts = []
    for item in raw_interrupts or []:
        value = getattr(item, "value", item)
        if isinstance(value, dict):
            interrupts.append(value)
    record_event(thread_id, "model", model_title, kind="other", status="completed", run_id=run_id)
    logger.info(
        "官方事件流消费完成：thread_id=%s tool_calls=%s subagents=%s",
        thread_id,
        tool_call_index,
        subagent_index,
    )
    return {"messages": _messages_from_output(output), "raw_output": output, "interrupts": interrupts}
