"""工具异常处理中间件。

职责范围：
  本中间件（ToolErrorMiddleware）运行在 LangGraph 的工具调用环节，捕获所有
  工具函数抛出的异常，并将其转换为「模型可读」的结构化错误 ToolMessage。
  这样模型可以把错误当作观察结果继续推理，不会因为某个文件工具路径错误或
  网络请求超时而直接终止整轮 Agent 任务。

为什么要单独做这个：
  1. LangGraph 默认行为：工具抛出异常 → 工具节点报错 → 整轮任务 fail。
     在 FastAPI 后台任务场景里，任务 fail 后前端只能看到一个"任务失败"，
     用户和模型都无法知道原因、无法自行修正。
  2. 本中间件拦截后返回 status="error" 的 ToolMessage，content 里包含：
     - error_type（异常类名，如 FileNotFoundError）
     - error（脱敏后的异常文本）
     - hint（中文修正建议）
     - workspace（当前工作区路径）
     模型读到后可以判断是否路径写错了、是否需要先 ls 再读写、是否需要
     切换命令再试，从而实现一定程度的自主恢复。
  3. 除了返回 ToolMessage，本中间件还会把工具失败状态写回前端 run_events
     表，避免前端步骤长时间停留在 in_progress 的"加载中"状态。

配合关系：
  - tool_sanitize.py（SanitizeToolInputsMiddleware）在工具执行前清洗参数，
    减少路径穿越、URL 格式错误等可预防性异常。
  - 本中间件是兜底防线，处理所有未被前置检查挡住的运行时异常。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from agent.backends.local_shell import LocalShellBackend
from agent.backends.permissions import WorkspacePermissionError
from agent.core.events import record_event
from agent.tools.gitee_api import mask_token
from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langchain_core.messages import ToolMessage
from langgraph.config import get_config
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

logger = logging.getLogger("agent.run.middleware.tool_error")


def tool_error_result(
    error: Exception,
    *,
    tool_name: str,
    backend: LocalShellBackend,
) -> dict[str, Any]:
    """把未捕获的工具异常转换为结构化结果（字典），供 ToolMessage 序列化。

    本函数不依赖 ToolCallRequest 对象，因此也可以在非中间件场景下单独使用
    （例如单元测试中验证错误格式，或 stream 处理中直接构造错误返回）。

    返回的字典包含以下字段，模型可以通过读取 content 的 JSON 了解失败原因：

      ok          = False      模型或上层调用方通过 !result["ok"] 判断失败
      tool        = "read_file"  发生异常的工具名
      error_type  = "FileNotFoundError"  Python 异常类名，便于程序化判断
      error       = "文件不存在: ..."    脱敏后的异常文本
      workspace   = "B:\\ai_workspace"  当前工作区根路径，辅助模型修正路径
      hint        = "文件不存在。请先调用 ls 确认真实路径..."  中文建议

    异常类型判断逻辑：
      - WorkspacePermissionError：路径穿越，需改用工作区内虚拟路径
      - IsADirectoryError：对目录执行了 read/write，需先 ls 查看内容
      - FileNotFoundError：路径拼写错误或文件已被删除
      - PermissionError：权限不足或被其他进程占用
      - TimeoutError：命令或请求超过超时时间
      - 其他：兜底建议，引导模型先检查目录结构再重试
    """

    # 进入模型上下文和日志前先脱敏，避免 token、密钥出现在错误文本中。
    error_text = mask_token(str(error))

    # 按常见异常类型给出可执行的修正建议，帮助模型减少无效重试。
    # 这些提示不会覆盖原异常信息，而是作为额外辅助字段（hint）提供给模型。
    if isinstance(error, WorkspacePermissionError):
        hint = "只能访问工作区内路径。请使用 '/projects' 或 '/projects/仓库名' 这样的虚拟路径。"
    elif isinstance(error, IsADirectoryError):
        hint = "当前路径是目录。请先调用 ls（旧工具名 list_files）查看目录内容，再对具体文件调用 read_file 或 write_file。"
    elif isinstance(error, FileNotFoundError):
        hint = "文件不存在。请先调用 ls 确认真实路径，再继续操作。"
    elif isinstance(error, PermissionError):
        hint = "文件系统拒绝访问。请确认路径不是目录、没有被其他程序占用，并改用工作区内具体文件路径。"
    elif isinstance(error, TimeoutError):
        hint = "操作超时。请缩小任务范围，或先用更小的命令检查项目状态。"
    else:
        hint = "工具执行失败。请根据 error 字段调整参数，必要时先读取目录、文件或 Git 状态再重试。"

    return {
        "ok": False,
        "tool": tool_name,
        "error_type": error.__class__.__name__,
        "error": error_text,
        "workspace": str(backend.workspace.root),
        "hint": hint,
    }


def _get_tool_call_id(request: ToolCallRequest) -> str | None:
    """从 ToolCallRequest 中提取 tool_call_id。

    ToolMessage 必须绑定一个 tool_call_id，LangGraph 才能将这条 ToolMessage
    与对应的工具调用配对，否则会抛出"unmatched tool message"错误。

    注意点：
      - request.tool_call 可能是 dict 或 object，取决于 LangChain/LangGraph 版本。
      - 有些非法请求可能没有 id 字段，这里防御式读取，避免错误处理中再次抛错。
      - 返回 None 时，调用方构造的 ToolMessage 会缺失 tool_call_id，模型仍能
        看到错误内容，只是 LangGraph 层面的配对可能异常。
    """

    if isinstance(request.tool_call, dict):
        value = request.tool_call.get("id")
        return value if isinstance(value, str) else None
    return None


def _get_tool_name(request: ToolCallRequest) -> str:
    """从 ToolCallRequest 中提取工具名。

    工具名用于：
      - 日志输出（定位哪个工具出了问题）
      - 事件 key 前缀（写回 run_events 表）
      - 错误返回中的 tool 字段（模型了解失败来源）

    读取失败时统一回退为 "unknown_tool"，不影响整体流程。
    """

    if isinstance(request.tool_call, dict):
        name = request.tool_call.get("name")
        return name if isinstance(name, str) and name else "unknown_tool"
    return "unknown_tool"


def _get_tool_args(request: ToolCallRequest) -> dict[str, Any]:
    """从 ToolCallRequest 中提取工具调用参数。

    参数会写入错误事件的 detail 字段，用于后续复盘是哪组入参触发了失败。
    只接受 dict 类型，避免把非结构化对象写入事件 JSON 字段。

    注意：参数中可能包含 token、密钥等敏感信息，调用方在使用返回值写入事件
    前应当做脱敏处理（调用 mask_token）。
    """

    if isinstance(request.tool_call, dict):
        args = request.tool_call.get("args", {})
        return args if isinstance(args, dict) else {}
    return {}


def _get_thread_id() -> str | None:
    """通过 LangGraph 运行时配置读取当前线程的 thread_id。

    Runtime 对象本身没有 config 字段（见 langgraph.runtime.Runtime），
    必须通过 langgraph.config.get_config() 才能访问 RunnableConfig。

    thread_id 是写入运行事件表的关联键，没有 thread_id 时仍然返回 ToolMessage，
    只是不会记录前端事件（不影响模型正常恢复处理）。
    """

    configurable = get_config().get("configurable", {})
    if not isinstance(configurable, dict):
        return None
    thread_id = configurable.get("thread_id")
    return thread_id if isinstance(thread_id, str) and thread_id else None


def _error_tool_message(
    error: Exception,
    *,
    request: ToolCallRequest,
    tool_name: str,
    backend: LocalShellBackend,
) -> ToolMessage:
    """把工具异常转换为结构化的 ToolMessage（status="error"）。

    ToolMessage 的 content 是 JSON 序列化的错误详情（由 tool_error_result 生成）。
    模型读取 content 时可以解析出 error_type、error、hint 等字段，自行判断下一步。

    status="error" 的含义：
      LangGraph 中 ToolMessage 默认 status 为空（表示成功）。
      显式设为 "error" 可以让中间件、前端或图结构中其他节点根据 status 做条件判断，
      而不仅仅是靠 content 文本。

    参数：
      error:     原始异常对象。
      request:   触发异常的工具调用请求，用于提取 tool_call_id。
      tool_name: 工具名称（已从 request 中提取，避免重复解析）。
      backend:   LocalShellBackend 实例，用于在错误结果中携带 workspace 路径。
    """

    return ToolMessage(
        content=json.dumps(
            tool_error_result(error, tool_name=tool_name, backend=backend),
            ensure_ascii=False,
        ),
        tool_call_id=_get_tool_call_id(request),
        status="error",
    )


def _record_original_tool_error(
    thread_id: str,
    *,
    tool_name: str,
    kwargs: dict[str, Any],
    error: Exception,
) -> None:
    """把工具失败状态写回运行事件表中该工具原步骤的 key。

    为什么需要这个：
      每个工具在真正执行前（在 streaming_runtime.py 中）会先通过 record_event
      写入一条 in_progress 事件，前端会展示为"加载中"状态。工具执行过程中一旦
      抛出异常，如果只新增一条 "tool-error:*" 事件，原先的 in_progress 步骤
      会永远停留在"运行中"，前端看起来就像卡住了一样。
      这个函数通过反向查找工具名对应的原步骤 key，把那条事件的 status 改为 error。

    工作方式：
      1. 根据 tool_name 在一张预定义映射表中查找原事件的 key 模板。
      2. 用工具调用的参数（kwargs）填充 key 模板中的占位符（如 {path}、{command}）。
      3. 通过 record_event 写入相同 key + status="error" 覆盖原事件状态。

    注意：
      - 不是所有工具都在映射表中登记了。未登记的工具仍会记录通用 tool-error 事件，
        但原步骤会停留在 in_progress。新增工具时应同步更新 mapping 表。
      - kwargs 中的敏感信息在写入事件前会调用 mask_token 脱敏。
    """

    error_detail = mask_token(str(error))

    # 工具名 → (事件 key 模板, 标题, kind) 反向映射表。
    # key 模板中的 {path}、{command} 等占位符由工具调用的实际参数填充。
    # 新增原生文件工具或命令工具时，应同步在此添加映射条目。
    mapping = {
        "ls": ("list:{path}", "查看目录", "search"),
        "read_file": ("read:{path}", "读取文件", "read"),
        "write_file": ("write:{path}", "写入文件", "edit"),
        "edit_file": ("write:{file_path}", "修改文件", "edit"),
        "execute": ("cmd:{command}", "执行命令", "execute"),
        "list_files": ("list:{path}", "查看目录", "search"),
        "run_command": ("cmd:{command}:{cwd}", "执行命令", "execute"),
        "open_gitee_pull_request": ("gitee:pr", "创建或复用 Pull Request", "fetch"),
        "publish_gitee_pr_comment": ("gitee:comment", "发布 PR 评论", "fetch"),
        "web_search": ("web:search:{query}", "搜索网络", "search"),
        "fetch_url": ("fetch:{url}", "抓取网页", "fetch"),
        "get_gitee_pull_request_context": ("gitee:pr-context", "读取 PR 审查上下文", "fetch"),
        "load_default_review_rules": ("review:rules", "读取默认审查规则", "read"),
        "get_review_diff_summary": ("review:diff:{repo_dir}", "读取审查 diff", "read"),
        "validate_review_finding_location": ("review:validate:{file}", "校验审查位置", "other"),
        "add_review_finding": ("review:add:{file}", "记录审查发现", "other"),
        "list_review_findings": ("review:list", "列出审查发现", "other"),
    }
    item = mapping.get(tool_name)
    if not item:
        # 未登记的工具不强行猜测原步骤 key，避免覆盖错误的事件。
        # 会记录通用 tool-error 事件作为兜底。
        return

    key_template, title, kind = item
    try:
        # 部分 key 模板需要 path/command/cwd 等参数，用工具调用的实际参数填充。
        # 如果参数缺失（例如 open_gitee_pull_request 没有 path），用 kwargs 的 get
        # 默认值 "." 或回退到通用 key。
        key = key_template.format(**{"cwd": ".", **kwargs})
    except Exception:
        key = f"tool:{tool_name}"
    record_event(
        thread_id,
        key,
        title,
        kind=kind,
        status="error",
        detail=json.dumps(
            {
                "tool": tool_name,
                # 参数可能包含 token 或敏感 URL，写事件前逐项脱敏。
                "args": {name: mask_token(str(value)) for name, value in kwargs.items()},
                "error": error_detail,
            },
            ensure_ascii=False,
        ),
    )


class ToolErrorMiddleware(AgentMiddleware):
    """工具异常处理中间件。

    它包装了 LangGraph 工具节点的工具调用过程，捕获所有 throw 的异常，
    并返回 status="error" 的 ToolMessage，把错误信息以结构化 JSON 形式
    交还给模型。

    工作流程：
      Agent 生成工具调用
        → LangGraph 工具节点执行 handler(request)
        → wrap_tool_call / awrap_tool_call 捕获异常
        → _record_error() 写回前端事件（原步骤 in_progress → error）
        → _error_tool_message() 构造 status="error" 的 ToolMessage
        → 模型在下一次推理中看到该 ToolMessage，根据 error/hint 字段
          自行判断是否需要修正路径、重试或切换方案

    和 SanitizeToolInputsMiddleware 的关系：
      SanitizeToolInputsMiddleware 在工具调用前清洗参数，阻挡明显非法
      的工具调用（路径穿越、格式错误等），返回 ToolMessage(status="error")。
      本中间件作为第二道防线，捕获运行时异常（文件不存在、网络超时、权限
      拒绝等）。两者配合实现完整的工具调用安全与容错。

    注意：
      - 中间件不区分可恢复和不可恢复异常，全部捕获并返回 ToolMessage。
      - 如果某个异常确实不应该恢复（例如配置错误），可以在模型连续重试
        多次失败后通过 run_limits.py 限制 Agent 运行次数来终止。
    """

    state_schema = AgentState

    def __init__(self, *, backend: LocalShellBackend) -> None:
        super().__init__()
        # backend 用于在错误结果中返回当前 workspace 路径（backend.workspace.root），
        # 帮助模型了解自己的工作区根目录，从而修正路径参数的写法。
        self.backend = backend

    def _record_error(self, request: ToolCallRequest, tool_name: str, error: Exception) -> None:
        """记录工具异常事件到运行事件表。

        这个方法同时做两件事：
          1. 通过 _record_original_tool_error 尝试把原工具步骤从 in_progress
             更新为 error，避免前端步骤长时间"转圈"。
          2. 新增一条通用 tool-error 事件，保留异常类型和脱敏后的错误信息，
             作为兜底记录。

        如果当前线程没有 thread_id（例如在执行探测性图结构时），不会记录事件，
        但异常仍会被正常转换为 ToolMessage 返回。
        """

        thread_id = _get_thread_id()
        if not thread_id:
            return
        kwargs = _get_tool_args(request)
        _record_original_tool_error(thread_id, tool_name=tool_name, kwargs=kwargs, error=error)
        record_event(
            thread_id,
            f"tool-error:{tool_name}",
            f"工具失败：{tool_name}",
            kind="other",
            status="error",
            detail=json.dumps(
                {
                    "tool": tool_name,
                    "error_type": error.__class__.__name__,
                    "error": mask_token(str(error)),
                },
                ensure_ascii=False,
            ),
        )

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        """同步工具调用异常拦截点。

        LangGraph 在每次工具调用前会调用 middleware 的 wrap_tool_call。
        本方法用 try/except 包裹下游 handler 调用，正常返回时不额外处理，
        异常时统一走错误兜底路径。

        参数：
          request: LangGraph 的 ToolCallRequest，包含工具名、参数和调用上下文。
          handler: 下游的调用链，可能是其他 middleware 的 wrap_tool_call，
                   也可能是真正的工具函数。

        返回：
          正常情况：handler 返回的 ToolMessage 或 Command。
          异常情况：status="error" 的 ToolMessage。
        """

        tool_name = _get_tool_name(request)
        try:
            return handler(request)
        except Exception as exc:  # noqa: BLE001
            # BLE001 被忽略：middleware 的职责就是兜底所有工具异常，
            # 包括那些上层不应该捕获的 Exception 基类异常。
            logger.warning(
                "工具执行异常已被中间件捕获：tool=%s error=%s",
                tool_name, mask_token(str(exc)),
            )
            logger.debug("工具异常调试栈：tool=%s", tool_name, exc_info=True)
            self._record_error(request, tool_name, exc)
            return _error_tool_message(exc, request=request, tool_name=tool_name, backend=self.backend)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        """异步工具调用异常拦截点。

        与 wrap_tool_call 保持同样的错误兜底语义，覆盖异步工具和
        异步执行链路。LangGraph 在异步运行时会自动选择 awrap 路径。

        实现逻辑与同步版本完全一致，只是 handler 调用使用了 await。

        参数：
          request: LangGraph 的 ToolCallRequest。
          handler: 异步的调用链。

        返回：
          正常情况：handler 返回的 ToolMessage 或 Command。
          异常情况：status="error" 的 ToolMessage。
        """

        tool_name = _get_tool_name(request)
        try:
            return await handler(request)
        except Exception as exc:  # noqa: BLE001
            # BLE001 被忽略：与同步版本同样的兜底逻辑。
            logger.warning(
                "工具执行异常已被中间件捕获：tool=%s error=%s",
                tool_name, mask_token(str(exc)),
            )
            logger.debug("工具异常调试栈：tool=%s", tool_name, exc_info=True)
            self._record_error(request, tool_name, exc)
            return _error_tool_message(exc, request=request, tool_name=tool_name, backend=self.backend)
