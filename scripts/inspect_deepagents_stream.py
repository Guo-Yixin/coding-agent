from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.core.graph import build_agent
from agent.tools.gitee_api import mask_token


def _short(value: Any, *, limit: int = 500) -> str:
    """把诊断输出压缩并脱敏，避免控制台打印过长内容或密钥。"""

    if value is None:
        return ""
    text = value if isinstance(value, str) else repr(value)
    text = mask_token(text)
    return text[:limit] + ("..." if len(text) > limit else "")


def _safe_attr(value: Any, name: str, default: Any = None) -> Any:
    try:
        return getattr(value, name, default)
    except Exception as exc:
        return f"<attr-error {type(exc).__name__}: {exc}>"


def _summarize_raw_event(event: Any) -> dict[str, Any]:
    """生成 raw event 摘要。

    这个脚本是手工诊断工具，不属于正式 Agent 运行链路。摘要逻辑放在脚本内部，
    避免核心 streaming_runtime.py 为了诊断场景保留额外调试函数。
    """

    if not isinstance(event, dict):
        return {"type": type(event).__name__, "repr": _short(event, limit=800)}
    summary: dict[str, Any] = {
        "keys": list(event.keys()),
        "method": event.get("method"),
        "event": event.get("event"),
    }
    params = event.get("params")
    if isinstance(params, dict):
        summary["params_keys"] = list(params.keys())
        summary["namespace"] = params.get("namespace")
        data = params.get("data")
        if isinstance(data, list):
            summary["data_type"] = "list"
            summary["data_len"] = len(data)
            sample = data[0] if data else None
        else:
            summary["data_type"] = type(data).__name__
            sample = data
        if isinstance(sample, dict):
            summary["data_sample_keys"] = list(sample.keys())
            summary["data_sample_event"] = sample.get("event")
            delta = sample.get("delta")
            if isinstance(delta, dict):
                summary["delta_keys"] = list(delta.keys())
                summary["delta_type"] = delta.get("type")
                if delta.get("text"):
                    summary["delta_text_preview"] = _short(delta.get("text"), limit=120)
        elif sample is not None:
            summary["data_sample_type"] = type(sample).__name__
            summary["data_sample_repr"] = _short(sample, limit=300)
    data = event.get("data")
    if isinstance(data, dict):
        summary["top_data_keys"] = list(data.keys())
        chunk = data.get("chunk")
        if chunk is not None:
            summary["top_data_chunk_type"] = type(chunk).__name__
            summary["top_data_chunk_repr"] = _short(chunk, limit=300)
    return summary


def inspect_raw(agent: Any, *, prompt: str, thread_id: str, limit: int) -> None:
    """直接遍历 raw protocol events，确认 method/params/data 的真实结构。"""

    print("\n=== RAW EVENTS ===")
    stream = agent.stream_events(
        {"messages": [{"role": "user", "content": prompt}]},
        version="v3",
        config={"configurable": {"thread_id": f"{thread_id}:raw"}},
    )
    for index, event in enumerate(stream):
        if index >= limit:
            print(f"... raw event limit reached: {limit}")
            break
        print(f"[raw {index}] {json.dumps(_summarize_raw_event(event), ensure_ascii=False)}")
    try:
        output = stream.output
        print("[raw output]", _short(output, limit=1200))
    except Exception as exc:
        print("[raw output error]", type(exc).__name__, _short(str(exc)))


def inspect_interleave(agent: Any, *, prompt: str, thread_id: str, limit: int) -> None:
    """遍历 interleave 投影，确认 messages/tool_calls 是否是 chunk 或完整对象。"""

    print("\n=== INTERLEAVE(messages, tool_calls, subagents) ===")
    stream = agent.stream_events(
        {"messages": [{"role": "user", "content": prompt}]},
        version="v3",
        config={"configurable": {"thread_id": f"{thread_id}:interleave"}},
    )
    for index, (name, item) in enumerate(stream.interleave("messages", "tool_calls", "subagents")):
        if index >= limit:
            print(f"... interleave event limit reached: {limit}")
            break
        summary = {
            "name": name,
            "type": type(item).__name__,
            "text": _short(_safe_attr(item, "text"), limit=300),
            "content": _short(_safe_attr(item, "content"), limit=300),
            "tool_name": _short(_safe_attr(item, "tool_name"), limit=120),
            "name_attr": _short(_safe_attr(item, "name"), limit=120),
            "id": _short(_safe_attr(item, "id"), limit=120),
            "input": _short(_safe_attr(item, "input"), limit=500),
            "args": _short(_safe_attr(item, "args"), limit=500),
            "completed": _short(_safe_attr(item, "completed"), limit=120),
            "error": _short(_safe_attr(item, "error"), limit=200),
            "repr": _short(item, limit=700),
        }
        print(f"[interleave {index}] {json.dumps(summary, ensure_ascii=False)}")
    try:
        output = stream.output
        print("[interleave output]", _short(output, limit=1200))
    except Exception as exc:
        print("[interleave output error]", type(exc).__name__, _short(str(exc)))


def inspect_projection(agent: Any, *, prompt: str, thread_id: str, projection: str, limit: int) -> None:
    """单独遍历 stream.messages 或 stream.tool_calls 等投影。"""

    print(f"\n=== PROJECTION {projection} ===")
    stream = agent.stream_events(
        {"messages": [{"role": "user", "content": prompt}]},
        version="v3",
        config={"configurable": {"thread_id": f"{thread_id}:{projection}"}},
    )
    source = getattr(stream, projection, None)
    if source is None:
        print(f"projection not available: {projection}")
        return
    try:
        iterator = iter(source)
    except TypeError as exc:
        print(f"projection not iterable: {projection}: {exc}")
        return
    for index, item in enumerate(iterator):
        if index >= limit:
            print(f"... projection limit reached: {limit}")
            break
        summary = {
            "type": type(item).__name__,
            "text": _short(_safe_attr(item, "text"), limit=500),
            "content": _short(_safe_attr(item, "content"), limit=500),
            "tool_name": _short(_safe_attr(item, "tool_name"), limit=120),
            "input": _short(_safe_attr(item, "input"), limit=500),
            "output": _short(_safe_attr(item, "output"), limit=500),
            "output_deltas": _short(_safe_attr(item, "output_deltas"), limit=500),
            "repr": _short(item, limit=700),
        }
        print(f"[{projection} {index}] {json.dumps(summary, ensure_ascii=False)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect DeepAgents stream shapes.")
    parser.add_argument(
        "--prompt",
        default=(
            "请用中文输出一个非常短的技术方案，包含三条任务计划，"
            "不要修改文件，不要提交代码。"
        ),
    )
    parser.add_argument("--task-kind", default="planning", choices=["planning", "analysis", "qa", "coding"])
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--mode", choices=["raw", "interleave", "messages", "tool_calls", "all"], default="all")
    args = parser.parse_args()

    thread_id = f"inspect-stream-{uuid.uuid4()}"
    agent = build_agent(thread_id, task_kind=args.task_kind)
    print("thread_id", thread_id)
    print("task_kind", args.task_kind)
    print("prompt", args.prompt)

    if args.mode in {"raw", "all"}:
        inspect_raw(agent, prompt=args.prompt, thread_id=thread_id, limit=args.limit)
    if args.mode in {"interleave", "all"}:
        inspect_interleave(agent, prompt=args.prompt, thread_id=thread_id, limit=args.limit)
    if args.mode in {"messages", "all"}:
        inspect_projection(agent, prompt=args.prompt, thread_id=thread_id, projection="messages", limit=args.limit)
    if args.mode in {"tool_calls", "all"}:
        inspect_projection(agent, prompt=args.prompt, thread_id=thread_id, projection="tool_calls", limit=args.limit)


if __name__ == "__main__":
    main()
