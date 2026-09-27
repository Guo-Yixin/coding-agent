from __future__ import annotations

import json
from pathlib import Path

from scripts.run_eval_agent import _blocks_eval_git_write, _finalize_tool_trace, _usage_from_callback_calls


def test_eval_git_guard_catches_global_options_and_remote_writes():
    assert _blocks_eval_git_write("git -C repo commit -m 'candidate patch'")
    assert _blocks_eval_git_write("git -C repo push origin branch")
    assert _blocks_eval_git_write("git -C repo remote add origin https://example.invalid/repo.git")
    assert not _blocks_eval_git_write("git -C repo status --short")
    assert not _blocks_eval_git_write("git -C repo remote get-url origin")


def test_callback_usage_sums_provider_reported_tokens():
    assert _usage_from_callback_calls([
        {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14},
        {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25},
    ]) == {"input_tokens": 30, "output_tokens": 9, "total_tokens": 39}


def test_callback_usage_does_not_guess_when_any_model_call_is_missing_usage():
    result = _usage_from_callback_calls([
        {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14},
        {"input_tokens": None, "output_tokens": None, "total_tokens": None},
    ])
    assert result["total_tokens"] is None
    assert "every model call" in result["unavailable_reason"]


def test_tool_trace_joins_names_and_marks_later_success_as_recovery(tmp_path: Path):
    trace = tmp_path / "events.jsonl"
    events = [
        {"type": "tool_call", "payload": {"tool_call_id": "t1", "tool_name": "hybrid_code_search"}},
        {"type": "tool_error", "payload": {"tool_call_id": "t1", "error": "timeout"}},
        {"type": "tool_call", "payload": {"tool_call_id": "t2", "tool_name": "hybrid_code_search"}},
        {"type": "tool_result", "payload": {"tool_call_id": "t2"}},
    ]
    trace.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")

    _finalize_tool_trace(trace)

    actual = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    assert actual[1]["payload"]["tool_name"] == "hybrid_code_search"
    assert actual[1]["payload"]["recovered"] is True
    assert actual[3]["payload"]["tool_name"] == "hybrid_code_search"


def test_injected_retrieval_error_can_recover_through_a_successful_fallback_tool(tmp_path: Path):
    trace = tmp_path / "events.jsonl"
    events = [
        {"type": "tool_error", "payload": {"probe_id": "probe-1", "tool_name": "hybrid_code_search", "injected": True}},
        {"type": "tool_call", "payload": {"tool_call_id": "call-2", "tool_name": "read_file"}},
        {"type": "tool_result", "payload": {"tool_call_id": "call-2", "tool_name": "read_file", "status": "success"}},
    ]
    trace.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")

    _finalize_tool_trace(trace)

    actual = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    assert actual[0]["payload"]["recovered"] is True
    assert actual[0]["payload"]["recovery_strategy"] == "fallback_read_file"
    assert actual[-1]["type"] == "tool_recovery"
    assert actual[-1]["payload"]["probe_id"] == "probe-1"
