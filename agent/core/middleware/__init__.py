"""Agent middleware 包导出入口。

中间件顺序建议：
1. `ContextInjectionMiddleware`：整轮任务开始前注入仓库级记忆。
2. `MessageSanitizeMiddleware`：模型调用前清洗历史消息中的不兼容 content block。
3. `SanitizeToolInputsMiddleware`：工具执行前清洗路径、Gitee URL 等参数。
4. `ModelCallLimitMiddleware`：限制模型循环次数。
5. `ToolErrorMiddleware`：把工具异常转成模型可恢复的 ToolMessage。
"""

from __future__ import annotations

from agent.core.middleware.context_injection import ContextInjectionMiddleware
from agent.core.middleware.message_sanitize import MessageSanitizeMiddleware
from agent.core.middleware.tool_error import ToolErrorMiddleware
from agent.core.middleware.tool_sanitize import SanitizeToolInputsMiddleware

__all__ = [
    "ContextInjectionMiddleware",
    "MessageSanitizeMiddleware",
    "SanitizeToolInputsMiddleware",
    "ToolErrorMiddleware",
]
