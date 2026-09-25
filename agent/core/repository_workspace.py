"""Prepare and validate the local checkout bound to a selected repository."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.core.repo_memory import repo_project_dir
from agent.repository import Repository, parse_repo_url

logger = logging.getLogger(__name__)


class RepositoryWorkspaceError(RuntimeError):
    """Raised when a local checkout cannot safely represent the selected repo."""


@dataclass(frozen=True)
class PreparedRepositoryWorkspace:
    directory: str
    default_branch: str
    current_branch: str


def task_branch_name(thread_id: str) -> str:
    """Return a stable, Git-safe branch name for one conversation."""

    suffix = re.sub(r"[^A-Za-z0-9._-]+", "-", (thread_id or "task")[:24]).strip(".-") or "task"
    return f"codex/task-{suffix}"


def _run(backend: Any, command: str, *, cwd: str, timeout: int = 300) -> Any:
    result = backend.run(command, cwd=cwd, timeout=timeout)
    combined_output = f"{result.stdout}\n{result.stderr}".lower()
    if result.exit_code != 0 and command.startswith("git fetch") and "cannot open .git/fetch_head" in combined_output:
        # Preserve the existing Windows recovery for a stale/locked FETCH_HEAD,
        # but only remove this generated file inside the already-validated repo.
        fetch_head = backend.workspace.resolve(Path(cwd) / ".git" / "FETCH_HEAD")
        try:
            if fetch_head.is_file():
                fetch_head.unlink()
                result = backend.run(command, cwd=cwd, timeout=timeout)
        except OSError as exc:
            logger.warning("删除仓库 FETCH_HEAD 失败，保留原 Git 错误：%s", exc)
    if result.exit_code != 0:
        detail = (result.stderr or result.stdout or "命令失败").strip()
        raise RepositoryWorkspaceError(f"准备仓库工作区失败（{command.split()[1]}）：{detail}")
    return result


def _ensure_clean_before_switch(backend: Any, *, cwd: str) -> None:
    result = _run(backend, "git status --porcelain --untracked-files=normal", cwd=cwd)
    if result.stdout.strip():
        raise RepositoryWorkspaceError(
            f"仓库目录 {cwd} 存在未提交或未跟踪文件。为保护本地改动，CODING 不会自动切换分支；"
            "请先提交/移走这些文件，或使用新的仓库工作区。"
        )


def _remote_default_branch(backend: Any, *, cwd: str) -> str:
    # `remote set-head -a` reads the hosting provider's symbolic HEAD after fetch.
    auto_head = backend.run("git remote set-head origin -a", cwd=cwd, timeout=120)
    if auto_head.exit_code == 0:
        result = backend.run("git symbolic-ref --short refs/remotes/origin/HEAD", cwd=cwd)
        if result.exit_code == 0:
            value = result.stdout.strip().splitlines()
            if value:
                branch = value[0].strip().removeprefix("origin/")
                if branch:
                    return _validate_branch_name(branch)

    # Older Git servers may not expose origin/HEAD consistently. Ask the remote
    # directly instead of guessing main/master from the provider.
    result = _run(backend, "git ls-remote --symref origin HEAD", cwd=cwd, timeout=120)
    for line in result.stdout.splitlines():
        match = re.match(r"ref:\s+refs/heads/([^\s]+)\s+HEAD$", line.strip())
        if match:
            return _validate_branch_name(match.group(1))
    raise RepositoryWorkspaceError("无法从远端识别默认分支；请检查仓库权限和 origin/HEAD 配置。")


def _validate_branch_name(branch: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", branch) or any(part in {"", ".", ".."} for part in branch.split("/")):
        raise RepositoryWorkspaceError("远端默认分支名称包含不支持的字符，已停止执行以保护工作区。")
    return branch


def _switch_to_default_branch(backend: Any, *, cwd: str, branch: str) -> None:
    current = _run(backend, "git branch --show-current", cwd=cwd).stdout.strip()
    if current != branch:
        _ensure_clean_before_switch(backend, cwd=cwd)
        local_ref = backend.run(f"git show-ref --verify --quiet refs/heads/{branch}", cwd=cwd)
        if local_ref.exit_code == 0:
            _run(backend, f"git checkout {branch}", cwd=cwd)
        else:
            _run(backend, f"git checkout --track -b {branch} origin/{branch}", cwd=cwd)
    _ensure_clean_before_switch(backend, cwd=cwd)
    _run(backend, f"git pull --ff-only origin {branch}", cwd=cwd, timeout=300)


def _activate_task_branch(backend: Any, *, cwd: str, default_branch: str, branch: str) -> str:
    current = _run(backend, "git branch --show-current", cwd=cwd).stdout.strip()
    if current == branch:
        # Re-entering the same thread should preserve its in-progress changes.
        base = backend.run(f"git merge-base origin/{default_branch} HEAD", cwd=cwd)
        if base.exit_code != 0:
            raise RepositoryWorkspaceError(
                f"任务分支 {branch} 与远端默认分支 {default_branch} 没有共同历史；"
                "为避免错误 PR，未继续使用该分支。"
            )
        return current

    _ensure_clean_before_switch(backend, cwd=cwd)
    local_ref = backend.run(f"git show-ref --verify --quiet refs/heads/{branch}", cwd=cwd)
    if local_ref.exit_code == 0:
        _run(backend, f"git checkout {branch}", cwd=cwd)
        base = backend.run(f"git merge-base origin/{default_branch} HEAD", cwd=cwd)
        if base.exit_code != 0:
            raise RepositoryWorkspaceError(
                f"已有任务分支 {branch} 与远端默认分支 {default_branch} 没有共同历史；"
                "为避免错误 PR，未继续使用该分支。"
            )
        return branch

    _switch_to_default_branch(backend, cwd=cwd, branch=default_branch)
    _run(backend, f"git checkout -b {branch} origin/{default_branch}", cwd=cwd)
    return branch


def prepare_repository_workspace(
    repo: Repository,
    backend: Any,
    *,
    thread_id: str | None = None,
    create_task_branch: bool = False,
) -> PreparedRepositoryWorkspace:
    """Clone or validate the exact selected repository, then select a safe base.

    Existing mismatched/non-Git directories are never overwritten and their origin
    is never silently rewritten. All Git operations go through LocalShellBackend so
    its non-interactive provider credentials and token redaction remain in effect.
    """

    directory = repo_project_dir(repo).replace("\\", "/")
    target = backend.workspace.resolve(directory)
    project_root = backend.projects_dir
    project_root.mkdir(parents=True, exist_ok=True)

    if not target.exists():
        clone = backend.run(f"git clone -- {repo.clone_url} {target.name}", cwd="projects", timeout=600)
        if clone.exit_code != 0:
            detail = (clone.stderr or clone.stdout or "克隆失败").strip()
            raise RepositoryWorkspaceError(f"无法克隆所选 {repo.provider} 仓库 {repo.full_name}：{detail}")
    elif not target.is_dir():
        raise RepositoryWorkspaceError(f"仓库目标路径不是目录：{directory}")

    cwd = directory
    is_git = backend.run("git rev-parse --is-inside-work-tree", cwd=cwd)
    if is_git.exit_code != 0 or is_git.stdout.strip().lower() != "true":
        raise RepositoryWorkspaceError(
            f"目标路径 {directory} 已存在但不是 Git 仓库；为保护现有文件，未自动覆盖。"
        )

    remote = _run(backend, "git remote get-url origin", cwd=cwd).stdout.strip()
    try:
        actual_repo = parse_repo_url(remote)
    except ValueError as exc:
        raise RepositoryWorkspaceError(
            f"工作区 origin 不是当前支持的 HTTPS 仓库地址；请勿复用该目录：{directory}"
        ) from exc
    if (actual_repo.provider, actual_repo.owner.lower(), actual_repo.repo.lower()) != (
        repo.provider,
        repo.owner.lower(),
        repo.repo.lower(),
    ):
        raise RepositoryWorkspaceError(
            f"工作区 origin 指向 {actual_repo.provider}/{actual_repo.full_name}，"
            f"但本轮选择的是 {repo.provider}/{repo.full_name}。为避免串仓库，未改写 origin。"
        )

    _run(backend, "git fetch origin --prune", cwd=cwd, timeout=300)
    default_branch = _remote_default_branch(backend, cwd=cwd)
    remote_ref = backend.run(f"git rev-parse --verify origin/{default_branch}", cwd=cwd)
    if remote_ref.exit_code != 0:
        raise RepositoryWorkspaceError(f"远端默认分支 origin/{default_branch} 不存在或不可读取。")

    if create_task_branch:
        if not thread_id:
            raise ValueError("创建任务分支时必须提供 thread_id")
        current_branch = _activate_task_branch(
            backend,
            cwd=cwd,
            default_branch=default_branch,
            branch=task_branch_name(thread_id),
        )
    else:
        _switch_to_default_branch(backend, cwd=cwd, branch=default_branch)
        current_branch = default_branch

    logger.info(
        "仓库工作区已校验：provider=%s repo=%s directory=%s default_branch=%s current_branch=%s",
        repo.provider,
        repo.full_name,
        directory,
        default_branch,
        current_branch,
    )
    return PreparedRepositoryWorkspace(directory, default_branch, current_branch)
