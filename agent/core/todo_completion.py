"""Helpers for reconciling the latest Agent todo list with run completion."""

from __future__ import annotations

import json
from typing import Any


def summarize_latest_todos(events: list[dict[str, Any]]) -> dict[str, int | bool] | None:
    """Summarize the latest structured todo event for one run.

    The event's own status is its tool/event lifecycle. Individual item statuses
    in ``detail.todos`` are authoritative for work completion.
    """

    latest_todos: list[Any] | None = None
    for event in events:
        if event.get("kind") != "todo":
            continue
        detail = event.get("detail")
        if isinstance(detail, str):
            try:
                detail = json.loads(detail)
            except (TypeError, ValueError):
                continue
        todos = detail.get("todos") if isinstance(detail, dict) else None
        if isinstance(todos, list):
            latest_todos = todos

    if not latest_todos:
        return None

    completed = 0
    in_progress = 0
    for todo in latest_todos:
        status = str(todo.get("status") or "pending").lower() if isinstance(todo, dict) else "pending"
        if status in {"completed", "complete", "done"}:
            completed += 1
        elif status in {"in_progress", "in-progress", "active", "doing"}:
            in_progress += 1

    total = len(latest_todos)
    pending = total - completed - in_progress
    return {
        "total": total,
        "completed": completed,
        "in_progress": in_progress,
        "pending": pending,
        "complete": completed == total,
    }
