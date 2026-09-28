"""Coding-Agent backend that binds Eval file and command tools to OpenSandbox.

The host keeps only an empty path-mapping workspace. Repository source bytes are
uploaded to an ephemeral container; all Agent file operations and commands are
handled by the OpenSandbox service. At task end, a binary Git diff is exported
and applied to the case's disposable host checkout for independent scoring.
"""

from __future__ import annotations

import base64
import atexit
import json
import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any
from uuid import uuid4

from deepagents.backends.protocol import ExecuteResponse, FileDownloadResponse, FileUploadResponse
from deepagents.backends.sandbox import BaseSandbox

from agent.backends.local_shell import CommandResult, LocalShellBackend
from agent.sandbox.opensandbox_executor import OpenSandboxExecutor, SandboxFile


class OpenSandboxEvalBackend(LocalShellBackend):
    """Use LocalShell's virtual path policy with BaseSandbox's remote file helpers."""

    _sandbox_root = ""

    def __init__(
        self, *args: Any, runtime_case_repo: str | Path | None = None,
        runtime_repo_url: str | None = None, runtime_branch: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        from agent.sandbox.opensandbox_executor import OpenSandboxConfig

        self.executor = OpenSandboxExecutor(OpenSandboxConfig.from_env())
        self.runtime_mode = runtime_case_repo is not None
        if self.runtime_mode:
            self.case_repo = Path(runtime_case_repo).expanduser().resolve()
            self.repo_url = str(runtime_repo_url or "").strip()
            if not self.repo_url:
                raise ValueError("OpenSandbox runtime requires a selected repository URL")
            self.runtime_branch = runtime_branch or "codex/sandbox-task"
        else:
            self.case_repo = Path(os.environ["EVAL_CASE_REPO"]).expanduser().resolve()
            self.repo_url = os.environ["EVAL_REPO_URL"].strip()
            self.runtime_branch = "eval-baseline"
        self._closed = False
        self._uploaded_file_count = 0
        self._uploaded_bytes = 0
        self._execute_injection_remaining = 0
        self._pending_execute_recovery: str | None = None
        case_config = "" if self.runtime_mode else os.environ.get("EVAL_CASE_CONFIG", "").strip()
        if case_config:
            try:
                payload = json.loads(Path(case_config).read_text(encoding="utf-8"))
                injection = payload.get("metadata", {}).get("inject_tool_error_once", {})
                if str(injection.get("tool", "")).lower() in {"execute", "sandbox_execute"}:
                    self._execute_injection_remaining = 1
            except (OSError, json.JSONDecodeError, AttributeError):
                pass
        self._sandbox_id = self.executor.start()
        atexit.register(self._close_at_exit)
        try:
            self._upload_snapshot()
            self._initialize_candidate_repo()
        except Exception:
            self._closed = True
            try:
                self.executor.close()
            except Exception:
                pass
            raise

    def _close_at_exit(self) -> None:
        try:
            self.close()
        except Exception:
            # Explicit runtime close surfaces export/cleanup errors to the worker;
            # interpreter shutdown must not emit an unhandled atexit traceback.
            pass

    @property
    def id(self) -> str:
        return f"opensandbox:{self._sandbox_id}"

    def _remote_path(self, path: str | Path) -> str:
        raw = str(path).replace("\\", "/")
        if raw.startswith("/workspace/"):
            raw = raw.removeprefix("/workspace")
        if raw.startswith("/tmp/.deepagents_edit_"):
            return raw
        local = self._resolve_virtual_path(self._normalize_compat_path(raw))
        relative = local.resolve().relative_to(self.root.resolve())
        return "/" + relative.as_posix() if relative.parts else "/"

    def _remote_cwd(self, path: str | Path | None) -> str:
        virtual = self.working_dir if path is None or str(path) in {"", "."} else str(path)
        return self._remote_path(virtual)

    def _upload_snapshot(self) -> None:
        from agent.sandbox.opensandbox_executor import collect_safe_workspace_files

        if self.runtime_mode:
            roots = [self.case_repo, self.skills_dir, self.policies_dir]
            files = []
            for source_root in roots:
                if not source_root.is_dir():
                    continue
                prefix = source_root.resolve().relative_to(self.root.resolve()).as_posix()
                files.extend(
                    type(item)(path=f"{prefix}/{item.path}", data=item.data, mode=item.mode)
                    for item in collect_safe_workspace_files(
                        source_root, max_file_bytes=self.executor.config.max_upload_bytes
                    )
                )
        else:
            files = collect_safe_workspace_files(self.root, max_file_bytes=self.executor.config.max_upload_bytes)
        total_bytes = sum(len(item.data) for item in files)
        if total_bytes > 32 * 1024 * 1024:
            raise ValueError("Eval workspace snapshot exceeds the 32 MiB OpenSandbox upload budget")
        self._uploaded_file_count = self.executor.upload_files(files)
        self._uploaded_bytes = total_bytes

    def _initialize_candidate_repo(self) -> None:
        remote_repo = self._remote_path(self.working_dir)
        commands = [
            "mkdir -p " + shlex.quote(remote_repo),
            "git init -b " + shlex.quote(self.runtime_branch) + " " + shlex.quote(remote_repo),
            "git -C " + shlex.quote(remote_repo) + " config user.name 'Agent Eval'",
            "git -C " + shlex.quote(remote_repo) + " config user.email 'agent-eval@localhost'",
            "git -C " + shlex.quote(remote_repo) + " add -A",
            "git -C " + shlex.quote(remote_repo) + " commit -m 'Pinned Agent Eval baseline'",
            "git -C " + shlex.quote(remote_repo) + " remote add origin " + shlex.quote(self.repo_url),
        ]
        provision = self.executor.execute(
            " && ".join(commands), cwd=remote_repo, timeout=180
        )
        if provision.exit_code != 0:
            raise RuntimeError("Could not initialize isolated sandbox Git baseline")
        tools = self.executor.execute("git --version && python --version", cwd=remote_repo)
        if tools.exit_code != 0:
            raise RuntimeError("The configured OpenSandbox image must include git and pytest")

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        if self._execute_injection_remaining:
            self._execute_injection_remaining -= 1
            probe_id = uuid4().hex
            self._pending_execute_recovery = probe_id
            self._record("tool_error", {
                "probe_id": probe_id,
                "tool_name": "sandbox_execute",
                "injected": True,
                "error_type": "InjectedSandboxCommandError",
            })
            return ExecuteResponse(
                output="评测注入的一次性沙箱命令失败；请检查错误并重试或改用其他命令验证。",
                exit_code=75,
                truncated=False,
            )
        base_sandbox_script = command.lstrip().startswith(("python3 -c", "python -c"))
        if self.command_guard_enabled and not base_sandbox_script:
            denied = self._deny_reason(command)
            if denied:
                return ExecuteResponse(output=f"命令被拒绝：{denied}", exit_code=126, truncated=False)
        if (getattr(self, "runtime_mode", False) or os.environ.get("CODING_AGENT_EVAL_MODE", "").strip() == "1") and self._blocks_git_write(command):
            return ExecuteResponse(output="OpenSandbox blocks Git history and remote write commands", exit_code=126, truncated=False)
        remote_command = self._map_command_paths(command)
        try:
            result = self.executor.execute(
                remote_command,
                cwd=self._remote_cwd(None),
                timeout=timeout,
            )
        except TimeoutError:
            return ExecuteResponse(output="OpenSandbox 命令执行超时", exit_code=124, truncated=False)
        output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
        self._record("sandbox_command", {
            "sandbox_id": self._sandbox_id,
            "exit_code": result.exit_code,
            "duration_ms": result.duration_ms,
            "command_class": self._command_class(command),
        })
        if result.exit_code == 0 and self._pending_execute_recovery:
            self._record("tool_recovery", {
                "probe_id": self._pending_execute_recovery,
                "tool_name": "sandbox_execute",
                "strategy": "retry_or_alternate_sandbox_command",
                "success": True,
            })
            self._pending_execute_recovery = None
        if len(output) > 500_000:
            output = output[:250_000] + "\n...[sandbox output truncated]...\n" + output[-250_000:]
            return ExecuteResponse(output=output, exit_code=result.exit_code, truncated=True)
        return ExecuteResponse(output=output, exit_code=result.exit_code, truncated=False)

    @staticmethod
    def _command_class(command: str) -> str:
        first = command.strip().split(maxsplit=1)[0].lower() if command.strip() else "empty"
        return first[:40]

    def _map_command_paths(self, command: str) -> str:
        # BaseSandbox helpers pass validated host-side virtual paths through
        # execute(). Remap those path literals to the identical remote layout.
        root_variants = {str(self.root), str(self.root).replace("\\", "/")}
        mapped = command
        for root in sorted(root_variants, key=len, reverse=True):
            mapped = mapped.replace(root, self._sandbox_root)
        virtual = re.compile(r"(?<![A-Za-z0-9])/(projects|skills|policies|reviews|runtimes|tmp|logs)(/[A-Za-z0-9._~!$&'()+,;=@%-]+(?:/[A-Za-z0-9._~!$&'()+,;=@%-]+)*)?")
        return virtual.sub(lambda match: self._sandbox_root + match.group(0), mapped)

    @staticmethod
    def _blocks_git_write(command: str) -> bool:
        forbidden = re.compile(
            r"(?i)\b(push|commit|fetch|pull|reset|clean|worktree|merge|rebase|tag|config|"
            r"checkout|switch|cherry-pick|revert|stash|am|apply)\b"
        )
        for match in re.finditer(r"(?i)\bgit(?:\.exe)?\b", command):
            tail = re.split(r"&&|\|\||[;|\r\n]", command[match.end():], maxsplit=1)[0]
            if forbidden.search(tail):
                return True
            remote = re.search(r"(?i)\bremote\b(?:\s+([^\s]+))?", tail)
            if remote and remote.group(1) and remote.group(1).lower() not in {"get-url", "show", "-v", "--verbose"}:
                return True
        return False

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        responses: list[FileUploadResponse] = []
        for path, content in files:
            try:
                remote = self._remote_path(path)
                relative = remote.lstrip("/")
                self.executor.upload_files([SandboxFile(path=relative, data=content)])
                responses.append(FileUploadResponse(path=path, error=None))
            except PermissionError:
                responses.append(FileUploadResponse(path=path, error="permission_denied"))
            except Exception:
                responses.append(FileUploadResponse(path=path, error="invalid_path"))
        return responses

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        responses: list[FileDownloadResponse] = []
        for path in paths:
            try:
                remote = self._remote_path(path)
                encoded = base64.b64encode(remote.encode("utf-8")).decode("ascii")
                command = (
                    "python3 -c \"import base64,pathlib;"
                    f"p=base64.b64decode('{encoded}').decode();"
                    "print(base64.b64encode(pathlib.Path(p).read_bytes()).decode())\""
                )
                result = self.executor.execute(command, cwd=self._remote_cwd(None), timeout=30)
                if result.exit_code != 0:
                    responses.append(FileDownloadResponse(path=path, content=None, error="file_not_found"))
                else:
                    responses.append(FileDownloadResponse(path=path, content=base64.b64decode(result.stdout.strip()), error=None))
            except Exception:
                responses.append(FileDownloadResponse(path=path, content=None, error="invalid_path"))
        return responses

    # LocalShellBackend has local implementations for these APIs. Explicitly
    # route them through BaseSandbox, whose implementation uses execute/upload.
    def ls(self, path: str):
        result = BaseSandbox.ls(self, self._remote_path(path))
        if result.entries:
            result.entries = [
                {**entry, "path": str(entry.get("path", "")) or "/"}
                for entry in result.entries
            ]
        return result

    def read(self, file_path: str, offset: int = 0, limit: int = 2000):
        return BaseSandbox.read(self, self._remote_path(file_path), offset=offset, limit=limit)

    def write(self, file_path: str, content: str):
        remote = self._remote_path(file_path)
        preflight = BaseSandbox._write_preflight(self, remote)
        if preflight is not None:
            return preflight
        response = self.upload_files([(remote, content.encode("utf-8"))])[0]
        from deepagents.backends.protocol import WriteResult

        return WriteResult(error=response.error) if response.error else WriteResult(path=file_path)

    def edit(self, file_path: str, old_string: str, new_string: str, replace_all: bool = False):
        return BaseSandbox.edit(self, self._remote_path(file_path), old_string, new_string, replace_all=replace_all)

    def glob(self, pattern: str, path: str | None = None):
        remote = self._remote_path(path or "/")
        result = BaseSandbox.glob(self, pattern, remote)
        if result.matches:
            for match in result.matches:
                match["path"] = str(match.get("path", "")) or "/"
        return result

    def grep(self, pattern: str, path: str | None = None, glob: str | None = None, *, max_count: int | None = None):
        remote = self._remote_path(path or self.working_dir)
        result = BaseSandbox.grep(self, pattern, remote, glob, max_count=max_count)
        if result.matches:
            for match in result.matches:
                match["path"] = str(match.get("path", "")) or "/"
        return result

    def delete(self, file_path: str):
        return BaseSandbox.delete(self, self._remote_path(file_path))

    def write_file(self, path: str, content: str) -> str:
        result = self.upload_files([(path, content.encode("utf-8"))])[0]
        if result.error:
            raise PermissionError(result.error)
        return self._remote_path(path)

    def read_file(self, path: str) -> str:
        result = self.read(path, offset=0, limit=200_000)
        if result.error:
            raise FileNotFoundError(result.error)
        return str(result.file_data.get("content", "") if result.file_data else "")

    def list_files(self, path: str = ".") -> list[str]:
        result = BaseSandbox.ls(self, path)
        if result.error:
            return []
        return [str(entry.get("path")) for entry in result.entries or []]

    def run(self, command: str, cwd: str = ".", timeout: int = 300) -> CommandResult:
        cwd_path = self._remote_cwd(cwd)
        response = self.execute(command, timeout=timeout)
        return CommandResult(
            command=command,
            cwd=cwd_path,
            exit_code=int(response.exit_code if response.exit_code is not None else 1),
            stdout=response.output,
            stderr="",
        )

    def workspace_is_clean(self) -> bool:
        result = self.executor.execute(
            "git status --porcelain --untracked-files=all",
            cwd=self._remote_cwd(None),
            timeout=30,
        )
        return result.exit_code == 0 and not result.stdout.strip()

    def close(self) -> dict[str, Any]:
        if self._closed:
            return {"sandbox_id": self._sandbox_id, "cleanup_succeeded": True, "already_closed": True}
        self._closed = True
        evidence: dict[str, Any] = {
            "sandbox_id": self._sandbox_id,
            "uploaded_file_count": self._uploaded_file_count,
            "uploaded_bytes": self._uploaded_bytes,
            "target_workspace": "OpenSandbox:/",
            "host_patch_exported": False,
            "cleanup_succeeded": False,
        }
        try:
            cwd = self._remote_cwd(None)
            diff = self.executor.execute(
                "git add -N -- .; git diff --binary HEAD | base64 -w0",
                cwd=cwd,
                timeout=60,
            )
            if diff.exit_code != 0:
                raise RuntimeError("Could not create a binary patch from the OpenSandbox candidate")
            patch = base64.b64decode(diff.stdout.strip()) if diff.stdout.strip() else b""
            evidence["patch_bytes"] = len(patch)
            if patch:
                check = subprocess.run(
                    ["git", "apply", "--check", "--binary", "-"],
                    cwd=self.case_repo,
                    input=patch,
                    env=LocalShellBackend._execution_env(self),
                    capture_output=True,
                    check=False,
                    shell=False,
                )
                if check.returncode != 0:
                    raise RuntimeError("OpenSandbox patch did not apply to its pinned host case checkout")
                applied = subprocess.run(
                    ["git", "apply", "--binary", "-"],
                    cwd=self.case_repo,
                    input=patch,
                    env=LocalShellBackend._execution_env(self),
                    capture_output=True,
                    check=False,
                    shell=False,
                )
                if applied.returncode != 0:
                    raise RuntimeError("Could not export the OpenSandbox patch into the disposable host case checkout")
            evidence["host_patch_exported"] = True
            self._record("sandbox_patch_export", evidence)
        except Exception as exc:
            evidence["error"] = type(exc).__name__
            self._record("sandbox_patch_export_error", evidence)
        finally:
            try:
                self.executor.close()
                evidence["cleanup_succeeded"] = True
            except Exception as exc:
                evidence["cleanup_error"] = type(exc).__name__
        return evidence

    @staticmethod
    def _record(event_type: str, payload: dict[str, Any]) -> None:
        try:
            from agent.evals.telemetry import record_eval_event

            record_eval_event(event_type, payload)
        except Exception:
            pass


class OpenSandboxRuntimeBackend(OpenSandboxEvalBackend):
    """Per-run remote backend that exports only its checkout patch to the host."""

    def __init__(
        self, *, working_dir: str, case_repo: str | Path, repo_url: str,
        branch_name: str, provider: str | None = None,
    ) -> None:
        super().__init__(
            provider=provider,
            working_dir=working_dir,
            runtime_case_repo=case_repo,
            runtime_repo_url=repo_url,
            runtime_branch=branch_name,
        )

    def close(self) -> dict[str, Any]:
        previous = getattr(self, "_runtime_close_evidence", None)
        if previous is not None:
            return previous
        evidence = super().close()
        self._runtime_close_evidence = evidence
        if not evidence.get("host_patch_exported") or not evidence.get("cleanup_succeeded"):
            raise RuntimeError(
                "OpenSandbox runtime could not safely export the task patch or destroy its sandbox: "
                + str(evidence.get("error") or evidence.get("cleanup_error") or "unknown failure")
            )
        return evidence

    @staticmethod
    def _record(event_type: str, payload: dict[str, Any]) -> None:
        try:
            from agent.evals.telemetry import record_eval_event

            record_eval_event(event_type, payload)
        except Exception:
            pass


def close_opensandbox_backends(backends: list[Any]) -> list[dict[str, Any]]:
    """Export patches and destroy the sandboxes created for one Eval process."""

    evidence: list[dict[str, Any]] = []
    seen: set[int] = set()
    for backend in backends:
        if isinstance(backend, OpenSandboxEvalBackend) and id(backend) not in seen:
            seen.add(id(backend))
            evidence.append(backend.close())
    return evidence
