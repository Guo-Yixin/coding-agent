from __future__ import annotations

import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.backends.local_shell import LocalShellBackend
from agent.backends.workspace import Workspace


def main() -> None:
    """验证 DeepAgents 原生文件协议遇到目录/文件/只读目录时返回可恢复错误。"""

    workspace_root = PROJECT_ROOT / ".tmp_file_tool_workspace"
    if workspace_root.exists():
        shutil.rmtree(workspace_root)
    case_dir = workspace_root / "projects" / "demo" / "case"
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "test_demo.py").write_text("def test_demo():\n    assert True\n", encoding="utf-8")

    backend = LocalShellBackend(Workspace(workspace_root))

    read_dir = backend.read("/projects/demo/case")
    if not read_dir.error or "目录" not in read_dir.error:
        raise AssertionError(f"读取目录应返回可恢复错误，实际: {read_dir}")

    write_dir = backend.write("/projects/demo/case", "should not overwrite a directory")
    if not write_dir.error:
        raise AssertionError(f"写入目录应返回可恢复错误，实际: {write_dir}")

    read_file = backend.read("/projects/demo/case/test_demo.py")
    if read_file.error or not read_file.file_data or "assert True" not in read_file.file_data["content"]:
        raise AssertionError(f"读取具体文件应成功，实际: {read_file}")

    protected_write = backend.write("/skills/new-skill/SKILL.md", "# bad")
    if not protected_write.error or "skills are read-only" not in protected_write.error:
        raise AssertionError(f"/skills 应保持只读，实际: {protected_write}")

    shutil.rmtree(workspace_root)
    print("file tools recoverable errors verified")


if __name__ == "__main__":
    main()
