import json
from pathlib import Path

from agent.evals.public_export import export_public_report


def test_public_export_redacts_local_paths_and_copies_only_text_artifacts(tmp_path: Path):
    run_dir = tmp_path / "run"
    artifact = run_dir / "cases" / "case-a" / "artifacts" / "agent-output.txt"
    artifact.parent.mkdir(parents=True)
    artifact.write_text(
        'Read A:\\private\\workspace\\repo\\src.py; token=secret-value; {"api_key": "hidden-secret"}',
        encoding="utf-8",
    )
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
                    "agent_source_root": "C:\\Users\\someone\\source",
                    "python": "C:\\Python\\python.exe",
                },
                "summary": {"case_count": 1, "passed_count": 1, "failed_count": 0},
                "cases": [
                    {
                        "case_id": "case-a",
                        "status": "passed",
                        "agent_exit_code": 0,
                        "artifacts": {"agent_output": "cases\\case-a\\artifacts\\agent-output.txt"},
                        "metadata": {"repo_path": "A:\\private\\workspace\\repo", "model_name": "test-model"},
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
    assert "A:\\private" not in public_report + public_artifact
    assert "C:\\Users" not in public_report
    assert "secret-value" not in public_artifact
    assert "hidden-secret" not in public_artifact
    assert "[LOCAL_PATH]" in public_artifact
    assert not (output / "cases" / "case-a" / "state" / "store.sqlite").exists()
    html = (output / "report.html").read_text(encoding="utf-8")
    assert "cases/case-a/artifacts/agent-output.txt" in html
