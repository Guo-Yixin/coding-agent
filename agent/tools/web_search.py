"""联网搜索工具。

该工具用于在本地仓库上下文不足时，补充公开网络资料，例如框架文档、第三方库变更说明、
错误信息背景和公开技术资料。工具本身只返回搜索摘要，不替代本地代码分析。

外部搜索依赖智谱 Web Search API。SDK 采用懒加载方式初始化，避免后端启动阶段因为可选依赖
或 API Key 缺失而直接失败。
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Any

from langchain_core.tools import tool

from agent.core.events import record_event
from agent.env_utils import require_env
from agent.tools.gitee_api import mask_token
from agent.tools.runtime_context import get_runtime_thread_id

logger = logging.getLogger("agent.run.web_search")


@lru_cache(maxsize=1)
def _get_zhipu_client() -> Any:
    """懒加载智谱 SDK 客户端。

    Web 搜索不是后端启动的必要能力，所以不能在模块导入时直接初始化 SDK。
    这样即使本地暂时没有安装 `zai`，FastAPI 也能正常启动；只有 Agent 真正调用
    web_search 时，才返回明确的依赖或密钥错误。
    """

    # API Key 在真正搜索时才读取，避免导入模块阶段对环境变量产生强依赖。
    api_key = require_env("ZHIPU_API_KEY")
    try:
        # 优先兼容新版 `zai` SDK。
        from zai import ZhipuAiClient

        return ZhipuAiClient(api_key=api_key)
    except (ImportError, AttributeError):
        pass

    try:
        # 回退兼容旧版 `zhipuai` SDK，降低部署环境升级成本。
        from zhipuai import ZhipuAI
    except ImportError as exc:
        raise RuntimeError("缺少智谱 SDK，请先安装依赖：pip install zhipuai") from exc
    return ZhipuAI(api_key=api_key)


@tool("web_search", parse_docstring=True)
def web_search(query: str) -> str:
    """使用智谱搜狗 Web Search API 进行联网搜索。

    适用于需要外部资料支撑的任务，例如查询最新框架文档、第三方库用法、
    API 变更说明、行业资料或错误信息背景。不要搜索密钥、token、私有仓库内容。

    Args:
        query: 需要搜索的关键词或问题。

    Returns:
        搜索结果摘要文本；失败时返回明确错误信息。
    """

    thread_id = get_runtime_thread_id()
    # 压缩空白，避免模型生成多行 query 或带大量空格影响搜索质量。
    normalized_query = " ".join((query or "").split())
    if not normalized_query:
        return "搜索失败：query 不能为空"

    if thread_id:
        # 写入工具调用事件，前端可以展示“正在联网搜索”的运行过程。
        record_event(
            thread_id,
            f"web_search:{normalized_query[:80]}",
            "联网搜索资料",
            kind="fetch",
            status="in_progress",
            detail=json.dumps({"query": normalized_query}, ensure_ascii=False),
        )
    try:
        client = _get_zhipu_client()
        # 这里固定使用 search_pro 并限制 count=3，控制外部结果数量和模型上下文体积。
        response = client.web_search.web_search(
            search_engine="search_pro",
            search_query=normalized_query,
            count=3,
            search_recency_filter="noLimit",
        )
        results = getattr(response, "search_result", None) or []
        if not results:
            output = "没有搜索到任何内容。"
        else:
            # 只抽取 content 字段，避免把 SDK 的复杂对象直接暴露给模型。
            output = "\n\n".join(
                str(getattr(item, "content", "") or "").strip()
                for item in results
                if str(getattr(item, "content", "") or "").strip()
            )
            if not output:
                output = "搜索结果为空。"
        if thread_id:
            # 事件详情只记录预览片段，避免把大量搜索结果重复写入事件表。
            record_event(
                thread_id,
                f"web_search:{normalized_query[:80]}",
                "联网搜索资料",
                kind="fetch",
                status="completed",
                detail=json.dumps(
                    {"query": normalized_query, "result_preview": output[:1200]},
                    ensure_ascii=False,
                ),
            )
        return output
    except Exception as exc:
        # 外部 API 错误、网络异常、SDK 异常都返回可读文本，让模型可以继续降级处理。
        error = mask_token(str(exc))
        logger.warning("联网搜索失败：query=%s error=%s", normalized_query, error)
        if thread_id:
            record_event(
                thread_id,
                f"web_search:{normalized_query[:80]}",
                "联网搜索资料",
                kind="fetch",
                status="error",
                detail=json.dumps({"query": normalized_query, "error": error}, ensure_ascii=False),
            )
        return f"搜索失败: {error}"
