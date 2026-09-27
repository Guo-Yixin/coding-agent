from __future__ import annotations

from pathlib import Path

from agent.sandbox.eval_backend import OpenSandboxEvalBackend


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
