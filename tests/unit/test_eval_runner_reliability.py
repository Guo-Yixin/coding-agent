from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import agent.evals.runner as eval_runner_module
from agent.evals.runner import EvalRunner, _plan_rejection_evidence_ok
from agent.evals.runtime_snapshot import prepare_agent_runtime_snapshot, verify_agent_runtime_snapshot
from agent.evals.schemas import EvalCase


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def _target_repo(root: Path) -> tuple[Path, str]:
    repo = root / "task-repository"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "eval-test@example.invalid")
    _git(repo, "config", "user.name", "Eval test")
    (repo / "result.txt").write_text("baseline\n", encoding="utf-8")
    (repo / "existing.txt").write_text("must stay intact\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "fixed evaluation baseline")
    sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "remote", "add", "origin", "https://github.com/example/eval-target.git")
    return repo, sha


def _agent_source(root: Path) -> Path:
    source = root / "agent-source"
    scripts = source / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "run_eval_agent.py").write_text(
        """from __future__ import annotations

import json
import os
from pathlib import Path

case_id = os.environ["EVAL_CASE_ID"]
repo = Path(os.environ["EVAL_CASE_REPO"])
(repo / "result.txt").write_text(case_id + "\\n", encoding="utf-8")
events = [
    {"type": "retrieval", "payload": {"hits": [{"path": "result.txt", "rank": 1}]}},
    {"type": "tool_call", "payload": {"tool_call_id": "call-1", "tool_name": "write_file"}},
    {"type": "tool_result", "payload": {"tool_call_id": "call-1", "content": "ok"}},
]
Path(os.environ["EVAL_EVENT_FILE"]).write_text(
    "\\n".join(json.dumps(event) for event in events) + "\\n", encoding="utf-8"
)
Path(os.environ["EVAL_USAGE_FILE"]).write_text(
    json.dumps({"input_tokens": 120, "output_tokens": 35}), encoding="utf-8"
)
Path(os.environ["EVAL_RESULT_FILE"]).write_text(
    json.dumps({"status": "completed", "model_provider": "test", "model_name": "fake"}),
    encoding="utf-8",
)
print("simulated Agent completed")
""",
        encoding="utf-8",
    )
    _git(source, "init", "-q")
    _git(source, "config", "user.email", "eval-agent@example.invalid")
    _git(source, "config", "user.name", "Eval agent")
    _git(source, "add", "-A")
    _git(source, "commit", "-qm", "fixed simulated Agent")
    return source


def _enable_fake_codegraph(monkeypatch) -> None:
    original_run = subprocess.run

    def run(command, *args, **kwargs):
        if isinstance(command, (list, tuple)) and command and str(command[0]) == "codegraph":
            target = Path(str(command[2])) / ".codegraph"
            target.mkdir(parents=True, exist_ok=True)
            (target / ".gitignore").write_text("*\n!.gitignore\n", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "index ready", "")
        return original_run(command, *args, **kwargs)

    monkeypatch.setattr(eval_runner_module.shutil, "which", lambda _name: "codegraph")
    monkeypatch.setattr(eval_runner_module.subprocess, "run", run)


def _case(case_id: str, *, target_test: list[str] | None = None) -> EvalCase:
    expected = case_id
    passing_check = [
        "python",
        "-c",
        "from pathlib import Path; assert Path('result.txt').read_text(encoding='utf-8').strip() == "
        + repr(expected),
    ]
    return EvalCase(
        case_id=case_id,
        prompt=f"Write {case_id} to result.txt",
        base_ref=None,
        gold_files=["result.txt"],
        target_tests=[target_test or passing_check],
        regression_tests=[
            [
                "python",
                "-c",
                "from pathlib import Path; assert Path('existing.txt').read_text(encoding='utf-8') == 'must stay intact\\n'",
            ]
        ],
        oracle_tests=[passing_check],
        requires_patch=True,
        allowed_files=["result.txt"],
        expected_status="completed",
        metadata={"required_changed_files": ["result.txt"], "model_call_limit": 4, "tool_call_limit": 4},
    )


def _runner(output: Path, source: Path, env_file: Path) -> EvalRunner:
    return EvalRunner(
        output_dir=output,
        mode="real",
        python_executable=sys.executable,
        env_file=env_file,
        agent_source_root=source,
    )


def test_real_cases_use_independent_workspaces_and_capture_provenance_and_metrics(
    tmp_path: Path, monkeypatch
) -> None:
    repository, target_sha = _target_repo(tmp_path)
    source = _agent_source(tmp_path)
    config_dir = tmp_path / "private-config"
    config_dir.mkdir()
    env_file = config_dir / "model.env"
    env_file.write_text("", encoding="utf-8")
    _enable_fake_codegraph(monkeypatch)
    cases = [_case("case-one"), _case("case-two")]

    first = _runner(tmp_path / "run-one", source, env_file).run(cases, repository=repository)
    second = _runner(tmp_path / "run-two", source, env_file).run(cases, repository=repository)

    assert [case.status for case in first.cases] == ["passed", "passed"]
    assert first.config["agent_source_sha"] == _git(source, "rev-parse", "HEAD")
    assert first.config["agent_source_sha"] == second.config["agent_source_sha"]
    assert first.config["agent_source_dirty_patch_sha256"] == second.config["agent_source_dirty_patch_sha256"]
    assert [case.metadata["target_repo_sha"] for case in first.cases] == [target_sha, target_sha]
    assert [case.metadata["target_repo_sha"] for case in second.cases] == [target_sha, target_sha]
    assert first.config["agent_runtime_snapshot_sha256"]
    run_manifest = json.loads((tmp_path / "run-one" / "manifest.json").read_text(encoding="utf-8"))
    assert run_manifest["agent"]["source_sha"] == first.config["agent_source_sha"]
    assert run_manifest["cases"][0]["target_repo_sha"] == target_sha

    repos = [Path(case.metadata["repo_path"]) for case in first.cases]
    assert repos[0] != repos[1]
    states = [Path(case.metadata["workspace_root"]).parent / "state" for case in first.cases]
    assert states[0] != states[1]
    assert states[0].parent != states[1].parent
    assert (repos[0] / "result.txt").read_text(encoding="utf-8") == "case-one\n"
    assert (repos[1] / "result.txt").read_text(encoding="utf-8") == "case-two\n"
    assert ".codegraph/" in (repos[0] / ".git" / "info" / "exclude").read_text(encoding="utf-8")
    assert EvalRunner._changed_files(repos[0]) == ["result.txt"]
    assert (repository / "result.txt").read_text(encoding="utf-8") == "baseline\n"
    assert not (repository / "case-one").exists()
    assert not (repository / "case-two").exists()

    result = first.cases[0]
    assert result.patch_apply is True
    assert "result.txt" in result.changed_files
    assert "case-one" in result.patch
    assert result.input_tokens == 120
    assert result.output_tokens == 35
    assert result.total_tokens == 155
    assert result.retrieval_hit_at_k == 1.0
    assert result.metadata["tool_usage"] == {
        "call_count": 1,
        "result_count": 1,
        "success_count": 1,
        "failure_count": 0,
        "calls_by_tool": {"write_file": 1},
    }
    trace_path = tmp_path / "run-one" / result.artifacts["trace"]
    trace = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    assert [event["type"] for event in trace] == ["retrieval", "tool_call", "tool_result"]
    review_path = tmp_path / "run-one" / result.artifacts["manual_review"]
    review = review_path.read_text(encoding="utf-8")
    assert "不会把待复核项目计为通过" in review
    assert "改动文件：result.txt" in review
    assert "target=True; regression=True; oracle=True" in review
    assert "Agent 声称的测试结果与测试日志一致" in review


def test_runtime_snapshot_uses_requested_commit_and_hashes_eval_overlay(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "value.txt").write_text("pinned\n", encoding="utf-8")
    _git(source, "init", "-q")
    _git(source, "config", "user.email", "snapshot-test@example.invalid")
    _git(source, "config", "user.name", "Snapshot test")
    _git(source, "add", "-A")
    _git(source, "commit", "-qm", "first revision")
    pinned = _git(source, "rev-parse", "HEAD")
    (source / "value.txt").write_text("working tree changed\n", encoding="utf-8")
    _git(source, "commit", "-qam", "second revision")

    overlay = tmp_path / "overlay"
    (overlay / "scripts").mkdir(parents=True)
    (overlay / "agent/evals").mkdir(parents=True)
    (overlay / "scripts/run_eval_agent.py").write_text("print('adapter')\n", encoding="utf-8")
    (overlay / "scripts/run_eval_app.py").write_text("print('app adapter')\n", encoding="utf-8")
    (overlay / "agent/evals/telemetry.py").write_text("def record_eval_event(*args, **kwargs): pass\n", encoding="utf-8")
    snapshot = prepare_agent_runtime_snapshot(
        source_root=source,
        revision=pinned,
        destination=tmp_path / "run" / "agent-runtime",
        adapter_source_root=overlay,
    )

    assert snapshot.commit == pinned
    assert (snapshot.source_dir / "value.txt").read_text(encoding="utf-8") == "pinned\n"
    assert set(snapshot.overlay_files) == {"scripts/run_eval_agent.py", "scripts/run_eval_app.py", "agent/evals/telemetry.py", "agent/evals/__init__.py"}
    assert verify_agent_runtime_snapshot(snapshot)
    (snapshot.source_dir / "value.txt").write_text("tampered\n", encoding="utf-8")
    assert not verify_agent_runtime_snapshot(snapshot)


def test_plan_rejection_requires_pending_rejected_state_and_clean_workspace() -> None:
    evidence = {
        "plan_rejection_performed": True,
        "plan_pending_before_rejection": True,
        "workspace_clean_before_rejection": True,
        "workspace_clean_after_rejection": True,
        "final_plan_status": "rejected",
    }

    assert _plan_rejection_evidence_ok(evidence, []) is True
    assert _plan_rejection_evidence_ok(evidence, ["taskboard/tasks.py"]) is False
    assert _plan_rejection_evidence_ok({**evidence, "final_plan_status": "approved"}, []) is False
    assert _plan_rejection_evidence_ok({**evidence, "workspace_clean_after_rejection": False}, []) is False


def test_git_diff_normalizes_windows_patch_line_endings(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(EvalRunner, "_include_untracked_for_diff", lambda _workspace: None)
    monkeypatch.setattr(
        eval_runner_module.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "diff --git a/x b/x\r\n+line\r\n", ""),
    )

    assert EvalRunner._git_diff(tmp_path) == "diff --git a/x b/x\n+line\n"


def test_real_report_preserves_target_test_failure_diagnostics(tmp_path: Path, monkeypatch) -> None:
    repository, _ = _target_repo(tmp_path)
    source = _agent_source(tmp_path)
    config_dir = tmp_path / "private-config"
    config_dir.mkdir()
    env_file = config_dir / "model.env"
    env_file.write_text("", encoding="utf-8")
    _enable_fake_codegraph(monkeypatch)
    failing_test = [
        "python",
        "-c",
        "import sys; print('visible failure'); print('failure detail', file=sys.stderr); sys.exit(7)",
    ]

    report = _runner(tmp_path / "failed-run", source, env_file).run(
        [_case("case-fails", target_test=failing_test)], repository=repository
    )

    result = report.cases[0]
    assert result.status == "failed"
    assert result.target_tests_passed is False
    assert any("test failed (7)" in error and "visible failure" in error and "failure detail" in error for error in result.errors)
    test_log = (tmp_path / "failed-run" / result.artifacts["tests"]).read_text(encoding="utf-8")
    assert "EXIT: 7" in test_log
    assert "visible failure" in test_log
    assert "failure detail" in test_log
    report_json = json.loads((tmp_path / "failed-run" / "report.json").read_text(encoding="utf-8"))
    assert report_json["summary"]["failed_count"] == 1


@pytest.mark.parametrize("stage", ["regression", "oracle"])
def test_real_report_names_regression_and_oracle_failures(tmp_path: Path, monkeypatch, stage: str) -> None:
    repository, _ = _target_repo(tmp_path)
    source = _agent_source(tmp_path)
    config_dir = tmp_path / "private-config"
    config_dir.mkdir()
    env_file = config_dir / "model.env"
    env_file.write_text("", encoding="utf-8")
    _enable_fake_codegraph(monkeypatch)
    failure = ["python", "-c", "import sys; print('stage-specific failure'); sys.exit(9)"]
    case = _case("case-stage-fails")
    if stage == "regression":
        case.regression_tests = [failure]
    else:
        case.oracle_tests = [failure]

    report = _runner(tmp_path / f"failed-{stage}", source, env_file).run([case], repository=repository)

    result = report.cases[0]
    assert result.status == "failed"
    passed = result.regression_tests_passed if stage == "regression" else result.oracle_tests_passed
    assert passed is False
    assert any("test failed (9)" in error and "stage-specific failure" in error for error in result.errors)


def test_real_report_names_test_timeout(tmp_path: Path, monkeypatch) -> None:
    repository, _ = _target_repo(tmp_path)
    source = _agent_source(tmp_path)
    config_dir = tmp_path / "private-config"
    config_dir.mkdir()
    env_file = config_dir / "model.env"
    env_file.write_text("", encoding="utf-8")
    _enable_fake_codegraph(monkeypatch)
    case = _case("case-timeout", target_test=["python", "-c", "import time; time.sleep(3)"])
    case.timeout_seconds = 1

    report = _runner(tmp_path / "timed-out-run", source, env_file).run([case], repository=repository)

    result = report.cases[0]
    assert result.status == "failed"
    assert result.target_tests_passed is False
    assert any("test timeout:" in error for error in result.errors)
    assert "TIMEOUT:" in (tmp_path / "timed-out-run" / result.artifacts["tests"]).read_text(encoding="utf-8")


def test_patch_collection_uses_workspace_baseline_even_after_agent_commit(tmp_path: Path, monkeypatch) -> None:
    repository, _ = _target_repo(tmp_path)
    source = _agent_source(tmp_path)
    script = source / "scripts" / "run_eval_agent.py"
    content = script.read_text(encoding="utf-8")
    content = content.replace("import os\n", "import os\nimport subprocess\n")
    content = content.replace(
        '(repo / "result.txt").write_text(case_id + "\\n", encoding="utf-8")',
        '(repo / "result.txt").write_text(case_id + "\\n", encoding="utf-8")\n'
        'subprocess.run(["git", "add", "-A"], cwd=repo, check=True)\n'
        'subprocess.run(["git", "commit", "-m", "agent local commit"], cwd=repo, check=True)',
    )
    script.write_text(content, encoding="utf-8")
    _git(source, "add", "-A")
    _git(source, "commit", "-qm", "simulated Agent commits in its isolated answer sheet")
    config_dir = tmp_path / "private-config"
    config_dir.mkdir()
    env_file = config_dir / "model.env"
    env_file.write_text("", encoding="utf-8")
    _enable_fake_codegraph(monkeypatch)

    report = _runner(tmp_path / "committed-run", source, env_file).run([_case("committed-case")], repository=repository)

    result = report.cases[0]
    assert result.status == "passed"
    assert result.changed_files == ["result.txt"]
    assert "committed-case" in result.patch
    assert result.patch_apply is True
