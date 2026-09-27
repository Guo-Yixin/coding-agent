from __future__ import annotations

from pathlib import Path

from agent.sandbox.eval_backend import OpenSandboxEvalBackend
from agent.sandbox.opensandbox_executor import SandboxExecution


def _backend(tmp_path: Path) -> OpenSandboxEvalBackend:
    backend = object.__new__(OpenSandboxEvalBackend)
    backend.root = tmp_path.resolve()
    backend.projects_dir = backend.root / "projects"
    backend.skills_dir = backend.root / "skills"
    backend.policies_dir = backend.root / "policies"
    backend.reviews_dir = backend.root / "reviews"
    backend.runtimes_dir = backend.root / "runtimes"
    backend.tmp_dir = backend.root / "tmp"
    backend.logs_dir = backend.root / "logs"
    backend.working_dir = "/projects/github-owner-repo"
    return backend


def test_opensandbox_backend_maps_agent_virtual_paths_without_host_paths(tmp_path: Path):
    backend = _backend(tmp_path)

    assert backend._remote_path("/projects/github-owner-repo/taskboard/tasks.py") == (
        "/projects/github-owner-repo/taskboard/tasks.py"
    )
    mapped = backend._map_command_paths(
        'python -m pytest tests/test_search_tasks.py -q --config "/projects/github-owner-repo/pyproject.toml"'
    )
    assert str(tmp_path) not in mapped
    assert "/projects/github-owner-repo/pyproject.toml" in mapped
    assert backend._remote_cwd(None) == "/projects/github-owner-repo"


def test_opensandbox_backend_rejects_workspace_escape_and_eval_git_writes(tmp_path: Path):
    backend = _backend(tmp_path)

    try:
        backend._remote_path("/projects/../../outside.py")
    except PermissionError:
        pass
    else:
        raise AssertionError("path traversal must be rejected before remote execution")

    assert not backend._blocks_git_write("git status --short")
    assert not backend._blocks_git_write("git remote get-url origin")
    assert backend._blocks_git_write("git push origin main")
    assert backend._blocks_git_write("git -C repo commit -m done")


def test_sandbox_command_error_injection_records_recovery_after_success(tmp_path: Path, monkeypatch):
    backend = _backend(tmp_path)
    backend.command_guard_enabled = False
    backend._sandbox_id = "sandbox-test"
    backend._execute_injection_remaining = 1
    backend._pending_execute_recovery = None
    monkeypatch.setenv("CODING_AGENT_EVAL_MODE", "0")
    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(OpenSandboxEvalBackend, "_record", staticmethod(lambda name, payload: events.append((name, payload))))

    class FakeExecutor:
        sandbox_id = "sandbox-test"

        def execute(self, command: str, *, cwd: str | None = None, timeout: int | None = None):
            return SandboxExecution(
                sandbox_id=self.sandbox_id,
                command=command,
                exit_code=0,
                stdout="tests passed",
                stderr="",
                duration_ms=12,
            )

    backend.executor = FakeExecutor()
    first = backend.execute("python -m pytest -q")
    second = backend.execute("python -m pytest -q")

    assert first.exit_code == 75
    assert second.exit_code == 0
    assert [name for name, _ in events] == ["tool_error", "sandbox_command", "tool_recovery"]
    assert events[0][1]["probe_id"] == events[2][1]["probe_id"]
    assert events[2][1]["success"] is True
