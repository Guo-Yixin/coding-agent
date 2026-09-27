from __future__ import annotations

from pathlib import Path

from agent.evals.reporting import write_report_artifacts
from agent.evals.schemas import EvalCaseResult, EvalReport


def _report() -> EvalReport:
    case = EvalCaseResult(
        case_id="case <one>",
        status="failed",
        agent_exit_code=0,
        patch_apply=True,
        target_tests_passed=True,
        regression_tests_passed=False,
        retrieval_hit_at_k=0.0,
        tool_recovery_rate=None,
        input_tokens=1250,
        output_tokens=200,
        total_tokens=1450,
        agent_latency_ms=12_500,
        target_test_latency_ms=800,
        regression_test_latency_ms=1000,
        changed_files=["src/task.py"],
        errors=["regression failed <assertion>"],
        artifacts={"patch": "cases/case-one/artifacts/patch.diff"},
        oracle_tests_passed=True,
    )
    return EvalReport(
        report_id="report-123",
        mode="real",
        repository="https://github.com/example/tasks",
        cases=[case],
        config={"agent_source_sha": "abc1234", "runner_version": "3"},
        created_at="2026-09-26T00:00:00+00:00",
    )


def test_report_writer_emits_markdown_and_self_contained_html(tmp_path: Path) -> None:
    paths = write_report_artifacts(_report(), tmp_path)

    assert paths == {"markdown": "report.md", "html": "report.html"}
    markdown = (tmp_path / "report.md").read_text(encoding="utf-8")
    html = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert "1/1 cases passed" not in markdown
    assert "**未通过**" in markdown
    assert "regression failed <assertion>" in markdown
    assert html.startswith("<!doctype html>")
    assert "<script" not in html.lower()
    assert 'href="https://' not in html
    assert "<script src=" not in html.lower()
    assert "case &lt;one&gt;" in html
    assert "regression failed &lt;assertion&gt;" in html
    assert "cases/case-one/artifacts/patch.diff" in html
    assert "Agent SHA：abc1234" in html


def test_report_summary_exposes_denominators_for_optional_checks() -> None:
    data = _report().to_dict()
    assert data["summary"]["target_test_passed_case_count"] == 1
    assert data["summary"]["target_test_case_count"] == 1
    assert data["summary"]["regression_test_passed_case_count"] == 0
    assert data["summary"]["regression_test_case_count"] == 1
    assert data["summary"]["oracle_test_pass_rate"] == 1.0


def test_database_report_uses_component_checks_instead_of_agent_token_metrics(tmp_path: Path) -> None:
    case = EvalCaseResult(
        case_id="postgres-smoke",
        status="passed",
        agent_exit_code=0,
        patch_apply=True,
        target_tests_passed=True,
        regression_tests_passed=None,
        retrieval_hit_at_k=None,
        tool_recovery_rate=None,
        input_tokens=None,
        output_tokens=None,
        total_tokens=None,
        agent_latency_ms=1500,
        target_test_latency_ms=1500,
        regression_test_latency_ms=0,
        metadata={
            "database_evaluation": {
                "localhost_only": True,
                "ephemeral_instance": True,
                "cleanup_succeeded": True,
                "component_results": {
                    "business_store": True,
                    "langgraph_store": True,
                    "checkpointer": True,
                },
            }
        },
    )
    report = EvalReport(
        report_id="database-report",
        mode="database",
        repository="coding-agent",
        cases=[case],
        config={"framework_source_sha": "framework-sha", "database_image": "postgres:18"},
        created_at="2026-09-26T00:00:00Z",
    )

    write_report_artifacts(report, tmp_path)

    markdown = (tmp_path / "report.md").read_text(encoding="utf-8")
    html = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert "业务 Store" in markdown and "Checkpointer" in markdown
    assert "不适用（未调用模型）" in markdown
    assert "一次性数据库" in html
    assert "Token 不适用" in html
    assert "持久化组件" in html


def test_report_shows_plan_rubric_evidence(tmp_path: Path) -> None:
    report = _report()
    report.cases[0].metadata = {
        "plan_rubric": [
            {"accepted_terms": ["taskboard/tasks.py"], "passed": True},
            {"accepted_terms": ["test_count_by_status.py"], "passed": False},
        ]
    }

    write_report_artifacts(report, tmp_path)

    html = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert "计划质量" in html
    assert "1/2 项通过" in html
    assert "taskboard/tasks.py：通过" in html
    assert "test_count_by_status.py：未通过" in html
