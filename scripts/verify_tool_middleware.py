from __future__ import annotations

import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.backends.local_shell import LocalShellBackend
from agent.backends.permissions import WorkspacePermissionError
from agent.backends.workspace import Workspace
from agent.core.middleware.tool_sanitize import ToolInputRejected, sanitize_workspace_path


def main() -> None:
    """验证当前工具治理策略不再依赖旧文件/命令工具。

    文件和命令能力已经迁移到 DeepAgents 原生工具，真正的边界由
    `LocalShellBackend` 承担；middleware 只继续负责自定义业务工具的入参清洗。
    """

    workspace_root = PROJECT_ROOT / ".tmp_tool_middleware_workspace"
    if workspace_root.exists():
        shutil.rmtree(workspace_root)
    (workspace_root / "projects" / "demo").mkdir(parents=True, exist_ok=True)
    (workspace_root / "projects" / "demo" / "README.md").write_text("# demo\n", encoding="utf-8")

    backend = LocalShellBackend(Workspace(workspace_root))

    try:
        sanitize_workspace_path("E:\\outside", argument_name="path", backend=backend)
    except ToolInputRejected:
        pass
    else:
        raise AssertionError("工作区外 Windows 绝对路径应该被 middleware 拦截")

    try:
        sanitize_workspace_path(".secrets/token.txt", argument_name="path", backend=backend)
    except ToolInputRejected:
        pass
    else:
        raise AssertionError(".secrets 敏感目录应该被 middleware 拦截")

    inside_absolute_path = workspace_root / "projects" / "demo" / "README.md"
    normalized = sanitize_workspace_path(str(inside_absolute_path), argument_name="path", backend=backend)
    if normalized != "projects/demo/README.md":
        raise AssertionError(f"工作区内绝对路径应转换成相对路径，实际: {normalized}")

    prepared_git = backend._prepare_command("git -C projects/demo status", cwd_path=backend.projects_dir)
    if "projects/demo" in prepared_git or "-C demo" not in prepared_git:
        raise AssertionError(f"execute 默认目录下的 git 路径没有被正确收敛: {prepared_git}")

    prepared_pytest = backend._prepare_command("python -m pytest projects/demo", cwd_path=backend.projects_dir)
    if "projects/demo" in prepared_pytest or "pytest demo" not in prepared_pytest:
        raise AssertionError(f"execute 默认目录下的 pytest 路径没有被正确收敛: {prepared_pytest}")

    denied = backend._deny_reason("git status projects/projects/demo")
    if not denied:
        raise AssertionError("projects/projects 嵌套路径应该被后端拒绝")

    try:
        backend.run("echo ok", cwd=".")
    except WorkspacePermissionError:
        pass
    else:
        raise AssertionError("旧兼容 run() 必须继续使用命令白名单，echo ok 不应被允许")

    shutil.rmtree(workspace_root)
    print("tool middleware verification passed")


if __name__ == "__main__":
    main()
