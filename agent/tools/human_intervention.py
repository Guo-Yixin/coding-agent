"""LangGraph-backed human intervention tool for coding runs."""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool
from langgraph.types import interrupt

from agent.tools.runtime_context import get_runtime_task_kind


@tool
def request_human_intervention(question: str, reason: str, options: list[str] | None = None) -> dict[str, Any]:
    """Pause a coding task and ask the user a blocking question before an out-of-scope or risky action."""

    if get_runtime_task_kind() != "coding":
        return {"ok": False, "error": "仅已批准的编码任务可以请求实施中人工介入。"}
    response = interrupt(
        {
            "type": "human_intervention",
            "question": question.strip(),
            "reason": reason.strip(),
            "options": [item.strip() for item in (options or []) if item.strip()][:6],
        }
    )
    return {"ok": True, "user_response": response}
