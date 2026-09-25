from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.core.repository_workspace import (
    RepositoryWorkspaceError,
    prepare_repository_workspace,
    task_branch_name,
)
from agent.repository import parse_repo_url
from agent.backends.local_shell import LocalShellBackend
from agent.backends.workspace import Workspace


class FakeGitBackend:
    def __init__(self, root: Path, *, remote_url: str | None = None, default_branch: str = "main") -> None:
        self.workspace = Workspace(root)
        self.projects_dir = root / "projects"
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self.remote_url = remote_url
        self.default_branch = default_branch
        self.current_branch = default_branch
        self.dirty = False
        self.commands: list[str] = []
        self.cloned = False

    def run(self, command: str, *, cwd: str = ".", timeout: int = 300):
        del timeout
        self.commands.append(command)
        if command.startswith("git clone -- "):
            _, _, _, url, dirname = command.split(maxsplit=4)
            target = self.projects_dir / dirname
            target.mkdir()
            (target / ".git").mkdir()
            self.remote_url = url
            self.cloned = True
            return self._result(0)
        if command == "git rev-parse --is-inside-work-tree":
            return self._result(0, "true")
        if command == "git remote get-url origin":
            return self._result(0 if self.remote_url else 2, self.remote_url or "")
        if command in {"git fetch origin --prune", "git remote set-head origin -a", "git pull --ff-only origin main", "git pull --ff-only origin develop"}:
            return self._result(0)
        if command == "git symbolic-ref --short refs/remotes/origin/HEAD":
            return self._result(0, f"origin/{self.default_branch}")
        if command.startswith("git rev-parse --verify origin/"):
            return self._result(0, "deadbeef")
        if command == "git branch --show-current":
            return self._result(0, self.current_branch)
        if command == "git status --porcelain --untracked-files=normal":
            return self._result(0, "?? local.txt" if self.dirty else "")
        if command.startswith("git show-ref --verify --quiet refs/heads/"):
            branch = command.rsplit("/", 1)[-1]
            return self._result(0 if branch in {self.default_branch, self.current_branch} else 1)
        if command.startswith("git merge-base origin/"):
            return self._result(0, "base-sha")
        if command.startswith("git checkout -b "):
            self.current_branch = command.split()[3]
            return self._result(0)
        if command.startswith("git checkout "):
            self.current_branch = command.split()[-1]
            return self._result(0)
        if command.startswith("git checkout --track -b "):
            self.current_branch = command.split()[4]
            return self._result(0)
        return self._result(0)

    @staticmethod
    def _result(exit_code: int, stdout: str = "", stderr: str = ""):
        return SimpleNamespace(exit_code=exit_code, stdout=stdout, stderr=stderr)


def test_prepares_selected_github_repo_in_isolated_directory(tmp_path: Path) -> None:
    repo = parse_repo_url("https://github.com/Guo-Yixin/test-coding-repo")
    backend = FakeGitBackend(tmp_path)

    prepared = prepare_repository_workspace(repo, backend, thread_id="thread-123")

    assert prepared.directory == "projects/github-Guo-Yixin-test-coding-repo"
    assert prepared.default_branch == "main"
    assert backend.cloned is True
    assert "git clone -- https://github.com/Guo-Yixin/test-coding-repo.git github-Guo-Yixin-test-coding-repo" in backend.commands
    assert not any(command.startswith("git remote set-url") for command in backend.commands)


def test_uses_remote_default_branch_instead_of_provider_guess(tmp_path: Path) -> None:
    repo = parse_repo_url("owner/repo", provider="github")
    backend = FakeGitBackend(tmp_path, default_branch="develop")

    prepared = prepare_repository_workspace(repo, backend)

    assert prepared.default_branch == "develop"
    assert "git pull --ff-only origin develop" in backend.commands


def test_rejects_shell_unsafe_remote_default_branch(tmp_path: Path) -> None:
    repo = parse_repo_url("owner/repo", provider="github")
    backend = FakeGitBackend(tmp_path, default_branch="main;whoami")

    with pytest.raises(RepositoryWorkspaceError, match="不支持的字符"):
        prepare_repository_workspace(repo, backend)

    assert not any(command.startswith("git checkout") for command in backend.commands)


def test_refuses_existing_checkout_with_mismatched_origin_without_rewriting_it(tmp_path: Path) -> None:
    repo = parse_repo_url("https://github.com/owner/repo")
    old_remote = "https://gitee.com/owner/repo.git"
    backend = FakeGitBackend(tmp_path, remote_url=old_remote)
    target = backend.projects_dir / "github-owner-repo"
    target.mkdir()
    (target / ".git").mkdir()
    marker = target / "keep-me.txt"
    marker.write_text("user data", encoding="utf-8")

    with pytest.raises(RepositoryWorkspaceError, match="但本轮选择的是 github/owner/repo"):
        prepare_repository_workspace(repo, backend)

    assert marker.read_text(encoding="utf-8") == "user data"
    assert not any(command.startswith("git remote set-url") for command in backend.commands)


def test_creates_stable_task_branch_from_default_branch(tmp_path: Path) -> None:
    repo = parse_repo_url("owner/repo", provider="github")
    backend = FakeGitBackend(tmp_path)

    prepared = prepare_repository_workspace(repo, backend, thread_id="12345678-abcd", create_task_branch=True)

    assert prepared.current_branch == "codex/task-12345678-abcd"
    assert prepared.current_branch == task_branch_name("12345678-abcd")
    assert "git checkout -b codex/task-12345678-abcd origin/main" in backend.commands


def test_does_not_switch_when_worktree_has_uncommitted_files(tmp_path: Path) -> None:
    repo = parse_repo_url("owner/repo", provider="github")
    backend = FakeGitBackend(tmp_path, remote_url="https://github.com/owner/repo.git")
    backend.current_branch = "old-feature"
    backend.dirty = True
    target = backend.projects_dir / "github-owner-repo"
    target.mkdir()
    (target / ".git").mkdir()

    with pytest.raises(RepositoryWorkspaceError, match="保护本地改动"):
        prepare_repository_workspace(repo, backend)

    assert backend.current_branch == "old-feature"


def test_local_shell_backend_defaults_to_thread_repository_directory(tmp_path: Path) -> None:
    backend = LocalShellBackend(Workspace(tmp_path), working_dir="/projects/github-owner-repo")

    assert backend.get_work_dir() == "/projects/github-owner-repo"
    cwd, _ = backend._prepare_run_command("git status", ".")
    assert cwd == tmp_path / "projects" / "github-owner-repo"


def test_local_shell_backend_rejects_working_directory_traversal(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="inside /projects|traversal"):
        LocalShellBackend(Workspace(tmp_path), working_dir="/projects/../skills")
