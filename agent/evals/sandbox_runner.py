"""在 OpenSandbox 中运行同一套 Agent Eval case。"""

from __future__ import annotations

import shlex
import time
from pathlib import Path
from typing import Any, Callable

from agent.evals.metrics import calculate_metrics
from agent.evals.runner import EvalRunner
from agent.evals.schemas import EvalCase, EvalCaseResult
from agent.sandbox import OpenSandboxConfig, OpenSandboxExecutor, SandboxFile


class SandboxEvalRunner(EvalRunner):
    """把 EvalCase 的仓库快照和命令放进 OpenSandbox 执行。"""

    def __init__(
        self,
        *,
        output_dir: Path,
        config: OpenSandboxConfig | None = None,
        executor_factory: Callable[[OpenSandboxConfig], Any] | None = None,
    ) -> None:
        super().__init__(output_dir=output_dir, mode="sandbox")
        self.sandbox_config = config or OpenSandboxConfig.from_env()
        self.executor_factory = executor_factory or OpenSandboxExecutor

    def _run_case(self, case: EvalCase, *, repository: Path) -> EvalCaseResult:
        started = time.perf_counter()
        errors: list[str] = []
        executor = self.executor_factory(self.sandbox_config)
        agent_output = ""
        patch = ""
        changed_files: list[str] = []
        try:
            executor.start()
            source_files = self._sandbox_files(repository)
            executor.upload_files(source_files)
            self._run_remote(executor, "git init -q", cwd="repo", errors=errors)
            self._run_remote(executor, "git config user.email eval@example.invalid", cwd="repo", errors=errors)
            self._run_remote(executor, "git config user.name Agent-Eval", cwd="repo", errors=errors)
            self._run_remote(executor, "git add -A && git commit -qm 'eval baseline'", cwd="repo", errors=errors)
            self._run_remote(executor, "mkdir -p .eval", cwd="repo", errors=errors)

            command = case.agent_command
            if command:
                result = executor.execute(shlex.join(command), cwd="repo")
                agent_output = result.stdout + result.stderr
                if result.exit_code not in (0, None):
                    errors.append(f"agent exit code {result.exit_code}: {agent_output[-2000:]}")
                agent_exit = result.exit_code
            else:
                agent_exit = 0
                agent_output = "no agent command configured"
            agent_latency = int((time.perf_counter() - started) * 1000)

            patch = self._remote_text(executor, "git diff --binary", cwd="repo", errors=errors)
            changed_files = [
                line.strip()
                for line in self._remote_text(executor, "git diff --name-only", cwd="repo", errors=errors).splitlines()
                if line.strip()
            ]
            patch_apply = bool(agent_exit == 0 and (bool(patch) or not case.requires_patch))
            target_pass, target_latency = self._run_remote_tests(executor, case.target_tests, case.timeout_seconds, errors)
            regression_pass, regression_latency = self._run_remote_tests(executor, case.regression_tests, case.timeout_seconds, errors)
            retrieval = self._read_remote_json(executor, ".eval/retrieval.json")
            events = self._read_remote_jsonl(executor, ".eval/events.jsonl")
            usage = self._read_remote_json(executor, ".eval/usage.json")
            metric = calculate_metrics(retrieval=retrieval, events=events, usage=usage, gold_files=case.gold_files)
            status = "passed" if agent_exit == 0 and patch_apply and target_pass is not False and regression_pass is not False else "failed"
            return self._result(
                case=case, status=status, agent_exit=agent_exit, patch_apply=patch_apply,
                target_pass=target_pass, regression_pass=regression_pass,
                target_latency=target_latency, regression_latency=regression_latency,
                agent_latency=agent_latency, changed_files=changed_files, patch=patch,
                agent_output=agent_output, events=events, metric=metric, errors=errors,
            )
        except Exception as exc:
            errors.append(str(exc))
            return self._result(
                case=case, status="failed", agent_exit=None, patch_apply=False,
                target_pass=None, regression_pass=None, target_latency=0,
                regression_latency=0, agent_latency=int((time.perf_counter() - started) * 1000),
                changed_files=changed_files, patch=patch, agent_output=agent_output,
                events=[], metric=calculate_metrics(retrieval=[], events=[], usage={}, gold_files=case.gold_files),
                errors=errors,
            )
        finally:
            executor.close()

    @staticmethod
    def _sandbox_files(repository: Path) -> list[SandboxFile]:
        from agent.sandbox import collect_safe_workspace_files

        return [
            SandboxFile(path=f"repo/{item.path}", data=item.data, mode=item.mode)
            for item in collect_safe_workspace_files(repository)
        ]

    @staticmethod
    def _run_remote(executor: Any, command: str, *, cwd: str, errors: list[str]) -> Any:
        result = executor.execute(command, cwd=cwd)
        if result.exit_code not in (0, None):
            errors.append(f"remote command failed ({result.exit_code}): {command}\n{result.stderr[-1000:]}")
        return result

    def _remote_text(self, executor: Any, command: str, *, cwd: str, errors: list[str]) -> str:
        return str(self._run_remote(executor, command, cwd=cwd, errors=errors).stdout)

    def _run_remote_tests(self, executor: Any, commands: list[list[str] | str], timeout: int, errors: list[str]) -> tuple[bool | None, int]:
        if not commands:
            return None, 0
        started = time.perf_counter()
        passed = True
        for raw in commands:
            command = shlex.join(raw if isinstance(raw, list) else shlex.split(raw))
            result = executor.execute(command, cwd="repo")
            if result.exit_code not in (0, None):
                passed = False
                errors.append(f"remote test failed ({result.exit_code}): {command}\n{result.stderr[-1000:]}")
        return passed, int((time.perf_counter() - started) * 1000)

    @staticmethod
    def _read_remote_json(executor: Any, path: str) -> Any:
        import json

        try:
            return json.loads(executor.read_file(f"repo/{path}"))
        except Exception:
            return [] if path.endswith("retrieval.json") else {}

    @staticmethod
    def _read_remote_jsonl(executor: Any, path: str) -> list[dict[str, Any]]:
        import json

        try:
            rows: list[dict[str, Any]] = []
            for line in executor.read_file(f"repo/{path}").splitlines():
                value = json.loads(line)
                if isinstance(value, dict):
                    rows.append(value)
            return rows
        except Exception:
            return []

    def _result(self, *, case: EvalCase, status: str, agent_exit: int | None, patch_apply: bool,
                target_pass: bool | None, regression_pass: bool | None, target_latency: int,
                regression_latency: int, agent_latency: int, changed_files: list[str], patch: str,
                agent_output: str, events: list[dict[str, Any]], metric: dict[str, Any],
                errors: list[str]) -> EvalCaseResult:
        artifact_dir = self.output_dir / "cases" / case.case_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / "agent-output.txt").write_text(agent_output, encoding="utf-8")
        (artifact_dir / "patch.diff").write_text(patch, encoding="utf-8")
        import json

        (artifact_dir / "events.jsonl").write_text(
            "\n".join(json.dumps(item, ensure_ascii=False, sort_keys=True) for item in events), encoding="utf-8"
        )
        return EvalCaseResult(
            case_id=case.case_id, status=status, agent_exit_code=agent_exit,
            patch_apply=patch_apply, target_tests_passed=target_pass,
            regression_tests_passed=regression_pass,
            retrieval_hit_at_k=metric["retrieval_hit_at_k"],
            tool_recovery_rate=metric["tool_recovery_rate"],
            input_tokens=metric["input_tokens"], output_tokens=metric["output_tokens"],
            total_tokens=metric["total_tokens"], agent_latency_ms=agent_latency,
            target_test_latency_ms=target_latency, regression_test_latency_ms=regression_latency,
            changed_files=changed_files, patch=patch, errors=errors,
            artifacts={"agent_output": str(artifact_dir / "agent-output.txt"), "patch": str(artifact_dir / "patch.diff")},
        )
