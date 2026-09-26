from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    target_repo = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(target_repo))
    from agent.evals.schemas import EvalCaseResult, EvalReport

    def result(case_id: str, status: str) -> EvalCaseResult:
        return EvalCaseResult(
            case_id=case_id,
            status=status,
            agent_exit_code=0,
            patch_apply=True,
            target_tests_passed=True,
            regression_tests_passed=True,
            retrieval_hit_at_k=None,
            tool_recovery_rate=None,
            input_tokens=1,
            output_tokens=1,
            total_tokens=2,
            agent_latency_ms=10,
            target_test_latency_ms=0,
            regression_test_latency_ms=0,
        )

    mixed = EvalReport("oracle", "real", "repo", [result("ok", "passed"), result("bad", "failed")], {}, "now")
    summary = mixed.to_dict()["summary"]
    assert summary.get("failed_count") == 1, f"expected failed_count=1, got {summary.get('failed_count')!r}"
    assert summary["case_count"] == 2
    assert summary["passed_count"] == 1
    assert summary["patch_apply_rate"] == 1.0
    assert summary["target_test_pass_rate"] == 1.0
    assert summary["regression_test_pass_rate"] == 1.0
    assert summary["retrieval_hit_at_k"] is None
    assert summary["tool_recovery_rate"] is None
    assert summary["total_tokens"] == 4
    assert summary["total_latency_ms"] == 20
    for existing_field in (
        "patch_apply_rate",
        "target_test_pass_rate",
        "regression_test_pass_rate",
        "retrieval_hit_at_k",
        "tool_recovery_rate",
        "total_tokens",
        "total_latency_ms",
    ):
        assert existing_field in summary, f"existing summary field disappeared: {existing_field}"

    all_passed = EvalReport("oracle", "real", "repo", [result("ok", "passed")], {}, "now")
    assert all_passed.to_dict()["summary"].get("failed_count") == 0

    empty = EvalReport("oracle", "real", "repo", [], {}, "now")
    assert empty.to_dict()["summary"].get("failed_count") == 0


if __name__ == "__main__":
    main()
