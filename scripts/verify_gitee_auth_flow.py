from __future__ import annotations

import sys
import tempfile
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.backends.local_shell import LocalShellBackend
from agent.backends.workspace import Workspace
from agent.tools.gitee_api import authenticated_clone_url, get_gitee_token, mask_token, parse_gitee_repo_url


def main() -> None:
    """验证 Gitee 认证链路按 open-swe 方式工作。"""

    repo = parse_gitee_repo_url("https://gitee.com/clumsypsc/test_coding_repo.git")
    clone_url = authenticated_clone_url(repo)
    if clone_url != "https://gitee.com/clumsypsc/test_coding_repo.git":
        raise AssertionError(f"clone URL 不应包含 token: {clone_url}")
    if "oauth2:" in clone_url:
        raise AssertionError("clone URL 禁止包含 oauth2 token")

    token = get_gitee_token()
    if not token:
        raise AssertionError("测试环境缺少 GITEE_TOKEN 或 SCM_GITEE_TOKEN")
    masked = mask_token(f"token={token}")
    if token in masked or "***" not in masked:
        raise AssertionError("mask_token 没有正确隐藏 Gitee token")

    with tempfile.TemporaryDirectory() as tmp:
        workspace_root = Path(tmp) / "workspace"
        workspace = Workspace(workspace_root)
        for name in ["projects", "skills", "policies", "reviews", "logs", "runtimes", "tmp", ".secrets"]:
            (workspace_root / name).mkdir(parents=True, exist_ok=True)
        backend = LocalShellBackend(workspace)
        env = backend._execution_env()
        if env.get("GIT_TERMINAL_PROMPT") != "0":
            raise AssertionError("Git 必须禁用交互式凭据提示")
        expected_suffix = "gitee_askpass.cmd" if os.name == "nt" else "gitee_askpass.sh"
        if not env.get("GIT_ASKPASS", "").endswith(expected_suffix):
            raise AssertionError("GIT_ASKPASS 未指向 Gitee askpass 脚本")
        if env.get("GITEE_ASKPASS_USERNAME") != "oauth2":
            raise AssertionError("Gitee askpass username 应为 oauth2")
        if env.get("GITEE_ASKPASS_TOKEN") != token:
            raise AssertionError("Gitee askpass token 未使用 GITEE_TOKEN/SCM_GITEE_TOKEN")

    runtime_source = (PROJECT_ROOT / "agent" / "core" / "runtime.py").read_text(encoding="utf-8")
    if "oauth2:" in runtime_source:
        raise AssertionError("runtime.py 不应拼接带 token 的 remote URL")
    if "authenticated_clone_url" in runtime_source:
        raise AssertionError("runtime.py 不应依赖 authenticated_clone_url 执行 clone/pull")

    print("gitee auth flow verification passed")


if __name__ == "__main__":
    main()
