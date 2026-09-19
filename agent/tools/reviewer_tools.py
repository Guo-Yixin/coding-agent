"""代码审查结果工具。

这些工具把模型发现的问题保存到业务 SQLite Store 中，供前端、任务详情页或后续流程读取。
与直接把审查结论写在自然语言回复中相比，结构化保存可以支持筛选、排序、状态流转和二次汇总。
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from agent.backends.local_shell import LocalShellBackend
from agent.core.graph import get_store
from agent.reviewer_diff import get_local_diff_summary, parse_unified_diff, validate_finding_location
from agent.tools.runtime_context import get_runtime_thread_id

DEFAULT_RULES_PATH = Path(__file__).resolve().parents[1] / "reviewer_rules" / "default_review_rules.md"


def _compact_diff_for_model(raw_diff: str, *, limit: int = 20000) -> str:
    """限制传给模型的 diff 文本长度，避免 reviewer 首轮上下文过大。"""

    text = raw_diff.strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n\n...（diff 内容过长，已截断；必要时请读取具体文件继续审查）"


@tool
def load_default_review_rules() -> dict[str, Any]:
    """读取项目内置的默认代码审查规则。

    这个工具只做兜底读取，不再访问 `/policies` 或 `/projects`。
    Reviewer 子 Agent 应优先通过 DeepAgents 原生 `read_file` 读取：

    - `/policies/review_rules.md`：项目工作区的通用审查规则；
    - `/projects/<repo>/.lx/review-rules.md`：仓库自己的补充审查规则。

    只有这些规则文件不存在或为空时，才调用本工具读取项目内置默认规则。
    这样可以避免工具内部私自创建 backend，保证文件访问都走 Agent 运行时
    统一注入的 backend 和权限边界。

    Returns:
        包含规则来源和 Markdown 文本的字典。
    """

    default_rules = DEFAULT_RULES_PATH.read_text(encoding="utf-8").strip()
    source = "agent/reviewer_rules/default_review_rules.md"
    return {
        "sources": [source] if default_rules else [],
        "rules": f"## 规则来源：{source}\n\n{default_rules}" if default_rules else "",
    }


@tool
def get_review_diff_summary(repo_dir: str, base: str = "master", head: str | None = None) -> dict[str, Any]:
    """读取本地 git diff，并返回变更文件、变更行号和截断后的 diff 文本。

    Args:
        repo_dir: 仓库虚拟路径，例如 `projects/ai_coding`。
        base: 基准分支或 commit，默认 `master`。
        head: 可选目标分支。传入时比较 `base...head`；不传时比较工作区相对 base 的 diff。
    """

    backend = LocalShellBackend()
    summary = get_local_diff_summary(backend, repo_dir=repo_dir, base=base, head=head)
    files = [
        {
            "path": file.path,
            "changed_lines": list(file.changed_lines),
            "changed_lines_count": len(file.changed_lines),
        }
        for file in summary.files
    ]
    return {
        "base": summary.base,
        "head": summary.head,
        "files": files,
        "files_count": len(files),
        "raw_diff_preview": _compact_diff_for_model(summary.raw_diff),
    }


@tool
def validate_review_finding_location(raw_diff: str, file: str, line: int | None = None) -> dict[str, Any]:
    """校验审查发现是否落在真实 diff 文件和变更行上。

    Args:
        raw_diff: unified diff 文本。通常来自 `get_review_diff_summary` 的完整 diff；
            如果只有 preview，超长 diff 场景下建议读取具体文件后把 finding 标为文件级。
        file: finding 指向的仓库内相对路径。
        line: finding 指向的新文件行号。无法定位时可以为空。
    """

    summary = parse_unified_diff(raw_diff)
    ok, message = validate_finding_location(summary, file=file, line=line)
    return {"ok": ok, "message": message}


@tool
def add_review_finding(
    file: str,
    line: int | None,
    severity: str,
    title: str,
    description: str,
) -> dict[str, str]:
    """把代码审查发现记录到本地 SQLite Store。

    Args:
        file: 问题所在文件路径，通常是仓库内相对路径。
        line: 问题所在行号；无法定位到具体行时可以为空。
        severity: 严重级别，例如 blocker、major、minor、info。
        title: 简短标题，用于列表展示。
        description: 详细说明，包含风险、触发条件和建议修复方式。

    Returns:
        成功时返回 finding id 和初始状态；缺少 thread_id 时返回 error。
    """

    thread_id = get_runtime_thread_id()
    if not thread_id:
        return {"status": "error", "error": "缺少 thread_id，无法记录审查发现。"}

    if severity not in {"critical", "high", "medium", "low", "info", "blocker", "major", "minor"}:
        return {"status": "error", "error": f"不支持的 severity: {severity}"}

    # 使用短 UUID 作为本地发现项 id，避免依赖数据库自增 id 暴露给模型。
    finding_id = f"finding-{uuid.uuid4().hex[:8]}"
    # 所有审查发现都绑定当前 thread_id，保证不同任务之间的数据不会串联。
    get_store().add_finding(
        finding_id=finding_id,
        thread_id=thread_id,
        file=file,
        line=line,
        severity=severity,
        title=title,
        description=description,
    )
    return {"id": finding_id, "status": "open"}


@tool
def list_review_findings() -> list[dict[str, Any]]:
    """列出当前 thread 的代码审查发现。

    该工具用于让模型在最终回复前重新读取已记录的问题，避免遗漏前面阶段保存的发现项。
    """

    thread_id = get_runtime_thread_id()
    if not thread_id:
        return [{"status": "error", "error": "缺少 thread_id，无法读取审查发现。"}]
    # Store 层负责具体 SQL 查询和结果结构化，这里只传递当前任务的 thread_id。
    return get_store().list_findings(thread_id)
