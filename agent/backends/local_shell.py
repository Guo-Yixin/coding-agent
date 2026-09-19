"""本地文件后端实现。

这个模块是当前项目 Agent 运行时最关键的工程化组件之一：

1. 它把 DeepAgents 的文件后端协议落到本机文件系统上；
2. 它把模型看到的虚拟路径（例如 `/projects`、`/skills`）映射到真实工作区目录；
3. 它为命令执行增加安全守卫、超时控制、Token 脱敏和 Gitee 非交互认证；
4. 它保留了旧版 Gitee/Git 工具需要的兼容方法，降低业务代码迁移成本。

开发调试时可以把它理解为“Agent 与真实电脑之间的工程边界”：
Prompt 负责告诉模型应该怎么做，LocalShellBackend 负责决定模型最终能不能读、写、执行。
"""

from __future__ import annotations

import fnmatch
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from deepagents.backends.protocol import (  # DeepAgents 协议：文件操作、命令执行等标准接口
    EditResult,
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
    GlobResult,
    GrepResult,
    LsResult,
    ReadResult,
    WriteResult,
)
from deepagents.backends.sandbox import BaseSandbox  # 沙箱基类

from agent.core.settings import WORKSPACE_ROOT  # 统一的工作区根目录（由 settings.py 管理）
from agent.env_utils import get_env

from .permissions import normalize_safe_command
from .workspace import Workspace

logger = logging.getLogger("agent.run.shell")

IS_WINDOWS = os.name == "nt"


# ── 虚拟路径常量 ──────────────────────────────────────────────
# Agent 内部通过 /projects、/skills 等虚拟路径访问文件，
# 这里定义所有虚拟路径的映射关系。
VIRTUAL_PROJECTS = "/projects"
VIRTUAL_SKILLS = "/skills"
VIRTUAL_POLICIES = "/policies"
VIRTUAL_REVIEWS = "/reviews"
VIRTUAL_RUNTIMES = "/runtimes"
VIRTUAL_TMP = "/tmp"
VIRTUAL_LOGS = "/logs"

# 匹配命令中的 Windows 绝对路径（如 D:\xxx）
_DRIVE_PATH_RE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z]:[\\/][^\s\"';&|<>]*)")
# 匹配命令中的虚拟路径（如 /projects/my-repo），用于自动转换为真实路径
_VIRTUAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])/(projects|skills|policies|reviews|runtimes|tmp|logs)(/[^\s\"';&|<>]*)?"
)
_RELATIVE_PROJECTS_PATH_RE = re.compile(r"(?<![A-Za-z0-9_./\\-])projects[\\/](?=[^\s\"';&|<>]+)")
_RELATIVE_PROJECTS_DIR_RE = re.compile(r"(?<![A-Za-z0-9_./\\-])projects(?=\s|$)")
_NESTED_PROJECTS_PATH_RE = re.compile(r"(?<![A-Za-z0-9_./\\-])projects[\\/]projects(?:[\\/]|(?=\s|$))")
# 危险命令黑名单 —— 匹配到的命令直接拒绝执行
_DANGEROUS_PATTERNS = (
    r"\bformat\b",
    r"\bshutdown\b",
    r"\brestart-computer\b",
    r"\bstop-computer\b",
    r"\bset-executionpolicy\b",
    r"\breg\s+(delete|add|import|save|restore)\b",
    r"\bnet\s+user\b",
    r"\bnet\s+localgroup\b",
    r"\btaskkill\b",
    r"\bdiskpart\b",
    r"\bbcdedit\b",
    r"\bsudo\b",
    r"\bsu\b",
    r"\bchown\b",
    r"\bchmod\s+-r\b",
)
_LINUX_SENSITIVE_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9:])/(etc|root|home|proc|sys|dev|run|var/run|var/lib/docker|var/log)(?:/|\s|$)"
)


def _mask_token(text: str) -> str:
    """把文本中的 Gitee Token 替换为 ***，防止泄露到日志和返回值里。

    Agent 后端会把命令 stdout/stderr、异常信息、Git 输出写入日志或返回给模型。
    如果 Git 认证失败、远端 URL 展开或调试信息里包含 token，就可能造成泄露。
    因此所有准备进入日志和模型上下文的文本，都应先经过这个函数脱敏。
    """

    masked = text
    for token_name in ("GITEE_TOKEN", "SCM_GITEE_TOKEN"):
        token = get_env(token_name).strip()
        if token:
            masked = masked.replace(token, "***")
    return masked


@dataclass
class CommandResult:
    """兼容旧版 Gitee/Git 工具的命令执行结果。

    DeepAgents 原生 `execute()` 返回 `ExecuteResponse`，但项目里部分历史工具仍然依赖
    `command/cwd/exit_code/stdout/stderr` 这种更接近 subprocess 的结构。
    保留这个 dataclass 可以让旧工具逐步迁移，而不需要一次性改完整个调用链。
    """

    command: str
    cwd: str
    exit_code: int
    stdout: str
    stderr: str


class LocalShellBackend(BaseSandbox):
    """本地 DeepAgents backend。

    核心职责：
    1. 实现 DeepAgents 原生文件协议：`ls/read/write/edit/glob/grep/upload/download`；
    2. 实现命令执行协议：`execute()`，负责 Windows/Linux 适配、路径转换、超时和脱敏；
    3. 实现本地工作区布局：projects、skills、policies、reviews、runtimes、tmp、logs；
    4. 实现 Gitee Git 非交互认证：通过 `GIT_ASKPASS` 注入 token，避免后台进程弹窗；
    5. 保留旧版兼容接口：`run/read_file/write_file/list_files`，避免一次性重构业务工具。

    这个类不是“完全可信的 shell 代理”，而是项目里的受控本地执行层。
    真正企业生产环境还应叠加容器隔离、系统用户隔离、审计日志和更完整的权限策略。
    """

    def __init__(
        self,
        workspace: Workspace | str | os.PathLike[str] | None = None,
        *,
        timeout: int = 3600,
    ) -> None:
        # 确定工作区根目录：传入的 workspace > 环境变量 > settings.py 的默认值
        if isinstance(workspace, Workspace):
            self.workspace = workspace
            configured_root = workspace.root
        else:
            configured_root = workspace or os.environ.get("LOCAL_SHELL_WORKSPACE") or str(WORKSPACE_ROOT)
            self.workspace = Workspace(Path(configured_root))

        self.root = Path(configured_root).expanduser().resolve()
        # 工作区子目录规划
        self.projects_dir = self.root / os.environ.get("LOCAL_SHELL_PROJECTS_DIR", "projects")
        self.skills_dir = self.root / "skills"
        self.policies_dir = self.root / "policies"
        self.reviews_dir = self.root / "reviews"
        self.runtimes_dir = self.root / "runtimes"
        self.tmp_dir = self.root / "tmp"
        self.logs_dir = self.root / "logs"
        self.secrets_dir = self.root / ".secrets"  # 存放 Git askpass 脚本等敏感文件
        self.shared_python_venv = self.root / os.environ.get(
            "LOCAL_SHELL_SHARED_PYTHON_VENV",
            "runtimes/python/default/.venv",
        )
        self.default_timeout = timeout
        # 命令安全守卫，默认开启
        self.command_guard_enabled = (
            os.environ.get("LOCAL_SHELL_ENABLE_COMMAND_GUARD", "true").lower()
            not in {"0", "false", "no"}
        )
        self._venv_error: str | None = None
        self._ensure_layout()

    @property
    def id(self) -> str:
        platform = "windows" if IS_WINDOWS else "linux"
        return f"local-{platform}:{self.root}"

    def get_work_dir(self) -> str:
        # DeepAgents 协议：返回默认工作目录的虚拟路径
        return VIRTUAL_PROJECTS

    def get_workspace_root(self) -> str:
        # DeepAgents 协议：返回虚拟根路径
        return "/"

    def health(self) -> dict[str, Any]:
        """健康检查：检测目录、Git、Python、Node 等是否可用。"""
        checks = {
            "root_exists": self.root.exists(),
            "root_writable": self._is_writable(self.root),
            "projects_exists": self.projects_dir.exists(),
            "skills_exists": self.skills_dir.exists(),
            "python_venv_exists": self.shared_python_venv.exists(),
            "git_available": shutil.which("git") is not None,
            "python_available": self._system_python() is not None,
            "node_available": shutil.which("node") is not None,
            "command_guard_enabled": self.command_guard_enabled,
        }
        return {
            "type": "local_shell",
            "root": str(self.root),
            "healthy": bool(checks["root_exists"] and checks["root_writable"] and checks["projects_exists"]),
            "checks": checks,
            "errors": {"python_venv": self._venv_error} if self._venv_error else {},
        }

    def _system_python(self) -> str | None:
        """按当前系统查找可用 Python。

        Windows 上通常是 python，Linux 服务器上更常见的是 python3。
        """

        return shutil.which("python") or shutil.which("python3")

    def _venv_bin_dir(self) -> Path:
        """返回共享虚拟环境的可执行文件目录。"""

        return self.shared_python_venv / ("Scripts" if IS_WINDOWS else "bin")

    def _venv_python(self) -> Path:
        """返回共享虚拟环境中的 Python 可执行文件路径。"""

        return self._venv_bin_dir() / ("python.exe" if IS_WINDOWS else "python")

    def _shell_kwargs(self) -> dict[str, str]:
        """返回 subprocess shell 兼容参数。

        Windows 使用系统默认 shell；Linux 下优先使用 bash，保证 `source`、
        引号和常见 shell 语义更稳定。
        """

        if IS_WINDOWS:
            return {}
        bash = shutil.which("bash")
        return {"executable": bash} if bash else {}

    def _git_askpass_path(self) -> Path:
        """返回当前平台的 Git askpass 脚本路径。"""

        return self.secrets_dir / ("gitee_askpass.cmd" if IS_WINDOWS else "gitee_askpass.sh")

    # ── DeepAgents 原生协议实现 ─────────────────────────────

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        """执行 DeepAgents 原生命令工具请求。

        这里是模型调用 `execute` 工具时最终进入的入口，处理顺序是：
        1. 先做安全拒绝判断，拦截危险命令和工作区外路径；
        2. 再做命令预处理，把虚拟路径和部分跨平台差异命令转换成当前系统可执行形式；
        3. 最后通过 subprocess 执行，并把 stdout/stderr 合并成模型容易阅读的文本。

        注意：这个方法不向上抛异常，而是按 DeepAgents 协议返回结构化结果。
        这样模型可以基于 exit_code 和 output 继续修正命令或解释失败原因。
        """
        if self.command_guard_enabled:
            denied = self._deny_reason(command)
            if denied:
                return ExecuteResponse(output=f"命令被拒绝：{denied}", exit_code=126, truncated=False)

        prepared_command = self._prepare_command(command, cwd_path=self.projects_dir)
        effective_timeout = timeout if timeout is not None else self.default_timeout
        try:
            completed = subprocess.run(
                prepared_command,  # 最终执行的命令字符串，已经完成虚拟路径转换、Git 认证注入等预处理
                cwd=self.projects_dir,  # 子进程工作目录，默认限制在 projects 目录下执行
                capture_output=True,  # 捕获 stdout 和 stderr，避免命令输出直接写到后端进程控制台
                text=True,  # 以文本模式返回输出内容，而不是 bytes
                encoding="utf-8",  # 使用 UTF-8 解码 stdout/stderr，保持日志和模型上下文编码一致
                errors="replace",  # 遇到无法解码的字符时用替代字符处理，避免解码异常中断任务
                timeout=effective_timeout,  # 单次命令执行超时时间，防止长时间阻塞 Agent 运行线程
                env=self._execution_env(),  # 子进程环境变量，包含 PATH、虚拟环境、Git 非交互认证等配置
                check=False,  # 不因非 0 退出码抛异常，保留 exit_code 交给 Agent 判断后续处理
                shell=True,  # 通过系统 shell 执行字符串命令，兼容内置命令和 Git 命令
                **self._shell_kwargs(),
            )
            output = completed.stdout
            # stderr 内容拼到 output 里，方便 LLM 统一查看
            if completed.stderr.strip():
                stderr = completed.stderr.strip()
                output = f"{output}\n<stderr>{stderr}</stderr>" if output else stderr
            return ExecuteResponse(
                output=_mask_token(output.rstrip()),
                exit_code=completed.returncode,
                truncated=False,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            return ExecuteResponse(
                output=_mask_token(f"命令执行超时：{effective_timeout} 秒\n{stdout}{stderr}".strip()),
                exit_code=124,
                truncated=False,
            )
        except Exception as exc:
            # 协议要求：所有异常都要转成结构化结果，不能抛出去
            return ExecuteResponse(output=f"命令执行失败：{_mask_token(str(exc))}", exit_code=1, truncated=False)

    def ls(self, path: str) -> LsResult:
        """列出虚拟路径下的文件和目录。"""
        try:
            resolved = self._resolve_virtual_path(path)
            if not resolved.exists():
                return LsResult(entries=None, error=f"路径不存在：{path}")
            if not resolved.is_dir():
                return LsResult(entries=None, error=f"当前路径不是目录：{path}")
            return LsResult(
                entries=[
                    {
                        "path": self._to_virtual_path(child),
                        "is_dir": child.is_dir(),
                        "size": child.stat().st_size if child.is_file() else 0,
                        "modified_at": datetime.fromtimestamp(child.stat().st_mtime, UTC).isoformat(),
                    }
                    for child in sorted(resolved.iterdir(), key=lambda p: p.name.lower())
                ]
            )
        except PermissionError as exc:
            return LsResult(entries=None, error=str(exc))

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        """读取文件内容（支持偏移和行数限制）。

        默认先按 UTF-8 解码，失败后回退到 Latin-1。
        这个回退策略的目标不是精准识别编码，而是保证模型在遇到非 UTF-8 文件时仍能看到内容，
        避免因为一次编码异常中断整个 Agent 任务。
        """
        try:
            resolved = self._resolve_virtual_path(file_path)
            if not resolved.exists():
                return ReadResult(error=f"文件不存在：{file_path}")
            if resolved.is_dir():
                return ReadResult(error=f"当前路径是目录，不能读取为文件：{file_path}")
            raw = resolved.read_bytes()
            try:
                text = raw.decode("utf-8")
                encoding = "utf-8"
            except UnicodeDecodeError:
                # 非 UTF-8 文件回退用 Latin-1，保证任何二进制都能读
                text = raw.decode("latin-1")
                encoding = "latin-1"
            lines = text.splitlines()
            if offset or limit:
                text = "\n".join(lines[int(offset) : int(offset) + int(limit)])
            stat = resolved.stat()
            return ReadResult(
                file_data={
                    "content": text,
                    "encoding": encoding,
                    "created_at": datetime.fromtimestamp(stat.st_ctime, UTC).isoformat(),
                    "modified_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
                }
            )
        except PermissionError as exc:
            return ReadResult(error=str(exc))

    def write(self, file_path: str, content: str) -> WriteResult:
        """新建文件。如果文件已存在则报错（修改请用 edit）。"""
        try:
            resolved = self._resolve_virtual_path(file_path)
            denied = self._write_deny_reason(resolved)
            if denied:
                return WriteResult(error=denied)
            if resolved.exists():
                return WriteResult(error=f"文件已存在，修改文件请使用 edit_file：{file_path}")
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content, encoding="utf-8", newline="")
            return WriteResult(path=file_path)
        except PermissionError as exc:
            return WriteResult(error=str(exc))

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        """替换文件中的文本 —— 相当于精细化的 find & replace。"""
        try:
            resolved = self._resolve_virtual_path(file_path)
            if not resolved.exists():
                return EditResult(error=f"文件不存在：{file_path}")
            if resolved.is_dir():
                return EditResult(error=f"当前路径是目录，不能修改为文件：{file_path}")
            denied = self._write_deny_reason(resolved)
            if denied:
                return EditResult(error=denied)
            text = resolved.read_text(encoding="utf-8")
            count = text.count(old_string)
            if count == 0:
                return EditResult(error=f"没有找到要替换的内容：{old_string}")
            if count > 1 and not replace_all:
                return EditResult(error=f"要替换的内容出现 {count} 次，请设置 replace_all=True 或提供更精确片段。")
            updated = text.replace(old_string, new_string, -1 if replace_all else 1)
            resolved.write_text(updated, encoding="utf-8", newline="")
            return EditResult(path=file_path, occurrences=count if replace_all else 1)
        except PermissionError as exc:
            return EditResult(error=str(exc))

    def glob(self, pattern: str, path: str | None = None) -> GlobResult:
        """递归搜索匹配模式的文件路径（支持 fnmatch 通配符）。"""
        try:
            base = self._resolve_virtual_path(path or "/")
            matches = []
            for child in base.rglob("*"):
                virtual = self._to_virtual_path(child)
                if fnmatch.fnmatch(virtual, pattern) or fnmatch.fnmatch(child.name, pattern):
                    matches.append(
                        {
                            "path": virtual,
                            "is_dir": child.is_dir(),
                            "size": child.stat().st_size if child.is_file() else 0,
                            "modified_at": datetime.fromtimestamp(child.stat().st_mtime, UTC).isoformat(),
                        }
                    )
            return GlobResult(matches=matches)
        except PermissionError as exc:
            return GlobResult(matches=None, error=str(exc))

    def grep(self, pattern: str, path: str | None = None, glob: str | None = None) -> GrepResult:
        """在文件中搜索关键词，返回匹配的行号和内容。"""
        try:
            base = self._resolve_virtual_path(path or VIRTUAL_PROJECTS)
            files = [base] if base.is_file() else [p for p in base.rglob("*") if p.is_file()]
            matches = []
            for file in files:
                if glob and not fnmatch.fnmatch(file.name, glob):
                    continue
                try:
                    for line_no, line in enumerate(file.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                        if pattern in line:
                            matches.append({"path": self._to_virtual_path(file), "line": line_no, "text": line})
                except OSError:
                    continue
            return GrepResult(matches=matches)
        except PermissionError as exc:
            return GrepResult(matches=None, error=str(exc))

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """批量上传文件（二进制内容直接写入）。"""
        responses: list[FileUploadResponse] = []
        for path, content in files:
            try:
                resolved = self._resolve_virtual_path(path)
                denied = self._write_deny_reason(resolved)
                if denied:
                    responses.append(FileUploadResponse(path=path, error=denied))
                    continue
                resolved.parent.mkdir(parents=True, exist_ok=True)
                resolved.write_bytes(content)
                responses.append(FileUploadResponse(path=path, error=None))
            except PermissionError:
                responses.append(FileUploadResponse(path=path, error="permission_denied"))
            except IsADirectoryError:
                responses.append(FileUploadResponse(path=path, error="is_directory"))
            except Exception:
                responses.append(FileUploadResponse(path=path, error="invalid_path"))
        return responses

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """批量下载文件，返回二进制内容。"""
        responses: list[FileDownloadResponse] = []
        for path in paths:
            try:
                resolved = self._resolve_virtual_path(path)
                if not resolved.exists():
                    responses.append(FileDownloadResponse(path=path, content=None, error="file_not_found"))
                elif resolved.is_dir():
                    responses.append(FileDownloadResponse(path=path, content=None, error="is_directory"))
                else:
                    responses.append(FileDownloadResponse(path=path, content=resolved.read_bytes(), error=None))
            except PermissionError:
                responses.append(FileDownloadResponse(path=path, content=None, error="permission_denied"))
            except Exception:
                responses.append(FileDownloadResponse(path=path, content=None, error="invalid_path"))
        return responses

    # ── 旧兼容接口 ──────────────────────────────────────────
    # 下面的 read_file / write_file / list_files / run
    # 是为旧版 Gitee/Git 工具保留的入口，内部调上面原生方法。

    def read_file(self, path: str) -> str:
        """读取文本文件（兼容旧工具）。"""
        result = self.read(self._normalize_compat_path(path), offset=0, limit=200_000)
        if result.error:
            if "目录" in result.error or "is_directory" in result.error:
                raise IsADirectoryError(result.error)
            raise FileNotFoundError(result.error)
        return str(result.file_data["content"]) if result.file_data else ""

    def write_file(self, path: str, content: str) -> str:
        """写入文本文件（兼容旧工具，可新建也可覆盖）。"""
        virtual_path = self._normalize_compat_path(path)
        resolved = self._resolve_virtual_path(virtual_path)
        denied = self._write_deny_reason(resolved)
        if denied:
            raise PermissionError(denied)
        if resolved.exists() and resolved.is_dir():
            raise IsADirectoryError(f"write_file 必须写入具体文件，当前路径是目录: {path}")
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8", newline="")
        return str(resolved)

    def list_files(self, path: str = ".") -> list[str]:
        """列出目录下一层内容（兼容旧工具，返回相对路径）。"""
        virtual_path = self._normalize_compat_path(path)
        resolved = self._resolve_virtual_path(virtual_path)
        if not resolved.exists():
            return []
        if resolved.is_file():
            return [str(resolved.relative_to(self.root)).replace("\\", "/")]
        return [str(child.relative_to(self.root)).replace("\\", "/") for child in sorted(resolved.iterdir())]

    def run(self, command: str, cwd: str = ".", timeout: int = 300) -> CommandResult:
        """受控执行命令（给旧 Gitee/Git 工具用，带日志和 Token 屏蔽）。

        与 `execute()` 的区别：
        - `execute()` 面向 DeepAgents 原生协议，返回 `ExecuteResponse`；
        - `run()` 面向项目里的历史工具，返回 `CommandResult`；
        - `run()` 允许指定 cwd，并兼容旧工具常见的 `cd xxx && git ...` 写法。

        这是一层迁移适配，不建议新工具继续绕过 DeepAgents 原生协议调用它。
        """
        cwd_path, command_text = self._prepare_run_command(command, cwd)
        logger.info("执行命令：cwd=%s command=%s timeout=%s", cwd_path, _mask_token(command_text), timeout)
        completed = subprocess.run(
            command_text,
            cwd=str(cwd_path),
            shell=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
            env=self._execution_env(),
            **self._shell_kwargs(),
        )
        logger.info(
            "命令结束：exit_code=%s command=%s stdout_bytes=%s stderr_bytes=%s",
            completed.returncode,
            _mask_token(command_text),
            len(completed.stdout.encode("utf-8", errors="replace")),
            len(completed.stderr.encode("utf-8", errors="replace")),
        )
        return CommandResult(
            command=command_text,
            cwd=str(cwd_path),
            exit_code=completed.returncode,
            stdout=_mask_token(completed.stdout),
            stderr=_mask_token(completed.stderr),
        )

    # ── 初始化相关 ───────────────────────────────────────────

    def _ensure_layout(self) -> None:
        """创建工作区目录结构，写入 workspace 标记文件。

        后端启动时会确保这些目录存在，而不是要求运维或用户手工创建。
        这样 Agent 第一次启动就具备稳定的文件系统语义：
        - `projects`：模型实际修改的业务仓库；
        - `skills`：DeepAgents skills，只读，防止任务过程中被模型篡改；
        - `policies`：工作区说明和安全规则，只读，作为长期规则的一部分；
        - `reviews/tmp/logs`：审查产物、临时文件和运行日志；
        - `.secrets`：Git askpass 脚本等敏感辅助文件，不允许模型读写。
        """
        for directory in (
            self.root,
            self.projects_dir,
            self.skills_dir,
            self.policies_dir,
            self.reviews_dir,
            self.runtimes_dir,
            self.tmp_dir,
            self.logs_dir,
            self.secrets_dir,
            self.shared_python_venv.parent,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        if os.environ.get("LOCAL_SHELL_CREATE_PYTHON_VENV", "false").lower() not in {"0", "false", "no"}:
            self._ensure_shared_python_venv()
        self._ensure_policy_files()
        self._ensure_gitee_askpass_files()
        # 写一个 .ai_coding_workspace.json 标记文件，方便外部工具识别工作区
        state = {
            "backend": "local_shell",
            "root": str(self.root),
            "updated_at": datetime.now(UTC).isoformat(),
            "virtual_dirs": [
                VIRTUAL_PROJECTS,
                VIRTUAL_SKILLS,
                VIRTUAL_POLICIES,
                VIRTUAL_REVIEWS,
                VIRTUAL_RUNTIMES,
                VIRTUAL_TMP,
                VIRTUAL_LOGS,
            ],
        }
        (self.root / ".ai_coding_workspace.json").write_text(
            __import__("json").dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _ensure_policy_files(self) -> None:
        """补全默认的 policy 文件（工作区说明、Git 规范、安全规范）。

        这些文件相当于“文件化的长期规则”：
        - 不依赖数据库即可持久化；
        - 可以被 Prompt 或工具读取后注入 Agent 上下文；
        - 可以随着企业规范演进做版本管理。

        注意这里采用“文件不存在才创建”的策略，避免覆盖用户后续维护过的规则内容。
        """
        defaults = {
            "workspace.md": "# 工作区目录说明\n\n- /projects：Gitee 项目源码目录。\n- /skills：DeepAgents 技能目录。\n- /runtimes：本机运行环境目录。\n- /reviews：审查结果目录。\n- /tmp：临时文件目录。\n- /logs：运行日志目录。\n",
            "git.md": "# Git 规范\n\n- 第一版只处理 Gitee 仓库。\n- 修改代码前先确认仓库目录和当前分支。\n- 提交前必须运行必要测试。\n",
            "security.md": "# 安全规范\n\n- 不读取或输出 .secrets 目录内容。\n- 不提交密钥、Token、私钥或 .env 文件。\n",
        }
        for name, content in defaults.items():
            path = self.policies_dir / name
            if not path.exists():
                path.write_text(content, encoding="utf-8")

    def _ensure_shared_python_venv(self) -> None:
        """创建共享 Python 虚拟环境（供所有项目复用）。"""
        if self._venv_python().exists():
            return
        python = self._system_python()
        if not python:
            self._venv_error = "python executable not found on PATH"
            return
        try:
            completed = subprocess.run(
                [python, "-m", "venv", str(self.shared_python_venv)],
                cwd=self.root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=300,
                check=False,
            )
        except Exception as exc:
            self._venv_error = str(exc)
            return
        if completed.returncode != 0:
            self._venv_error = (completed.stderr or completed.stdout or "venv creation failed").strip()
            return
        self._venv_error = None

    def _ensure_gitee_askpass_files(self) -> None:
        """生成 Git 非交互认证脚本。

        因为 Agent 后台不能弹窗让用户输密码，所以预先创建 askpass 脚本，
        Git 需要凭据时会自动调用它，从环境变量读取 token。

        这个实现的核心价值是把认证从命令参数里移出去：
        - 命令日志里不会出现 token；
        - Git 命令仍然可以走标准 HTTPS 认证流程；
        - 后端可以统一通过 `_execution_env()` 注入认证环境变量。
        """
        ps1 = self.secrets_dir / "gitee_askpass.ps1"
        cmd = self.secrets_dir / "gitee_askpass.cmd"
        sh = self.secrets_dir / "gitee_askpass.sh"
        if not IS_WINDOWS:
            if not sh.exists():
                sh.write_text(
                    "\n".join(
                        [
                            "#!/usr/bin/env bash",
                            "case \"$1\" in",
                            "  *sername*|*Username*) printf '%s' \"$GITEE_ASKPASS_USERNAME\" ;;",
                            "  *) printf '%s' \"$GITEE_ASKPASS_TOKEN\" ;;",
                            "esac",
                        ]
                    )
                    + "\n",
                    encoding="utf-8",
                )
                sh.chmod(0o700)
            return
        if not ps1.exists():
            ps1.write_text(
                "\n".join(
                    [
                        "param([string]$Prompt)",
                        "if ($Prompt -match '(?i)username') {",
                        "  [Console]::Out.Write($env:GITEE_ASKPASS_USERNAME)",
                        "} else {",
                        "  [Console]::Out.Write($env:GITEE_ASKPASS_TOKEN)",
                        "}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
        if not cmd.exists():
            cmd.write_text(
                f'@echo off\r\npowershell -NoProfile -ExecutionPolicy Bypass -File "{ps1}" %*\r\n',
                encoding="utf-8",
            )

    # ── 路径处理 ─────────────────────────────────────────────

    def _normalize_compat_path(self, path: str | os.PathLike[str]) -> str:
        """把旧工具传过来的路径统一成虚拟路径格式（/ 开头）。

        旧工具可能传入 `.`、`projects/a.py`、`\\projects\\a.py` 等形式。
        后端内部统一转换成 `/projects/a.py` 这种虚拟路径，后续再走同一套解析和权限检查。
        """
        raw = str(path).strip().replace("\\", "/")
        if raw in {"", "."}:
            return "/"
        if raw.startswith("/"):
            return raw
        return "/" + raw

    def _resolve_virtual_path(self, path: str | os.PathLike[str]) -> Path:
        """把虚拟路径（如 `/projects/my-repo`）转成真实文件系统路径。

        这是文件读写权限的关键入口。无论调用方传入虚拟路径还是 Windows 绝对路径，
        最终都必须解析成真实路径，并确认它仍然位于 `self.root` 工作区内。
        """
        raw = str(path).strip() or "/"
        if re.match(r"^[A-Za-z]:[\\/]", raw):
            resolved = Path(raw).resolve()
        else:
            normalized = raw.replace("\\", "/")
            virtual_roots = (
                "/projects",
                "/skills",
                "/policies",
                "/reviews",
                "/runtimes",
                "/tmp",
                "/logs",
            )
            if (
                not IS_WINDOWS
                and Path(normalized).is_absolute()
                and not any(normalized == root or normalized.startswith(root + "/") for root in virtual_roots)
            ):
                resolved = Path(normalized).resolve()
            else:
                if normalized.startswith("/"):
                    normalized = normalized[1:]
                resolved = (self.root / normalized).resolve()
        # 安全检查：必须落在工作区范围内
        if not self._is_under_root(resolved):
            raise PermissionError(f"path outside local workspace is denied: {path}")
        return resolved

    def _to_virtual_path(self, path: Path) -> str:
        """把真实路径转回虚拟路径（/ 开头）。

        DeepAgents 和模型不应该直接感知宿主机真实磁盘路径。
        返回虚拟路径可以降低环境耦合，也能避免把本机目录结构暴露给模型上下文。
        """
        resolved = path.resolve()
        if not self._is_under_root(resolved):
            raise PermissionError(f"path outside local workspace is denied: {path}")
        rel = resolved.relative_to(self.root).as_posix()
        return "/" + rel if rel else "/"

    def _is_under_root(self, path: Path) -> bool:
        """判断路径是否在工作区根目录之下（安全工作区边界检查）。"""
        try:
            path.relative_to(self.root)
            return True
        except ValueError:
            return False

    def _is_under(self, path: Path, parent: Path) -> bool:
        """判断 path 是否在 parent 目录之下。"""
        try:
            path.relative_to(parent)
            return True
        except ValueError:
            return False

    # ── 安全控制 ─────────────────────────────────────────────

    def _write_deny_reason(self, path: Path) -> str | None:
        """检查目录是否禁止写入。

        项目只允许模型主要修改 `/projects` 下的业务仓库。
        `skills/policies/runtimes/logs/.secrets` 都属于后端运行基础设施或规则资产，
        不允许在普通任务中被模型写入，避免 Agent 自己改掉工具、规则、运行时或敏感文件。
        """
        if self._is_under(path, self.policies_dir):
            return "write denied: policies are read-only"
        if self._is_under(path, self.skills_dir):
            return "write denied: skills are read-only"
        if self._is_under(path, self.runtimes_dir):
            return "write denied: runtimes are read-only"
        if self._is_under(path, self.logs_dir):
            return "write denied: logs are read-only"
        if self._is_under(path, self.secrets_dir):
            return "write denied: secrets are protected"
        return None

    def _is_writable(self, path: Path) -> bool:
        """测写入权限：尝试写一个临时文件，成功就表示可写。"""
        try:
            probe = path / ".write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return True
        except OSError:
            return False

    def _deny_reason(self, command: str) -> str | None:
        """安全守卫：检测命令是否越界或使用了危险操作。

        这里是 `normalize_safe_command()` 之前的第一层粗粒度拒绝：
        - 拦截 `..` 路径穿越；
        - 拦截明显危险的系统命令；
        - 拦截指向工作区外的 Windows 绝对路径。

        两层校验的分工是：本函数做场景级拒绝，`normalize_safe_command()` 做命令白名单和语法收敛。
        """
        lowered = command.lower()
        if _NESTED_PROJECTS_PATH_RE.search(command.replace("\\", "/")):
            return "nested projects path is denied; use /projects/<repo> for file tools or <repo> in execute commands"
        if "../" in command or "..\\" in command:
            return "path traversal outside workspace is denied"
        if not IS_WINDOWS and _LINUX_SENSITIVE_PATH_RE.search(command):
            return "absolute Linux system path is denied"
        for pattern in _DANGEROUS_PATTERNS:
            if re.search(pattern, lowered):
                return f"dangerous command pattern matched: {pattern}"
        for match in _DRIVE_PATH_RE.finditer(command):
            candidate = Path(match.group(1)).resolve()
            if not self._is_under_root(candidate):
                return f"absolute path outside workspace: {candidate}"
        return None

    # ── 命令预处理 ───────────────────────────────────────────

    def _prepare_command(self, command: str, *, cwd_path: Path | None = None) -> str:
        """执行前的命令预处理：适配当前系统、替换虚拟路径。

        LLM 常按 Linux/Unix 习惯生成命令，例如 `python3`、`pwd`、`test -d`。
        Windows 本地开发时，本方法会把这些常见表达转换成 Windows 可执行形式；
        Linux 部署时，这些命令通常可以原样执行。
        同时把 `/projects/...` 这样的虚拟路径替换为带引号的真实路径。
        """
        if cwd_path is not None and cwd_path.resolve() == self.projects_dir.resolve():
            command = self._normalize_command_for_projects_cwd(command)
        prepared = command.replace("python3 ", "python ") if IS_WINDOWS else command
        prepared = _VIRTUAL_PATH_RE.sub(self._virtual_command_path_replacement, prepared)
        # 兼容 Unix 常用命令
        if IS_WINDOWS and prepared.strip() == "pwd":
            return "cd"
        if IS_WINDOWS and prepared.startswith('printf %s "$HOME"'):
            return "echo %USERPROFILE%"
        if IS_WINDOWS and prepared.startswith("test -d "):
            return "echo ok"
        return self._prepare_git_command(prepared)

    def _normalize_command_for_projects_cwd(self, command: str) -> str:
        """修正默认在 /projects 目录执行时容易产生的重复相对路径。

        DeepAgents 原生 execute 没有 cwd 参数，本项目会把命令默认放在
        `/projects` 对应的真实 projects 目录下执行。此时如果命令中再写
        projects/<repo>，实际访问路径会变成 projects/projects/<repo>。
        这里把相对的 projects/<repo> 收敛成 <repo>，把单独的 projects 收敛成 .。
        以 /projects 开头的虚拟路径不受影响，后续仍会映射到真实工作区目录。
        """

        normalized = _RELATIVE_PROJECTS_PATH_RE.sub("", command)
        normalized = _RELATIVE_PROJECTS_DIR_RE.sub(".", normalized)
        if normalized != command:
            logger.info(
                "已修正 projects 工作目录下的重复相对路径：%s -> %s",
                _mask_token(command),
                _mask_token(normalized),
            )
        return normalized

    def _prepare_git_command(self, command: str) -> str:
        """给 git 命令注入 askpass 配置，避免弹窗或使用过期的凭据管理器。

        通过 `git -c credential.helper= -c core.askPass=...` 临时覆盖 Git 配置，
        可以让单次命令稳定使用当前 Agent 后端注入的 Gitee token。
        这样不会污染用户全局 Git 配置，也不会依赖桌面凭据管理器。
        """
        stripped = command.lstrip()
        leading = command[: len(command) - len(stripped)]
        if stripped == "git":
            rest = ""
        elif stripped.lower().startswith("git "):
            rest = stripped[4:]
        else:
            return command
        askpass = str(self._git_askpass_path())
        return f'{leading}git -c credential.helper= -c core.askPass="{askpass}" {rest}'.rstrip()

    def _prepare_run_command(self, command: str, cwd: str) -> tuple[Path, str]:
        """准备 `run()` 的命令：解析 cwd、兼容 `cd`、安全检查、规范化。

        旧工具常把命令写成 `cd repo && git status`。
        这里不会直接把整段 shell 原样执行，而是提取 `cd` 后的目录作为 subprocess 的 cwd，
        再对后半段命令做安全检查和白名单归一化。
        """
        cwd_path = self._resolve_virtual_path(self._normalize_compat_path(cwd))
        command = re.sub(r"\s+2>&1(?=\s*(?:&&|\|\||$))", "", command.strip())
        first_part = command.split("&&", 1)[0].strip()
        cd_match = re.fullmatch(r"cd\s+(.+)", first_part, flags=re.IGNORECASE)
        if cd_match:
            # 兼容 `cd xxx && command`，但不把 `cd` 作为真正的 shell 片段执行。
            # 这样可以减少 shell 拼接能力，同时保留旧工具的使用习惯。
            cwd_path = self._resolve_virtual_path(self._normalize_compat_path(cd_match.group(1).strip().strip('"').strip("'")))
            command = command.split("&&", 1)[1].strip() if "&&" in command else ""
        if not command:
            raise ValueError("Command cannot be empty")
        if self.command_guard_enabled:
            denied = self._deny_reason(command)
            if denied:
                raise PermissionError(f"命令被拒绝：{denied}")
        # 第二层安全校验：命令白名单、危险 shell 操作符和危险片段收敛。
        safe_command = normalize_safe_command(command)
        return cwd_path, self._prepare_command(safe_command, cwd_path=cwd_path)

    def _virtual_command_path_replacement(self, match: re.Match[str]) -> str:
        """把命令中的 `/projects/xxx` 等虚拟路径替换为真实路径（带引号防空格）。

        这个函数只用于命令文本中的路径替换；文件工具的路径解析走 `_resolve_virtual_path()`。
        两者都必须确认最终路径仍在工作区内，避免模型通过构造路径逃逸。
        """
        roots = {
            "projects": self.projects_dir,
            "skills": self.skills_dir,
            "policies": self.policies_dir,
            "reviews": self.reviews_dir,
            "runtimes": self.runtimes_dir,
            "tmp": self.tmp_dir,
            "logs": self.logs_dir,
        }
        root = roots[match.group(1)]
        suffix = (match.group(2) or "").lstrip("/")
        path = (root / Path(*suffix.split("/"))).resolve() if suffix else root
        if not self._is_under_root(path):
            raise PermissionError(f"virtual path escapes workspace: {match.group(0)}")
        return f'"{path}"'

    def _execution_env(self) -> dict[str, str]:
        """构造子进程环境变量：注入 venv、Git 安全配置、Gitee 认证信息。

        命令执行环境是企业项目里很容易失控的地方，所以这里统一集中处理：
        - 如果共享 Python venv 存在，优先放到 PATH 前面；
        - 禁用 Git 交互式弹窗，后台任务失败也要以文本形式返回；
        - 如果配置了 Gitee token，通过 `GIT_ASKPASS` 注入，不拼进命令字符串。
        """
        env = os.environ.copy()
        scripts = self._venv_bin_dir()
        if scripts.exists():
            env["PATH"] = f"{scripts}{os.pathsep}{env.get('PATH', '')}"
            env["VIRTUAL_ENV"] = str(self.shared_python_venv)
        # 禁止 Git 交互式弹窗，出错直接返回
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["GCM_INTERACTIVE"] = "Never"
        gitee_token = get_env("GITEE_TOKEN").strip() or get_env("SCM_GITEE_TOKEN").strip()
        if gitee_token:
            env["GIT_ASKPASS"] = str(self._git_askpass_path())
            env["GITEE_ASKPASS_USERNAME"] = "oauth2"
            env["GITEE_ASKPASS_TOKEN"] = gitee_token
        return env


# ── 模块级单例 ────────────────────────────────────────────

_BACKEND: LocalShellBackend | None = None


def get_local_shell_backend() -> LocalShellBackend:
    """获取全局唯一的 LocalShellBackend 实例（单例）。"""
    global _BACKEND
    if _BACKEND is None:
        _BACKEND = LocalShellBackend()
    return _BACKEND


def create_local_shell_backend(_sandbox_id: str | None = None) -> LocalShellBackend:
    """DeepAgents 工厂函数：创建（或复用）backend 实例。"""
    return get_local_shell_backend()


def validate_local_shell_startup_config() -> None:
    """启动时验证：确保 backend 可以正常创建。"""
    get_local_shell_backend()
