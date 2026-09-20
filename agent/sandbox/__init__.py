"""可选的轻量隔离执行能力。

默认运行时仍使用项目已有的本地 backend；只有显式配置或 CLI 指定
OpenSandbox 时才创建远端沙箱，避免开发环境因为缺少 SDK 而无法启动。
"""

from agent.sandbox.opensandbox_executor import (
    OpenSandboxConfig,
    OpenSandboxExecutor,
    SandboxExecution,
    SandboxFile,
    collect_safe_workspace_files,
    sandbox_health,
)

__all__ = [
    "OpenSandboxConfig",
    "OpenSandboxExecutor",
    "SandboxExecution",
    "SandboxFile",
    "collect_safe_workspace_files",
    "sandbox_health",
]
