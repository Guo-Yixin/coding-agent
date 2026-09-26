from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENV = PROJECT_ROOT / ".env"


def _load_non_empty_env(path: Path, *, override: bool, allowed_keys: set[str] | None = None) -> None:
    r"""加载 .env 中的非空变量。

    python-dotenv 默认会把 `DEEPSEEK_API_KEY=` 这种空值也写入环境变量。
    项目的 `.env` 通常会保留空字段作为模板，如果直接加载空值，

    所以这里采用自定义加载规则：
    - 空值不写入环境变量。
    - open-swe 的 .env 先作为默认值加载。
    - 本项目 .env 只有填写了非空值时才覆盖默认值。
    """

    if not path.exists():
        return
    for key, value in dotenv_values(path).items():
        if allowed_keys is not None and key not in allowed_keys:
            continue
        if value is None or value.strip() == "":
            continue
        if override or key not in os.environ or os.environ.get(key, "").strip() == "":
            os.environ[key] = value


def load_environment() -> None:
    r"""加载项目运行需要的环境变量。

    加载顺序有意设计为：
    本项目 `.env` 中的空值不会覆盖 open-swe 的真实值；
    """
    # Eval child processes receive explicit per-case paths through their environment.
    # Keep those values authoritative while still loading model credentials and
    # provider defaults that are intentionally sourced from the project's .env.
    eval_mode = os.environ.get("CODING_AGENT_EVAL_MODE", "").strip() == "1"
    env_file = os.environ.get("EVAL_ENV_FILE", "").strip() if eval_mode else ""
    configured_env = Path(env_file).expanduser().resolve() if env_file else LOCAL_ENV
    model_only_keys = {"DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "MAIN_MODEL", "INTENT_MODEL"}
    _load_non_empty_env(configured_env, override=not eval_mode, allowed_keys=model_only_keys if eval_mode else None)

    # 本地部署版默认关闭 LangSmith/LangChain tracing。
    # 这样开发者启动项目时不需要额外配置 LangSmith，也不会把运行数据发到外部观测平台。
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")
    os.environ.setdefault("LANGSMITH_TRACING", "false")
    os.environ.setdefault("LANGCHAIN_API_KEY", "")


def get_env(name: str, default: str = "") -> str:
    """读取环境变量。

    这个函数每次读取前都会调用 load_environment，
    目的是让脚本、测试、Uvicorn 启动入口都能得到一致的配置加载行为。
    """

    load_environment()
    value = os.environ.get(name)
    if value is not None and value.strip():
        return value

    return default if value is None else value


def require_env(name: str) -> str:
    """读取必填环境变量。

    DeepSeek API Key、DeepSeek Base URL、Gitee Token 这类关键配置缺失时，
    应该尽早抛出明确错误，而不是等到模型调用或 Git push 时才失败。
    """

    value = get_env(name).strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value
