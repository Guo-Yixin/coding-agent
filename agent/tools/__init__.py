"""Agent 自定义工具包导出入口。

DeepAgents 创建智能体时会从这里统一导入项目内置工具，避免工厂函数分散感知每个工具文件。
当前工具主要分为四类：

1. Gitee 协作工具：创建 PR、发布 PR 评论；
2. 资料获取工具：联网搜索、读取指定 URL；
3. Review 结构化记录工具：把审查发现写入业务 Store；
4. 运行上下文辅助能力：由各工具内部读取 thread_id、任务类型等 LangGraph 配置。

这里仅做工具导出，不放业务逻辑，便于后续在 `agent.server` 或子 Agent 配置中按需组装。
"""

from __future__ import annotations

# 网页读取工具：用于读取用户给定的官方文档、错误页面或资料链接。
from .fetch_url_tools import fetch_url
# Gitee 工具：用于把已经推送的分支转换为 PR，并支持向 PR 写评论。
from .gitee_tools import get_gitee_pull_request_context, open_gitee_pull_request, publish_gitee_pr_comment
# Review 工具：用于结构化保存和读取代码审查发现。
from .reviewer_tools import (
    add_review_finding,
    get_review_diff_summary,
    list_review_findings,
    load_default_review_rules,
    validate_review_finding_location,
)
# 联网搜索工具：用于在本地上下文不足时补充外部公开资料。
from .web_search import web_search

# 明确声明对外工具列表，避免调用方依赖模块内的临时变量或辅助函数。
__all__ = [
    "add_review_finding",
    "fetch_url",
    "get_gitee_pull_request_context",
    "get_review_diff_summary",
    "list_review_findings",
    "load_default_review_rules",
    "open_gitee_pull_request",
    "publish_gitee_pr_comment",
    "validate_review_finding_location",
    "web_search",
]
