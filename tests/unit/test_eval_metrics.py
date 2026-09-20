from __future__ import annotations

from agent.evals.metrics import calculate_metrics, retrieval_hit_at_k, tool_recovery_rate


def test_retrieval_hit_at_k_normalizes_paths() -> None:
    assert retrieval_hit_at_k([{"path": "./agent\\core\\runtime.py"}], ["agent/core/runtime.py"]) == 1.0
    assert retrieval_hit_at_k([{"path": "other.py"}], ["agent/core/runtime.py"]) == 0.0


def test_tool_recovery_rate_counts_recovered_failures() -> None:
    events = [
        {"type": "tool_error", "recovered": True},
        {"type": "tool_failed", "recovery": "failed"},
    ]
    assert tool_recovery_rate(events) == 0.5


def test_calculate_metrics_adds_token_fields() -> None:
    result = calculate_metrics(
        retrieval=[{"path": "agent/core/runtime.py"}],
        events=[],
        usage={"input_tokens": 10, "output_tokens": 5},
        gold_files=["agent/core/runtime.py"],
    )
    assert result["total_tokens"] == 15
    assert result["retrieval_hit_at_k"] == 1.0
