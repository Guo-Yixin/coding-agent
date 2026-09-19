"""后端安全校验模块。

这个文件提供的是 `LocalShellBackend` 之外的通用安全函数，主要覆盖三类风险：

1. 路径风险：
   - 防止 Agent 通过绝对路径或 `..` 访问工作区外文件。
2. 命令风险：
   - 限制模型只能执行少量项目需要的命令族。
   - 拦截管道、重定向、删除、关机、注册表等危险操作。
3. Git 参数风险：
   - 分支名、提交信息来自模型输出，必须在进入 shell 前做归一化和校验。

开发调试时要强调：
这里不是完整的企业沙箱，只是本地部署版 Windows backend 的安全收敛层。
真正生产环境还应结合容器、系统权限、审计、网络隔离和更严格的命令执行策略。
"""

from __future__ import annotations

import re
from pathlib import Path


class WorkspacePermissionError(PermissionError):
    """工作区或命令权限错误。

    继承 `PermissionError` 的好处是：
    - 调用方可以按标准权限异常处理；
    - middleware 能识别这是可恢复的安全拒绝，而不是系统崩溃；
    - 错误语义比普通 `ValueError` 更明确。
    """


def assert_path_inside(path: Path, root: Path) -> Path:
    """确认 path 解析后仍位于 root 工作区内。

    参数：
        path: 待校验路径，可以是相对路径或绝对路径。
        root: 工作区根目录。

    返回：
        解析后的绝对路径。

    抛出：
        WorkspacePermissionError: 如果 path 不在 root 内。

    这是文件访问的基础安全边界，防止模型使用 `..`、盘符绝对路径等方式
    读取或写入项目工作区外的文件。
    """

    resolved_root = root.resolve()
    resolved_path = path.resolve()
    if resolved_path == resolved_root or resolved_root in resolved_path.parents:
        return resolved_path
    raise WorkspacePermissionError(f"Path is outside workspace: {resolved_path}")


def normalize_safe_command(command: str) -> str:
    """校验 Agent 准备执行的本地命令。

    本地部署版第一版只允许少量开发需要的命令族：
    python/python3/py、pytest、pip、git、dir、type、ruff。

    模型经常会在命令末尾追加 `2>&1` 或 `| tail -5`。
    前者是为了合并 stderr，后者是 Unix 查看末尾输出的习惯。
    本地部署版在 Python 中已经捕获 stdout/stderr，也会把完整输出返回给模型，
    所以这里剥离这两个尾部片段，既兼容模型习惯，又不放开任意管道/重定向能力。
    """

    normalized = command.strip()
    normalized = re.sub(r"\s+\|\s*tail\s+-?\d+\s*$", "", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\s+2>&1\s*$", "", normalized)
    lowered = normalized.lower()
    first_word = normalized.split(maxsplit=1)[0].lower() if normalized else ""
    # 本地部署版只放开和 Python/Git 项目验证相关的命令。
    # 如果未来要允许 npm、mvn、gradle 等命令，应在这里明确加白名单，
    # 同时补充对应的安全测试，而不是直接放开任意 shell。
    allowed_commands = {"python", "python3", "py", "pytest", "pip", "git", "dir", "type", "ruff"}
    if first_word not in allowed_commands:
        raise WorkspacePermissionError(f"Command is not allowed: {command}")

    # shell 操作符会显著扩大命令能力，例如管道、重定向、命令拼接、命令替换。
    # 本地部署版不允许模型组合复杂 shell 片段，避免绕过上面的命令白名单。
    shell_operators = [
        "&&",
        "||",
        "|",
        "&",
        ";",
        ">",
        "<",
        "`",
        "$(",
        "\n",
        "\r",
    ]
    if any(operator in normalized for operator in shell_operators):
        raise WorkspacePermissionError(f"Blocked shell operator in command: {command}")
    # 这些危险片段即使出现在白名单命令后面，也应直接拒绝。
    # 例如模型生成 `python -c "import os; os.system('del ...')"` 时，仍需要额外防线。
    blocked = [
        "format ",
        "shutdown",
        "restart-computer",
        "remove-item",
        "remove-item -recurse",
        "rm -rf",
        "reg delete",
        "del ",
        "del /s",
        "rmdir ",
        "rmdir /s",
        "cipher /w",
    ]
    if any(token in lowered for token in blocked):
        raise WorkspacePermissionError(f"Blocked dangerous command: {command}")
    return normalized


def ensure_safe_command(command: str) -> None:
    """兼容旧调用方的命令校验函数。

    旧代码只需要“成功或抛异常”，不关心归一化后的命令文本。
    因此这里直接调用 `normalize_safe_command`，如果命令不安全就抛出异常。
    """

    normalize_safe_command(command)


_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")


def ensure_safe_git_branch(branch: str) -> str:
    """校验 Git 分支名是否安全。

    分支名通常由 Agent 根据任务自动生成或拼接。进入 shell 前必须限制字符集，
    防止出现命令注入、路径穿越、Git 特殊引用语法等问题。
    """

    if not _BRANCH_RE.fullmatch(branch):
        raise WorkspacePermissionError(f"Invalid git branch name: {branch}")
    if ".." in branch or branch.endswith("/") or branch.endswith(".lock") or "@{" in branch:
        raise WorkspacePermissionError(f"Invalid git branch name: {branch}")
    return branch


def ensure_safe_git_message(message: str) -> str:
    """把模型生成的提交信息归一化为安全的单行 commit message。

    模型经常会生成多行提交说明，甚至包含 JSON 示例中的双引号。
    Git 本身支持复杂 message，但本地部署版当前通过 Windows shell 执行 git commit，
    所以这里把 message 压缩成单行，并移除 shell 风险字符。
    """

    # 先把所有换行、Tab 和连续空白压缩成单行，避免命令参数被拆成多段。
    normalized = " ".join(message.split())
    # Windows shell 下双引号会影响参数边界，这里替换成单引号，保留语义但降低注入风险。
    normalized = normalized.replace('"', "'")
    # 即使 message 不作为命令本体执行，也会出现在 shell 参数里；
    # 因此把常见 shell 控制符清理掉，避免意外改变 git commit 命令结构。
    for token in ["&", "|", ";", "<", ">", "`", "$("]:
        normalized = normalized.replace(token, " ")
    normalized = " ".join(normalized.split())
    # 给空 message 一个稳定兜底值，避免 Git 因提交信息为空而失败。
    if not normalized:
        return "CODING generated changes"
    # 控制长度，避免模型生成超长 message 影响日志可读性或命令行参数长度。
    return normalized[:200]
