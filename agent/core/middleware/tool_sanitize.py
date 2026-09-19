"""工具入参清洗中间件。

模型生成工具调用参数时，常见问题包括：
1. 把 Windows 绝对路径直接传给文件工具；
2. 使用 `..` 访问工作区外路径；
3. 访问 `.secrets` 等敏感目录；
4. 把带 token 的 Gitee URL 传入工具；
5. 把本应为整数的 offset/limit 生成为字符串。

本模块在工具真正执行前统一清洗这些高风险参数。
LocalShellBackend 仍然是最终安全边界；middleware 的职责是提前给模型返回更明确的中文反馈，
减少无效重试，并避免把明显危险的参数送入工具实现。
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from pathlib import PureWindowsPath
from typing import Any

from agent.backends.local_shell import LocalShellBackend
from agent.core.events import record_event
from agent.tools.gitee_api import mask_token, normalize_gitee_repo_url
from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

logger = logging.getLogger("agent.run.middleware.tool_sanitize")

# 所有工具中具有“路径语义”的参数名，统一经过工作区路径清洗。
PATH_ARGUMENTS = {"path", "cwd", "repo_dir", "project_dir", "file_path", "old_path", "new_path"}
# 仓库地址参数需要规范为不含 token 的标准 Gitee HTTPS 地址。
GITEE_URL_ARGUMENTS = {"repo_url"}
# DeepAgents read_file 的 offset/limit 容易被模型生成为字符串，这里做轻量纠正。
READ_FILE_INT_ARGUMENTS = {"offset", "limit"}


class ToolInputRejected(ValueError):
    """工具入参被 middleware 拒绝。

    这是“可恢复错误”，不是系统异常。返回给模型后，模型应改用工作区相对路径、
    正确 Gitee 地址或更安全的命令重新调用工具。
    """


def _reject_result(error: ToolInputRejected, *, tool_name: str, backend: LocalShellBackend) -> dict[str, Any]:
    """把入参拦截结果转换成模型可读的中文结构。

    该结构会被序列化为 ToolMessage content。
    模型可以读取 `error` 和 `hint` 字段后修正参数，而前端也可以展示 `workspace` 辅助定位。
    """

    return {
        "ok": False,
        "tool": tool_name,
        "error_type": "ToolInputRejected",
        "error": str(error),
        "workspace": str(backend.workspace.root),
        "hint": "请改用工作区内相对路径，例如 '.'、'projects' 或 'projects/仓库名'；不要访问 .secrets。仓库地址请使用标准 Gitee HTTPS 地址。",
    }


def _get_tool_call_id(request: ToolCallRequest) -> str | None:
    """兼容读取 LangGraph tool_call id。

    ToolMessage 需要携带 tool_call_id 才能和模型发起的工具调用正确配对。
    某些测试或异常路径下 tool_call 可能不是标准 dict，因此这里做防御式读取。
    """

    if isinstance(request.tool_call, dict):
        value = request.tool_call.get("id")
        return value if isinstance(value, str) else None
    return None


def _get_thread_id(request: ToolCallRequest) -> str | None:
    """从 runtime config 中读取 thread_id，用于写入前端运行事件。

    middleware 不直接接收业务参数，而是从 LangGraph runtime config 中读取当前任务上下文。
    没有 thread_id 时跳过事件记录，不影响工具错误反馈返回给模型。
    """

    config = getattr(getattr(request, "runtime", None), "config", None)
    configurable = config.get("configurable", {}) if isinstance(config, dict) else {}
    thread_id = configurable.get("thread_id") if isinstance(configurable, dict) else None
    return thread_id if isinstance(thread_id, str) and thread_id else None


def _coerce_int(value: Any) -> Any:
    """把模型偶尔生成的 `'1, 80'` 一类参数修正为整数。

    文件读取工具只需要单个整数，但模型有时会把 offset/limit 合并成字符串。
    这里取字符串开头的数字做温和修正；无法识别时原样返回，由工具自身校验。
    """

    if value is None or isinstance(value, int):
        return value
    if isinstance(value, str):
        match = re.match(r"\s*(\d+)", value)
        if match:
            return int(match.group(1))
    return value


def _reject_tool_message(
    error: ToolInputRejected,
    *,
    request: ToolCallRequest,
    tool_name: str,
    backend: LocalShellBackend,
) -> ToolMessage:
    """把参数拦截结果转换为 ToolMessage，让 Agent 可以继续修正。

    返回 `status="error"` 是为了告诉模型本次工具调用失败，但失败信息仍然是可读观察结果。
    这样比直接抛异常更适合多步 Agent 自我修正。
    """

    return ToolMessage(
        content=json.dumps(
            _reject_result(error, tool_name=tool_name, backend=backend),
            ensure_ascii=False,
        ),
        tool_call_id=_get_tool_call_id(request),
        status="error",
    )


def _is_windows_absolute_path(value: str) -> bool:
    """判断字符串是否像 Windows 绝对路径。

    pathlib.Path 在不同平台上对 Windows 盘符的解析不完全一致，因此这里用正则和
    PureWindowsPath 做轻量判断，只负责提前给模型更清楚的错误提示。
    """

    if re.match(r"^[A-Za-z]:[\\/]", value):
        return True
    try:
        return PureWindowsPath(value).is_absolute() and bool(PureWindowsPath(value).drive)
    except Exception:
        return False


def sanitize_workspace_path(value: Any, *, argument_name: str, backend: LocalShellBackend) -> Any:
    """清洗路径类参数。

    后端 `Workspace.resolve()` 仍是最终安全边界。middleware 只在调用前做更友好的
    规范化和敏感目录拦截，避免模型反复把 `E:\\`、`.secrets` 这类路径传给工具。
    """

    if not isinstance(value, str):
        return value
    # 去掉模型常见的包裹引号，并把 Windows 反斜杠统一成正斜杠。
    cleaned = value.strip().strip('"').strip("'").replace("\\", "/")
    if not cleaned:
        return cleaned
    if _is_windows_absolute_path(cleaned):
        # 如果绝对路径仍然落在 workspace 内，则转换成相对路径；
        # 如果指向 workspace 外部，则直接拒绝，避免工具层触达宿主机其他目录。
        resolved_root = backend.workspace.root.resolve()
        resolved_path = Path(cleaned).resolve()
        if resolved_path == resolved_root:
            return "."
        if resolved_root in resolved_path.parents:
            return resolved_path.relative_to(resolved_root).as_posix()
        raise ToolInputRejected(f"{argument_name} 不能使用工作区外的 Windows 绝对路径：{cleaned}")
    # 拆分路径片段后检查敏感目录和路径穿越，避免简单字符串包含判断产生误判。
    parts = [part for part in cleaned.split("/") if part not in {"", "."}]
    if ".secrets" in parts:
        raise ToolInputRejected(f"{argument_name} 禁止访问敏感目录 .secrets")
    if ".." in parts:
        raise ToolInputRejected(f"{argument_name} 禁止使用 '..' 跳出工作区：{cleaned}")
    return cleaned or "."


def _sanitize_gitee_url(value: Any) -> Any:
    """把 Gitee 地址规范为不带 token 的标准 HTTPS clone_url。

    Gitee token 不应出现在工具参数、日志、事件或 Git remote URL 中。
    这里只对包含 gitee.com 的字符串做规范化，其他普通字符串保持原样。
    """

    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return text
    if "gitee.com" not in text.lower():
        return text
    return normalize_gitee_repo_url(text)


def sanitize_tool_kwargs(tool_name: str, kwargs: dict[str, Any], *, backend: LocalShellBackend) -> dict[str, Any]:
    """根据参数名对工具入参做统一清洗。

    这里不做具体业务推断，只处理所有工具共享的高风险参数：路径和 Gitee URL。
    工具自己的业务校验仍放在原工具函数内部。
    """

    # 复制一份参数，避免直接修改 LangGraph 传入的原始 tool_call 对象。
    sanitized = dict(kwargs)
    for key in PATH_ARGUMENTS:
        if key in sanitized:
            sanitized[key] = sanitize_workspace_path(sanitized[key], argument_name=key, backend=backend)
    for key in GITEE_URL_ARGUMENTS:
        if key in sanitized:
            sanitized[key] = _sanitize_gitee_url(sanitized[key])
    for key in READ_FILE_INT_ARGUMENTS:
        if key in sanitized:
            sanitized[key] = _coerce_int(sanitized[key])
    logger.debug("工具入参清洗完成：tool=%s keys=%s", tool_name, sorted(sanitized))
    return sanitized


class SanitizeToolInputsMiddleware(AgentMiddleware):
    """工具入参清洗中间件。

    它运行在 DeepAgents 工具调用生命周期里，因此能同时覆盖自定义 Gitee 工具
    和 DeepAgents 原生的文件/命令工具。LocalShellBackend 仍是最终安全边界，
    这里主要负责把常见错误参数转换成 Agent 可恢复的中文反馈。
    """

    state_schema = AgentState

    def __init__(self, *, backend: LocalShellBackend) -> None:
        super().__init__()
        # backend 提供 workspace 根目录和最终文件系统边界，路径清洗需要基于它判断绝对路径归属。
        self.backend = backend

    def _sanitize_request(self, request: ToolCallRequest) -> ToolCallRequest:
        """返回清洗后的 ToolCallRequest。

        LangGraph 的 ToolCallRequest 是不可直接假定结构稳定的对象，所以先防御式读取 tool_call。
        如果参数不是 dict，则不做处理，让后续工具或框架按原有逻辑处理。
        """

        tool_call = request.tool_call
        if not isinstance(tool_call, dict):
            return request
        tool_name = str(tool_call.get("name") or "")
        args = tool_call.get("args", {})
        if not isinstance(args, dict):
            return request
        sanitized_args = sanitize_tool_kwargs(tool_name, args, backend=self.backend)
        # 使用 request.override 生成新的请求对象，避免原地修改 runtime 内部状态。
        return request.override(tool_call={**tool_call, "args": sanitized_args})

    def _record_rejection(self, request: ToolCallRequest, tool_name: str, error: ToolInputRejected) -> None:
        """把参数拒绝事件写入运行事件表。

        事件记录用于前端展示和问题排查；没有 thread_id 时跳过，不影响中间件返回 ToolMessage。
        """

        thread_id = _get_thread_id(request)
        if not thread_id:
            return
        record_event(
            thread_id,
            f"tool-sanitize:{tool_name}",
            f"参数被拦截：{tool_name}",
            kind="other",
            status="error",
            detail=json.dumps({"tool": tool_name, "error": mask_token(str(error))}, ensure_ascii=False),
        )

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        """同步工具调用拦截点。

        DeepAgents/LangGraph 执行同步工具前会经过该方法。
        如果参数清洗失败，直接返回错误 ToolMessage；否则继续调用下一个 handler。
        """

        tool_name = str(request.tool_call.get("name") or "") if isinstance(request.tool_call, dict) else ""
        try:
            return handler(self._sanitize_request(request))
        except ToolInputRejected as exc:
            logger.warning("工具入参被拒绝：tool=%s error=%s", tool_name, mask_token(str(exc)))
            self._record_rejection(request, tool_name, exc)
            return _reject_tool_message(exc, request=request, tool_name=tool_name, backend=self.backend)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        """异步工具调用拦截点。

        逻辑与 `wrap_tool_call` 保持一致，只是 handler 需要 await。
        同步和异步路径都覆盖，避免部分工具绕过参数清洗。
        """

        tool_name = str(request.tool_call.get("name") or "") if isinstance(request.tool_call, dict) else ""
        try:
            return await handler(self._sanitize_request(request))
        except ToolInputRejected as exc:
            logger.warning("工具入参被拒绝：tool=%s error=%s", tool_name, mask_token(str(exc)))
            self._record_rejection(request, tool_name, exc)
            return _reject_tool_message(exc, request=request, tool_name=tool_name, backend=self.backend)
