from __future__ import annotations

from functools import lru_cache

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from agent.env_utils import get_env, require_env

DEEPSEEK_V4_MAX_TOKENS = 25600
INTENT_MODEL_MAX_TOKENS = 200


def make_main_model() -> BaseChatModel:
    """创建编码智能体使用的 DeepSeek 模型。

    本地部署版只保留一个主模型，默认对齐 open-swe 使用的 `deepseek-v4-pro`。
    这里不引入多模型 profile、fallback、路由器等生产级能力，
    让开发者先理解“模型配置”和“Agent 编排”之间的关系。

    `thinking: disabled` 与 open-swe 的 DeepSeek 调用方式保持一致，
    避免模型输出额外思考内容影响工具调用和最终回复。

    这里使用 LangChain 1.x 推荐的 `init_chat_model` 统一初始化模型。
    DeepSeek 官方 API 兼容 OpenAI Chat Completions 协议，所以 provider 使用
    `openai`，并通过 `base_url` 指向 DeepSeek 服务地址。这样既保留当前
    `ChatOpenAI` 的稳定行为，又便于后续把模型供应商抽象成配置。
    """

    return init_chat_model(
        model=get_env("MAIN_MODEL", "deepseek-v4-pro"),
        model_provider="openai",
        temperature=1.1,
        api_key=require_env("DEEPSEEK_API_KEY"),
        base_url=require_env("DEEPSEEK_BASE_URL"),
        max_tokens=DEEPSEEK_V4_MAX_TOKENS,
        streaming=True,
        extra_body={"thinking": {"type": "disabled"}},
    )


@lru_cache(maxsize=1)
def make_intent_model() -> BaseChatModel:
    """创建用户意图分类专用模型。

    这个模型和主 Agent 模型使用同一套 DeepSeek/OpenAI-compatible 连接配置，
    但参数目标完全不同：

    - 主 Agent 模型负责长上下文推理、工具调用和流式输出，所以 `streaming=True`，
      `max_tokens` 也比较大。
    - 意图分类模型只负责把用户输入归类为固定任务类型，不需要流式输出，也不应该
      产生长文本，因此使用 `streaming=False`、`temperature=0` 和较小的 `max_tokens`。

    单独提供公共函数的好处是：模型初始化逻辑集中在 `agent.core.model`，业务模块
    `task_intent.py` 只关心“如何分类”，不再自己拼装模型连接参数。
    """

    return init_chat_model(
        model=get_env("INTENT_MODEL", get_env("MAIN_MODEL", "deepseek-v4-pro")),
        model_provider="openai",
        temperature=float(get_env("INTENT_MODEL_TEMPERATURE", "0")),
        api_key=require_env("DEEPSEEK_API_KEY"),
        base_url=require_env("DEEPSEEK_BASE_URL"),
        max_tokens=int(get_env("INTENT_MODEL_MAX_TOKENS", str(INTENT_MODEL_MAX_TOKENS))),
        streaming=False,
        extra_body={"thinking": {"type": "disabled"}},
    )
