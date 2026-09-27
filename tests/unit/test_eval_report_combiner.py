from __future__ import annotations

import json
from pathlib import Path

from scripts.combine_eval_reports import _copy_report_case, _summary
from agent.evals.reporting import _system_gates


def test_combined_summary_preserves_denominators_for_missing_metrics() -> None:
    summary = _summary(
        [
            {
                "case_id": "with-usage",
                "status": "passed",
                "patch_apply": True,
                "target_tests_passed": True,
                "regression_tests_passed": True,
                "oracle_tests_passed": True,
                "retrieval_hit_at_k": 1.0,
                "tool_recovery_rate": 1.0,
                "total_tokens": 300,
                "agent_latency_ms": 1200,
            },
            {
                "case_id": "without-usage",
                "status": "failed",
                "patch_apply": False,
                "target_tests_passed": None,
                "regression_tests_passed": True,
                "oracle_tests_passed": False,
                "retrieval_hit_at_k": None,
                "tool_recovery_rate": None,
                "total_tokens": None,
                "agent_latency_ms": 800,
            },
        ]
    )

    assert summary["case_count"] == 2
    assert summary["passed_count"] == 1
    assert summary["failed_count"] == 1
    assert summary["target_test_pass_rate"] == 1.0
    assert summary["target_test_case_count"] == 1
    assert summary["oracle_test_pass_rate"] == 0.5
    assert summary["oracle_test_case_count"] == 2
    assert summary["tool_recovery_rate"] == 1.0
    assert summary["total_tokens"] == 300
    assert summary["token_usage_case_count"] == 1
    assert summary["total_latency_ms"] == 2000


def test_system_gate_html_escapes_untrusted_report_text() -> None:
    rendered = _system_gates(
        [
            {
                "id": "gate-1",
                "title": "PostgreSQL <E2E>",
                "status": "passed",
                "description": "database <secret> stayed isolated",
                "checks": {"isolated <db>": True, "cleanup": False},
                "report_path": "gates/postgres/report.html",
            }
        ]
    )

    assert "PostgreSQL &lt;E2E&gt;" in rendered
    assert "database &lt;secret&gt; stayed isolated" in rendered
    assert "isolated &lt;db&gt;" in rendered
    assert "cleanup" in rendered
    assert 'href="gates/postgres/report.html"' in rendered
    assert "<secret>" not in rendered


def test_combined_case_artifacts_keep_their_artifact_or_trace_directory(tmp_path: Path) -> None:
    source = tmp_path / "source-run"
    case_root = source / "cases" / "sample"
    (case_root / "artifacts").mkdir(parents=True)
    (case_root / "traces").mkdir()
    (case_root / "artifacts" / "patch.diff").write_text("diff", encoding="utf-8")
    (case_root / "traces" / "events.jsonl").write_text("{}\n", encoding="utf-8")
    report = source / "report.json"
    report.write_text(json.dumps({"report_id": "source-report"}), encoding="utf-8")
    output = tmp_path / "combined"

    copied = _copy_report_case(
        report,
        {
            "case_id": "sample",
            "artifacts": {
                "patch": r"cases\sample\artifacts\patch.diff",
                "trace": r"cases\sample\traces\events.jsonl",
            },
            "metadata": {"agent_source_sha": "agent-sha", "target_repo_sha": "target-sha"},
        },
        output,
    )

    assert copied["artifacts"]["patch"] == "cases/sample/source-run/artifacts/patch.diff"
    assert copied["artifacts"]["trace"] == "cases/sample/source-run/traces/events.jsonl"
    assert (output / copied["artifacts"]["patch"]).is_file()
    assert (output / copied["artifacts"]["trace"]).is_file()
    assert copied["metadata"]["provenance"]["source_report_id"] == "source-report"
