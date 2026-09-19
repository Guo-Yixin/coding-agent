from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def ok(name: str, value: object) -> None:
    print(f"[OK] {name}: {value}")


def fail(name: str, message: str) -> None:
    raise SystemExit(f"[FAIL] {name}: {message}")


def require_writable_dir(name: str, path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    probe = path / ".write_test"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError as exc:
        fail(name, str(exc))
    ok(name, path)


def require_command(name: str, command: str) -> None:
    resolved = shutil.which(command)
    if not resolved:
        fail(name, f"{command} not found on PATH")
    ok(name, resolved)


def require_import(name: str) -> None:
    if importlib.util.find_spec(name) is None:
        fail(f"python import {name}", "module not found")
    ok(f"python import {name}", "available")


def main() -> None:
    if os.name == "nt":
        print("[WARN] 当前是 Windows；此脚本主要用于 Linux/Docker 部署自检。")

    from agent.backends.local_shell import LocalShellBackend
    from agent.core.settings import (
        CHECKPOINT_DB_PATH,
        LANGGRAPH_STORE_DB_PATH,
        LOG_DIR,
        PROJECTS_DIR,
        STORE_DB_PATH,
        WORKSPACE_ROOT,
    )

    ok("project root", PROJECT_ROOT)
    require_writable_dir("workspace root", WORKSPACE_ROOT)
    for name in ("projects", "skills", "policies", "reviews", "tmp", "logs", "runtimes"):
        require_writable_dir(f"workspace/{name}", WORKSPACE_ROOT / name)
    require_writable_dir("data dir", STORE_DB_PATH.parent)
    require_writable_dir("log dir", LOG_DIR)

    ok("checkpoint db path", CHECKPOINT_DB_PATH)
    ok("store db path", STORE_DB_PATH)
    ok("langgraph store db path", LANGGRAPH_STORE_DB_PATH)
    ok("projects dir", PROJECTS_DIR)

    require_command("git", "git")
    require_command("python", "python3" if os.name != "nt" else "python")
    if shutil.which("node"):
        ok("node", shutil.which("node"))
    else:
        print("[WARN] node not found on PATH; 仅后端部署可忽略，前端构建需要安装 Node.js。")

    for module in ("fastapi", "uvicorn", "deepagents", "langgraph"):
        require_import(module)

    backend = LocalShellBackend()
    health = backend.health()
    if not health.get("healthy"):
        fail("LocalShellBackend health", str(health))
    ok("LocalShellBackend health", health)

    tmp_virtual_path = f"/tmp/lx_deploy_check_{os.getpid()}.txt"
    tmp_result = backend.write(tmp_virtual_path, "ok")
    if getattr(tmp_result, "error", None):
        fail("backend write /tmp", str(tmp_result.error))
    read_result = backend.read(tmp_virtual_path)
    if getattr(read_result, "error", None):
        fail("backend read /tmp", str(read_result.error))
    ok("backend virtual file io", tmp_virtual_path)

    git_result = backend.execute("git --version", timeout=30)
    if git_result.exit_code != 0:
        fail("backend execute git", git_result.output)
    ok("backend execute git", git_result.output.strip())

    print("Linux deployment verification passed.")


if __name__ == "__main__":
    main()
