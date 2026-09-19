"""指定 URL 读取工具。

`fetch_url` 用于读取用户提供的 HTTP/HTTPS 链接，并把 HTML 页面转换成模型更容易处理的
Markdown 或纯文本。它适合读取官方文档、接口说明、错误页面、公开资料链接等外部内容。

网络访问统一通过 `safe_http.request_with_safe_redirects()`，在请求前和每次重定向前校验目标地址，
避免工具访问内网、本机地址或保留地址。
"""

from __future__ import annotations

import html
import json
import logging
import re
from html.parser import HTMLParser
from typing import Any

import requests
from langchain_core.tools import tool

from agent.core.events import record_event
from agent.tools.gitee_api import mask_token
from agent.tools.runtime_context import get_runtime_thread_id
from agent.tools.safe_http import request_with_safe_redirects

logger = logging.getLogger("agent.run.fetch_url")


class _TextExtractor(HTMLParser):
    """极简 HTML 文本提取器。

    项目当前没有显式依赖 markdownify/bs4。
    fetch_url 优先尝试 markdownify；如果环境里没有，就用这个标准库解析器
    提取正文文本，仍然能满足 Agent 阅读网页资料的基本需求。
    """

    def __init__(self) -> None:
        super().__init__()
        # script/style/noscript 内通常不是正文内容，使用深度计数处理嵌套标签。
        self._skip_depth = 0
        # 按片段收集文本，最后统一归一化空白。
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # 跳过脚本、样式和 noscript 内容，避免把页面代码喂给模型。
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
        # 块级标签前补换行，保留基本段落结构。
        if tag in {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        # 结束跳过区域时减少深度，避免误丢后续正文。
        if tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
        # 段落、列表项、表格行和标题结束时补换行，提升可读性。
        if tag in {"p", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        # HTML 实体解码后压缩片段内空白，减少模型上下文浪费。
        text = " ".join(html.unescape(data).split())
        if text:
            self.parts.append(text)

    def text(self) -> str:
        # 合并片段后清理多余空白和连续空行，输出稳定的正文文本。
        raw = " ".join(self.parts)
        raw = re.sub(r"[ \t]+\n", "\n", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def _html_to_markdown(content: str) -> str:
    """把 HTML 转成适合模型阅读的文本。

    如果用户后续愿意增加 markdownify 依赖，这里会自动获得更好的 Markdown 结果；
    没有该依赖时，退化为标准库纯文本提取。
    """

    try:
        # markdownify 能保留链接、标题、列表等结构，优先使用。
        from markdownify import markdownify  # type: ignore

        return str(markdownify(content)).strip()
    except Exception:
        # 任何导入或转换异常都降级到标准库解析，保证工具可用性。
        parser = _TextExtractor()
        parser.feed(content)
        return parser.text()


@tool("fetch_url", parse_docstring=True)
def fetch_url(url: str, timeout: int = 30) -> dict[str, Any]:
    """读取指定 HTTP/HTTPS URL，并把 HTML 内容转换成 Markdown/文本。

    适用于用户给出官方文档、错误页面、接口说明或资料链接时。调用前仍应优先
    读取本地仓库上下文；不要用网页内容替代真实项目代码分析。

    Args:
        url: 需要读取的 HTTP/HTTPS URL。
        timeout: 请求超时时间，单位秒，默认 30。

    Returns:
        包含 ok、url、markdown_content、status_code、content_length 或 error 的字典。
    """

    thread_id = get_runtime_thread_id()
    # 归一化 URL 文本，避免模型传入换行或多余空白。
    normalized_url = " ".join((url or "").split())
    if not normalized_url:
        return {"ok": False, "error": "url 不能为空"}

    if thread_id:
        # 记录开始事件，前端可以展示 Agent 正在读取外部资料。
        record_event(
            thread_id,
            f"fetch_url:{normalized_url[:100]}",
            "读取网页资料",
            kind="fetch",
            status="in_progress",
            detail=json.dumps({"url": normalized_url}, ensure_ascii=False),
        )

    try:
        response, blocked = request_with_safe_redirects(
            "GET",
            normalized_url,
            # 限制超时时间范围，避免模型传入过大数值导致任务长期阻塞。
            timeout=max(1, min(int(timeout), 60)),
            headers={"User-Agent": "CODING/1.0"},
        )
        if blocked:
            # 安全策略拒绝访问时，safe_http 会返回统一错误结构。
            result = blocked
        else:
            assert response is not None
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if "html" in content_type.lower():
                markdown_content = _html_to_markdown(response.text)
            else:
                # 非 HTML 内容按文本处理，例如 JSON、Markdown、纯文本错误日志。
                markdown_content = response.text.strip()
            result = {
                "ok": True,
                "url": str(response.url),
                "status_code": response.status_code,
                "content_type": content_type,
                # 控制返回给模型的最大正文长度，避免单个网页占满上下文窗口。
                "markdown_content": markdown_content[:20000],
                "content_length": len(markdown_content),
            }
    except requests.RequestException as exc:
        # requests 层网络异常通常是可恢复问题，直接返回给模型做降级解释。
        result = {"ok": False, "url": normalized_url, "error": f"网页读取失败：{mask_token(str(exc))}"}
    except Exception as exc:  # noqa: BLE001 - 工具层返回可恢复错误，由 middleware 再做兜底
        # 其他异常写 warning 日志，并对错误文本做 token 脱敏。
        logger.warning("读取网页资料失败：url=%s error=%s", normalized_url, mask_token(str(exc)))
        result = {"ok": False, "url": normalized_url, "error": f"网页处理失败：{mask_token(str(exc))}"}

    if thread_id:
        # 完成事件只记录状态、状态码和错误摘要，不重复写入完整网页正文。
        record_event(
            thread_id,
            f"fetch_url:{normalized_url[:100]}",
            "读取网页资料",
            kind="fetch",
            status="completed" if result.get("ok") else "error",
            detail=json.dumps(
                {
                    "url": normalized_url,
                    "ok": result.get("ok"),
                    "status_code": result.get("status_code"),
                    "error": result.get("error"),
                },
                ensure_ascii=False,
            ),
        )
    return result
