from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from io import BytesIO
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent.evals.metrics import calculate_metrics
from agent.evals.reporting import write_report_artifacts
from agent.evals.schemas import EvalCase, EvalCaseResult, EvalReport


class EvalRunner:
    """Run reproducible coding-agent cases in clean local workspaces.

    The runner deliberately uses a command adapter instead of embedding a model
    provider.  A real Agent adapter and an OpenSandbox adapter can therefore
    produce the same `.eval/*.json` artifacts and share the scoring/reporting
    code.
    """

    def __init__(
        self,
        *,
        output_dir: Path,
        mode: str = "fake",
        python_executable: str | None = None,
        env_file: Path | None = None,
        agent_source_root: Path | None = None,
    ) -> None:
        self.output_dir = output_dir
        self.mode = mode
        self.python_executable = python_executable or os.environ.get("PYTHON", sys.executable)
        self.env_file = env_file.expanduser().resolve() if env_file else None
        self.agent_source_root = (agent_source_root or Path(__file__).resolve().parents[2]).expanduser().resolve()
        self._test_logs: list[str] = []

    def run(self, cases: list[EvalCase], *, repository: Path) -> EvalReport:
        repository = repository.resolve()
        self.output_dir = self.output_dir.expanduser().resolve()
        if self.mode == "real":
            if not cases:
                raise ValueError("Real Agent Eval requires at least one case")
            if self.output_dir == repository or repository in self.output_dir.parents:
                raise ValueError("Real Eval output must be outside the source repository")
            if (self.output_dir / "report.json").exists():
                raise FileExistsError(f"Refusing to overwrite existing Eval run: {self.output_dir}")
            if self.output_dir.exists() and any(self.output_dir.iterdir()):
                raise FileExistsError(f"Real Eval run directory must be new or empty: {self.output_dir}")
            if self.env_file is None or not self.env_file.is_file():
                raise ValueError("Real Eval requires --env-file pointing to the project's model configuration; the file is read-only and must remain outside the Eval workspace")
            for protected in self._protected_roots(repository):
                if self.output_dir == protected or protected in self.output_dir.parents or self.output_dir in protected.parents:
                    raise ValueError(f"Real Eval output overlaps protected source/configuration path: {protected}")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        manifest = json.dumps([case.to_dict() for case in cases], sort_keys=True, ensure_ascii=False)
        report_id = hashlib.sha256(manifest.encode("utf-8")).hexdigest()[:16]
        results: list[EvalCaseResult] = []
        for case in cases:
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", case.case_id):
                raise ValueError(f"Unsafe Eval case_id: {case.case_id!r}")
            try:
                results.append(self._run_real_case(case, repository=repository) if self.mode == "real" else self._run_case(case, repository=repository))
            except Exception as exc:
                if self.mode != "real":
                    raise
                errors = [self._sanitize_output(str(exc))[:2000]]
                failed = EvalCaseResult(
                    case_id=case.case_id,
                    status="failed",
                    agent_exit_code=None,
                    patch_apply=False,
                    target_tests_passed=None,
                    regression_tests_passed=None,
                    retrieval_hit_at_k=None,
                    tool_recovery_rate=None,
                    input_tokens=None,
                    output_tokens=None,
                    total_tokens=None,
                    agent_latency_ms=0,
                    target_test_latency_ms=0,
                    regression_test_latency_ms=0,
                    errors=errors,
                )
                results.append(failed)
                case_dir = self.output_dir / "cases" / case.case_id
                if case_dir.exists():
                    report_path = case_dir / "artifacts" / "report.json"
                    report_path.parent.mkdir(parents=True, exist_ok=True)
                    report_path.write_text(json.dumps(failed.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        source_sha = self._git_output(self.agent_source_root, "rev-parse", "HEAD").strip()
        remote_sha = self._git_output(repository, "rev-parse", "origin/main").strip()
        source_patch_sha = self._source_patch_fingerprint(self.agent_source_root)
        report = EvalReport(
            report_id=report_id,
            mode=self.mode,
            repository=str(repository.resolve()),
            cases=results,
            config={
                "python": self.python_executable,
                "runner_version": "2",
                "agent_source_sha": source_sha,
                "agent_source_dirty_patch_sha256": source_patch_sha,
                "agent_source_root": str(self.agent_source_root),
                "remote_main_sha": remote_sha or None,
            },
            created_at=datetime.now(UTC).isoformat(),
        )
        (self.output_dir / "report.json").write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        if self.mode == "real":
            (self.output_dir / "run.json").write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        self._write_summary(report)
        return report

    def _run_case(self, case: EvalCase, *, repository: Path) -> EvalCaseResult:
        if self.mode == "real":
            raise RuntimeError("Real mode uses the isolated production-runtime adapter; command mode cannot score it")
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

    def _run_real_case(self, case: EvalCase, *, repository: Path) -> EvalCaseResult:
        """Run the production runtime in a durable, per-case isolated workspace."""
        from agent.repository import parse_repo_url
        from agent.core.repo_memory import repo_project_dir

        started = time.perf_counter()
        self._test_logs = []
        errors: list[str] = []
        agent_adapter = self.agent_source_root / "scripts" / "run_eval_agent.py"
        if not agent_adapter.is_file():
            raise FileNotFoundError(f"Real Agent adapter not found in Agent source tree: {agent_adapter}")
        case_dir = self.output_dir / "cases" / case.case_id
        if case_dir.exists():
            raise FileExistsError(f"Refusing to reuse existing case directory: {case_dir}")
        case_dir.mkdir(parents=True)
        repo_url = str(case.metadata.get("repo_url") or self._git_output(repository, "remote", "get-url", "origin")).strip()
        parsed_repo = parse_repo_url(repo_url)
        target_sha = case.base_ref or self._git_output(repository, "rev-parse", "origin/main").strip()
        if not target_sha:
            target_sha = self._git_output(repository, "rev-parse", "HEAD").strip()
        if not target_sha or self._git_output(repository, "cat-file", "-e", f"{target_sha}^{{commit}}", check=False) is None:
            raise ValueError(f"Cannot resolve target baseline for case {case.case_id}: {target_sha}")

        workspace_root = case_dir / "workspace"
        repo_path = (workspace_root / repo_project_dir(parsed_repo)).resolve()
        oracle_root = case_dir / "oracle"
        oracle_repo = (oracle_root / "repo").resolve()
        state_dir = case_dir / "state"
        artifact_dir = case_dir / "artifacts"
        trace_dir = case_dir / "traces"
        for directory in (repo_path, oracle_repo, state_dir, artifact_dir, trace_dir):
            directory.mkdir(parents=True, exist_ok=True)
        protected = self._protected_roots(repository)
        db_paths = [state_dir / name for name in ("checkpoints.sqlite", "store.sqlite", "langgraph_store.sqlite")]
        for path in (repo_path, oracle_repo, workspace_root, *db_paths, artifact_dir, trace_dir):
            resolved = path.resolve()
            if any(resolved == item or item in resolved.parents for item in protected):
                raise ValueError(f"Eval path overlaps protected project data: {resolved}")

        self._extract_git_archive(repository, target_sha, repo_path)
        self._extract_git_archive(repository, target_sha, oracle_repo)
        self._init_git_baseline(repo_path)
        self._init_git_baseline(oracle_repo)

        index_started = time.perf_counter()
        codegraph = shutil.which(os.environ.get("CODEGRAPH_BIN", "codegraph"))
        index_result: dict[str, Any] = {"available": bool(codegraph), "succeeded": False}
        if not codegraph:
            errors.append("CodeGraph CLI is unavailable; hybrid retrieval can only use its lexical fallback")
        else:
            completed = subprocess.run(
                [codegraph, "init", str(repo_path), "--yes"], capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=case.timeout_seconds,
                check=False, shell=False, env=self._safe_subprocess_env(),
            )
            index_result.update({
                "exit_code": completed.returncode,
                "latency_ms": int((time.perf_counter() - index_started) * 1000),
                "succeeded": completed.returncode == 0,
                "output_tail": (completed.stdout + completed.stderr)[-1500:],
            })
            if completed.returncode != 0:
                errors.append(f"CodeGraph indexing failed ({completed.returncode})")

        trace_file = trace_dir / "agent-events.jsonl"
        agent_output_file = artifact_dir / "agent-output.txt"
        usage_file = trace_dir / "usage.json"
        result_file = trace_dir / "runtime-result.json"
        case_payload = case.to_dict()
        case_config = artifact_dir / "case-config.json"
        case_config.write_text(json.dumps(case_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        env = self._safe_subprocess_env()
        env.update({
            "CODING_AGENT_EVAL_MODE": "1",
            "EVAL_CASE_ID": case.case_id,
            "EVAL_PROMPT": case.prompt,
            "EVAL_CASE_REPO": str(repo_path),
            "EVAL_EVENT_FILE": str(trace_file),
            "EVAL_RESULT_FILE": str(result_file),
            "EVAL_USAGE_FILE": str(usage_file),
            "EVAL_CASE_CONFIG": str(case_config),
            "EVAL_REPO_URL": repo_url,
            "EVAL_MODEL_CALL_LIMIT": str(min(max(int(case.metadata.get("model_call_limit", 24)), 1), 40)),
            "EVAL_TOOL_CALL_LIMIT": str(min(max(int(case.metadata.get("tool_call_limit", 24)), 1), 40)),
            "AGENT_CODING_MAX_TOOL_CALLS": str(min(max(int(case.metadata.get("tool_call_limit", 24)), 1), 40)),
            "AGENT_CODING_MAX_SECONDS": str(max(1, case.timeout_seconds)),
            "AI_WORKSPACE_ROOT": str(workspace_root),
            "PERSISTENCE_BACKEND": "sqlite",
            "POSTGRES_DSN": "",
            "CODING_DATA_DIR": str(state_dir),
            "CHECKPOINT_DB_PATH": str(db_paths[0]),
            "STORE_DB_PATH": str(db_paths[1]),
            "LANGGRAPH_STORE_DB_PATH": str(db_paths[2]),
            "CODING_LOG_DIR": str(case_dir / "logs"),
            "PYTHONPATH": str(self.agent_source_root),
            "EVAL_AGENT_SOURCE_ROOT": str(self.agent_source_root),
            "EVAL_ENV_FILE": str(self.env_file) if self.env_file else "",
        })
        command = [self.python_executable, str(agent_adapter)]
        agent_exit: int | None = None
        agent_output = ""
        agent_latency = 0
        if not index_result["succeeded"]:
            errors.append("Real Agent was not started because the required target CodeGraph index was not built")
        else:
            agent_started = time.perf_counter()
            try:
                completed = subprocess.run(
                    command, cwd=repo_path, env=env, capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=case.timeout_seconds,
                    check=False, shell=False,
                )
                agent_exit = completed.returncode
                agent_output = (completed.stdout or "") + (completed.stderr or "")
                if agent_exit != 0:
                    errors.append(f"real Agent adapter exited with {agent_exit}: {agent_output[-2000:]}")
            except subprocess.TimeoutExpired as exc:
                errors.append(f"real Agent timed out after {case.timeout_seconds}s")
                agent_output = str(exc)
            agent_latency = int((time.perf_counter() - agent_started) * 1000)
        agent_output = self._sanitize_output(agent_output)
        agent_output_file.write_text(agent_output, encoding="utf-8")

        self._include_untracked_as_diff(repo_path)
        patch = self._git_diff(repo_path)
        changed_files = self._changed_files(repo_path)
        allowed_files = set(case.allowed_files)
        changed_outside = sorted(set(changed_files) - allowed_files) if allowed_files else []
        required_changed_files = {str(path).replace("\\", "/") for path in case.metadata.get("required_changed_files", [])}
        missing_required_files = sorted(required_changed_files - set(changed_files))
        if changed_outside and case.allowed_files:
            errors.append(f"Agent changed files outside allowed_files: {', '.join(changed_outside)}")
        if missing_required_files:
            errors.append(f"Agent did not modify required files: {', '.join(missing_required_files)}")
        if not case.requires_patch and changed_files:
            errors.append("Read-only Eval case changed repository files")
        patch_apply = False
        if agent_exit == 0 and (bool(patch) or not case.requires_patch) and not changed_outside:
            if patch:
                check = subprocess.run(["git", "apply", "--check", "-"], cwd=oracle_repo, input=patch,
                                       capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
                if check.returncode == 0:
                    applied = subprocess.run(["git", "apply", "-"], cwd=oracle_repo, input=patch,
                                              capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
                    patch_apply = applied.returncode == 0
                if not patch_apply:
                    errors.append(f"patch does not apply to clean oracle baseline: {(check.stderr or '')[-1000:]}")
            else:
                patch_apply = not case.requires_patch

        scorer_env = {**env, "PYTHONPATH": str(oracle_repo)}
        target_pass, target_latency = self._run_tests(case.target_tests, oracle_repo, case.timeout_seconds, errors, env=scorer_env)
        regression_pass, regression_latency = self._run_tests(case.regression_tests, oracle_repo, case.timeout_seconds, errors, env=scorer_env)
        oracle_commands = [
            [part.replace("{oracle_scripts}", str(Path(__file__).resolve().parent / "oracles"))
                 .replace("{target_repo}", str(oracle_repo)) for part in command]
            if isinstance(command, list)
            else command.replace("{oracle_scripts}", str(Path(__file__).resolve().parent / "oracles"))
                 .replace("{target_repo}", str(oracle_repo))
            for command in case.oracle_tests
        ]
        oracle_pass, oracle_latency = self._run_tests(oracle_commands, oracle_repo, case.timeout_seconds, errors, env=scorer_env)
        trace_events = self._read_jsonl(trace_file)
        retrieval_events = [event.get("payload", {}) for event in trace_events if event.get("type") == "retrieval"]
        retrieval = [hit for event in retrieval_events for hit in event.get("hits", [])]
        usage = self._read_json(usage_file, {})
        metric = calculate_metrics(retrieval=retrieval, events=trace_events, usage=usage, gold_files=case.gold_files)
        runtime_result = self._read_json(result_file, {})
        expected_status = case.expected_status
        runtime_status = runtime_result.get("status")
        model_limit_exceeded = bool(re.search(r"model call limits exceeded|run limit \(\d+/\d+\)|达到模型调用限制", agent_output, re.IGNORECASE))
        if model_limit_exceeded:
            errors.append("Agent reached its configured model-call limit before completing the case")
        required_output_terms = [str(term).lower() for term in case.metadata.get("required_output_terms", [])]
        missing_output_terms = [term for term in required_output_terms if term not in agent_output.lower()]
        if missing_output_terms:
            errors.append("Agent output omitted required evidence terms: " + ", ".join(missing_output_terms))
        case_pass = (
            agent_exit == 0
            and runtime_status == expected_status
            and patch_apply
            and target_pass is not False
            and regression_pass is not False
            and oracle_pass is not False
            and not changed_outside
            and not missing_required_files
            and (case.requires_patch or not changed_files)
            and not model_limit_exceeded
            and not missing_output_terms
            and bool(retrieval_events)
            and metric["retrieval_hit_at_k"] == 1.0 if case.gold_files else
            agent_exit == 0 and runtime_status == expected_status and patch_apply
            and target_pass is not False and regression_pass is not False and not changed_outside
            and not missing_required_files
            and (case.requires_patch or not changed_files)
            and oracle_pass is not False
            and not model_limit_exceeded
            and not missing_output_terms
        )
        if case.requires_patch and not case.target_tests:
            errors.append("Coding case requires at least one independent target test")
            case_pass = False
        if case.requires_patch and not case.oracle_tests:
            errors.append("Coding case requires independent oracle tests")
            case_pass = False
        if case.requires_patch and not case.allowed_files:
            errors.append("Coding case requires an explicit allowed_files list")
            case_pass = False
        errors = [self._sanitize_output(error) for error in errors]
        if case.gold_files and not retrieval_events:
            errors.append("No real hybrid retrieval event was recorded")
        status = "passed" if case_pass else "failed"
        patch_file = artifact_dir / "patch.diff"
        patch_file.write_text(patch, encoding="utf-8")
        (artifact_dir / "tests.log").write_text("\n".join(self._test_logs + ["ERROR: " + error for error in errors]), encoding="utf-8")
        case_report = EvalCaseResult(
            case_id=case.case_id,
            status=status,
            agent_exit_code=agent_exit,
            patch_apply=patch_apply,
            target_tests_passed=target_pass,
            regression_tests_passed=regression_pass,
            retrieval_hit_at_k=metric["retrieval_hit_at_k"] if retrieval_events else None,
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
            artifacts={
                "agent_output": str(agent_output_file.relative_to(self.output_dir)),
                "patch": str(patch_file.relative_to(self.output_dir)),
                "tests": str((artifact_dir / "tests.log").relative_to(self.output_dir)),
                "trace": str(trace_file.relative_to(self.output_dir)),
            },
            metadata={
                "target_repo_sha": target_sha,
                "repo_path": str(repo_path),
                "workspace_root": str(workspace_root),
                "state_files": [str(path) for path in db_paths if path.exists()],
                "codegraph_index": index_result,
                "runtime_status": runtime_status,
                "expected_status": expected_status,
                "model_call_limit": env["EVAL_MODEL_CALL_LIMIT"],
                "tool_call_limit": env["EVAL_TOOL_CALL_LIMIT"],
                "model_usage": usage,
                "model_provider": runtime_result.get("model_provider"),
                "model_name": runtime_result.get("model_name"),
                "retrieval_call_count": len(retrieval_events),
                "tool_usage": metric["tool_usage"],
                "test_behavior": {
                    "required_test_files": sorted(path for path in required_changed_files if path.startswith("tests/")),
                    "required_test_files_modified": not any(path.startswith("tests/") for path in missing_required_files),
                },
                "oracle_test_latency_ms": oracle_latency,
                "case_total_latency_ms": int((time.perf_counter() - started) * 1000),
            },
            oracle_tests_passed=oracle_pass,
        )
        (artifact_dir / "report.json").write_text(json.dumps(case_report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return case_report

    @staticmethod
    def _safe_subprocess_env() -> dict[str, str]:
        keep = {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE", "HOME", "APPDATA", "LOCALAPPDATA", "VIRTUAL_ENV", "PYTHON", "PYTHONPATH", "CODEGRAPH_BIN"}
        env = {key: value for key, value in os.environ.items() if key.upper() in keep}
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["GCM_INTERACTIVE"] = "Never"
        return env

    def _protected_roots(self, repository: Path) -> set[Path]:
        protected = {repository.resolve(), Path(__file__).resolve().parents[2], Path(__file__).resolve().parents[2] / ".env"}
        if self.env_file is not None:
            protected.add(self.env_file.resolve().parent)
        common_dir = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"], cwd=repository,
            env=self._safe_subprocess_env(), capture_output=True, text=True,
            encoding="utf-8", errors="replace", check=False, shell=False,
        )
        if common_dir.returncode == 0 and common_dir.stdout.strip():
            path = Path(common_dir.stdout.strip())
            if not path.is_absolute():
                path = (repository / path).resolve()
            if path.name == ".git":
                protected.add(path.parent.resolve())
        return protected

    @staticmethod
    def _sanitize_output(value: str) -> str:
        value = re.sub(r"(?i)(api[_-]?key|token|password|secret)(\s*[=:]\s*)([^\s,;]+)", r"\1\2[REDACTED]", value)
        for key, secret in os.environ.items():
            if any(marker in key.upper() for marker in ("API_KEY", "_TOKEN", "_SECRET", "_PASSWORD", "_DSN")) and secret:
                value = value.replace(secret, "[REDACTED]")
        return value

    @staticmethod
    def _include_untracked_as_diff(workspace: Path) -> None:
        result = subprocess.run(["git", "ls-files", "--others", "--exclude-standard"], cwd=workspace,
                                env=EvalRunner._safe_subprocess_env(), capture_output=True, text=True,
                                encoding="utf-8", errors="replace", check=False, shell=False)
        if result.returncode != 0:
            raise RuntimeError("Cannot inspect untracked Agent changes")
        for relative in result.stdout.splitlines():
            if relative == ".codegraph" or relative.startswith(".codegraph/") or relative == ".eval" or relative.startswith(".eval/"):
                continue
            path = (workspace / relative).resolve()
            if workspace.resolve() not in path.parents:
                raise RuntimeError(f"Agent created an untracked path outside its checkout: {relative}")
            added = subprocess.run(["git", "add", "-N", "--", relative], cwd=workspace,
                                   env=EvalRunner._safe_subprocess_env(), capture_output=True,
                                   text=True, encoding="utf-8", errors="replace", check=False, shell=False)
            if added.returncode != 0:
                raise RuntimeError(f"Cannot capture untracked Agent change: {relative}")

    @staticmethod
    def _git_output(repository: Path, *args: str, check: bool = True) -> str | None:
        completed = subprocess.run(["git", *args], cwd=repository, env=EvalRunner._safe_subprocess_env(), capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", check=False, shell=False)
        if completed.returncode != 0:
            if check:
                return ""
            return None
        return completed.stdout.strip()

    @classmethod
    def _source_patch_fingerprint(cls, repository: Path) -> str | None:
        patch = cls._git_output(repository, "diff", "--binary", "HEAD") or ""
        untracked = cls._git_output(repository, "ls-files", "--others", "--exclude-standard") or ""
        digest = hashlib.sha256(patch.encode("utf-8", errors="replace"))
        included_untracked = False
        for relative in sorted(Path(item) for item in untracked.splitlines()):
            normalized = relative.as_posix()
            if not (normalized.startswith("agent/evals/") or normalized == "scripts/run_eval_agent.py"):
                continue
            path = repository / relative
            if path.is_file():
                included_untracked = True
                digest.update(normalized.encode("utf-8"))
                digest.update(path.read_bytes())
        return digest.hexdigest() if patch or included_untracked else None

    @staticmethod
    def _extract_git_archive(repository: Path, ref: str, destination: Path) -> None:
        completed = subprocess.run(["git", "archive", "--format=tar", ref], cwd=repository,
                                   env=EvalRunner._safe_subprocess_env(), capture_output=True, check=False, shell=False)
        if completed.returncode != 0:
            raise RuntimeError(f"git archive failed for target ref {ref}")
        destination.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=BytesIO(completed.stdout), mode="r:") as archive:
            members = archive.getmembers()
            if any(Path(member.name).is_absolute() or ".." in Path(member.name).parts for member in members):
                raise RuntimeError("Git archive contains an unsafe path")
            for member in members:
                if member.issym() or member.islnk():
                    target = Path(member.name).parent / member.linkname
                    normalized: list[str] = []
                    for part in target.parts:
                        if part in {"", "."}:
                            continue
                        if part == "..":
                            if not normalized:
                                raise RuntimeError("Git archive contains a link that escapes its root")
                            normalized.pop()
                        else:
                            normalized.append(part)
            archive.extractall(destination, members=members)

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
            subprocess.run(command, cwd=workspace, env=EvalRunner._safe_subprocess_env(), check=True, capture_output=True, text=True, encoding="utf-8", errors="replace", shell=False)

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

    def _run_tests(
        self,
        commands: list[list[str] | str],
        workspace: Path,
        timeout: int,
        errors: list[str],
        *,
        env: dict[str, str] | None = None,
    ) -> tuple[bool | None, int]:
        if not commands:
            return None, 0
        started = time.perf_counter()
        passed = True
        for raw in commands:
            command = self._normalize_command(raw if isinstance(raw, list) else shlex.split(raw))
            try:
                completed = subprocess.run(command, cwd=workspace, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, shell=False, check=False)
            except subprocess.TimeoutExpired:
                errors.append(f"test timeout: {' '.join(command)}")
                self._test_logs.append(f"TIMEOUT: {' '.join(command)}")
                passed = False
                continue
            self._test_logs.append(
                f"COMMAND: {' '.join(command)}\nEXIT: {completed.returncode}\n"
                f"STDOUT:\n{completed.stdout[-8000:]}\nSTDERR:\n{completed.stderr[-8000:]}"
            )
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
        result = subprocess.run(["git", "diff", "--binary", "HEAD"], cwd=workspace, env=EvalRunner._safe_subprocess_env(), capture_output=True, text=True, encoding="utf-8", errors="replace", shell=False, check=False)
        return result.stdout

    @staticmethod
    def _changed_files(workspace: Path) -> list[str]:
        result = subprocess.run(["git", "diff", "--name-only", "HEAD"], cwd=workspace, env=EvalRunner._safe_subprocess_env(), capture_output=True, text=True, encoding="utf-8", errors="replace", shell=False, check=False)
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
            f"- oracle test pass rate: `{summary['oracle_test_pass_rate']}`",
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
        write_report_artifacts(report, self.output_dir)
