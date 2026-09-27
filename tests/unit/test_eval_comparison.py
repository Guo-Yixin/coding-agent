from __future__ import annotations

import json
from pathlib import Path

from agent.evals.comparison import compare_report_files, render_comparison


def _report(report_id: str, status: str) -> dict:
    return {
        "report_id": report_id,
        "config": {"agent_source_sha": "abc123456789"},
        "summary": {"case_count": 1, "passed_count": int(status == "passed"), "patch_apply_rate": 1.0,
                    "target_test_pass_rate": 1.0, "regression_test_pass_rate": 1.0,
                    "oracle_test_pass_rate": 1.0, "total_tokens": 400, "total_latency_ms": 12500},
        "cases": [{"case_id": "fixed-case", "status": status, "total_tokens": 400, "agent_latency_ms": 12500}],
    }


def test_comparison_is_self_contained_and_escapes_case_data() -> None:
    report = _report("run <one>", "passed")
    report["cases"][0]["case_id"] = "case <unsafe>"
    page = render_comparison([report, _report("run-two", "failed")])

    assert page.startswith("<!doctype html>")
    assert "Agent Eval 多轮对比" in page
    assert "run &lt;one&gt;" in page
    assert "case &lt;unsafe&gt;" in page
    assert "通过" in page and "未通过" in page
    assert "<script" not in page.lower()
    assert "abc123456789" in page


def test_compare_report_files_writes_portable_html(tmp_path: Path) -> None:
    source = tmp_path / "report.json"
    source.write_text(json.dumps(_report("run-1", "passed")), encoding="utf-8")
    destination = compare_report_files([source], tmp_path / "comparison.html")

    assert destination.is_file()
    assert "400" in destination.read_text(encoding="utf-8")
