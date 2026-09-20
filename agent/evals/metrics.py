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


def calculate_metrics(
    *,
    retrieval: list[dict[str, Any]],
    events: list[dict[str, Any]],
    usage: dict[str, Any],
    gold_files: list[str],
    k: int = 5,
) -> dict[str, Any]:
    input_tokens = int(usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0)
    output_tokens = int(usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0)
    total_tokens = int(usage.get("total_tokens", input_tokens + output_tokens) or 0)
    return {
        "retrieval_hit_at_k": retrieval_hit_at_k(retrieval, gold_files, k=k),
        "tool_recovery_rate": tool_recovery_rate(events),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }
