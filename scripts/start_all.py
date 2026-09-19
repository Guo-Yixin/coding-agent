from __future__ import annotations

import subprocess
import sys
import os
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.stop_all import stop_ports  # noqa: E402


def python_executable() -> str:
    """返回当前平台推荐的项目 Python 可执行文件。"""

    candidates = []
    if os.name == "nt":
        candidates.extend(
            [
                PROJECT_ROOT / ".venv" / "Scripts" / "python.exe",
                PROJECT_ROOT / "venv" / "Scripts" / "python.exe",
            ]
        )
    else:
        candidates.extend(
            [
                PROJECT_ROOT / ".venv" / "bin" / "python",
                PROJECT_ROOT / "venv" / "bin" / "python",
            ]
        )
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return sys.executable


def vite_command() -> list[str]:
    """返回跨平台 Vite 启动命令。"""

    vite = PROJECT_ROOT / "ui" / "node_modules" / "vite" / "bin" / "vite.js"
    return ["node", str(vite), "dev", "--host", "127.0.0.1", "--port", "3000"]


def start_process(
    name: str,
    command: list[str],
    cwd: Path,
    env: dict[str, str] | None = None,
) -> subprocess.Popen:
    print(f"启动 {name}: {' '.join(command)}")
    process_env = os.environ.copy()
    if env:
        process_env.update(env)
    return subprocess.Popen(command, cwd=str(cwd), env=process_env)


def main() -> None:
    """同时启动本地部署版后端和前端。

    后端运行在 http://127.0.0.1:2024。
    前端运行在 http://127.0.0.1:3000。
    按 Ctrl+C 会同时停止两个进程。
    """

    backend = start_process(
        "backend",
        [
            python_executable(),
            "-m",
            "uvicorn",
            "agent.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            "2024",
        ],
        PROJECT_ROOT,
    )
    frontend = start_process(
        "frontend",
        vite_command(),
        PROJECT_ROOT / "ui",
        env={"VITE_DASHBOARD_API_BASE_URL": "http://127.0.0.1:2024"},
    )

    try:
        while True:
            backend_code = backend.poll()
            frontend_code = frontend.poll()
            if backend_code is not None:
                raise SystemExit(f"backend exited: {backend_code}")
            if frontend_code is not None:
                raise SystemExit(f"frontend exited: {frontend_code}")
            time.sleep(1)
    except KeyboardInterrupt:
        print("正在停止服务...")
    finally:
        # 先停止 start_all.py 直接创建的子进程。
        for process in (frontend, backend):
            if process.poll() is None:
                process.terminate()
        for process in (frontend, backend):
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        # 再按端口兜底清理，处理 PyCharm 停止按钮或 Windows 进程树残留。
        stopped = stop_ports((2024, 3000))
        if stopped:
            print(f"已清理残留服务进程：{stopped}")
        sys.exit(0)


if __name__ == "__main__":
    main()
