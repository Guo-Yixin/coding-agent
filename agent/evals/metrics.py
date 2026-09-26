from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any


def _normal(path: str) -> str:
    return str(PurePosixPath(path.replace("\\", "/"))).lstrip("./")


def retrieval_hit_at_k(retrieval: list[dict[str, Any]], gold_files: list[str], k: int = 5) -> float | None:
    if not gold_files:
        return None
    expected = {_normal(path) for path in gold_files}
    returned = {_normal(str(item.get("path", ""))) for item in retrieval[:k]}
    return 1.0 if expected.intersection(returned) else 0.0


def tool_recovery_rate(events: list[dict[str, Any]]) -> float | None:
    failures = [event for event in events if event.get("type") in {"tool_error", "tool_failed"}]
    if not failures:
        return None
    recovered = sum(1 for event in failures if event.get("recovered") is True or event.get("recovery") in {"success", "recovered"})
    return round(recovered / len(failures), 4)


def tool_usage_metrics(events: list[dict[str, Any]]) -> dict[str, Any]:
    calls_by_id: dict[str, dict[str, Any]] = {}
    anonymous_calls: list[dict[str, Any]] = []
    results_by_id: dict[str, dict[str, Any]] = {}
    anonymous_results: list[dict[str, Any]] = []
    for event in events:
        payload = event.get("payload", {})
        event_type = event.get("type")
        call_id = str(payload.get("tool_call_id") or "")
        if event_type == "tool_call":
            if call_id:
                calls_by_id.setdefault(call_id, payload)
            else:
                anonymous_calls.append(payload)
        elif event_type in {"tool_failed", "tool_error"}:
            if call_id:
                results_by_id[call_id] = {**payload, "failed": True}
            else:
                anonymous_results.append({**payload, "failed": True})
        elif event_type == "tool_result":
            if call_id:
                results_by_id[call_id] = payload
            else:
                anonymous_results.append(payload)
    calls = [*calls_by_id.values(), *anonymous_calls]
    results = [*results_by_id.values(), *anonymous_results]
    failed = sum(bool(payload.get("failed")) for payload in results)
    names: dict[str, int] = {}
    for payload in calls:
        name = str(payload.get("tool_name") or "unknown")
        names[name] = names.get(name, 0) + 1
    return {
        "call_count": len(calls),
        "result_count": len(results),
        "success_count": max(0, len(results) - failed),
        "failure_count": failed,
        "calls_by_tool": dict(sorted(names.items())),
    }


def calculate_metrics(
    *,
    retrieval: list[dict[str, Any]],
    events: list[dict[str, Any]],
    usage: dict[str, Any],
    gold_files: list[str],
    k: int = 5,
) -> dict[str, Any]:
    input_value = usage.get("input_tokens", usage.get("prompt_tokens"))
    output_value = usage.get("output_tokens", usage.get("completion_tokens"))
    input_tokens = int(input_value) if input_value is not None else None
    output_tokens = int(output_value) if output_value is not None else None
    total_value = usage.get("total_tokens")
    total_tokens = (
        int(total_value)
        if total_value is not None
        else (input_tokens + output_tokens if input_tokens is not None and output_tokens is not None else None)
    )
    return {
        "retrieval_hit_at_k": retrieval_hit_at_k(retrieval, gold_files, k=k),
        "tool_recovery_rate": tool_recovery_rate(events),
        "tool_usage": tool_usage_metrics(events),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }
