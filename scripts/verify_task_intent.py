from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.core.task_intent import classify_task_kind
from agent.tools import (
    add_review_finding,
    fetch_url,
    list_review_findings,
    open_gitee_pull_request,
    publish_gitee_pr_comment,
    web_search,
)


def _tool_names(tools: list[object]) -> set[str]:
    names: set[str] = set()
    for item in tools:
        names.add(getattr(item, "name", type(item).__name__))
    return names


def main() -> None:
    prompt = "先帮我解析一下整个项目的目录结构?"
    task_kind = classify_task_kind(prompt)
    if task_kind != "analysis":
        raise AssertionError(f"任务类型识别错误：{task_kind}")

    qa_prompt = "当前项目的记忆文件内容是什么？"
    qa_task_kind = classify_task_kind(qa_prompt)
    if qa_task_kind != "qa":
        raise AssertionError(f"普通问答不应进入方案或编码流程：{qa_prompt} -> {qa_task_kind}")

    coding_prompts = [
        "我想把这个项目的数据存储改为：sqlite数据库",
        "我想把这个项目的数据存储，改成sqlite",
        "把 JSON 存储迁移到 SQLite",
    ]
    for coding_prompt in coding_prompts:
        detected = classify_task_kind(coding_prompt)
        if detected != "coding":
            raise AssertionError(f"改造类任务应识别为 coding：{coding_prompt} -> {detected}")

    tools = [
        web_search,
        fetch_url,
        open_gitee_pull_request,
        publish_gitee_pr_comment,
        add_review_finding,
        list_review_findings,
    ]
    names = _tool_names(tools)
    forbidden = {
        "clone_gitee_repo",
        "git_status",
        "commit_and_push",
    }
    leaked = forbidden.intersection(names)
    if leaked:
        raise AssertionError(f"工具列表暴露了已移除的仓库/Git 操作工具：{sorted(leaked)}")

    required = {"open_gitee_pull_request", "publish_gitee_pr_comment"}
    missing = required.difference(names)
    if missing:
        raise AssertionError(f"编码任务缺少 Gitee 平台 API 工具：{sorted(missing)}")
    print("task intent verification passed")


if __name__ == "__main__":
    main()
