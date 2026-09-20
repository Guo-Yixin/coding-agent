"""OpenSandbox 轻量隔离执行适配器。

这个模块刻意把第三方 SDK 放在懒加载路径中：

* 本地开发和单元测试不安装 SDK 也能导入项目；
* 只有调用 :meth:`OpenSandboxExecutor.start` 时才建立远端沙箱；
* 上传工作区时默认排除凭据、Git 元数据、虚拟环境和 CodeGraph 缓存；
* Agent Eval 可以把同一份干净快照送入沙箱，记录命令、退出码和耗时。

OpenSandbox SDK 是异步 API，而当前 Coding Agent 的 legacy tool/runtime 仍是同步
调用链，因此这里提供同步外观，并保留 async 内部实现。若调用线程已经运行事件循环，
同步方法会明确报错，调用方应使用 async 方法，避免隐式嵌套事件循环。
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Iterable

import requests


_DENY_DIRS = {
    ".git",
    ".venv",
    ".codegraph",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    "eval_runs",
}
_DENY_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
}
_DENY_SUFFIXES = {".sqlite", ".sqlite3", ".db", ".pyc", ".pyo"}


@dataclass(frozen=True)
class OpenSandboxConfig:
    """OpenSandbox 连接和资源配置。"""

    domain: str = "http://127.0.0.1:8080"
    api_key: str | None = None
    image: str = "python:3.11"
    cpu: str = "1"
    memory: str = "1Gi"
    timeout_seconds: int = 600
    command_timeout_seconds: int = 300
    max_upload_bytes: int = 2 * 1024 * 1024
    keep_sandbox: bool = False

    @classmethod
    def from_env(cls) -> "OpenSandboxConfig":
        """从环境读取配置，不回显 API key。"""

        return cls(
            domain=(
                os.environ.get("OPEN_SANDBOX_DOMAIN")
                or os.environ.get("SANDBOX_DOMAIN")
                or cls.domain
            ).rstrip("/"),
            api_key=os.environ.get("OPEN_SANDBOX_API_KEY")
            or os.environ.get("SANDBOX_API_KEY")
            or None,
            image=os.environ.get("OPEN_SANDBOX_IMAGE")
            or os.environ.get("SANDBOX_IMAGE")
            or cls.image,
            cpu=os.environ.get("OPEN_SANDBOX_CPU") or os.environ.get("SANDBOX_CPU") or cls.cpu,
            memory=os.environ.get("OPEN_SANDBOX_MEMORY")
            or os.environ.get("SANDBOX_MEMORY")
            or cls.memory,
            timeout_seconds=int(
                os.environ.get("OPEN_SANDBOX_TIMEOUT_SECONDS")
                or os.environ.get("SANDBOX_TIMEOUT_SECONDS")
                or cls.timeout_seconds
            ),
            command_timeout_seconds=int(
                os.environ.get("OPEN_SANDBOX_COMMAND_TIMEOUT_SECONDS")
                or os.environ.get("SANDBOX_COMMAND_TIMEOUT_SECONDS")
                or cls.command_timeout_seconds
            ),
            max_upload_bytes=int(
                os.environ.get("OPEN_SANDBOX_MAX_UPLOAD_BYTES") or cls.max_upload_bytes
            ),
            keep_sandbox=(
                os.environ.get("OPEN_SANDBOX_KEEP", "0").lower()
                in {"1", "true", "yes", "on"}
            ),
        )


@dataclass(frozen=True)
class SandboxExecution:
    """与 OpenSandbox SDK 解耦的可序列化执行结果。"""

    sandbox_id: str
    command: str
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int


@dataclass(frozen=True)
class SandboxFile:
    """待上传文件，path 始终是相对于仓库根目录的 POSIX 路径。"""

    path: str
    data: bytes
    mode: int = 0o644


def _run_sync(awaitable: Any) -> Any:
    """在没有活动事件循环的同步 runtime 中执行 coroutine。"""

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)
    raise RuntimeError("OpenSandbox 同步 API 不能在运行中的事件循环内调用，请使用 async 方法")


def _safe_relative_path(root: Path, candidate: Path) -> str | None:
    try:
        relative = candidate.resolve().relative_to(root.resolve())
    except ValueError:
        return None
    if any(part in _DENY_DIRS for part in relative.parts):
        return None
    if relative.name in _DENY_NAMES or relative.suffix.lower() in _DENY_SUFFIXES:
        return None
    return relative.as_posix()


def collect_safe_workspace_files(
    root: str | Path,
    *,
    max_file_bytes: int = 2 * 1024 * 1024,
) -> list[SandboxFile]:
    """收集可上传到沙箱的源码快照。

    这不是安全边界的唯一实现：调用方仍需在上传前确认仓库内容可信。但它保证
    默认不会把 `.env`、Git 凭据、虚拟环境、数据库文件和 CodeGraph 缓存送入远端。
    """

    root_path = Path(root).expanduser().resolve()
    if not root_path.is_dir():
        raise NotADirectoryError(root_path)

    files: list[SandboxFile] = []
    for candidate in sorted(root_path.rglob("*")):
        if not candidate.is_file():
            continue
        relative = _safe_relative_path(root_path, candidate)
        if relative is None:
            continue
        try:
            size = candidate.stat().st_size
        except OSError:
            continue
        if size > max_file_bytes:
            continue
        try:
            data = candidate.read_bytes()
        except OSError:
            continue
        mode = 0o755 if os.access(candidate, os.X_OK) else 0o644
        files.append(SandboxFile(path=relative, data=data, mode=mode))
    return files


def sandbox_health(
    domain: str,
    *,
    api_key: str | None = None,
    timeout_seconds: float = 5,
) -> dict[str, Any]:
    """探测 OpenSandbox server，返回可写入验证报告的健康信息。"""

    url = domain.rstrip("/") + "/health"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    started = time.perf_counter()
    try:
        response = requests.get(url, headers=headers, timeout=timeout_seconds)
        return {
            "ok": response.ok,
            "status_code": response.status_code,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "url": url,
            "body": response.text[:500],
        }
    except requests.RequestException as exc:
        return {
            "ok": False,
            "status_code": None,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "url": url,
            "error": str(exc),
        }


class OpenSandboxExecutor:
    """在 OpenSandbox 中执行命令并管理沙箱生命周期。"""

    def __init__(self, config: OpenSandboxConfig | None = None) -> None:
        self.config = config or OpenSandboxConfig.from_env()
        self._sandbox: Any | None = None

    @property
    def sandbox_id(self) -> str | None:
        return getattr(self._sandbox, "id", None) if self._sandbox is not None else None

    def _sdk_types(self) -> tuple[Any, Any, Any, Any]:
        try:
            from opensandbox import Sandbox
            from opensandbox.config import ConnectionConfig
            from opensandbox.models.execd import RunCommandOpts
            from opensandbox.models.filesystem import WriteEntry
        except ImportError as exc:
            raise RuntimeError(
                "OpenSandbox SDK 未安装，请执行 `uv pip install --python .venv\\Scripts\\python.exe "
                "-e .[sandbox]`"
            ) from exc
        return Sandbox, ConnectionConfig, RunCommandOpts, WriteEntry

    async def start_async(self) -> str:
        if self._sandbox is not None:
            return str(self.sandbox_id)
        Sandbox, ConnectionConfig, _, _ = self._sdk_types()
        connection = ConnectionConfig(domain=self.config.domain, api_key=self.config.api_key)
        self._sandbox = await Sandbox.create(
            self.config.image,
            timeout=timedelta(seconds=self.config.timeout_seconds),
            resource={"cpu": self.config.cpu, "memory": self.config.memory},
            connection_config=connection,
        )
        return str(self.sandbox_id)

    def start(self) -> str:
        return str(_run_sync(self.start_async()))

    @staticmethod
    def _output_text(messages: Iterable[Any]) -> str:
        chunks: list[str] = []
        for message in messages:
            text = getattr(message, "text", None)
            if text is None and isinstance(message, dict):
                text = message.get("text") or message.get("content")
            if text is not None:
                chunks.append(str(text))
        return "".join(chunks)

    async def execute_async(self, command: str, *, cwd: str | None = None) -> SandboxExecution:
        if self._sandbox is None:
            await self.start_async()
        _, _, RunCommandOpts, _ = self._sdk_types()
        started = time.perf_counter()
        opts = RunCommandOpts(
            working_directory=cwd,
            timeout=timedelta(seconds=self.config.command_timeout_seconds),
        )
        result = await self._sandbox.commands.run(command, opts=opts)
        logs = getattr(result, "logs", None)
        stdout = self._output_text(getattr(logs, "stdout", []) if logs else [])
        stderr = self._output_text(getattr(logs, "stderr", []) if logs else [])
        error = getattr(result, "error", None)
        if error is not None and not stderr:
            stderr = str(getattr(error, "message", error))
        return SandboxExecution(
            sandbox_id=str(self.sandbox_id),
            command=command,
            exit_code=getattr(result, "exit_code", None),
            stdout=stdout,
            stderr=stderr,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    def execute(self, command: str, *, cwd: str | None = None) -> SandboxExecution:
        return _run_sync(self.execute_async(command, cwd=cwd))

    async def upload_files_async(self, files: Iterable[SandboxFile]) -> int:
        if self._sandbox is None:
            await self.start_async()
        _, _, _, WriteEntry = self._sdk_types()
        entries = [
            WriteEntry(path=file.path, data=file.data, mode=file.mode)
            for file in files
        ]
        if entries:
            await self._sandbox.files.write_files(entries)
        return len(entries)

    def upload_files(self, files: Iterable[SandboxFile]) -> int:
        return int(_run_sync(self.upload_files_async(files)))

    async def upload_workspace_async(self, root: str | Path) -> int:
        files = collect_safe_workspace_files(root, max_file_bytes=self.config.max_upload_bytes)
        return await self.upload_files_async(files)

    def upload_workspace(self, root: str | Path) -> int:
        return int(_run_sync(self.upload_workspace_async(root)))

    async def read_file_async(self, path: str) -> str:
        if self._sandbox is None:
            await self.start_async()
        return str(await self._sandbox.files.read_file(path))

    def read_file(self, path: str) -> str:
        return str(_run_sync(self.read_file_async(path)))

    async def close_async(self) -> None:
        if self._sandbox is None:
            return
        sandbox = self._sandbox
        self._sandbox = None
        if not self.config.keep_sandbox:
            await sandbox.destroy()

    def close(self) -> None:
        _run_sync(self.close_async())

    async def __aenter__(self) -> "OpenSandboxExecutor":
        await self.start_async()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.close_async()
