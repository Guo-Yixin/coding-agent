from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent.evals.metrics import calculate_metrics
from agent.evals.schemas import EvalCase, EvalCaseResult, EvalReport


class EvalRunner:
    """Run reproducible coding-agent cases in clean local workspaces.

    The runner deliberately uses a command adapter instead of embedding a model
    provider.  A real Agent adapter and an OpenSandbox adapter can therefore
    produce the same `.eval/*.json` artifacts and share the scoring/reporting
    code.
    """

    def __init__(self, *, output_dir: Path, mode: str = "fake", python_executable: str | None = None) -> None:
        self.output_dir = output_dir
        self.mode = mode
        self.python_executable = python_executable or os.environ.get("PYTHON", sys.executable)

    def run(self, cases: list[EvalCase], *, repository: Path) -> EvalReport:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        manifest = json.dumps([case.to_dict() for case in cases], sort_keys=True, ensure_ascii=False)
        report_id = hashlib.sha256(manifest.encode("utf-8")).hexdigest()[:16]
        results = [self._run_case(case, repository=repository) for case in cases]
        report = EvalReport(
            report_id=report_id,
            mode=self.mode,
            repository=str(repository.resolve()),
            cases=results,
            config={"python": self.python_executable, "runner_version": "1"},
            created_at=datetime.now(UTC).isoformat(),
        )
        (self.output_dir / "report.json").write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        self._write_summary(report)
        return report

    def _run_case(self, case: EvalCase, *, repository: Path) -> EvalCaseResult:
        started = time.perf_counter()
        errors: list[str] = []
        with tempfile.TemporaryDirectory(prefix=f"eval-{case.case_id}-") as temp:
            workspace = Path(temp) / "repo"
            self._copy_repository(repository, workspace)
            self._init_git_baseline(workspace)
            eval_dir = workspace / ".eval"
            eval_dir.mkdir()
            command = case.fake_command if self.mode == "fake" else case.agent_command
            agent_exit, agent_output = self._run_command(command, workspace, case, eval_dir, errors)
            agent_latency = int((time.perf_counter() - started) * 1000)
            patch = self._git_diff(workspace)
            changed_files = self._changed_files(workspace)
            patch_apply = bool(agent_exit == 0 and (bool(patch) or not case.requires_patch))
            target_pass, target_latency = self._run_tests(case.target_tests, workspace, case.timeout_seconds, errors)
            regression_pass, regression_latency = self._run_tests(case.regression_tests, workspace, case.timeout_seconds, errors)
            retrieval = self._read_json(eval_dir / "retrieval.json", [])
            events = self._read_jsonl(eval_dir / "events.jsonl")
            usage = self._read_json(eval_dir / "usage.json", {})
            metric = calculate_metrics(retrieval=retrieval, events=events, usage=usage, gold_files=case.gold_files)
            status = "passed" if agent_exit == 0 and patch_apply and target_pass is not False and regression_pass is not False else "failed"
            artifact_dir = self.output_dir / "cases" / case.case_id
            artifact_dir.mkdir(parents=True, exist_ok=True)
            (artifact_dir / "agent-output.txt").write_text(agent_output, encoding="utf-8")
            (artifact_dir / "patch.diff").write_text(patch, encoding="utf-8")
            (artifact_dir / "events.jsonl").write_text("\n".join(json.dumps(item, ensure_ascii=False, sort_keys=True) for item in events), encoding="utf-8")
            return EvalCaseResult(
                case_id=case.case_id,
                status=status,
                agent_exit_code=agent_exit,
                patch_apply=patch_apply,
                target_tests_passed=target_pass,
                regression_tests_passed=regression_pass,
                retrieval_hit_at_k=metric["retrieval_hit_at_k"],
                tool_recovery_rate=metric["tool_recovery_rate"],
                input_tokens=metric["input_tokens"],
                output_tokens=metric["output_tokens"],
                total_tokens=metric["total_tokens"],
                agent_latency_ms=agent_latency,
                target_test_latency_ms=target_latency,
                regression_test_latency_ms=regression_latency,
                changed_files=changed_files,
                patch=patch,
                errors=errors,
                artifacts={"agent_output": str(artifact_dir / "agent-output.txt"), "patch": str(artifact_dir / "patch.diff")},
            )

    @staticmethod
    def _copy_repository(source: Path, destination: Path) -> None:
        ignored = shutil.ignore_patterns(".git", ".venv", ".codegraph", "__pycache__", ".pytest_cache", "*.sqlite", ".env")
        shutil.copytree(source, destination, ignore=ignored)

    @staticmethod
    def _init_git_baseline(workspace: Path) -> None:
        commands = [
            ["git", "init", "-q"],
            ["git", "config", "user.email", "eval@example.invalid"],
            ["git", "config", "user.name", "Agent Eval"],
            ["git", "add", "-A"],
            ["git", "commit", "-qm", "eval baseline"],
        ]
        for command in commands:
            subprocess.run(command, cwd=workspace, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace", shell=False)

    def _run_command(self, command: list[str] | None, workspace: Path, case: EvalCase, eval_dir: Path, errors: list[str]) -> tuple[int | None, str]:
        if not command:
            return 0, "no agent command configured"
        normalized = self._normalize_command(command)
        env = os.environ.copy()
        env.update({"EVAL_CASE_ID": case.case_id, "EVAL_PROMPT": case.prompt, "EVAL_WORKSPACE": str(workspace), "EVAL_ARTIFACT_DIR": str(eval_dir)})
        try:
            completed = subprocess.run(normalized, cwd=workspace, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=case.timeout_seconds, shell=False, check=False)
            output = (completed.stdout or "") + (completed.stderr or "")
            if completed.returncode != 0:
                errors.append(f"agent exit code {completed.returncode}: {output[-2000:]}")
            return completed.returncode, output
        except subprocess.TimeoutExpired as exc:
            errors.append(f"agent timeout after {case.timeout_seconds}s")
            return None, str(exc)

    def _run_tests(self, commands: list[list[str] | str], workspace: Path, timeout: int, errors: list[str]) -> tuple[bool | None, int]:
        if not commands:
            return None, 0
        started = time.perf_counter()
        passed = True
        for raw in commands:
            command = self._normalize_command(raw if isinstance(raw, list) else shlex.split(raw))
            try:
                completed = subprocess.run(command, cwd=workspace, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, shell=False, check=False)
            except subprocess.TimeoutExpired:
                errors.append(f"test timeout: {' '.join(command)}")
                passed = False
                continue
            if completed.returncode != 0:
                passed = False
                errors.append(f"test failed ({completed.returncode}): {' '.join(command)}\n{(completed.stdout + completed.stderr)[-2000:]}")
        return passed, int((time.perf_counter() - started) * 1000)

    def _normalize_command(self, command: list[str]) -> list[str]:
        if command and Path(command[0]).name in {"python", "python.exe"}:
            return [self.python_executable, *command[1:]]
        return command

    @staticmethod
    def _git_diff(workspace: Path) -> str:
        result = subprocess.run(["git", "diff", "--binary"], cwd=workspace, capture_output=True, text=True, encoding="utf-8", errors="replace", shell=False, check=False)
        return result.stdout

    @staticmethod
    def _changed_files(workspace: Path) -> list[str]:
        result = subprocess.run(["git", "diff", "--name-only"], cwd=workspace, capture_output=True, text=True, encoding="utf-8", errors="replace", shell=False, check=False)
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    @staticmethod
    def _read_json(path: Path, default: Any) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                value = json.loads(line)
                if isinstance(value, dict):
                    rows.append(value)
            except json.JSONDecodeError:
                continue
        return rows

    def _write_summary(self, report: EvalReport) -> None:
        data = report.to_dict()
        summary = data["summary"]
        lines = [
            f"# Agent Eval Report `{report.report_id}`",
            "",
            f"- mode: `{report.mode}`",
            f"- repository: `{report.repository}`",
            f"- cases: `{summary['case_count']}`",
            f"- passed: `{summary['passed_count']}`",
            f"- patch apply rate: `{summary['patch_apply_rate']}`",
            f"- target test pass rate: `{summary['target_test_pass_rate']}`",
            f"- regression test pass rate: `{summary['regression_test_pass_rate']}`",
            f"- retrieval hit@5: `{summary['retrieval_hit_at_k']}`",
            f"- tool recovery rate: `{summary['tool_recovery_rate']}`",
            f"- total tokens: `{summary['total_tokens']}`",
            f"- total latency: `{summary['total_latency_ms']} ms`",
            "",
            "## Cases",
            "",
        ]
        for case in report.cases:
            lines.append(f"- `{case.case_id}`: **{case.status}**, target={case.target_tests_passed}, regression={case.regression_tests_passed}, latency={case.agent_latency_ms}ms")
        (self.output_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
