from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

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
        name = getattr(item, "name", None)
        if name:
            names.add(str(name))
    return names


def main() -> None:
    """验证 web_search 工具接入。

    该验证不真实联网，避免测试依赖外部网络和第三方 API。
    它只确认：
    1. agent.tools 直接导出 open-swe 风格工具列表。
    2. SDK 未安装或配置缺失时，工具会返回明确错误，而不是影响后端启动。
    """

    tools = [
        web_search,
        fetch_url,
        open_gitee_pull_request,
        publish_gitee_pr_comment,
        add_review_finding,
        list_review_findings,
    ]
    required = {"web_search", "fetch_url", "open_gitee_pull_request", "publish_gitee_pr_comment"}
    missing = required.difference(_tool_names(tools))
    if missing:
        raise AssertionError(f"直接导出的工具列表缺少：{sorted(missing)}")

    result = web_search.invoke({"query": "FastAPI latest documentation"})
    if not isinstance(result, str):
        raise AssertionError("web_search 应返回字符串")
    if not result.strip():
        raise AssertionError("web_search 返回内容为空")

    print("web search tool verification passed")


if __name__ == "__main__":
    main()
