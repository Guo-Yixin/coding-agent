from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from langgraph.store.base import BaseStore

from agent.core.repo_memory import build_repo_memory_namespace, get_repo_memory_item, repo_memory_store_key
from agent.tools.gitee_api import GiteeRepo, mask_token

logger = logging.getLogger("agent.run.repo_memory_update")

MAX_RECENT_ITEMS = 20
MAX_FACT_CHARS = 350
SENSITIVE_MARKERS = (".env", ".secrets", "api_key", "apikey", "private key", "私钥")


@dataclass(frozen=True)
class RepoMemoryUpdate:
    """一次仓库记忆更新所需的稳定事实。"""

    task_kind: str
    final_text: str
    branch_name: str | None = None
    pr_url: str | None = None


def _contains_sensitive_text(text: str) -> bool:
    """判断文本是否包含不应写入长期记忆的敏感标记。"""

    lowered = text.lower()
    return any(marker in lowered for marker in SENSITIVE_MARKERS)


def _compact_line(text: str, *, limit: int = MAX_FACT_CHARS) -> str:
    """把最终回答压缩成适合写入“最近结论”的单行文本。"""

    compacted = " ".join(mask_token(text).split())
    if len(compacted) > limit:
        compacted = compacted[:limit].rstrip() + "..."
    return compacted


def _extract_bullets(text: str, *, keywords: tuple[str, ...], limit: int = 8) -> list[str]:
    """从最终回答中提取包含关键词的列表项。

    这里只做规则提取，不调用模型。它适合抓取 Agent 最终总结里的测试命令、
    关键文件、已完成能力等稳定信息。
    """

    results: list[str] = []
    for raw_line in text.splitlines():
        if not re.match(r"^\s*(?:[-*]|\d+[.)、])\s+", raw_line):
            continue
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^[-*]\s+", "", line)
        line = re.sub(r"^\d+[.)、]\s*", "", line)
        if line.startswith(("#", "|", "```")):
            continue
        if not line or _contains_sensitive_text(line):
            continue
        lowered = line.lower()
        if any(keyword.lower() in lowered for keyword in keywords):
            clean = mask_token(line)
            if clean not in results:
                results.append(clean)
        if len(results) >= limit:
            break
    return results


def _extract_code_items(text: str, *, suffixes: tuple[str, ...], limit: int = 10) -> list[str]:
    """从 Markdown 反引号内容中提取文件名或命令。"""

    results: list[str] = []
    for item in re.findall(r"`([^`]+)`", text):
        clean = item.strip()
        if not clean or _contains_sensitive_text(clean):
            continue
        if any(clean.endswith(suffix) for suffix in suffixes) or any(suffix in clean for suffix in suffixes):
            if clean not in results:
                results.append(mask_token(clean))
        if len(results) >= limit:
            break
    return results


def _extract_test_commands(text: str, *, limit: int = 5) -> list[str]:
    """提取明确可执行的测试命令，避免把 git log 或说明文字误当命令。"""

    results: list[str] = []
    for item in re.findall(r"`([^`]+)`", text):
        clean = item.strip()
        lowered = clean.lower()
        if lowered.startswith(("python -m pytest", "pytest")) and not _contains_sensitive_text(clean):
            if clean not in results:
                results.append(mask_token(clean))
        if len(results) >= limit:
            return results

    for raw_line in text.splitlines():
        line = raw_line.strip()
        lowered = line.lower()
        if lowered.startswith(("python -m pytest", "pytest")) and not _contains_sensitive_text(line):
            clean = mask_token(line)
            if clean not in results:
                results.append(clean)
        if len(results) >= limit:
            break
    if len(results) < limit:
        for match in re.findall(r"(?:python\s+-m\s+pytest|pytest)(?:\s+[A-Za-z0-9_./\\:-]+)?", text, flags=re.I):
            clean = " ".join(match.strip().split())
            if clean and clean not in results and not _contains_sensitive_text(clean):
                results.append(mask_token(clean))
            if len(results) >= limit:
                break
    return results


def _extract_file_names(text: str, *, limit: int = 10) -> list[str]:
    """从普通说明文字中提取常见项目文件名。"""

    results: list[str] = []
    for match in re.findall(r"[\w.-]+\.(?:py|md|txt|html|json|toml)", text, flags=re.I):
        clean = match.strip()
        if clean and clean not in results and not _contains_sensitive_text(clean):
            results.append(mask_token(clean))
        if len(results) >= limit:
            break
    return results


def _detect_stack(text: str) -> list[str]:
    """从最终回答中识别常见技术栈关键词。"""

    candidates = {
        "FastAPI": ("fastapi",),
        "SQLite": ("sqlite",),
        "pytest": ("pytest",),
        "uvicorn": ("uvicorn",),
        "JWT": ("jwt", "python-jose"),
        "passlib/bcrypt": ("passlib", "bcrypt"),
    }
    lowered = text.lower()
    return [name for name, markers in candidates.items() if any(marker in lowered for marker in markers)]


def _replace_section(memory: str, heading: str, items: list[str]) -> str:
    """用列表项替换 Markdown 二级标题下的内容。"""

    if not items:
        return memory
    section = f"{heading}\n" + "\n".join(f"- {item}" for item in items) + "\n\n"
    pattern = re.compile(rf"(^## {re.escape(heading.removeprefix('## '))}\n)(.*?)(?=^## |\Z)", re.M | re.S)
    if pattern.search(memory):
        return pattern.sub(section, memory, count=1)
    return f"{memory.rstrip()}\n\n{section}"


def _append_recent(memory: str, *, task_kind: str, fact: str) -> str:
    """追加“最近结论”，并限制条数。"""

    if not fact or _contains_sensitive_text(fact):
        return memory
    entry = f"- {date.today().isoformat()}（{task_kind}）：{fact}"
    heading = "## 最近结论"
    if entry in memory:
        return memory
    if heading not in memory:
        return f"{memory.rstrip()}\n\n{heading}\n{entry}\n"
    before, after = memory.split(heading, 1)
    lines = []
    for line in after.strip().splitlines():
        stripped = line.strip()
        if not stripped or stripped == "- 暂无":
            continue
        # 早期版本可能把整段 Markdown、表格或代码块塞进最近结论。
        # 长期记忆只保留短事实，避免下一轮上下文被历史噪声污染。
        if len(stripped) > 520 or "```" in stripped or "| 项目 |" in stripped:
            continue
        lines.append(stripped)
    recent_items = [entry, *lines][:MAX_RECENT_ITEMS]
    return f"{before.rstrip()}\n\n{heading}\n" + "\n".join(recent_items) + "\n"


def _metadata_items(*, branch_name: str | None, pr_url: str | None) -> list[str]:
    """整理分支和 PR 这类线程元数据。"""

    items: list[str] = []
    if branch_name:
        items.append(f"最近分支：`{branch_name}`")
    if pr_url:
        items.append(f"最近 Pull Request：{pr_url}")
    return items


def build_updated_repo_memory(memory: str, update: RepoMemoryUpdate) -> str:
    """根据任务最终输出生成更新后的仓库记忆正文。"""

    text = mask_token(update.final_text or "")
    if not text.strip() or _contains_sensitive_text(text):
        return memory

    stack = _detect_stack(text)
    test_commands = _extract_test_commands(text, limit=5)
    key_files = _extract_code_items(text, suffixes=(".py", ".md", ".txt", ".html", ".json", ".toml"), limit=10)
    for file_name in _extract_file_names(text, limit=10):
        if file_name not in key_files:
            key_files.append(file_name)
        if len(key_files) >= 10:
            break
    completed_features = _extract_bullets(
        text,
        keywords=("接口", "新增", "完成", "实现", "测试通过", "passed"),
        limit=8,
    )
    completed_features = [
        item
        for item in completed_features
        if not any(skip in item for skip in ("分支", "Pull Request", " PR", "Fast-forward", "merge"))
    ]

    updated = memory
    if stack:
        updated = _replace_section(updated, "## 技术栈", stack)
    if test_commands:
        updated = _replace_section(updated, "## 测试命令", test_commands)
    if key_files:
        updated = _replace_section(updated, "## 关键文件", key_files)
    metadata = _metadata_items(branch_name=update.branch_name, pr_url=update.pr_url)
    if metadata:
        updated = _replace_section(updated, "## 分支与 PR", metadata)
    if completed_features:
        updated = _replace_section(updated, "## 已完成能力", completed_features)

    return _append_recent(updated, task_kind=update.task_kind, fact=_compact_line(text))


def update_repo_memory_from_text(
    *,
    store: BaseStore,
    repo: GiteeRepo,
    update: RepoMemoryUpdate,
) -> bool:
    """把任务最终输出写回仓库级长期记忆。

    返回值表示是否真的修改了记忆文件。调用方可以据此记录日志或前端事件。
    """

    namespace = build_repo_memory_namespace(repo.owner, repo.repo)
    item = get_repo_memory_item(store, namespace)
    if item is None:
        logger.info("仓库记忆不存在，跳过结构化更新：repo=%s/%s", repo.owner, repo.repo)
        return False

    current = str(item.value.get("content") or "")
    updated = build_updated_repo_memory(current, update)
    if updated == current:
        logger.info("仓库记忆无新增稳定结论：repo=%s/%s task_kind=%s", repo.owner, repo.repo, update.task_kind)
        return False

    value = dict(item.value)
    value["content"] = updated
    store.put(namespace, repo_memory_store_key(repo.owner, repo.repo), value)
    logger.info("仓库记忆已结构化更新：repo=%s/%s task_kind=%s", repo.owner, repo.repo, update.task_kind)
    return True
