import json
from pathlib import Path

from agent.evals.public_export import export_public_report
from agent.evals.public_export import _redact


def test_redaction_preserves_task_branch_and_masks_standalone_api_key():
    api_key = "sk-" + "x" * 32
    assert _redact("git push codex/task-status-search") == "git push codex/task-status-search"
    assert api_key not in _redact(f"credential={api_key}")


def test_public_export_redacts_local_paths_and_copies_only_text_artifacts(tmp_path: Path):
    run_dir = tmp_path / "run"
    artifact = run_dir / "cases" / "case-a" / "artifacts" / "agent-output.txt"
    artifact.parent.mkdir(parents=True)
    artifact.write_text(
        'Read A:\\private\\workspace\\repo\\src.py; token=secret-value; {"api_key": "hidden-secret"}',
        encoding="utf-8",
    )
    review_artifact = run_dir / "cases" / "case-a" / "artifacts" / "manual-review.md"
    review_artifact.write_text("review checklist\n", encoding="utf-8")
    (run_dir / "cases" / "case-a" / "state").mkdir(parents=True)
    (run_dir / "cases" / "case-a" / "state" / "store.sqlite").write_bytes(b"private")
    (run_dir / "report.json").write_text(
        json.dumps(
            {
                "report_id": "run-1",
                "mode": "real",
                "created_at": "2026-09-26T00:00:00Z",
                "repository": "A:\\private\\benchmark",
                "config": {
                    "agent_source_sha": "abc123",
                    "agent_adapter_sha256": "adapter123",
                    "agent_runtime_snapshot_sha256": "snapshot123",
                    "framework_source_sha": "framework123",
                    "agent_source_root": "C:\\Users\\someone\\source",
                    "python": "C:\\Python\\python.exe",
                },
                "summary": {"case_count": 1, "passed_count": 1, "failed_count": 0},
                "cases": [
                    {
                        "case_id": "case-a",
                        "status": "passed",
                        "agent_exit_code": 0,
                        "artifacts": {
                            "agent_output": "cases\\case-a\\artifacts\\agent-output.txt",
                            "manual_review": "cases\\case-a\\artifacts\\manual-review.md",
                        },
                        "metadata": {
                            "repo_path": "A:\\private\\workspace\\repo",
                            "model_name": "test-model",
                            "selected_adapter_sha256": "selected123",
                            "plan_rejection_ok": True,
                            "plan_rubric": [{"accepted_terms": ["taskboard/tasks.py"], "passed": True}],
                            "api_e2e": {
                                "health_passed": True,
                                "sqlite_isolated": True,
                                "database_paths": ["A:\\private\\state\\db.sqlite"],
                                "browser": {"task_submitted": True, "thread_id": "private-thread", "plan_text": "private path"},
                            },
                        },
                        "errors": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    output = tmp_path / "public"
    result = export_public_report(run_dir, output)

    assert result["html"] == "report.html"
    public_report = (output / "report.json").read_text(encoding="utf-8")
    public_artifact = (output / "cases" / "case-a" / "artifacts" / "agent-output.txt").read_text(encoding="utf-8")
    public_review = (output / "cases" / "case-a" / "artifacts" / "manual-review.md").read_text(encoding="utf-8")
    assert "A:\\private" not in public_report + public_artifact
    assert "C:\\Users" not in public_report
    assert "secret-value" not in public_artifact
    assert "hidden-secret" not in public_artifact
    assert "[LOCAL_PATH]" in public_artifact
    assert public_review == "review checklist\n"
    public_data = json.loads(public_report)
    assert public_data["config"]["agent_adapter_sha256"] == "adapter123"
    assert public_data["config"]["framework_source_sha"] == "framework123"
    assert public_data["cases"][0]["metadata"]["selected_adapter_sha256"] == "selected123"
    assert public_data["cases"][0]["metadata"]["plan_rejection_ok"] is True
    assert public_data["cases"][0]["metadata"]["plan_rubric"][0]["passed"] is True
    api_e2e = public_data["cases"][0]["metadata"]["api_e2e"]
    assert api_e2e["sqlite_isolated"] is True
    assert api_e2e["browser"]["task_submitted"] is True
    assert "database_paths" not in api_e2e and "thread_id" not in api_e2e["browser"]
    assert "private-thread" not in public_report
    assert not (output / "cases" / "case-a" / "state" / "store.sqlite").exists()
    html = (output / "report.html").read_text(encoding="utf-8")
    assert "cases/case-a/artifacts/agent-output.txt" in html
    assert "cases/case-a/artifacts/manual-review.md" in html
